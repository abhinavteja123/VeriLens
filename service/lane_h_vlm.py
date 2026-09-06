"""Lane H - VLM screen/print-replay and whole-image synthesis check (Groq).

Replaces lane_a_refine.py (retired). That module quietly folded a secondary
opinion into Lane A and fell back to a *guess* on any error. Measured this
session: Lanes A/B/C carry no screen-replay signal at all (PLAN.md Findings
1-3), while the same six images sent through this exact prompt to
qwen/qwen3.8-27b separated replay from genuine 6/6. So this is promoted to
its own required lane instead of a hidden nudge, and its failure mode is
changed from "silently guess" to "abstain with a visible reason" -- the
direct fix for the intermittent-REVIEW complaint (no cache before) and the
silent-fallback bug (no distinction between "abstained" and "read clean"
before).

Never raises: a missing key, a network error, a rate limit, or an
unparseable reply all abstain (score 0.0, confidence 0.0, a reason
explaining why) rather than fail the request or fall through to a guess.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import re
import time
from pathlib import Path

import cv2
import httpx
import numpy as np
from PIL import Image

from config import CFG
from env_loader import load_env
from lanes import LaneResult

_LOG = logging.getLogger("verilens.lane_h")

_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
_MODEL = "qwen/qwen3.8-27b"
_TIMEOUT_S = 20.0
_MAX_SIDE = 1024
_JPEG_QUALITY = 88

# Bump this whenever _PROMPT's meaning changes -- it's part of the cache
# key, so a prompt edit can't silently serve a stale verdict for an
# already-cached image.
_PROMPT_VERSION = "h1"
_CACHE_DIR = Path(__file__).parent / ".vlm_cache"

# Verified live this session: 6/6 correct on the measured sample (PLAN.md
# Finding 4). Folds in the whole-image AI-synthesis cues from the retired
# lane_a_refine.py's prompt (unnaturally perfect skin, missing catchlights,
# melted hair/background transitions), which HANDOFF.md records fixed a
# real miss.
_PROMPT = (
    "Forensic KYC check on this capture. Decide if the camera photographed a REAL physical "
    "scene, or RE-PHOTOGRAPHED a display/print. Screen-replay cues: monitor or phone bezel, "
    "browser tabs, window chrome, app UI, cursor, taskbar, thumbnail filmstrip, screen glare, "
    "backlight glow, flat uniform illumination, refresh banding. Print-replay cues: halftone "
    "dots, paper fibre, page curl. Also judge AI generation: unnaturally perfect or symmetric "
    "skin with no pores, blemishes, or texture variation; missing or asymmetric catchlights/"
    "reflections in the eyes; unnaturally smooth or melted-looking hair-to-background "
    "transitions.\n"
    'Reply JSON only: {"screen_replay":0..1,"print_replay":0..1,"synthetic":0..1,"cues":["..."]}'
)

# Groq's 429 body writes the wait as "Xs" for a short (per-minute) limit but
# "YmXs" once it's long enough to span minutes -- observed live: a spent
# tokens-per-day quota reported "try again in 13m29.568s". The plain
# `([\d.]+)s` form never matches that (the leading "13m" breaks it before
# the digit run reaches the trailing "s"), silently falling back to the 5s
# default and retrying into a wait that won't be over for another 13
# minutes. Match an optional leading "Nm" so both forms parse correctly.
_RETRY_AFTER_RE = re.compile(r"try again in (?:(\d+)m)?([\d.]+)s", re.I)


def _downscale_jpeg_b64(bgr: np.ndarray) -> str:
    """1024px longest side, JPEG q88. For latency, not quota -- Groq bills
    a flat ~1850 input tokens per image regardless of resolution (measured).
    """
    h, w = bgr.shape[:2]
    longest = max(h, w)
    if longest > _MAX_SIDE:
        s = _MAX_SIDE / longest
        bgr = cv2.resize(bgr, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, format="JPEG", quality=_JPEG_QUALITY)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _cache_path(data: bytes) -> Path:
    digest = hashlib.sha256(data).hexdigest()
    return _CACHE_DIR / f"{digest}-{_PROMPT_VERSION}.json"


def _parse_payload(text: str) -> dict | None:
    """Tolerant of a fenced code block or leading/trailing prose around the
    JSON object, same tolerance as the retired lane_a_refine.py's parser.
    """
    if not text:
        return None
    blob = text.strip()
    if blob.startswith("```"):
        blob = re.sub(r"^```(?:json)?\s*|\s*```$", "", blob, flags=re.I | re.S)
    try:
        obj = json.loads(blob)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", blob, re.S)
        if not m:
            return None
        try:
            obj = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(obj, dict):
        return None

    out: dict = {}
    for key in ("screen_replay", "print_replay", "synthetic"):
        try:
            out[key] = float(np.clip(float(obj.get(key, 0.0)), 0.0, 1.0))
        except (TypeError, ValueError):
            out[key] = 0.0
    cues = obj.get("cues", [])
    out["cues"] = [str(c) for c in cues][:8] if isinstance(cues, list) else []
    return out


def _retry_after_seconds(body: str) -> float:
    m = _RETRY_AFTER_RE.search(body or "")
    if not m:
        return 5.0
    minutes = float(m.group(1)) if m.group(1) else 0.0
    return minutes * 60.0 + float(m.group(2))


def _query(jpeg_b64: str, api_key: str) -> tuple[dict | None, str | None]:
    """POST once; on a 429 parse the wait time, sleep, retry once; any
    other failure (network, non-200, unparseable body) abstains
    immediately. Returns (parsed, None) on success or (None, reason) to
    abstain -- never raises.
    """
    body = {
        "model": _MODEL,
        "temperature": 0,
        "max_completion_tokens": 200,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{jpeg_b64}"}},
                ],
            }
        ],
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    for attempt in range(2):  # first try, then one retry after a 429
        try:
            with httpx.Client(timeout=_TIMEOUT_S) as client:
                res = client.post(_ENDPOINT, headers=headers, json=body)
        except Exception as e:  # noqa: BLE001 - network failure: abstain, never guess
            _LOG.warning("Lane H request failed (%s)", type(e).__name__)
            return None, f"Lane H request failed ({type(e).__name__}); abstaining rather than guessing."

        if res.status_code == 429:
            wait_s = min(_retry_after_seconds(res.text), 60.0)
            if attempt == 0:
                _LOG.warning("Lane H rate-limited; sleeping %.1fs then retrying once", wait_s)
                time.sleep(wait_s)
                continue
            return None, (
                f"Lane H rate-limited by Groq (waited {wait_s:.1f}s, retried once, still 429); "
                "abstaining rather than falling back to a guess."
            )

        if res.status_code != 200:
            snippet = (res.text or "")[:160].replace("\n", " ")
            _LOG.warning("Lane H request failed (status %s) %s", res.status_code, snippet)
            return None, f"Lane H request failed (status {res.status_code}); abstaining."

        try:
            payload = res.json()
            text = payload["choices"][0]["message"].get("content") or ""
        except (KeyError, IndexError, TypeError, ValueError):
            return None, "Lane H returned an unparseable response; abstaining."

        parsed = _parse_payload(text)
        if parsed is None:
            return None, "Lane H response was not valid JSON; abstaining rather than guessing."
        return parsed, None

    return None, "Lane H rate-limited by Groq; abstaining rather than guessing."  # pragma: no cover


def lane_h_vlm(data: bytes, bgr: np.ndarray, is_id_document: bool) -> LaneResult:
    """One VLM call per image (cached by sha256(data)+prompt version).

    On an ID document image, print_replay is ignored entirely: a genuine
    paper ID legitimately reads as printed (measured print_replay=0.95 on a
    real Aadhaar) -- using it there would false-reject real IDs, the exact
    trap Lane G's guilloche false positive taught (LIMITATIONS.md 2c). On a
    selfie print_replay is a valid signal: nobody's live selfie is printed
    paper.
    """
    name = "Visual synthesis & replay check"

    if not CFG.vlm_enabled:
        return LaneResult("H", name, 0.0, 0.0, ["Lane H disabled (CFG.vlm_enabled=False)."])

    try:
        load_env()
        api_key = (os.environ.get("GROQ_API_KEY") or "").strip()
        if not api_key:
            return LaneResult("H", name, 0.0, 0.0, ["Lane H unavailable: GROQ_API_KEY not set (offline run)."])

        cache_file = _cache_path(data)
        parsed: dict | None = None
        abstain_reason: str | None = None
        cache_hit = False

        if cache_file.is_file():
            try:
                parsed = json.loads(cache_file.read_text())
                cache_hit = True
            except (OSError, json.JSONDecodeError):
                parsed = None

        if parsed is None:
            jpeg_b64 = _downscale_jpeg_b64(bgr)
            parsed, abstain_reason = _query(jpeg_b64, api_key)
            if parsed is not None:
                try:
                    _CACHE_DIR.mkdir(exist_ok=True)
                    cache_file.write_text(json.dumps(parsed))
                except OSError:
                    pass  # cache is an optimisation, not a correctness requirement

        if parsed is None:
            return LaneResult("H", name, 0.0, 0.0, [abstain_reason or "Lane H abstained."])

        screen_replay = float(parsed.get("screen_replay", 0.0))
        print_replay = float(parsed.get("print_replay", 0.0))
        synthetic = float(parsed.get("synthetic", 0.0))
        cues = parsed.get("cues", [])

        signals = [screen_replay, synthetic]
        if not is_id_document:
            signals.append(print_replay)
        score = max(signals)

        reasons = []
        if cache_hit:
            reasons.append("Cached VLM result (identical image analysed before).")
        if cues:
            reasons.append("VLM cues: " + ", ".join(cues) + ".")
        detail = f"screen_replay={screen_replay:.2f} synthetic={synthetic:.2f}"
        if is_id_document:
            detail += f" (print_replay={print_replay:.2f} ignored on an ID document)"
        else:
            detail += f" print_replay={print_replay:.2f}"
        reasons.append(detail)

        return LaneResult(
            "H", name, float(score), CFG.vlm_confidence_cap, reasons,
            extra={"screen_replay": screen_replay, "print_replay": print_replay, "synthetic": synthetic},
        )
    except Exception as e:  # noqa: BLE001 - Lane H must never fail the request
        _LOG.warning("Lane H error (%s)", type(e).__name__)
        return LaneResult("H", name, 0.0, 0.0, [f"Lane H error ({type(e).__name__}); abstaining."])


if __name__ == "__main__":
    # Smoke check: no key -> clean abstain, never raises, zero network I/O.
    # Set (not delete) the var to "" so load_env()'s "already in os.environ"
    # guard stops it from being repopulated from service/.env.
    os.environ["GROQ_API_KEY"] = ""
    blank = np.zeros((256, 256, 3), dtype=np.uint8)
    r = lane_h_vlm(b"\xff\xd8\xff" + b"0" * 32, blank, is_id_document=False)
    assert r.lane == "H" and r.confidence == 0.0 and r.score == 0.0, r
    print("ok  lane_h_vlm abstains cleanly with no API key")
