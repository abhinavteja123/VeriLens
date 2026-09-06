"""Training-free forensic lanes + the quality gate that gates them.

Both lanes look for regions that are anomalous *relative to the rest of the
same image*. Intra-image only: no reference image, no camera attribution,
no PRNU database. That keeps every claim self-contained and defensible.

Both normalise their statistic by local gradient energy. Without that,
Lane C flags every textured edge (ELA rises with detail) and Lane B flags
every smooth sky (residual falls with detail). Normalising asks the useful
question instead: is this region anomalous *given its own structure*?
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image

from config import CFG

# IJG Annex K standard luminance quantization table, used to invert a
# JPEG's stored table back into an approximate quality factor.
_IJG_LUMA = np.array(
    [
        [16, 11, 10, 16, 24, 40, 51, 61],
        [12, 12, 14, 19, 26, 58, 60, 55],
        [14, 13, 16, 24, 40, 57, 69, 56],
        [14, 17, 22, 29, 51, 87, 80, 62],
        [18, 22, 37, 56, 68, 109, 103, 77],
        [24, 35, 55, 64, 81, 104, 113, 92],
        [49, 64, 78, 87, 103, 121, 120, 101],
        [72, 92, 95, 98, 112, 100, 103, 99],
    ],
    dtype=np.float64,
)


@dataclass
class LaneResult:
    lane: str
    name: str
    score: float  # 0 = looks authentic, 1 = looks manipulated
    confidence: float  # how much this lane's read can be trusted at all
    reasons: list[str] = field(default_factory=list)
    box: tuple[int, int, int, int] | None = None  # x, y, w, h in pixels
    # Whether this lane counts toward the judge's weighted average and
    # disagreement gate. Lane A sets this False: measured anti-correlated
    # with ground truth (see PLAN.md Finding 2) -- it stays fully visible
    # in the API/UI as evidence, it just doesn't get a vote.
    voting: bool = True
    # Structured, lane-specific values that don't fit a single 0-1 score
    # (e.g. Lane H's separate screen_replay/print_replay/synthetic reads).
    # Kept out of `score`/`reasons` so the judge can gate on the specific
    # sub-signal it needs instead of parsing reason text.
    extra: dict = field(default_factory=dict)

    @property
    def usable(self) -> bool:
        return self.confidence >= CFG.min_lane_confidence


@dataclass
class QualityReport:
    usable: bool
    min_side: int
    laplacian_var: float
    jpeg_quality: int | None
    reasons: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- helpers


def _block_grid(arr: np.ndarray, block: int) -> np.ndarray:
    """Mean of `arr` over a non-overlapping block grid."""
    h, w = arr.shape[:2]
    bh, bw = h // block, w // block
    if bh == 0 or bw == 0:
        return np.zeros((0, 0), dtype=np.float64)
    cropped = arr[: bh * block, : bw * block].astype(np.float64)
    return cropped.reshape(bh, block, bw, block).mean(axis=(1, 3))


def _robust_z(grid: np.ndarray) -> np.ndarray:
    """Modified z-score (Iglewicz-Hoaglin). Median/MAD based, so a large
    manipulated region cannot drag the baseline it is measured against."""
    if grid.size == 0:
        return grid
    med = float(np.median(grid))
    mad = float(np.median(np.abs(grid - med)))
    if mad < 1e-9:
        return np.zeros_like(grid)
    return 0.6745 * (grid - med) / mad


def _gradient_energy(gray: np.ndarray) -> np.ndarray:
    """Per-block local gradient magnitude — the structure both lanes divide
    by so they measure anomaly rather than mere texture."""
    gx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    return _block_grid(np.sqrt(gx * gx + gy * gy), CFG.block_px)


def _largest_cluster(mask: np.ndarray) -> tuple[int, tuple[int, int, int, int] | None]:
    """Biggest connected run of flagged blocks, and its bbox in block units.

    A single outlier block is sensor noise or a compression artifact. A
    contiguous cluster is what an actual edited region looks like.
    """
    if mask.size == 0 or not mask.any():
        return 0, None
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    if n <= 1:
        return 0, None
    # row 0 is background
    areas = stats[1:, cv2.CC_STAT_AREA]
    i = int(np.argmax(areas)) + 1
    x, y, w, h = (
        int(stats[i, cv2.CC_STAT_LEFT]),
        int(stats[i, cv2.CC_STAT_TOP]),
        int(stats[i, cv2.CC_STAT_WIDTH]),
        int(stats[i, cv2.CC_STAT_HEIGHT]),
    )
    return int(areas.max()), (x, y, w, h)


def _score_from_cluster(cluster_blocks: int, total_blocks: int) -> float:
    """Saturating map from flagged area to a 0-1 score.

    Uncalibrated by design (see CFG.confidence_is_calibrated). Shaped so
    that `score_area_saturation` of the frame reads ~0.6.
    """
    if total_blocks == 0 or cluster_blocks < CFG.min_cluster_blocks:
        return 0.0
    frac = cluster_blocks / total_blocks
    k = -np.log(0.4) / CFG.score_area_saturation
    return float(np.clip(1.0 - np.exp(-k * frac), 0.0, 1.0))


def _to_block_box(box: tuple[int, int, int, int] | None) -> tuple[int, int, int, int] | None:
    if box is None:
        return None
    x, y, w, h = box
    b = CFG.block_px
    return (x * b, y * b, w * b, h * b)


def estimate_jpeg_quality(img: Image.Image) -> int | None:
    """Invert a JPEG's luma quantization table back to an IJG quality factor.

    Returns None for images with no JPEG history (PNG, raw camera output),
    which matters: Lane C has nothing to read when there is no prior
    compression, and must say so rather than invent a score.
    """
    tables = getattr(img, "quantization", None)
    if not tables:
        return None
    luma = np.array(tables[0], dtype=np.float64)
    if luma.size != 64:
        return None
    base = _IJG_LUMA.flatten()
    # T = (base*scale + 50)/100  ->  scale = (100*T - 50)/base
    scale = float(np.mean((100.0 * luma.flatten() - 50.0) / base))
    if scale <= 0:
        return 100
    q = 5000.0 / scale if scale > 100.0 else (200.0 - scale) / 2.0
    return int(np.clip(round(q), 1, 100))


def load_image(data: bytes) -> tuple[Image.Image, np.ndarray]:
    """Decode once, downscale if huge, hand back PIL (for JPEG tables) and BGR."""
    pil = Image.open(io.BytesIO(data))
    pil.load()
    rgb = pil.convert("RGB")
    w, h = rgb.size
    longest = max(w, h)
    if longest > CFG.max_analysis_side:
        s = CFG.max_analysis_side / longest
        rgb = rgb.resize((max(1, int(w * s)), max(1, int(h * s))), Image.LANCZOS)
    bgr = cv2.cvtColor(np.array(rgb), cv2.COLOR_RGB2BGR)
    return pil, bgr


# ------------------------------------------------------------ quality gate


def quality_gate(pil: Image.Image, bgr: np.ndarray) -> QualityReport:
    """Decide whether the image can carry a verdict at all.

    This is what makes INSUFFICIENT_EVIDENCE honest rather than decorative:
    a 200px over-compressed thumbnail has had its forensic traces destroyed,
    and any detector claiming 90% confidence on it is lying.
    """
    h, w = bgr.shape[:2]
    min_side = min(h, w)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    jpeg_q = estimate_jpeg_quality(pil)

    reasons: list[str] = []
    if min_side < CFG.min_side_px:
        reasons.append(
            f"Resolution too low ({w}x{h}); forensic traces need at least "
            f"{CFG.min_side_px}px on the short side."
        )
    if lap_var < CFG.min_laplacian_var:
        reasons.append(
            f"Image is blurred or upscaled (Laplacian variance {lap_var:.0f} < "
            f"{CFG.min_laplacian_var:.0f}); high-frequency evidence is gone."
        )
    if jpeg_q is not None and jpeg_q < CFG.min_jpeg_quality:
        reasons.append(
            f"Heavy JPEG recompression (estimated quality {jpeg_q} < "
            f"{CFG.min_jpeg_quality}); compression and noise traces are destroyed."
        )

    return QualityReport(
        usable=not reasons,
        min_side=min_side,
        laplacian_var=lap_var,
        jpeg_quality=jpeg_q,
        reasons=reasons,
    )


# ----------------------------------------------------- Lane C: compression


def lane_c_compression(pil: Image.Image, bgr: np.ndarray) -> LaneResult:
    """ELA: recompress at a known quality and look for regions whose error
    is anomalous *given their own gradient content*.

    A region pasted or synthesised at a different compression history
    reacts differently to recompression than the rest of the frame.
    """
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, format="JPEG", quality=CFG.ela_quality)
    buf.seek(0)
    recompressed = np.array(Image.open(buf).convert("RGB"))

    ela = np.abs(rgb.astype(np.int16) - recompressed.astype(np.int16)).max(axis=2)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    ela_g = _block_grid(ela, CFG.block_px)
    grad_g = _gradient_energy(gray)
    if ela_g.size == 0:
        return LaneResult("C", "Compression / ELA", 0.0, 0.0,
                          ["Image too small to form a block grid."])

    # Normalise: ELA rises with detail, so raw ELA flags every edge.
    norm = ela_g / (grad_g + 1.0)
    z = _robust_z(norm)
    mask = np.abs(z) > CFG.outlier_z
    cluster, box = _largest_cluster(mask)
    score = _score_from_cluster(cluster, int(ela_g.size))

    jpeg_q = estimate_jpeg_quality(pil)
    if jpeg_q is None:
        conf = 0.30  # no JPEG history: ELA has little to compare against
        note = "No JPEG history; ELA is weakly informative for this image."
    else:
        # Mid-to-high quality single compression is where ELA reads best.
        conf = float(np.clip((jpeg_q - CFG.min_jpeg_quality) / 40.0, 0.0, 1.0)) * 0.9
        note = f"Estimated JPEG quality {jpeg_q}."

    reasons = [note]
    if score > 0:
        reasons.append(
            f"{cluster} contiguous blocks show recompression error inconsistent "
            f"with their local detail (max |z|={np.abs(z).max():.1f})."
        )
    else:
        reasons.append("Recompression error is uniform across the frame.")

    return LaneResult("C", "Compression / ELA", score, conf, reasons, _to_block_box(box))


# ---------------------------------------------------------- Lane B: noise


def lane_b_noise(bgr: np.ndarray) -> LaneResult:
    """Noise-residual consistency across regions of the same image.

    Diffusion-generated content is typically *smoother* than sensor output:
    it lacks the per-pixel noise a real camera imprints. So we look for
    regions whose residual energy is anomalously LOW given their structure.
    """
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    denoised = cv2.bilateralFilter(gray, d=5, sigmaColor=50, sigmaSpace=50)
    residual = np.abs(gray.astype(np.float64) - denoised.astype(np.float64))

    res_g = _block_grid(residual, CFG.block_px)
    grad_g = _gradient_energy(gray)
    if res_g.size == 0:
        return LaneResult("B", "Noise residual", 0.0, 0.0,
                          ["Image too small to form a block grid."])

    # Normalise: smooth areas legitimately carry little residual.
    norm = res_g / (grad_g + 1.0)
    z = _robust_z(norm)
    mask = z < -CFG.outlier_z  # low-side only: synthetic = too clean
    cluster, box = _largest_cluster(mask)
    score = _score_from_cluster(cluster, int(res_g.size))

    # No texture anywhere means no noise floor to compare against.
    energy = float(np.median(res_g))
    conf = float(np.clip(energy / 3.0, 0.0, 1.0)) * 0.9

    reasons = [f"Median residual energy {energy:.2f}."]
    if score > 0:
        reasons.append(
            f"{cluster} contiguous blocks are unnaturally noise-free for their "
            f"detail level (min z={z.min():.1f}), consistent with synthesised content."
        )
    else:
        reasons.append("Noise floor is consistent across the frame.")

    return LaneResult("B", "Noise residual", score, conf, reasons, _to_block_box(box))
