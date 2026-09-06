"""One runnable check per non-trivial path. Run: python test_service.py

Uses synthetic images so there are no fixtures to ship and the assertions
are deterministic.
"""

import hashlib
import io

import cv2
import nacl.signing
import numpy as np
from PIL import Image

from attestation import issue_nonce, verify_attestation
from config import CFG
from judge import judge
from lanes import (
    estimate_jpeg_quality,
    lane_b_noise,
    lane_c_compression,
    load_image,
    quality_gate,
)

rng = np.random.default_rng(0)


def _jpeg_bytes(arr: np.ndarray, quality: int = 92) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _textured(h=512, w=512) -> np.ndarray:
    """Noisy textured image - stands in for real sensor output."""
    base = rng.integers(60, 200, size=(h, w), dtype=np.uint8)
    base = cv2.GaussianBlur(base, (3, 3), 0)
    noise = rng.normal(0, 8, size=(h, w))
    out = np.clip(base.astype(np.float64) + noise, 0, 255).astype(np.uint8)
    return np.stack([out] * 3, axis=2)


def test_jpeg_quality_roundtrip():
    for q in (60, 75, 92):
        pil = Image.open(io.BytesIO(_jpeg_bytes(_textured(256, 256), q)))
        est = estimate_jpeg_quality(pil)
        assert est is not None, "JPEG must report a quality"
        assert abs(est - q) <= 8, f"quality estimate {est} too far from {q}"
    # PNG has no quantization table -> must return None, not a guess
    buf = io.BytesIO()
    Image.fromarray(_textured(256, 256)).save(buf, format="PNG")
    assert estimate_jpeg_quality(Image.open(buf)) is None
    print("ok  jpeg quality estimation")


def test_quality_gate_rejects_unreadable():
    tiny = _jpeg_bytes(_textured(120, 120))
    pil, bgr = load_image(tiny)
    q = quality_gate(pil, bgr)
    assert not q.usable, "120px image must not be judged"
    assert any("Resolution too low" in r for r in q.reasons)

    blurred = cv2.GaussianBlur(_textured(512, 512), (31, 31), 0)
    pil, bgr = load_image(_jpeg_bytes(blurred))
    q = quality_gate(pil, bgr)
    assert not q.usable, "heavily blurred image must not be judged"
    print("ok  quality gate rejects unreadable images")


def test_abstains_on_unreadable():
    pil, bgr = load_image(_jpeg_bytes(_textured(120, 120)))
    q = quality_gate(pil, bgr)
    v = judge(q, [lane_b_noise(bgr), lane_c_compression(pil, bgr)])
    assert v.authenticity == "INSUFFICIENT_EVIDENCE", v.authenticity
    assert v.decision == "REVIEW", v.decision
    assert v.confidence == 0.0
    print("ok  judge abstains instead of guessing")


def test_lane_b_flags_synthetic_smooth_patch():
    """A pasted, denoised region is the signature Lane B exists to catch."""
    img = _textured(512, 512)
    patch = cv2.GaussianBlur(img[160:360, 160:360], (0, 0), sigmaX=4)
    spliced = img.copy()
    spliced[160:360, 160:360] = patch

    _, bgr_clean = load_image(_jpeg_bytes(img))
    _, bgr_spliced = load_image(_jpeg_bytes(spliced))

    clean = lane_b_noise(bgr_clean)
    dirty = lane_b_noise(bgr_spliced)
    assert dirty.score > clean.score, f"spliced {dirty.score} must exceed clean {clean.score}"
    assert dirty.box is not None, "a flagged region must be localised"
    print(f"ok  lane B: clean={clean.score:.2f} spliced={dirty.score:.2f}")


def test_uncertainty_band_abstains():
    """A score between real_below and fake_above must not be forced either way."""
    from lanes import LaneResult

    mid = (CFG.real_below + CFG.fake_above) / 2
    pil, bgr = load_image(_jpeg_bytes(_textured(512, 512)))
    q = quality_gate(pil, bgr)
    assert q.usable, "control image should be readable"
    lanes = [
        LaneResult("B", "Noise residual", mid, 0.8),
        LaneResult("C", "Compression / ELA", mid, 0.8),
    ]
    v = judge(q, lanes)
    assert v.authenticity == "INSUFFICIENT_EVIDENCE", v.authenticity
    assert any("uncertainty band" in r.text for r in v.reasons)
    print("ok  uncertainty band abstains")


