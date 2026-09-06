"""FastAPI forensics service for KYC deepfake / AI-generated image detection.

Endpoints:
  POST /v1/analyze         ID photo + selfie -> full verdict
  POST /v1/analyze/single  one image -> authenticity only
  GET  /v1/health
  POST /v1/baseline        same image: baselines vs ours, side by side
  GET  /v1/model-card      thresholds, limits, and what we do NOT claim

Runs CPU-only. No model weights required for lanes B/C, so the service is
deployable on free CPU hosting as-is.
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from attestation import issue_nonce, verify_attestation
from baseline import run_all as run_baselines
from config import CFG
from judge import Verdict, judge
from lane_a import lane_a_synthesis
from lane_a_refine import refine_lane_a
from lane_screen import lane_screen_replay
from lane_face import face_similarity
from lanes import lane_b_noise, lane_c_compression, load_image, quality_gate

MAX_UPLOAD_BYTES = 12 * 1024 * 1024

app = FastAPI(title="VeriLens KYC Forensics", version=CFG.version)

# The Expo app calls this from a device/emulator on an arbitrary origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class LaneOut(BaseModel):
    lane: str
    name: str
    score: float
    confidence: float
    usable: bool
    reasons: list[str]
    box: list[int] | None = None


class ImageAnalysis(BaseModel):
    sha256: str
    width: int
    height: int
    quality_usable: bool
    quality_reasons: list[str]
    jpeg_quality: int | None
    lanes: list[LaneOut]


class VerdictOut(BaseModel):
    authenticity: str
    identity: str | None
    decision: str
    confidence: float
    confidence_is_calibrated: bool
    score: float | None
    reasons: list[dict]


class AnalyzeOut(BaseModel):
    version: str
    verdict: VerdictOut
    id_image: ImageAnalysis | None = None
    selfie: ImageAnalysis | None = None


def _verdict_out(v: Verdict) -> VerdictOut:
    return VerdictOut(
        authenticity=v.authenticity,
        identity=v.identity,
        decision=v.decision,
        confidence=v.confidence,
        confidence_is_calibrated=v.confidence_is_calibrated,
        score=v.score,
        reasons=[asdict(r) for r in v.reasons],
    )


async def _read_upload(f: UploadFile) -> bytes:
    data = await f.read()
    if not data:
        raise HTTPException(400, f"'{f.filename or 'file'}' is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"'{f.filename}' exceeds {MAX_UPLOAD_BYTES // 1024 // 1024}MB")
    return data


def _analyze_one(data: bytes):
    """Run the quality gate and every lane over one image.

    Lane G (screen/print replay) runs on the ID image too, not just the
    selfie -- it used to be selfie-only because a genuine laminated/
    holographic Aadhar card false-positived against it (confirmed live).
    Lane G is now patch-wise (see lane_screen.py): it scores by how many
    spatially DIFFERENT patches show the periodic signature, so a small
    localised feature (a hologram sticker) no longer reads the same as a
    genuine full-frame screen replay, and it's safe to run everywhere again.
    """
    import hashlib

    try:
        pil, bgr = load_image(data)
    except Exception as e:  # noqa: BLE001 - any decode failure is a client error
        raise HTTPException(400, f"Could not decode image: {e}") from e

    q = quality_gate(pil, bgr)
    results = [
        refine_lane_a(lane_a_synthesis(bgr), data, bgr),
        lane_b_noise(bgr),
        lane_c_compression(pil, bgr),
        lane_screen_replay(bgr),
    ]
    h, w = bgr.shape[:2]

    analysis = ImageAnalysis(
        sha256=hashlib.sha256(data).hexdigest(),
        width=w,
        height=h,
        quality_usable=q.usable,
        quality_reasons=q.reasons,
        jpeg_quality=q.jpeg_quality,
        lanes=[
            LaneOut(
                lane=r.lane,
                name=r.name,
                score=round(r.score, 3),
                confidence=round(r.confidence, 3),
                usable=r.usable,
                reasons=r.reasons,
                box=list(r.box) if r.box else None,
            )
            for r in results
        ],
    )
    return analysis, q, results, bgr, pil


def _check_attestation(
    subject_sha256: str,
    attestation_nonce: str | None,
    attestation_signature: str | None,
    attestation_public_key: str | None,
) -> bool:
    if not (attestation_nonce and attestation_signature and attestation_public_key):
        return False
    ok, _reason = verify_attestation(
        attestation_nonce, attestation_signature, attestation_public_key, subject_sha256
    )
    return ok


@app.get("/v1/attest/nonce")
def attest_nonce():
    return issue_nonce()


@app.post("/v1/analyze/single", response_model=AnalyzeOut)
async def analyze_single(
    image: UploadFile = File(...),
    attestation_nonce: str | None = Form(None),
    attestation_signature: str | None = Form(None),
    attestation_public_key: str | None = Form(None),
):
    """Authenticity only. No identity axis - there is nothing to match against."""
    analysis, q, results, _, _ = _analyze_one(await _read_upload(image))
    verified = _check_attestation(
        analysis.sha256, attestation_nonce, attestation_signature, attestation_public_key
    )
    v = judge(q, results, attested=verified)
    return AnalyzeOut(version=CFG.version, verdict=_verdict_out(v), selfie=analysis)


@app.post("/v1/analyze", response_model=AnalyzeOut)
async def analyze(
    id_image: UploadFile = File(...),
    selfie: UploadFile = File(...),
    attestation_nonce: str | None = Form(None),
    attestation_signature: str | None = Form(None),
    attestation_public_key: str | None = Form(None),
):
    """Full KYC check: both images, worst-case authenticity, identity axis.

    Authenticity takes the WORST of the two images: a genuine selfie paired
    with a doctored ID document is still a failed check.

    Attestation is always over the selfie — it's the image injection defence
    cares about (an ID document photo is not live-captured by the user).
    """
    id_analysis, id_q, id_results, id_bgr, _ = _analyze_one(await _read_upload(id_image))
    selfie_analysis, s_q, s_results, s_bgr, _ = _analyze_one(await _read_upload(selfie))
    verified = _check_attestation(
        selfie_analysis.sha256, attestation_nonce, attestation_signature, attestation_public_key
    )

    # Authenticity: judge each image on its own, then keep the worse one.
    # A genuine selfie paired with a doctored ID is still a failed check.
    # Lane G's hard-fail gate (see judge.py) only applies to the selfie: a
    # printed ID document can legitimately carry its own periodic security
    # pattern (a guilloche background) that an FFT can't tell apart from
    # screen moire, but a live selfie has no legitimate reason to. On the
    # ID image Lane G still runs and still contributes as ordinary soft
    # evidence in the weighted average -- it just can't unilaterally force
    # a verdict there.
    rank = {"LIKELY_FAKE": 0, "INSUFFICIENT_EVIDENCE": 1, "REAL": 2}
    id_v = judge(id_q, id_results, attested=False, apply_screen_replay_hard_gate=False)
    selfie_v = judge(s_q, s_results, attested=verified)
    worse_is_id = rank[id_v.authenticity] < rank[selfie_v.authenticity]

    # Identity is orthogonal, so it is resolved once over both images and
    # then folded into the decision by the judge.
    sim, face_reasons, low_quality_face = face_similarity(id_bgr, s_bgr)

    # Re-judge the worse image with the identity signal attached, so the
    # decision reflects both axes rather than being patched afterwards.
    if worse_is_id:
        final = judge(id_q, id_results, attested=False, face_similarity=sim,
                       require_identity=True, low_quality_face=low_quality_face,
                       apply_screen_replay_hard_gate=False)
    else:
        final = judge(s_q, s_results, attested=verified, face_similarity=sim,
                       require_identity=True, low_quality_face=low_quality_face)

    Reason = type(final.reasons[0]) if final.reasons else None
    labelled = (
        [type(r)(r.lane, f"[ID] {r.text}", r.severity) for r in id_v.reasons]
        + [type(r)(r.lane, f"[Selfie] {r.text}", r.severity) for r in selfie_v.reasons]
    )
    identity_reasons = [r for r in final.reasons if r.lane in ("E", "J")]
    final.reasons = identity_reasons + labelled
    if Reason is not None:
        final.reasons += [Reason("E", t, "info") for t in face_reasons]

    worst = final

    return AnalyzeOut(
        version=CFG.version,
        verdict=_verdict_out(worst),
        id_image=id_analysis,
        selfie=selfie_analysis,
    )


@app.post("/v1/baseline")
async def baseline(image: UploadFile = File(...)):
    """Same image through the baselines and through our judge, side by side.

    The comparison the demo turns on: a commercial detector returns one
    number with no region and no reasoning, and on a locally-edited image
    where the background is intact it has been measured at chance level.
    Ours reports per-lane evidence and abstains when it cannot read the image.
    """
    data = await _read_upload(image)
    analysis, q, results, _, _ = _analyze_one(data)
    ours = judge(q, results)
    baselines = await run_baselines(data, image.filename or "upload.jpg")

    return {
        "version": CFG.version,
        "baselines": [
            {
                "name": b.name,
                "available": b.available,
                "score": b.score,
                "verdict": b.verdict,
                "detail": b.detail,
                "reasons": b.reasons,
                "explains_reasoning": False,
                "localises_region": False,
                "can_abstain": False,
            }
            for b in baselines
        ],
        "ours": {
            "name": "VeriLens",
            "available": True,
            "authenticity": ours.authenticity,
            "decision": ours.decision,
            "score": ours.score,
            "confidence": ours.confidence,
            "confidence_is_calibrated": ours.confidence_is_calibrated,
            "reasons": [asdict(r) for r in ours.reasons],
            "lanes": [
                {"lane": l.lane, "name": l.name, "score": round(l.score, 3),
                 "confidence": round(l.confidence, 3), "usable": l.usable,
                 "box": list(l.box) if l.box else None}
                for l in results
            ],
            "explains_reasoning": True,
            "localises_region": True,
            "can_abstain": True,
        },
        "image": {"sha256": analysis.sha256, "width": analysis.width, "height": analysis.height},
    }


@app.get("/v1/health")
def health():
    return {"status": "ok", "version": CFG.version}


@app.get("/v1/model-card")
def model_card():
    """What this service does, what it does not, and the numbers behind it.

    Served as an endpoint so the honesty claims are inspectable rather than
    just asserted in a README.
    """
    return {
        "version": CFG.version,
        "lanes": [
            {"id": "B", "name": "Noise residual", "trained": False,
             "reads": "regions unnaturally noise-free for their detail level"},
            {"id": "C", "name": "Compression / ELA", "trained": False,
             "reads": "recompression error inconsistent with local detail"},
            {"id": "A", "name": "Local synthesis", "trained": True,
             "reads": "patch-level locally synthesised content; trained on INP-X "
                      "exchanged images so it cannot use the global VAE artifact",
             "optional_deps": "requirements-ml.txt + weights/lane_a.pt"},
            {"id": "E", "name": "Face match", "trained": True,
             "reads": "cosine similarity between ID and selfie face embeddings",
             "optional_deps": "requirements-ml.txt"},
            {"id": "G", "name": "Screen/print replay", "trained": False,
             "reads": "patch-wise FFT moire-pattern signature of a photographed screen/"
                      "print, scored by how many spatially different patches show it "
                      "(a widespread signature reads as a genuine replay; a signature "
                      "confined to one or two patches reads as a small physical feature "
                      "like a hologram sticker, not a replay); runs on both the ID image "
                      "and the selfie; new, unvalidated against any labelled dataset, "
                      "confidence capped accordingly (CFG.screen_replay_confidence)"},
        ],
        "thresholds": {k: v for k, v in vars(CFG).items()} or asdict(CFG),
        "confidence_is_calibrated": CFG.confidence_is_calibrated,
        "known_limitations": [
            "Confidence values are raw lane agreement, NOT calibrated probabilities.",
            "Lanes B and C are intra-image consistency checks. A fully synthetic "
            "image with globally uniform statistics can pass both.",
            "No camera attribution and no PRNU reference database.",
            "Absence of capture attestation is never treated as evidence of fakery.",
            "Capture attestation is verified server-side: the client requests a "
            "single-use nonce (120s TTL) from /v1/attest/nonce, Ed25519-signs it "
            "together with the subject image's sha256 using its on-device key, and "
            "the service verifies that signature before granting any confidence "
            "bonus. The nonce store is in-memory and single-process, not a "
            "distributed store.",
            "Heavily compressed or low-resolution images return "
            "INSUFFICIENT_EVIDENCE by design rather than a guess.",
            "Lane A (trained local-synthesis detector) is wired in but needs both "
            "requirements-ml.txt and a trained weights/lane_a.pt checkpoint. Without "
            "either it abstains, leaving lanes B and C to carry the verdict.",
            "Lane E (face match) is wired in but its dependencies are optional. "
            "Without requirements-ml.txt installed no similarity is computed, so "
            "a pair check reports identity=INDETERMINATE and routes to REVIEW "
            "rather than accepting an unverified identity.",
            "A face crop below the recognition model's native 112px input "
            "resolution (lane_face.LOW_QUALITY_FACE_PX) - a common case for a "
            "low-res ID-document photo - still gets an honest similarity score, "
            "but must clear face_match_above by an extra "
            "face_match_low_quality_margin before counting as a confident MATCH; "
            "otherwise it routes to INDETERMINATE rather than accepting a weak "
            "signal.",
            "Lane A's val_acc_exchanged is measured on a held-out split of the "
            "SAME narrow, curated CelebA-HQ/INP-X distribution it trained on - "
            "manual testing against real photos outside that distribution found "
            "confident false positives (>0.95 on genuine photos) AND a confident "
            "false negative (missed an actual AI-generated photo). Lane A now "
            "restricts scanning to the detected face region (matches how it was "
            "trained; falls back to the full frame if no face detector is "
            "available) and its confidence weight is capped "
            "(CFG.lane_a_confidence_cap) so it cannot dominate the judge until "
            "it's validated on a genuinely out-of-distribution test set. This "
            "did not produce a single false ACCEPT in testing - the "
            "min_usable_lanes and lane-disagreement gates correctly routed "
            "every affected case to REVIEW instead - but it does mean higher "
            "REVIEW rates on real users until Lane A is retrained on a broader "
            "dataset.",
            "Lane G (screen/print replay) is new and unvalidated against any "
            "labelled dataset of real vs. replayed photos - reasoned about and "
            "spot-checked manually only, not measured. It was originally selfie-only "
            "because a whole-image FFT couldn't tell a genuine laminated/holographic "
            "ID card's own surface pattern apart from a real screen replay (confirmed "
            "live) - fixed by scoring patch-wise instead of whole-image, so a signal "
            "confined to a small physical feature (hologram sticker, foil strip) no "
            "longer reads the same as a widespread full-frame replay, and it now runs "
            "on both images again. Known false-positive risk remains: fine periodic "
            "real-world texture spread across MOST of the frame (mesh fabric, a "
            "striped shirt filling most of the photo) can still read as widespread. "
            "Known false-negative risk: high-DPI/anti-moire screens and good print "
            "quality. Its confidence is capped low (CFG.screen_replay_confidence) "
            "so it contributes evidence without being trusted as a solved problem.",
        ],
        "does_not_claim": [
            "Novel research. The techniques (ELA, noise residuals, robust "
            "outlier statistics) are established image forensics.",
            "Detection of manipulations that leave no local statistical trace.",
        ],
    }
