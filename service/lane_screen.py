"""Lane G: screen/print replay detection via patch-wise moire analysis.

A digital screen re-photographed by a camera produces a periodic
interference pattern (moire) between the screen's own pixel grid and the
camera sensor's grid -- across the WHOLE photographed scene, since the
entire frame is a photo of a screen. A real photo of a real face has no
such periodic structure; its frequency spectrum falls off smoothly.

WHY PATCH-WISE, NOT ONE WHOLE-IMAGE FFT (found live, not guessed): a single
global FFT can't tell "strong periodic signal everywhere" from "strong
signal in one small corner" -- both look identical to it. That's exactly
why a genuine laminated/holographic Aadhar card false-positived: its
hologram/foil strip is a small, localised feature, but the whole-image FFT
read that patch's severity as if it were evidence about the whole photo.

Splitting the image into a grid and checking each patch separately fixes
this at the source: a genuine screen replay lights up MOST patches (the
whole frame is a screen), while a hologram sticker or foil strip only
lights up the one or two patches it physically overlaps. Score is severity
(how anomalous the peak is) times coverage (what fraction of spatially
DIFFERENT patches show it) -- a severe-but-localised signal now scores low,
a widespread one scores high, regardless of how it happens to distribute
within one patch.

NEW AND UNVALIDATED. Reasoned about and spot-checked manually, not measured
against a labelled dataset of real vs. screen/print-replay photos. Its
confidence is capped low regardless of what it finds (CFG.
screen_replay_confidence) so it can contribute evidence without dominating
the judge until it earns more trust -- same principle already applied to
Lane A after its own real-world reliability gap was found this session.

Known false-positive risk: fine periodic real-world texture spread across
most of the frame (mesh fabric, patterned wallpaper, window blinds, a
striped shirt filling most of the photo) can still produce a widespread
frequency-domain peak. Known false-negative risk: high-DPI/anti-moire
screens and good print quality reduce or eliminate the pattern regardless
of how widespread the check looks. Neither risk is calibrated away here --
the low confidence cap is the honest answer until real calibration data
exists, not a claim this lane is reliable.

TILT (found live, not guessed): the patch grid above assumes the
photographed screen fills the frame axis-aligned. A confirmed real replay
where the user held the phone at an angle to the screen (screen tilted
~15-20 degrees, dark bezel/background filling the rest) scored 0.0 --
every patch that straddled the screen's tilted edge mixed real periodic
screen content with flat non-periodic bezel, diluting each straddling
patch's own FFT below the per-patch cluster threshold, so only 4/16
scattered patches registered at all (well under MIN_COVERAGE_FRACTION).
Fixed by re-gridding the frame at a few candidate rotation angles and
keeping whichever reading scores highest: at the angle closest to the
screen's actual tilt, the screen's rectangular boundary realigns with the
axis-aligned patches, so patches stop straddling the edge and coverage
recovers. A dead-on, frame-filling replay already scores highest at 0
degrees, so this never changes that case -- it only recovers the tilted
one.
"""

from __future__ import annotations

import cv2
import numpy as np

from config import CFG
from lanes import LaneResult, _block_grid, _largest_cluster, _robust_z

# Finer grid than the spatial lanes (CFG.block_px=16): a moire peak in the
# frequency domain is narrow, and a coarse grid would average it away.
FFT_BLOCK_PX = 8
# Fraction of each patch's spectrum radius treated as "low-frequency
# center, real image content" and excluded from the outlier search.
CENTER_EXCLUDE_FRAC = 0.15
# Score saturates to 1.0 at this per-patch max z-score (z=25.4 observed
# live on a confirmed real screen replay's most-affected patch).
SEVERITY_SATURATION_Z = 20.0
# NxN spatial patches. Fine enough to localise a hologram sticker/foil
# strip to a minority of patches, coarse enough that each patch still has
# enough pixels for a meaningful FFT.
PATCH_GRID = 4
# Below this patch side length (px) the grid is too fine for this image's
# resolution to carry a meaningful per-patch spectrum -- fall back to a
# single whole-image read rather than division producing useless patches.
MIN_PATCH_SIDE_PX = 96
# Fraction of patches that must show a peak for this to read as a genuine
# full-frame screen replay. A hologram sticker covers 1-2 of PATCH_GRID**2
# patches; a real screen replay covers most of them. Score is normalised
# against this floor, not raw hit-count, so "most patches" saturates to
# full coverage regardless of the exact grid size.
MIN_COVERAGE_FRACTION = 0.4
# Candidate frame rotations tried before gridding (see module docstring,
# TILT). 0 first and always kept unless a rotation strictly beats it, so a
# dead-on replay's reading never changes. A handful of coarse angles, not a
# fine search -- this recovers a screen tilted at a rough angle, it doesn't
# need to find the exact tilt to realign the grid well enough to help.
ROTATION_ANGLES_DEG = (0, 15, -15, 30, -30)