def test_lane_disagreement_abstains():
    from lanes import LaneResult

    pil, bgr = load_image(_jpeg_bytes(_textured(512, 512)))
    q = quality_gate(pil, bgr)
    lanes = [
        LaneResult("B", "Noise residual", 0.05, 0.9),
        LaneResult("C", "Compression / ELA", 0.95, 0.9),
    ]
    v = judge(q, lanes)
    assert v.authenticity == "INSUFFICIENT_EVIDENCE", v.authenticity
    assert any("disagree" in r.text for r in v.reasons)
    print("ok  conflicting lanes abstain")


def test_screen_replay_rejects_despite_dilution():
    """The actual bug this fixes: Lane G's confidence is deliberately capped
    low (screen_replay_confidence) so it can't dominate the weighted
    average -- but that meant a confirmed screen replay (Lane G fires hard)
    got averaged away to REAL by lanes B/C, which read a re-photographed
    screen as ordinary clean pixels and carry much higher confidence. Uses
    the exact scores a live confirmed screen replay produces (see
    HANDOFF.md #8): B/C read clean at high confidence, Lane G fires at
    ~0.39 (z~10, coverage saturated) with its capped 0.4 confidence.
    """
    from lanes import LaneResult

    pil, bgr = load_image(_jpeg_bytes(_textured(512, 512)))
    q = quality_gate(pil, bgr)
    lanes = [
        LaneResult("B", "Noise residual", 0.05, 0.95),
        LaneResult("C", "Compression / ELA", 0.05, 0.95),
        LaneResult("A", "Local synthesis", 0.10, CFG.lane_a_confidence_cap),
        LaneResult("G", "Screen/print replay", 0.39, CFG.screen_replay_confidence),
    ]
    v = judge(q, lanes)
    assert v.decision == "REJECT", f"screen replay must REJECT, got {v.decision}"
    assert v.authenticity == "LIKELY_FAKE", v.authenticity
    print("ok  confident screen replay rejects instead of being averaged away")


def test_screen_replay_hard_gate_can_be_disabled_for_id_document():
    """Found live: a real Aadhaar card's own printed security pattern
    (a guilloche background) lit up 8/16 patches at z=6.3 -> Lane G score
    ~0.17, physically indistinguishable from screen moire by an FFT alone.
    Every other lane read the same capture as clean. Auto-rejecting a real
    ID on this uncalibrated, document-print-confused signal is wrong -- the
    hard gate is selfie-only (see main.py); on the ID image it's disabled
    and Lane G's score just joins the ordinary weighted average, where its
    capped confidence lets the other clean lanes carry the verdict.
    """
    from lanes import LaneResult

    pil, bgr = load_image(_jpeg_bytes(_textured(512, 512)))
    q = quality_gate(pil, bgr)
    lanes = [
        LaneResult("B", "Noise residual", 0.05, 0.9),
        LaneResult("C", "Compression / ELA", 0.02, 0.9),
        LaneResult("A", "Local synthesis", 0.46, CFG.lane_a_confidence_cap),
        LaneResult("G", "Screen/print replay", 0.17, CFG.screen_replay_confidence),
        LaneResult("H", "Visual synthesis & replay check", 0.05, CFG.vlm_confidence_cap,
                   ["stub clean VLM read"], extra={"screen_replay": 0.05, "print_replay": 0.05, "synthetic": 0.05}),
    ]
    v = judge(q, lanes, apply_screen_replay_hard_gate=False)
    assert v.authenticity == "REAL", f"real ID with a printed pattern must not auto-fail, got {v.authenticity}"
    assert v.decision == "ACCEPT", v.decision
    print("ok  screen-replay hard gate disabled for ID document lets a real printed pattern accept")


def test_screen_replay_rejects_at_real_observed_boundary():
    """Found live: a confirmed screen replay (ID card photographed with a
    laptop screen filling the background) scored 10/16 patches at z=8.4 ->
    Lane G score ~0.297 -- below the original screen_replay_reject_above of
    0.3, so it slipped through to ACCEPT despite Lane G's own text already
    calling it a widespread moire pattern. Locks in the corrected threshold
    against this exact real observed score.
    """
    from lanes import LaneResult

    pil, bgr = load_image(_jpeg_bytes(_textured(512, 512)))
    q = quality_gate(pil, bgr)
    lanes = [
        LaneResult("B", "Noise residual", 0.05, 0.9),
        LaneResult("C", "Compression / ELA", 0.02, 0.9),
        LaneResult("A", "Local synthesis", 0.01, CFG.lane_a_confidence_cap),
        LaneResult("G", "Screen/print replay", 0.297, CFG.screen_replay_confidence),
    ]
    v = judge(q, lanes)
    assert v.decision == "REJECT", f"real observed screen-replay score must REJECT, got {v.decision}"
    print("ok  real observed screen-replay boundary score (0.297) rejects")


