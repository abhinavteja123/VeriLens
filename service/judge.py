"""Rule-based judge. Combines lane outputs into a verdict.

Deliberately rules, not a learned meta-model: there is no honest data to
train one on yet, and rules can state *why* they concluded something.

Three independent axes, because conflating them is how detectors produce
nonsense. "The selfie is a real photo of the wrong person" and "the selfie
is an AI-generated image of the right person" are different failures and
need different handling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from config import CFG
from lanes import LaneResult, QualityReport

Authenticity = Literal["REAL", "LIKELY_FAKE", "INSUFFICIENT_EVIDENCE"]
Identity = Literal["MATCH", "MISMATCH", "INDETERMINATE"]
Decision = Literal["ACCEPT", "REJECT", "REVIEW"]


@dataclass
class Reason:
    lane: str
    text: str
    severity: Literal["info", "warn", "critical"]


@dataclass
class Verdict:
    authenticity: Authenticity
    identity: Identity | None  # None when only one image was supplied
    decision: Decision
    confidence: float
    confidence_is_calibrated: bool
    score: float | None  # aggregated lane score, None when abstaining early
    reasons: list[Reason] = field(default_factory=list)


def _abstain(reasons: list[Reason], identity: Identity | None) -> Verdict:
    """Authenticity couldn't be determined (bad quality, too few usable
    lanes, lane disagreement, or an uncertain aggregate score) -- but a
    confirmed identity MISMATCH is an independent, already-settled fact from
    Lane E, not entangled with any of those pixel-forensic uncertainties. A
    real photo of the wrong person must still REJECT even when the pixels'
    authenticity is unknown -- abstaining to REVIEW here would silently
    drop a confident MISMATCH the same way every early-return path used to.
    """
    return Verdict(
        authenticity="INSUFFICIENT_EVIDENCE",
        identity=identity,
        decision="REJECT" if identity == "MISMATCH" else "REVIEW",
        confidence=0.0,
        confidence_is_calibrated=CFG.confidence_is_calibrated,
        score=None,
        reasons=reasons,
    )


def judge(
    quality: QualityReport,
    lane_results: list[LaneResult],
    *,
    attested: bool = False,
    face_similarity: float | None = None,
    require_identity: bool = False,
    low_quality_face: bool = False,
    apply_screen_replay_hard_gate: bool = True,
) -> Verdict:
    reasons: list[Reason] = []

    identity: Identity | None = None
    if face_similarity is not None:
        match_bar = CFG.face_match_above + (CFG.face_match_low_quality_margin if low_quality_face else 0.0)
        if face_similarity >= match_bar:
            identity = "MATCH"
            reasons.append(Reason("E", f"Selfie matches ID photo (similarity {face_similarity:.2f}).", "info"))
        elif low_quality_face and face_similarity >= CFG.face_match_above:
            identity = "INDETERMINATE"
            reasons.append(Reason(
                "E",
                f"Similarity {face_similarity:.2f} clears the normal match bar "
                f"({CFG.face_match_above:.2f}) but the face crop was low-resolution, "
                f"which needs {match_bar:.2f}+ to count as a confident match. "
                "Routing to review rather than accepting a weak signal.",
                "warn",
            ))
        elif face_similarity <= CFG.face_mismatch_below:
            identity = "MISMATCH"
            reasons.append(Reason("E", f"Selfie does NOT match ID photo (similarity {face_similarity:.2f}).", "critical"))
        else:
            identity = "INDETERMINATE"
            reasons.append(Reason("E", f"Face match inconclusive (similarity {face_similarity:.2f}).", "warn"))
    elif require_identity:
        # A pair check with no computable similarity is NOT the same as a
        # single-image check where identity does not apply. Identity is
        # required here and unknown, so the case must go to a human.
        identity = "INDETERMINATE"
        reasons.append(
            Reason("E", "Identity could not be verified: no face similarity was computed. "
                        "If the ID document photo doesn't show a face (e.g. the back of the "
                        "card, or a portrait too small to read), photograph the FRONT of the "
                        "physical card with the printed photo clearly visible and resubmit. "
                        "Routing to review rather than accepting an unverified match.", "warn")
        )

    # Gate 1: is the image readable at all? Abstaining here is the whole
    # point -- a verdict on a destroyed image is a fabricated verdict.
    if not quality.usable:
        for r in quality.reasons:
            reasons.append(Reason("Q", r, "warn"))
        reasons.append(Reason("Q", "Abstaining: image quality too low to support a verdict.", "warn"))
        return _abstain(reasons, identity)

    # Gate 2: enough independent lanes to cross-check each other?
    # r.voting excludes Lane A: measured anti-correlated with ground truth
    # (PLAN.md Finding 2) and demonstrably the cause of a genuine pair
    # failing (0.87 at confidence 0.5 pushed the aggregate 0.001 over
    # real_below on its own). It stays fully visible below via the
    # unfiltered lane_results loop -- only its vote is withheld.
    usable = [r for r in lane_results if r.usable and r.voting]
    for r in lane_results:
        sev = "warn" if r.score >= CFG.fake_above else "info"
        for text in r.reasons:
            reasons.append(Reason(r.lane, text, sev))
        if not r.usable:
            reasons.append(
                Reason(r.lane, f"Lane abstained (confidence {r.confidence:.2f} below "
                               f"{CFG.min_lane_confidence:.2f}).", "warn")
            )

    # A confident, widespread screen/print-replay signature (Lane G) must
    # not be silently averaged away by lanes B/C, which read a
    # re-photographed screen as ordinary clean pixels and would dilute a
    # genuine replay down to "REAL" -- same mistake an identity MISMATCH
    # used to suffer before its own carve-out.
    #
    # Restricted to apply_screen_replay_hard_gate callers only (main.py:
    # the selfie, not the ID document). Found live: a real Aadhaar card's
    # printed security pattern (a guilloche background, common on ID
    # cards) lit up 8/16 patches (z=6.3) -- physically indistinguishable
    # from screen pixel-grid moire by an FFT alone, and Lane G is
    # explicitly "new and unvalidated" by its own docstring. That
    # false-positive class is a document-print phenomenon, not a selfie
    # one, so the hard gate only fires where the actual replay/deepfake
    # threat is: a live selfie has no legitimate reason to contain a
    # widespread periodic security pattern the way a printed ID does.
    screen_hit = None
    if apply_screen_replay_hard_gate:
        screen_hit = next(
            (r for r in usable if r.lane == "G" and r.score >= CFG.screen_replay_reject_above),
            None,
        )

    # Lane H (VLM) ORs into the same hard-fail path, but on a DIFFERENT
    # condition than Lane G -- do not conflate the two. Lane H's
    # screen_replay is checked on BOTH images, unconditionally:
    # apply_screen_replay_hard_gate=False for the ID image exists only to
    # suppress Lane G's guilloche false positive (a real ID's own printed
    # security pattern reads as FFT moire); it must not also blind the
    # judge to a screen-replayed ID document, which is how 4 of the 6 real
    # attacks in the measured sample arrive (PLAN.md Finding 4/design
    # decision 5). Lane H's print_replay, by contrast, only hard-fails when
    # apply_screen_replay_hard_gate is True (the selfie): a genuine PRINTED
    # ID is supposed to read as printed (measured print_replay=0.95 on a
    # real Aadhaar) -- exactly Lane G's guilloche trap again -- but a
    # genuine selfie never legitimately does.
    vlm_hit = None
    vlm_field = None
    for r in usable:
        if r.lane != "H":
            continue
        if r.extra.get("screen_replay", 0.0) >= CFG.vlm_replay_reject_above:
            vlm_hit, vlm_field = r, "screen_replay"
            break
        if apply_screen_replay_hard_gate and r.extra.get("print_replay", 0.0) >= CFG.vlm_replay_reject_above:
            vlm_hit, vlm_field = r, "print_replay"
            break

    hard_hit = screen_hit or vlm_hit
    if hard_hit is not None:
        if hard_hit is screen_hit:
            reasons.append(Reason(
                "G", f"Screen/print replay signature (score {screen_hit.score:.2f}) is treated "
                     "as an independent hard fail, not averaged against other lanes.", "critical",
            ))
            hard_conf = CFG.screen_replay_confidence
        else:
            reasons.append(Reason(
                "H", f"VLM {vlm_field} score {hard_hit.extra.get(vlm_field, 0.0):.2f} is treated "
                     "as an independent hard fail, not averaged against other lanes.", "critical",
            ))
            hard_conf = CFG.vlm_confidence_cap
        severity_order = {"critical": 0, "warn": 1, "info": 2}
        reasons.sort(key=lambda r: severity_order[r.severity])
        return Verdict(
            authenticity="LIKELY_FAKE",
            identity=identity,
            decision="REJECT",
            confidence=hard_conf,
            confidence_is_calibrated=CFG.confidence_is_calibrated,
            score=round(hard_hit.score, 3),
            reasons=reasons,
        )

    if len(usable) < CFG.min_usable_lanes:
        reasons.append(
            Reason("J", f"Abstaining: only {len(usable)} of {len(lane_results)} lanes could "
                        f"read this image; need {CFG.min_usable_lanes} to cross-check.", "warn")
        )
        return _abstain(reasons, identity)

    scores = np.array([r.score for r in usable], dtype=float)
    weights = np.array([r.confidence for r in usable], dtype=float)
    agg = float(np.average(scores, weights=weights))

    # Gate 3: do the lanes actually agree? Averaging away a genuine conflict
    # manufactures false confidence, so a real disagreement abstains instead.
    spread = float(np.sqrt(np.average((scores - agg) ** 2, weights=weights)))

    # But: lanes whose confidence is deliberately capped (CFG.
    # lane_a_confidence_cap, CFG.screen_replay_confidence) are ALREADY
    # marked known-unreliable/unvalidated -- Lane A in particular has
    # confirmed, documented false positives on real photos outside its
    # training distribution (see HANDOFF.md). One capped lane's own noise
    # disagreeing with everything else is not the same signal as two
    # validated lanes genuinely conflicting, so it must not alone trigger
    # this gate -- that would route every real photo Lane A false-positives
    # on to REVIEW, defeating the point of capping its weight to begin
    # with. Disagreement is judged on the lanes that clear a real trust
    # bar; capped lanes still fully count in the aggregate score above.
    core = [r for r in usable if r.confidence >= CFG.core_disagreement_min_confidence]
    if len(core) >= 2:
        core_scores = np.array([r.score for r in core], dtype=float)
        core_weights = np.array([r.confidence for r in core], dtype=float)
        core_agg = float(np.average(core_scores, weights=core_weights))
        disagree_spread = float(np.sqrt(np.average((core_scores - core_agg) ** 2, weights=core_weights)))
    else:
        disagree_spread = spread  # not enough trusted lanes to judge agreement separately

    if disagree_spread > CFG.max_disagreement:
        reasons.append(
            Reason("J", f"Abstaining: lanes disagree (spread {disagree_spread:.2f} > "
                        f"{CFG.max_disagreement:.2f}). Conflicting evidence.", "warn")
        )
        v = _abstain(reasons, identity)
        v.score = agg
        return v

    base_conf = float(np.mean(weights)) * (1.0 - min(spread / CFG.max_disagreement, 1.0) * 0.5)
    if attested:
        # Attestation RAISES confidence only. Its absence is never evidence
        # of fakery -- almost every genuine photo carries no attestation.
        base_conf = min(1.0, base_conf + CFG.attested_bonus)
        reasons.append(
            Reason("D", "Image was captured live in-app with a verified device attestation.", "info")
        )

    if agg >= CFG.fake_above:
        authenticity: Authenticity = "LIKELY_FAKE"
    elif agg <= CFG.real_below:
        authenticity = "REAL"
    else:
        reasons.append(
            Reason("J", f"Abstaining: aggregate score {agg:.2f} falls in the uncertainty "
                        f"band ({CFG.real_below:.2f}-{CFG.fake_above:.2f}).", "warn")
        )
        v = _abstain(reasons, identity)
        v.score = agg
        return v

    # Decision folds both axes. Identity is checked even when the pixels
    # look authentic: a real photo of the wrong person still fails KYC.
    if authenticity == "LIKELY_FAKE":
        decision: Decision = "REJECT"
    elif identity == "MISMATCH":
        decision = "REJECT"
    elif identity == "INDETERMINATE":
        decision = "REVIEW"
    else:
        decision = "ACCEPT"

    # Fail CLOSED when the only lane with measured signal is missing.
    # Lanes A/B/C/G were all measured against real bucket captures and none of
    # them separates a screen replay from a genuine capture (Lane A and Lane G
    # are actively anti-correlated on ID documents). Lane H is what produced
    # 4-of-4 replay catches. If it is configured as required but could not
    # return a usable read -- no API key, a 429, a network error -- then this
    # verdict rests on lanes that are known not to detect the primary attack,
    # and the honest answer is REVIEW, not ACCEPT. Without this, an exhausted
    # Groq quota silently restores the exact configuration that produced two
    # false ACCEPTs on screen-replayed IDs.
    if decision == "ACCEPT" and CFG.vlm_enabled:
        vlm = next((r for r in lane_results if r.lane == "H"), None)
        if vlm is None or not vlm.usable:
            decision = "REVIEW"
            reasons.append(Reason(
                "H", "Routing to review: the visual synthesis/replay check could not "
                     "complete, and the remaining lanes are not able to detect a "
                     "screen replay on their own.", "warn",
            ))

    severity_order = {"critical": 0, "warn": 1, "info": 2}
    reasons.sort(key=lambda r: severity_order[r.severity])

    return Verdict(
        authenticity=authenticity,
        identity=identity,
        decision=decision,
        confidence=round(base_conf, 3),
        confidence_is_calibrated=CFG.confidence_is_calibrated,
        score=round(agg, 3),
        reasons=reasons,
    )