def _patch_max_z(gray_patch: np.ndarray) -> float:
    """Max z-score of a periodic peak within one spatial patch's own FFT.
    0.0 if the patch is too small, has no qualifying cluster, or is flat.
    """
    h, w = gray_patch.shape
    if min(h, w) < 32:
        return 0.0

    fshift = np.fft.fftshift(np.fft.fft2(gray_patch))
    mag = np.log1p(np.abs(fshift))

    cy, cx = h // 2, w // 2
    radius = int(min(h, w) * CENTER_EXCLUDE_FRAC)
    yy, xx = np.ogrid[:h, :w]
    mag[(yy - cy) ** 2 + (xx - cx) ** 2 <= radius * radius] = 0.0

    grid = _block_grid(mag, FFT_BLOCK_PX)
    if grid.size == 0:
        return 0.0

    z = _robust_z(grid)
    mask = z > CFG.outlier_z  # high-side only: a moire peak is unusually LOUD, not quiet
    cluster, _box = _largest_cluster(mask)
    if cluster < CFG.min_cluster_blocks:
        return 0.0
    return float(z[mask].max())


def _rotated(gray: np.ndarray, angle_deg: float) -> np.ndarray:
    if angle_deg == 0:
        return gray
    h, w = gray.shape
    m = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), angle_deg, 1.0)
    # Reflect, not a constant fill: a hard black border would itself be a
    # sharp non-periodic edge sitting right at the patch grid's own lines.
    return cv2.warpAffine(gray, m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


def _grid_read(gray: np.ndarray) -> tuple[float, int, int, float]:
    """One pass of the patch-grid moire read over an already-oriented frame.
    Returns (score, hit_patches, total_patches, max_z)."""
    h, w = gray.shape
    ph, pw = h // PATCH_GRID, w // PATCH_GRID
    if ph < MIN_PATCH_SIDE_PX or pw < MIN_PATCH_SIDE_PX:
        # Too small to subdivide meaningfully at this resolution -- one
        # whole-image read is still better than nothing, it just can't
        # distinguish a localised feature (hologram, foil strip) from a
        # genuine full-frame replay the way the patch grid can.
        max_z = _patch_max_z(gray)
        hit_patches, total_patches = (1, 1) if max_z > CFG.outlier_z else (0, 1)
    else:
        severities = [
            _patch_max_z(gray[i * ph:(i + 1) * ph, j * pw:(j + 1) * pw])
            for i in range(PATCH_GRID)
            for j in range(PATCH_GRID)
        ]
        total_patches = len(severities)
        hit_patches = sum(1 for s in severities if s > CFG.outlier_z)
        max_z = max(severities) if severities else 0.0

    if hit_patches == 0:
        score = 0.0
    else:
        severity = float(np.clip((max_z - CFG.outlier_z) / (SEVERITY_SATURATION_Z - CFG.outlier_z), 0.0, 1.0))
        # Hard floor, not a ramp: found live, a strong-but-localised hologram
        # foil strip (1-2 patches, high severity) still scored a meaningful
        # partial coverage under a linear clip(hit_frac/floor) -- silently
        # contradicting the reasons text below, which already calls the
        # same reading "localised, not widespread". Below the floor this
        # isn't a full-frame replay by this lane's own stated design (see
        # module docstring), so it must contribute nothing, regardless of
        # how severe the localised peak is.
        coverage = 1.0 if (hit_patches / total_patches) >= MIN_COVERAGE_FRACTION else 0.0
        score = severity * coverage
    return score, hit_patches, total_patches, max_z


def lane_screen_replay(bgr: np.ndarray) -> LaneResult:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float64)
    h, w = gray.shape
    if min(h, w) < 64:
        return LaneResult("G", "Screen/print replay", 0.0, 0.0,
                          ["Image too small for frequency analysis."])

    # Try a few candidate frame rotations and keep whichever reading scores
    # highest (see module docstring, TILT). 0 degrees is tried first and is
    # never beaten by a rotation that isn't a genuine improvement, so a
    # dead-on replay's score/reasons are unaffected.
    best_angle = 0
    best = _grid_read(gray)
    for angle in ROTATION_ANGLES_DEG[1:]:
        candidate = _grid_read(_rotated(gray, angle))
        if candidate[0] > best[0]:
            best, best_angle = candidate, angle
    score, hit_patches, total_patches, max_z = best

    reasons = [f"Checked {total_patches} spatial patch(es) for a periodic frequency signature."]
    if hit_patches == 0:
        reasons.append("No periodic moire signature detected.")
    elif (hit_patches / total_patches) >= MIN_COVERAGE_FRACTION:
        angle_note = f" (frame re-checked at a {best_angle:+d} degree tilt)" if best_angle else ""
        reasons.append(
            f"{hit_patches}/{total_patches} patches show an unusually strong periodic "
            f"peak (max z={max_z:.1f}), consistent with a screen/print moire pattern"
            f"{angle_note}."
        )
    else:
        reasons.append(
            f"A periodic peak (max z={max_z:.1f}) was confined to {hit_patches}/{total_patches} "
            "patches -- localised, not the widespread signature of a full-frame replay."
        )

    return LaneResult("G", "Screen/print replay", score, CFG.screen_replay_confidence, reasons)


if __name__ == "__main__":
    print(lane_screen_replay(np.zeros((256, 256, 3), np.uint8)))