def test_lane_a_false_positive_alone_does_not_abstain():
    """The other bug found via live testing on a real ID+selfie: Lane A
    confidently false-positives on real photos off its training
    distribution (score 1.00, see HANDOFF.md), which conflicted with lanes
    B/C/G reading the same photo as clean and blew the disagreement spread
    past max_disagreement -- routing every real capture Lane A happens to
    misfire on to REVIEW. Lane A's confidence is already capped
    (lane_a_confidence_cap) precisely because it's known-unreliable
    off-distribution, so its own noise must not alone count as "the lanes
    disagree" when the validated lanes (B, C) agree with each other.
    """
    from lanes import LaneResult

    pil, bgr = load_image(_jpeg_bytes(_textured(512, 512)))
    q = quality_gate(pil, bgr)
    lanes = [
        LaneResult("B", "Noise residual", 0.05, 0.9),
        LaneResult("C", "Compression / ELA", 0.03, 0.9),
        LaneResult("A", "Local synthesis", 1.00, CFG.lane_a_confidence_cap),
        LaneResult("G", "Screen/print replay", 0.10, CFG.screen_replay_confidence),
    ]
    v = judge(q, lanes)
    assert v.authenticity == "REAL", (
        f"validated lanes agree real; a capped Lane A false positive must not "
        f"force an abstain, got {v.authenticity}"
    )
    assert not any("disagree" in r.text for r in v.reasons), v.reasons
    print("ok  Lane A's known-unreliable false positive doesn't alone trigger disagreement-abstain")


def test_lane_a_does_not_vote():
    """Stage 2, pinned to the measured case that motivated it (PLAN.md
    Finding 2): mtowju5afd5obu's genuine ID image scored A=0.87@0.50,
    C=0.03@0.70, G=0.26@0.40. With Lane A voting, the aggregate + spread
    force a disagreement-abstain (REVIEW) -- a genuine physical card fails.
    With Lane A's vote withheld (voting=False), the aggregate drops to
    ~0.11 -> REAL/ACCEPT. Lane A must still show up in reasons: it stays
    visible as evidence, it just doesn't get a vote.
    """
    from lanes import LaneResult

    pil, bgr = load_image(_jpeg_bytes(_textured(512, 512)))
    q = quality_gate(pil, bgr)
    lanes = [
        LaneResult("A", "Local synthesis (trained)", 0.87, CFG.lane_a_confidence_cap, ["stub"], voting=False),
        LaneResult("C", "Compression / ELA", 0.03, 0.70),
        LaneResult("G", "Screen/print replay", 0.26, CFG.screen_replay_confidence),
        LaneResult("H", "Visual synthesis & replay check", 0.05, CFG.vlm_confidence_cap,
                   ["stub clean VLM read"], extra={"screen_replay": 0.05, "print_replay": 0.05, "synthetic": 0.05}),
    ]
    # This models the ID image (mtowju5afd5obu): Lane G's hard gate is
    # selfie-only (see judge.py/main.py), so it's disabled here exactly as
    # main.py disables it for the ID -- otherwise Lane G's own 0.26 (>
    # screen_replay_reject_above=0.15) would hard-fail before the judge
    # ever reaches the weighted average this test is about.
    v = judge(q, lanes, apply_screen_replay_hard_gate=False)
    assert v.authenticity == "REAL", f"Lane A must not force a disagreement-abstain, got {v.authenticity}"
    assert v.decision == "ACCEPT", v.decision
    assert any(r.lane == "A" for r in v.reasons), "Lane A must stay visible in reasons even without a vote"
    print(f"ok  Lane A stays visible but doesn't vote: aggregate={v.score:.3f} decision={v.decision}")


