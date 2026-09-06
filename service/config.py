"""Every threshold that drives a verdict, in one place.

Centralised so a judge can read exactly what numbers produce a decision,
and so W5 calibration has one file to touch. Lanes and judge must not
hardcode thresholds.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    # ---- quality gate: can this image support a forensic read at all ----
    # Forensic traces live in high-frequency detail. Below these, there is
    # not enough evidence to justify any verdict, so we abstain.
    min_side_px: int = 256
    min_laplacian_var: float = 60.0  # variance of Laplacian; low = blurred
    min_jpeg_quality: int = 55  # heavy recompression destroys ELA + residuals

    # ---- shared lane statistics ----
    block_px: int = 16
    outlier_z: float = 3.5  # modified z-score; Iglewicz-Hoaglin cutoff
    min_cluster_blocks: int = 4  # one stray block is noise, a cluster is evidence
    min_lane_confidence: float = 0.35  # below this a lane abstains
    # Flagged-area fraction that maps to a ~0.6 lane score. Shapes the
    # saturating area->score curve. Uncalibrated default.
    score_area_saturation: float = 0.05

    # Lane A's checkpoint reports val_acc_exchanged from ITS OWN held-out
    # split of the same narrow, curated CelebA-HQ/INP-X distribution it was
    # trained on -- a high number there proves the model fits that
    # distribution, not that it generalises to real-world phone photos.
    # Manual testing against real photos outside that distribution (not
    # CelebA-HQ-style headshots) found confident false positives (>0.95 on
    # genuine photos) AND a confident false negative (an actual AI-generated
    # photo scored as safe). Capping the weight this lane can carry in the
    # judge's weighted average until it's validated against a genuinely
    # out-of-distribution test set -- raise this only after that validation
    # exists, not by trusting a bigger same-distribution val_acc_exchanged.
    lane_a_confidence_cap: float = 0.5

    # Lane G (screen/print replay, moire detection) is new and unvalidated
    # against any labelled real-vs-replay dataset -- reasoned about and
    # spot-checked manually only. Capped low so it can contribute evidence
    # without dominating the judge until real calibration data exists.
    screen_replay_confidence: float = 0.4
    # Score above which Lane G's finding is trusted as an independent hard
    # fail (see judge.py) instead of being averaged against lanes B/C, which
    # read a re-photographed screen as ordinary clean pixels and would
    # otherwise dilute a genuine replay down to "REAL".
    # Was 0.3 -- too high, found live: a confirmed screen replay (10/16
    # patches, z=8.4 -- coverage saturated, Lane G's own text already calls
    # this "consistent with a screen/print moire pattern") scored 0.297 and
    # slipped under it, because real-world z values (7.0, 8.4, ~10 across
    # multiple live captures) sit far below lane_screen.py's
    # SEVERITY_SATURATION_Z=20 reference point -- that constant was
    # calibrated against an idealized synthetic test grating, not real
    # screens. Lowered to sit safely below every real positive observed so
    # far (0.21, 0.297) and above the 0.0 a clean photo or a localised
    # hologram sticker scores. Still uncalibrated -- same caveat as the
    # lane itself; revisit if a real clean/localised case ever scores
    # this high.
    screen_replay_reject_above: float = 0.15

    # ---- judge ----
    # Gap between these two is the abstention band. Deliberately wide: in KYC
    # a confidently wrong reject locks a real user out of their bank.
    real_below: float = 0.35
    fake_above: float = 0.65
    min_usable_lanes: int = 2  # fewer than this and there is nothing to cross-check
    max_disagreement: float = 0.28  # spread above which lanes conflict -> abstain
    # Below this confidence a lane is judged too provisional to count toward
    # "the lanes disagree" (see judge.py Gate 3) -- just above lane_a_
    # confidence_cap (0.5) and screen_replay_confidence (0.4), the two lanes
    # this exists for. Their own known unreliability shouldn't alone force
    # an abstain when the lanes that ARE validated agree with each other.
    core_disagreement_min_confidence: float = 0.55
    attested_bonus: float = 0.10  # attestation RAISES confidence only, never lowers

    # Cosine similarity on face embeddings (Lane E). Gap between them is the
    # inconclusive band -> REVIEW rather than a coin-flip identity call.
    face_match_above: float = 0.38
    face_mismatch_below: float = 0.22
    # A face crop smaller than the recognition model's own input resolution
    # (112px, see lane_face.LOW_QUALITY_FACE_PX) is upsampled internally,
    # degrading the embedding it produces. A barely-over-threshold MATCH off
    # a crop that small (e.g. a low-res ID photo) is a weaker signal than the
    # same score off a full-resolution face, so it must clear a higher bar
    # before being called a MATCH rather than INDETERMINATE.
    #
    # Was 0.15 (bar 0.53). Measured against two real low-quality-face pairs:
    # a genuine pair matched at 0.5723 (passed) and a SEPARATE genuine pair
    # at 0.5287 (failed by 0.0013 -- a razor's edge on real sub-112px ID
    # crops, which is every real ID). Lowered to 0.13 (bar 0.51): clears
    # 0.5287 with 0.0187 of headroom while staying well above
    # face_match_above (0.38) and face_mismatch_below (0.22), so the
    # low-quality path is still meaningfully stricter than a normal match,
    # not just disabled. This is a two-point fit, not a calibration --
    # the final value should come from scripts/regression.py's --sweep
    # over the full labelled `real` set, not this manual pick.
    face_match_low_quality_margin: float = 0.13

    ela_quality: int = 90  # recompression quality for Lane C
    max_analysis_side: int = 1600  # cap for CPU latency on free hosting

    # ---- Lane H: VLM screen/print-replay + synthesis check (Groq) ----
    # Verified live against the 6-case measured sample (PLAN.md Finding 4):
    # confirmed screen replays scored screen_replay=1.00 on every one of
    # them, genuine captures scored 0.05-0.10, and a genuine PRINTED ID
    # scored print_replay=0.95 (correctly, since it really is printed
    # paper -- see is_id_document handling in lane_h_vlm.py). Capped like
    # Lane A/G's confidence until validated at scale beyond these 6 cases.
    vlm_confidence_cap: float = 0.6
    vlm_enabled: bool = True
    # Score above which Lane H's screen_replay (checked on BOTH images) or
    # print_replay (selfie only -- see judge.py) is trusted as an
    # independent hard fail rather than averaged in, mirroring
    # screen_replay_reject_above's role for Lane G. Set well below the
    # measured replay score (1.00) and well above the measured genuine
    # ceiling (0.10) so there's headroom on both sides of the one real
    # sample this is tuned against; revisit once a larger labelled set
    # exists.
    vlm_replay_reject_above: float = 0.5

    # Confidence values are raw lane agreement, NOT calibrated probabilities.
    # Surfaced in /v1/model-card so nobody misreads them. Flip after W5.
    confidence_is_calibrated: bool = False

    version: str = "0.1.0-lanes-bc"


CFG = Config()
