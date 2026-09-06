"""In-process regression harness over the labelled kyc-media eval set.

Mirrors main.py's POST /v1/analyze route in-process (no HTTP, no uvicorn) --
see the "mirrors main.py:204-248" comment below for exactly which lines this
reproduces. Modeled on the in-process pattern at scripts/verify_baseline.py:
import lanes/judge directly and call them.

Usage:
    GROQ_API_KEY= .venv/bin/python scripts/regression.py --source local
    .venv/bin/python scripts/regression.py --source supabase

GROQ_API_KEY is forced to "" by default (see _force_groq_key_off below) so
runs are deterministic and free -- Lane A's optional secondary VLM read in
lane_a_refine.py silently no-ops without a key. Pass --vlm to opt into the
network lane once lane_h_vlm.py exists.

Exit code is non-zero iff any labelled case produced a false ACCEPT (an
expected-REJECT case that came back ACCEPT) or a false REJECT (an
expected-ACCEPT case that came back REJECT) -- the two conditions that must
never regress per PLAN.md.
"""

from __future__ import annotations

import argparse
import inspect
import json
import os
import sys
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVICE_DIR))

# Deterministic-by-default: force the optional network lane off before main.py
# (which imports lane_a_refine, which reads GROQ_API_KEY at call time) loads.
# lane_a_refine's own _load_local_env only sets a var if it is NOT already in
# os.environ, so pre-setting "" here wins over service/.env's real key.
if "--vlm" not in sys.argv:
    os.environ["GROQ_API_KEY"] = ""

from env_loader import get_supabase  # noqa: E402

EVAL_CACHE = SERVICE_DIR / ".eval_cache"
LABELS_PATH = SERVICE_DIR / "eval_labels.json"



def _load_labels() -> dict:
    if not LABELS_PATH.is_file():
        return {}
    return json.loads(LABELS_PATH.read_text())


def _list_supabase_cases(url: str, key: str) -> list[str]:
    import httpx

    res = httpx.post(
        f"{url}/storage/v1/object/list/kyc-media",
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        json={"prefix": "", "limit": 1000},
        timeout=15.0,
    )
    res.raise_for_status()
    items = res.json()
    # Non-recursive list at prefix="" returns folder entries (case ids) and
    # possibly stray top-level files; a folder name has no "." extension.
    return sorted({it["name"] for it in items if "name" in it and "." not in it["name"]})


def _download_supabase_case(url: str, key: str, case_id: str) -> None:
    import httpx

    dest_dir = EVAL_CACHE / case_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=15.0) as client:
        for fname in ("id.jpg", "selfie.jpg"):
            dest = dest_dir / fname
            if dest.is_file():
                continue
            r = client.get(f"{url}/storage/v1/object/public/kyc-media/{case_id}/{fname}")
            if r.status_code == 200:
                dest.write_bytes(r.content)
            else:
                print(f"  warn: {case_id}/{fname} -> HTTP {r.status_code}")


def _run_pair(id_bytes: bytes, selfie_bytes: bytes) -> dict:
    """Mirrors main.py:204-248 (the POST /v1/analyze route body), minus the
    async file-upload plumbing (_read_upload) which is irrelevant in-process.
    """
    from lane_face import face_similarity
    from judge import judge
    from main import _analyze_one

    # _analyze_one grows an is_id_document flag once Lane H lands (the VLM must
    # ignore print_replay on an ID -- a genuine paper Aadhaar really is printed
    # paper and scores 0.95 there). Pass it only if the parameter exists, so this
    # harness works either side of that change.
    _kw = "is_id_document" in inspect.signature(_analyze_one).parameters
    id_analysis, id_q, id_results, id_bgr, _ = (
        _analyze_one(id_bytes, is_id_document=True) if _kw else _analyze_one(id_bytes)
    )
    selfie_analysis, s_q, s_results, s_bgr, _ = (
        _analyze_one(selfie_bytes, is_id_document=False) if _kw else _analyze_one(selfie_bytes)
    )

    rank = {"LIKELY_FAKE": 0, "INSUFFICIENT_EVIDENCE": 1, "REAL": 2}
    id_v = judge(id_q, id_results, attested=False, apply_screen_replay_hard_gate=False)
    selfie_v = judge(s_q, s_results, attested=False)
    worse_is_id = rank[id_v.authenticity] < rank[selfie_v.authenticity]

    sim, face_reasons, low_quality_face = face_similarity(id_bgr, s_bgr)

    if worse_is_id:
        final = judge(id_q, id_results, attested=False, face_similarity=sim,
                       require_identity=True, low_quality_face=low_quality_face,
                       apply_screen_replay_hard_gate=False)
    else:
        final = judge(s_q, s_results, attested=False, face_similarity=sim,
                       require_identity=True, low_quality_face=low_quality_face)

    return {
        "id_analysis": id_analysis,
        "selfie_analysis": selfie_analysis,
        "id_results": id_results,
        "s_results": s_results,
        "final": final,
        "sim": sim,
    }