def test_lane_h_screen_replay_rejects_id_document():
    """4 of 6 real attacks in the measured sample arrive through the ID
    image (PLAN.md Finding 4). Lane H's screen_replay must hard-fail the ID
    document even though apply_screen_replay_hard_gate=False is passed for
    it -- that flag exists only to suppress Lane G's guilloche false
    positive, not to blind the judge to a screen-replayed ID (see
    judge.py's vlm_hit block).
    """
    from lanes import LaneResult

    pil, bgr = load_image(_jpeg_bytes(_textured(512, 512)))
    q = quality_gate(pil, bgr)
    lanes = [
        LaneResult("B", "Noise residual", 0.02, 0.9),
        LaneResult("C", "Compression / ELA", 0.03, 0.9),
        LaneResult("G", "Screen/print replay", 0.10, CFG.screen_replay_confidence),
        LaneResult(
            "H", "Visual synthesis & replay check", 1.0, CFG.vlm_confidence_cap,
            ["VLM cues: browser_tabs, window_chrome, thumbnail_filmstrip."],
            extra={"screen_replay": 1.0, "print_replay": 0.0, "synthetic": 0.0},
        ),
    ]
    v = judge(q, lanes, apply_screen_replay_hard_gate=False)
    assert v.decision == "REJECT", f"Lane H screen_replay must hard-fail the ID image, got {v.decision}"
    assert v.authenticity == "LIKELY_FAKE", v.authenticity
    assert any(r.lane == "H" for r in v.reasons), v.reasons
    print("ok  Lane H screen_replay hard-fails an ID document despite Lane G's gate being off")


def test_lane_h_print_replay_ignored_on_id_document():
    """Measured (PLAN.md Finding 4): a genuine paper Aadhaar scored
    print_replay=0.95 -- correctly, it really is printed paper. Counting
    that on the ID image would false-reject a real document, exactly the
    trap Lane G's guilloche false positive taught. is_id_document=True
    must drop print_replay from both the lane's own score and the judge's
    hard gate; the raw value must still be visible in `extra` for
    diagnostics.
    """
    import os
    import tempfile
    from pathlib import Path
    from unittest.mock import patch

    import lane_h_vlm
    from lanes import LaneResult

    parsed = {
        "screen_replay": 0.05, "print_replay": 0.95, "synthetic": 0.05,
        "cues": ["halftone_dots", "paper_fibre", "page_curl"],
    }
    prev_key = os.environ.get("GROQ_API_KEY")
    os.environ["GROQ_API_KEY"] = "test-key"
    try:
        with patch.object(lane_h_vlm, "_CACHE_DIR", Path(tempfile.mkdtemp())), \
             patch.object(lane_h_vlm, "_downscale_jpeg_b64", return_value="stub"), \
             patch.object(lane_h_vlm, "_query", return_value=(parsed, None)):
            r = lane_h_vlm.lane_h_vlm(b"id-card-stub-bytes", np.zeros((64, 64, 3), np.uint8), is_id_document=True)
    finally:
        if prev_key is not None:
            os.environ["GROQ_API_KEY"] = prev_key
        else:
            os.environ.pop("GROQ_API_KEY", None)

    assert r.score < CFG.vlm_replay_reject_above, f"print_replay must not leak into the ID score, got {r.score}"
    assert r.extra["print_replay"] == 0.95, "the raw value must still be visible for diagnostics"

    pil, bgr = load_image(_jpeg_bytes(_textured(512, 512)))
    q = quality_gate(pil, bgr)
    lanes = [
        LaneResult("B", "Noise residual", 0.02, 0.9),
        LaneResult("C", "Compression / ELA", 0.03, 0.9),
        r,
    ]
    v = judge(q, lanes, apply_screen_replay_hard_gate=False)
    assert v.decision != "REJECT", f"a genuine printed ID must not hard-fail on print_replay, got {v.decision}"
    print("ok  Lane H ignores print_replay on the ID document (genuine paper Aadhaar case)")


