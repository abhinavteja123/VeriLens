"""Lane G (screen/print replay) checks. Run: python test_lane_screen.py

Uses synthetic images -- a periodic grating simulates the moire signature
of a photographed screen; textured noise stands in for a real photo.
"""

import numpy as np

from config import CFG
from lane_screen import lane_screen_replay

rng = np.random.default_rng(0)


def _natural_texture(h=512, w=512) -> np.ndarray:
    """Smooth-falloff frequency content, no periodic structure -- stands
    in for a real camera photo."""
    base = rng.integers(60, 200, size=(h, w), dtype=np.uint8).astype(np.float64)
    # A few passes of box-blur approximate a natural 1/f-ish spectrum
    # without pulling in cv2/scipy filtering here.
    for _ in range(3):
        base = (base + np.roll(base, 1, axis=0) + np.roll(base, 1, axis=1)) / 3.0
    return np.stack([base] * 3, axis=2).astype(np.uint8)


def _moire_pattern(h=512, w=512, period_px=6) -> np.ndarray:
    """A fine periodic grating covering the WHOLE frame -- the signature a
    screen's own pixel grid leaves when re-photographed, aliased against
    the camera's sampling grid. Concentrates energy at one strong
    frequency, unlike natural image content's smooth falloff. Widespread
    across the frame, like a genuine full-frame screen replay."""
    yy, xx = np.meshgrid(np.arange(h), np.arange(w), indexing="ij")
    grating = 128 + 100 * np.sin(2 * np.pi * xx / period_px) * np.sin(2 * np.pi * yy / period_px)
    noise = rng.normal(0, 5, size=(h, w))
    out = np.clip(grating + noise, 0, 255).astype(np.uint8)
    return np.stack([out] * 3, axis=2)


def _localised_moire(h=512, w=512, period_px=6) -> np.ndarray:
    """The same grating, but confined to one small corner -- simulates a
    hologram sticker or foil strip on a real ID card: a genuine, strong
    periodic signal, but physically localised, not a full-frame replay."""
    img = _natural_texture(h, w).astype(np.float64)
    yy, xx = np.meshgrid(np.arange(h), np.arange(w), indexing="ij")
    grating = 128 + 100 * np.sin(2 * np.pi * xx / period_px) * np.sin(2 * np.pi * yy / period_px)
    sy, sx = h // 8, w // 8  # a small patch in one corner, well under one grid cell
    img[:sy, :sx, :] = grating[:sy, :sx, None]
    return np.clip(img, 0, 255).astype(np.uint8)


def test_natural_texture_reads_clean():
    r = lane_screen_replay(_natural_texture())
    assert r.usable, f"a natural photo's own baseline confidence must clear the floor, got {r.confidence}"
    assert r.score < CFG.fake_above, f"natural texture must not read as a screen replay, got {r.score}"
    print(f"ok  natural texture reads clean: score={r.score:.2f}")


def test_moire_grating_flagged():
    clean = lane_screen_replay(_natural_texture())
    moire = lane_screen_replay(_moire_pattern())
    assert moire.score > clean.score, (
        f"a periodic grating must score higher than natural texture, got moire={moire.score:.2f} "
        f"clean={clean.score:.2f}"
    )
    assert moire.score > 0, "the moire signature must actually flag something, not just score relatively higher"
    print(f"ok  moire grating flagged: clean={clean.score:.2f} moire={moire.score:.2f}")


def test_localised_pattern_scores_lower_than_widespread():
    """The actual bug this redesign fixes: a genuine periodic signal
    confined to a small corner (a hologram sticker on a real ID card) must
    NOT score as high as the same signal spread across the whole frame
    (a genuine screen replay) -- confirmed live, a single whole-image FFT
    couldn't tell these apart and false-positived on a real laminated
    Aadhar card.
    """
    widespread = lane_screen_replay(_moire_pattern())
    localised = lane_screen_replay(_localised_moire())
    assert widespread.score > localised.score, (
        f"a full-frame replay must score higher than a localised feature, got "
        f"widespread={widespread.score:.2f} localised={localised.score:.2f}"
    )
    print(f"ok  localised pattern (hologram-like) scores lower: "
          f"widespread={widespread.score:.2f} localised={localised.score:.2f}")


def test_strong_localised_signal_scores_zero():
    """Found live: a real ID card's hologram/foil strip produced a strong
    but localised periodic peak (high severity, ~1/16 patches) that used to
    still score ~0.17 under a linear coverage ramp -- contradicting this
    lane's own reasons text, which already correctly calls it "localised,
    not widespread". Below MIN_COVERAGE_FRACTION, severity must not matter
    at all: it's the same design boundary lane_screen.py's docstring
    already describes for the hologram-vs-replay distinction.
    """
    img = _localised_moire(period_px=3)  # tighter grating -> higher severity
    r = lane_screen_replay(img)
    assert r.score == 0.0, (
        f"a localised signal, however severe, must score 0 below the "
        f"coverage floor, got {r.score:.3f}"
    )
    print("ok  strong localised signal scores 0 regardless of severity")


def test_confidence_is_capped_low():
    """Regardless of what it finds, this lane must never claim more trust
    than CFG.screen_replay_confidence -- it is new and unvalidated."""
    for img in (_natural_texture(), _moire_pattern()):
        r = lane_screen_replay(img)
        assert r.confidence == CFG.screen_replay_confidence, r.confidence
    print("ok  confidence stays capped regardless of finding")


def test_tiny_image_abstains():
    r = lane_screen_replay(np.zeros((32, 32, 3), np.uint8))
    assert r.confidence == 0.0, "too small for frequency analysis must abstain, not guess"
    print("ok  tiny image abstains")


if __name__ == "__main__":
    for fn in [
        test_natural_texture_reads_clean,
        test_moire_grating_flagged,
        test_localised_pattern_scores_lower_than_widespread,
        test_strong_localised_signal_scores_zero,
        test_confidence_is_capped_low,
        test_tiny_image_abstains,
    ]:
        fn()
    print("\nall checks passed")