def _lane_str(results) -> str:
    """Lane list comes from what _analyze_one actually returned, never a hardcoded
    order: Lane H (the VLM replay/synthesis check) is the only lane with measured
    signal on real data, so a fixed list would silently omit the one that matters.
    """
    return " ".join(f"{r.lane}={r.score:.2f}" for r in results)


def _gate_for(final) -> str:
    texts = " | ".join(r.text for r in final.reasons)
    if "VLM " in texts and "independent hard fail" in texts:
        # Name the lane that actually fired: Lane H (VLM) and Lane G (FFT moire)
        # share the hard-fail path but are very different signals, and the whole
        # point of this column is telling you which one caused a regression.
        field = "screen_replay" if "VLM screen_replay" in texts else "print_replay"
        return f"H-hard-gate({field})"
    if "treated as an independent hard fail" in texts:
        return "G-hard-gate(screen-replay)"
    if "too low to support a verdict" in texts:
        return "quality-gate"
    if "could read this image" in texts:
        return "min-usable-lanes"
    if "lanes disagree" in texts:
        return "disagreement"
    if "uncertainty band" in texts:
        return "aggregate-band"
    return "aggregate+identity"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["local", "supabase"], default="local")
    ap.add_argument("--vlm", action="store_true", help="opt into the network VLM lane (Lane H)")
    args = ap.parse_args()

    labels = _load_labels()

    if args.source == "supabase":
        url, key = get_supabase()
        if not url or not key:
            print("Supabase creds not found (repo-root .env EXPO_PUBLIC_SUPABASE_URL / "
                  "EXPO_PUBLIC_SUPABASE_ANON_KEY). Cannot list bucket.")
            raise SystemExit(1)
        case_ids = _list_supabase_cases(url, key)
        print(f"{len(case_ids)} case folders in kyc-media; "
              f"{len(labels)} labelled, {len(case_ids) - len(labels)} diagnostic-only.")
        for cid in case_ids:
            _download_supabase_case(url, key, cid)
    else:
        if not EVAL_CACHE.is_dir():
            print(f"{EVAL_CACHE} does not exist -- nothing to run.")
            raise SystemExit(1)
        case_ids = sorted(p.name for p in EVAL_CACHE.iterdir() if p.is_dir())

    rows = []
    false_accept = 0
    false_reject = 0
    confusion: dict[str, dict[str, int]] = {}

    for cid in case_ids:
        id_path = EVAL_CACHE / cid / "id.jpg"
        selfie_path = EVAL_CACHE / cid / "selfie.jpg"
        if not id_path.is_file() or not selfie_path.is_file():
            print(f"  skip {cid}: missing id.jpg/selfie.jpg")
            continue

        result = _run_pair(id_path.read_bytes(), selfie_path.read_bytes())
        final = result["final"]
        meta = labels.get(cid)
        expect = meta["expect"] if meta else None
        label = meta["label"] if meta else "(unlabelled)"

        marker = ""
        if expect is not None:
            confusion.setdefault(label, {}).setdefault(final.decision, 0)
            confusion[label][final.decision] += 1
            if expect == "REJECT" and final.decision == "ACCEPT":
                false_accept += 1
                marker = "  <- FALSE ACCEPT"
            elif expect == "ACCEPT" and final.decision == "REJECT":
                false_reject += 1
                marker = "  <- FALSE REJECT"
            elif final.decision != expect:
                marker = f"  (expected {expect})"

        rows.append((cid, label, expect, final, result, marker))

    print()
    print(f"{'case':<16}{'label':<20}{'expect':<9}{'decision':<10}{'conf':>6}  gate")
    print("-" * 90)
    for cid, label, expect, final, result, marker in rows:
        print(
            f"{cid:<16}{label:<20}{(expect or '-'):<9}{final.decision:<10}"
            f"{final.confidence:>6.2f}  {_gate_for(final)}{marker}"
        )
        print(f"{'':16}  ID lanes:     {_lane_str(result['id_results'])}")
        print(f"{'':16}  selfie lanes: {_lane_str(result['s_results'])}")
        if result["sim"] is not None:
            print(f"{'':16}  face similarity: {result['sim']:.4f}  identity: {final.identity}")

    print()
    print("Confusion matrix (label x decision), labelled cases only:")
    decisions = ["ACCEPT", "REVIEW", "REJECT"]
    labels_seen = sorted(confusion.keys())
    print(f"{'label':<20}" + "".join(f"{d:>10}" for d in decisions))
    for lbl in labels_seen:
        print(f"{lbl:<20}" + "".join(f"{confusion[lbl].get(d, 0):>10}" for d in decisions))

    print()
    print(f"FALSE ACCEPTS: {false_accept}")
    print(f"FALSE REJECTS: {false_reject}")

    if false_accept > 0 or false_reject > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