def test_lane_h_print_replay_rejects_selfie():
    """On the selfie (not an ID document), print_replay is a valid signal
    -- nobody's live selfie is printed paper -- so it must both count in
    the lane's own aggregate score and hard-fail via the judge's
    selfie-only gate (apply_screen_replay_hard_gate defaults True there).
    """
    import os
    import tempfile
    from pathlib import Path
    from unittest.mock import patch

    import lane_h_vlm
    from lanes import LaneResult

    parsed = {"screen_replay": 0.05, "print_replay": 0.95, "synthetic": 0.05, "cues": ["halftone_dots"]}
    prev_key = os.environ.get("GROQ_API_KEY")
    os.environ["GROQ_API_KEY"] = "test-key"
    try:
        with patch.object(lane_h_vlm, "_CACHE_DIR", Path(tempfile.mkdtemp())), \
             patch.object(lane_h_vlm, "_downscale_jpeg_b64", return_value="stub"), \
             patch.object(lane_h_vlm, "_query", return_value=(parsed, None)):
            r = lane_h_vlm.lane_h_vlm(b"selfie-stub-bytes", np.zeros((64, 64, 3), np.uint8), is_id_document=False)
    finally:
        if prev_key is not None:
            os.environ["GROQ_API_KEY"] = prev_key
        else:
            os.environ.pop("GROQ_API_KEY", None)

    assert r.score >= CFG.vlm_replay_reject_above, f"print_replay must count toward a selfie's own score, got {r.score}"

    pil, bgr = load_image(_jpeg_bytes(_textured(512, 512)))
    q = quality_gate(pil, bgr)
    lanes = [
        LaneResult("B", "Noise residual", 0.02, 0.9),
        LaneResult("C", "Compression / ELA", 0.03, 0.9),
        r,
    ]
    v = judge(q, lanes)  # apply_screen_replay_hard_gate defaults True (selfie)
    assert v.decision == "REJECT", f"print_replay must hard-fail a selfie, got {v.decision}"
    print("ok  Lane H print_replay hard-fails a selfie")


def test_vlm_rate_limited_abstains_not_guesses():
    """The bug this fixes: the retired lane_a_refine.py silently fell back
    to Lane A's raw (possibly wrong) score on any Groq failure, including a
    429. Lane H must instead retry once (after sleeping the parsed
    Retry-After delay) and then ABSTAIN with confidence 0.0 and a visible
    reason -- never fall through to a guessed score.
    """
    import os
    import tempfile
    from pathlib import Path
    from unittest.mock import MagicMock, patch

    import lane_h_vlm

    class _FakeResponse:
        status_code = 429
        text = '{"error": "Please try again in 0.01s"}'

    fake_client = MagicMock()
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__ = MagicMock(return_value=False)
    fake_client.post = MagicMock(return_value=_FakeResponse())

    prev_key = os.environ.get("GROQ_API_KEY")
    os.environ["GROQ_API_KEY"] = "test-key"
    try:
        with patch.object(lane_h_vlm, "_CACHE_DIR", Path(tempfile.mkdtemp())), \
             patch.object(lane_h_vlm, "_downscale_jpeg_b64", return_value="stub"), \
             patch.object(lane_h_vlm.httpx, "Client", return_value=fake_client), \
             patch("lane_h_vlm.time.sleep") as mock_sleep:
            r = lane_h_vlm.lane_h_vlm(b"rate-limited-stub-bytes", np.zeros((64, 64, 3), np.uint8), is_id_document=False)
    finally:
        if prev_key is not None:
            os.environ["GROQ_API_KEY"] = prev_key
        else:
            os.environ.pop("GROQ_API_KEY", None)

    assert r.score == 0.0 and r.confidence == 0.0, f"a rate-limited lane must abstain, not guess, got {r}"
    assert mock_sleep.call_count == 1, "must sleep and retry exactly once after the first 429"
    assert any("rate-limit" in x.lower() or "429" in x or "abstain" in x.lower() for x in r.reasons), r.reasons
    assert fake_client.post.call_count == 2, "must attempt exactly one retry (2 total calls)"
    print("ok  Lane H abstains (never guesses) after being rate-limited twice")


def test_attestation_never_lowers():
    """Absence of attestation must not be treated as evidence of fakery."""
    from lanes import LaneResult

    pil, bgr = load_image(_jpeg_bytes(_textured(512, 512)))
    q = quality_gate(pil, bgr)
    lanes = [
        LaneResult("B", "Noise residual", 0.05, 0.8),
        LaneResult("C", "Compression / ELA", 0.10, 0.8),
    ]
    plain = judge(q, lanes, attested=False)
    signed = judge(q, lanes, attested=True)
    assert plain.authenticity == "REAL" == signed.authenticity
    assert signed.confidence >= plain.confidence, "attestation must not reduce confidence"
    print(f"ok  attestation raises only: {plain.confidence:.2f} -> {signed.confidence:.2f}")


def test_identity_axis_independent():
    """A real photo of the wrong person must still fail."""
    from lanes import LaneResult

    pil, bgr = load_image(_jpeg_bytes(_textured(512, 512)))
    q = quality_gate(pil, bgr)
    lanes = [
        LaneResult("B", "Noise residual", 0.05, 0.8),
        LaneResult("C", "Compression / ELA", 0.10, 0.8),
    ]
    v = judge(q, lanes, face_similarity=0.05)
    assert v.authenticity == "REAL", v.authenticity
    assert v.identity == "MISMATCH", v.identity
    assert v.decision == "REJECT", "authentic pixels + wrong face must reject"
    print("ok  identity axis is independent of authenticity")


def test_mismatch_rejects_even_when_authenticity_abstains():
    """Real bug found live: lanes disagreeing on authenticity (Gate 3) used
    to abstain to REVIEW unconditionally, discarding an already-confirmed
    identity MISMATCH from Lane E along the way. A wrong-person selfie must
    REJECT regardless of whether the pixel-forensic lanes could agree on
    real-vs-fake -- those are independent axes, and identity is the more
    settled one here.
    """
    from lanes import LaneResult

    pil, bgr = load_image(_jpeg_bytes(_textured(512, 512)))
    q = quality_gate(pil, bgr)
    # Deliberately disagreeing lanes -> Gate 3 (lane disagreement) fires
    lanes = [
        LaneResult("B", "Noise residual", 0.05, 0.9),
        LaneResult("C", "Compression / ELA", 0.95, 0.9),
    ]
    v = judge(q, lanes, face_similarity=0.05)  # below face_mismatch_below -> MISMATCH
    assert v.authenticity == "INSUFFICIENT_EVIDENCE", v.authenticity
    assert v.identity == "MISMATCH", v.identity
    assert v.decision == "REJECT", (
        "identity MISMATCH must reject even when authenticity abstains, got " + v.decision
    )
    print("ok  identity MISMATCH rejects even when authenticity gates abstain")


def test_low_quality_face_needs_wider_match_margin():
    """A similarity that clears face_match_above off a low-res crop (e.g. a
    small ID-document photo) must NOT be treated as confidently as the same
    score off a full-resolution face -- it needs face_match_low_quality_margin
    of extra headroom, else INDETERMINATE (never a silent downgrade to
    MISMATCH -- an unreliable signal is unknown, not evidence of the negative).
    """
    from lanes import LaneResult

    pil, bgr = load_image(_jpeg_bytes(_textured(512, 512)))
    q = quality_gate(pil, bgr)
    lanes = [
        LaneResult("B", "Noise residual", 0.05, 0.8),
        LaneResult("C", "Compression / ELA", 0.10, 0.8),
    ]
    marginal_sim = CFG.face_match_above + 0.02  # clears the normal bar...
    assert marginal_sim < CFG.face_match_above + CFG.face_match_low_quality_margin  # ...not the wide one

    v_normal = judge(q, lanes, face_similarity=marginal_sim, low_quality_face=False)
    assert v_normal.identity == "MATCH", v_normal.identity

    v_low_quality = judge(q, lanes, face_similarity=marginal_sim, low_quality_face=True)
    assert v_low_quality.identity == "INDETERMINATE", v_low_quality.identity

    # comfortably above even the widened bar: low-res crop shouldn't matter
    strong_sim = CFG.face_match_above + CFG.face_match_low_quality_margin + 0.05
    v_strong = judge(q, lanes, face_similarity=strong_sim, low_quality_face=True)
    assert v_strong.identity == "MATCH", v_strong.identity
    print("ok  low-quality face crop needs a wider match margin")



def test_pair_without_face_match_never_accepts():
    """A KYC pair check that cannot verify the face must not ACCEPT.

    identity=None means "not applicable" (single image). For a pair it is
    "unverified", which is a review case, not a pass.
    """
    from lanes import LaneResult

    pil, bgr = load_image(_jpeg_bytes(_textured(512, 512)))
    q = quality_gate(pil, bgr)
    lanes = [
        LaneResult("B", "Noise residual", 0.05, 0.8),
        LaneResult("C", "Compression / ELA", 0.10, 0.8),
        LaneResult("H", "Visual synthesis & replay check", 0.05, CFG.vlm_confidence_cap,
                   ["stub clean VLM read"], extra={"screen_replay": 0.05, "print_replay": 0.05, "synthetic": 0.05}),
    ]
    v = judge(q, lanes, face_similarity=None, require_identity=True)
    assert v.authenticity == "REAL", v.authenticity
    assert v.identity == "INDETERMINATE", v.identity
    assert v.decision == "REVIEW", "unverified identity must not accept"
    # single-image path is unaffected: identity genuinely does not apply
    single = judge(q, lanes, face_similarity=None, require_identity=False)
    assert single.identity is None and single.decision == "ACCEPT"
    print("ok  pair without face match routes to REVIEW")


def test_attestation_verifies_valid_signature():
    """A correctly signed nonce+subject-hash must verify."""
    subject_sha256 = hashlib.sha256(b"some image bytes").hexdigest()
    n = issue_nonce()
    key = nacl.signing.SigningKey.generate()
    message = bytes.fromhex(n["nonce"]) + bytes.fromhex(subject_sha256)
    sig = key.sign(message).signature.hex()
    pub = key.verify_key.encode().hex()

    ok, reason = verify_attestation(n["nonce"], sig, pub, subject_sha256)
    assert ok, reason
    print("ok  valid attestation verifies")


def test_attestation_nonce_is_single_use():
    subject_sha256 = hashlib.sha256(b"some image bytes").hexdigest()
    n = issue_nonce()
    key = nacl.signing.SigningKey.generate()
    message = bytes.fromhex(n["nonce"]) + bytes.fromhex(subject_sha256)
    sig = key.sign(message).signature.hex()
    pub = key.verify_key.encode().hex()

    ok1, _ = verify_attestation(n["nonce"], sig, pub, subject_sha256)
    ok2, reason2 = verify_attestation(n["nonce"], sig, pub, subject_sha256)
    assert ok1 and not ok2, "replaying the same nonce must fail"
    print("ok  nonce is single-use")


def test_attestation_rejects_unknown_nonce():
    subject_sha256 = hashlib.sha256(b"some image bytes").hexdigest()
    key = nacl.signing.SigningKey.generate()
    message = bytes.fromhex("00" * 32) + bytes.fromhex(subject_sha256)
    sig = key.sign(message).signature.hex()
    pub = key.verify_key.encode().hex()

    ok, reason = verify_attestation("ab" * 32, sig, pub, subject_sha256)
    assert not ok, "a made-up nonce must never verify"
    print("ok  unknown nonce rejected")


def test_attestation_rejects_wrong_signature():
    subject_sha256 = hashlib.sha256(b"some image bytes").hexdigest()
    other_sha256 = hashlib.sha256(b"different image bytes").hexdigest()

    n = issue_nonce()
    key = nacl.signing.SigningKey.generate()
    message = bytes.fromhex(n["nonce"]) + bytes.fromhex(subject_sha256)
    sig = key.sign(message).signature.hex()
    pub = key.verify_key.encode().hex()
    # tampered subject hash: signature no longer covers this message
    ok, _ = verify_attestation(n["nonce"], sig, pub, other_sha256)
    assert not ok, "signature over a different subject hash must fail"

    n2 = issue_nonce()
    wrong_key = nacl.signing.SigningKey.generate()
    message2 = bytes.fromhex(n2["nonce"]) + bytes.fromhex(subject_sha256)
    sig2 = key.sign(message2).signature.hex()  # signed with `key`, verified against `wrong_key`
    wrong_pub = wrong_key.verify_key.encode().hex()
    ok2, _ = verify_attestation(n2["nonce"], sig2, wrong_pub, subject_sha256)
    assert not ok2, "signature from the wrong keypair must fail"
    print("ok  wrong signature / wrong keypair rejected")


def test_pair_endpoint_runs_screen_replay_on_both_images():
    """Lane G runs on both images now that it's patch-wise (see
    test_lane_screen.py's test_localised_pattern_scores_lower_than_widespread
    for the fix itself) -- it was briefly selfie-only after a genuine
    laminated/holographic ID card false-positived against the old
    whole-image version, but the patch-wise redesign scores by how many
    spatially different patches show the signature, so a small physical
    feature (hologram sticker) no longer reads the same as a full-frame
    replay and it's safe to run everywhere again.
    """
    from fastapi.testclient import TestClient

    import main

    client = TestClient(main.app)
    image_bytes = _jpeg_bytes(_textured(512, 512))

    r = client.post(
        "/v1/analyze",
        files={
            "id_image": ("id.jpg", image_bytes, "image/jpeg"),
            "selfie": ("s.jpg", image_bytes, "image/jpeg"),
        },
    )
    body = r.json()
    id_lanes = {l["lane"] for l in body["id_image"]["lanes"]}
    selfie_lanes = {l["lane"] for l in body["selfie"]["lanes"]}
    assert "G" in id_lanes, f"Lane G must run on the ID image, got lanes {id_lanes}"
    assert "G" in selfie_lanes, f"Lane G must run on the selfie, got lanes {selfie_lanes}"
    print("ok  Lane G (screen/print replay) runs on both the ID image and the selfie")


def test_analyze_endpoint_honours_form_attestation():
    """Regression test for a real bug: attestation_nonce/signature/public_key
    were plain `str | None` params on a route that also takes `File(...)`.
    FastAPI then parses them as QUERY params, not form fields, so a client
    sending them as multipart form data (the only sane way to send them
    alongside an upload) silently got `attested=False` no matter what it
    sent. Direct calls to verify_attestation() (the tests above) can't catch
    this - it's a wiring bug in main.py's route signature, not the crypto.
    Must go through the actual FastAPI app, not the bare function.
    """
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    import main
    from lanes import LaneResult

    # Neutralise lane A: if weights/lane_a.pt happens to be installed in this
    # environment, the real trained model correctly scores a synthetic
    # noise texture as locally-synthesised (it looks nothing like a real
    # photo), which triggers the lane-disagreement abstain gate before the
    # judge ever reaches the attested-bonus branch. This test is only about
    # the FastAPI routing layer, not lane behaviour, so pin all three lanes
    # to agree.
    agreeable = LaneResult("X", "stub", 0.1, 0.9, ["stubbed for this test"])

    client = TestClient(main.app)
    image_bytes = _jpeg_bytes(_textured())
    subject_sha256 = hashlib.sha256(image_bytes).hexdigest()

    nonce = client.get("/v1/attest/nonce").json()["nonce"]
    key = nacl.signing.SigningKey.generate()
    message = bytes.fromhex(nonce) + bytes.fromhex(subject_sha256)
    sig = key.sign(message).signature.hex()
    pub = key.verify_key.encode().hex()

    with patch.object(main, "lane_a_synthesis", return_value=agreeable), \
         patch.object(main, "lane_b_noise", return_value=agreeable), \
         patch.object(main, "lane_c_compression", return_value=agreeable):
        r = client.post(
            "/v1/analyze/single",
            files={"image": ("s.jpg", image_bytes, "image/jpeg")},
            data={
                "attestation_nonce": nonce,
                "attestation_signature": sig,
                "attestation_public_key": pub,
            },
        )
    reasons = r.json()["verdict"]["reasons"]
    d_reasons = [x for x in reasons if x["lane"] == "D"]
    assert d_reasons, (
        "a valid attestation sent as multipart form data must be honoured "
        "by the /v1/analyze/single route - if this fails, the route's "
        "attestation params probably lost their Form(...) marker again"
    )
    print("ok  /v1/analyze/single honours attestation sent as real form data")


if __name__ == "__main__":
    for fn in [
        test_jpeg_quality_roundtrip,
        test_quality_gate_rejects_unreadable,
        test_abstains_on_unreadable,
        test_lane_b_flags_synthetic_smooth_patch,
        test_uncertainty_band_abstains,
        test_lane_disagreement_abstains,
        test_screen_replay_rejects_despite_dilution,
        test_screen_replay_hard_gate_can_be_disabled_for_id_document,
        test_screen_replay_rejects_at_real_observed_boundary,
        test_lane_a_false_positive_alone_does_not_abstain,
        test_lane_a_does_not_vote,
        test_lane_h_screen_replay_rejects_id_document,
        test_lane_h_print_replay_ignored_on_id_document,
        test_lane_h_print_replay_rejects_selfie,
        test_vlm_rate_limited_abstains_not_guesses,
        test_attestation_never_lowers,
        test_identity_axis_independent,
        test_mismatch_rejects_even_when_authenticity_abstains,
        test_low_quality_face_needs_wider_match_margin,
        test_pair_without_face_match_never_accepts,
        test_attestation_verifies_valid_signature,
        test_attestation_nonce_is_single_use,
        test_attestation_rejects_unknown_nonce,
        test_attestation_rejects_wrong_signature,
        test_pair_endpoint_runs_screen_replay_on_both_images,
        test_analyze_endpoint_honours_form_attestation,
    ]:
        fn()
    print("\nall checks passed")
