# VeriLens — Known Limitations

Honest, evidence-based record of what does not yet work reliably, found via
live testing (not assumed). Companion to `HANDOFF.md` — read that first for
what the system is and what's working. This file exists so nobody (including
future us) mistakes "shipped" for "solved."

---

## 1. Lane A (local synthesis detector) — accuracy is the main open problem

Lane A is a trained patch-level classifier (EfficientNet-B0), and its
checkpoint reports `val_acc_exchanged` around 0.66–0.99 depending on which
checkpoint is loaded — but that number is measured on a held-out split of
the *same* narrow dataset it trained on (CelebA-HQ / INP-X). It does **not**
generalise reliably to real phone photos outside that distribution.

Confirmed via manual testing this session, across two different checkpoints:

- Confident false positives (score >0.95 "fake") on genuine, untouched real
  photos — both a real ID card and a real selfie.
- A confident false negative on an actual AI-generated photo (scored ~0).

**Mitigations already shipped, not fixes:**
- Confidence capped at `lane_a_confidence_cap = 0.5` so it can't dominate
  the judge's weighted average.
- Restricted to the detected face region (matches training), instead of
  scanning the whole frame.
- A capped-confidence lane's own disagreement no longer alone forces the
  judge to abstain (see §3) — otherwise a Lane A false positive on an
  otherwise-clean real photo used to route straight to REVIEW.

**Not fixed:** the model itself. It needs retraining on a broader,
non-curated dataset (`train_lane_a.py` already supports blending in a
70k-real/70k-fake dataset plus CNNDetection-style augmentation) — that
retrain has not been run and validated against real, non-dataset photos as
of this writing. Until then, expect a mix of confident-but-wrong readings
that other lanes and the disagreement gate mostly catch (routing to REVIEW
rather than a false ACCEPT), but not reliably enough to trust Lane A's raw
score on its own.

---

## 2. Lane G (screen/print replay) — reliably catches some replays, misses others

Lane G is an FFT-based moire detector: a photographed screen produces a
periodic interference pattern between the screen's pixel grid and the
camera sensor's grid. It is explicitly unvalidated against any labelled
dataset — reasoned about and spot-checked live, not measured at scale.

### 2a. What it does catch (confirmed)

A screen replay that fills most of the frame, at a normal-DPI display,
roughly straight-on: Lane G correctly reads it as widespread (most of its
16 spatial patches show a strong periodic peak) and the judge now hard-fails
it. Confirmed on real captures scoring in the `0.21`–`0.30` range (z=7.0 to
z=8.4, 7–10 of 16 patches).

### 2b. What it misses (confirmed, root-caused)

A real screen-replayed selfie (a laptop screen photographed at an angle,
running a photo-editing app) scored **0.00** — only 4 of 16 patches
registered any signal at all (max z=4.9, well under the widespread floor).

Root-caused by direct analysis of the actual image, not guessed:
- **Ruled out:** frame tilt/rotation. Swept rotation angles from -45° to
  +45° in 5° steps — no angle recovered meaningful coverage. A
  rotation-tolerant re-grid was still added (harmless, no regressions,
  helps a *tilted-but-strong* replay) but does not rescue this case.
- **Actual cause:** the moire signal itself is weak everywhere in this
  capture, consistent with `lane_screen.py`'s own pre-documented risk —
  *"high-DPI/anti-moire screens... reduce or eliminate the pattern
  regardless of how widespread the check looks."* The photographed display
  in this case appears to be a modern high-resolution laptop screen, which
  fits that category. This is a physical/optical limit of FFT-based moire
  detection, not a bug in the patch grid, threshold, or coverage logic —
  closing it would need calibration data across real device/screen types,
  not another code change.

**Practical effect:** a screen replay on a low-DPI or older display, filling
most of the frame, will likely be caught. The same attack against a modern
high-DPI display, or a partial/off-axis replay, may not be.

### 2c. Lane G's hard-fail gate is selfie-only, not ID-document

Also found live this session: a real, physical ID card's own printed
security pattern (an Aadhaar card's guilloche background) is genuinely,
physically periodic across roughly half the card — indistinguishable from
screen moire by an FFT alone. It scored `0.17`–`0.30` (7–10 of 16 patches),
which would have hard-rejected a completely genuine ID document.

Fix applied: Lane G's automatic hard-fail only applies to the **selfie**
now. On the **ID document image**, Lane G still runs and still contributes
as ordinary (capped-weight) evidence to the aggregate score, but can no
longer unilaterally force a REJECT or REVIEW verdict by itself.

**Known tradeoff this introduces:** a screen replay attempted via the *ID
document* photo (e.g. photographing a screen showing a fake ID, rather than
photographing the real physical card) will **not** be hard-caught by Lane G
anymore — it just becomes soft, diluted evidence like every other lane on
that image. This is a deliberate choice to stop false-rejecting real ID
cards with legitimate security printing; it has not been re-tested against
an actual ID-side screen replay to confirm how it behaves in practice. Print
attacks against the ID image were already an untested, unbuilt-for gap
before this change (see `HANDOFF.md` §9 item 3); this narrows Lane G's
already-limited ability to help with that case even further.

---

## 3. Real captures sometimes routing to REVIEW instead of ACCEPT

Separate from Lane A's own accuracy, the **judge's disagreement gate**
used to be too aggressive: any time lanes' scores spread further apart than
`max_disagreement = 0.28`, the judge abstained to REVIEW rather than average
the conflict away. This is a correct instinct in general, but it originally
did not distinguish "two validated lanes genuinely disagree" from "one
already-known-unreliable, confidence-capped lane (A or G) is just being
noisy while the validated lanes agree."

**Fixed this session:** disagreement is now judged only among lanes whose
confidence clears `core_disagreement_min_confidence = 0.55` — Lane A
(capped at 0.5) and Lane G (capped at 0.4) can no longer, by themselves,
force an abstain when Lanes B/C agree the photo is clean.

**Not fully solved:** this only addresses disagreement caused by the two
lanes that are *already known* to be capped/unreliable. A genuine
disagreement between Lanes B and C (or any future validated lane) will
still correctly abstain to REVIEW — which is the intended, safe behavior,
but will still feel like "a real photo went to review" from the outside
whenever those lanes legitimately produce mixed signals (e.g. unusual but
non-fraudulent JPEG recompression history, an unusually processed real
photo from unfamiliar camera software, unusual lighting). No dataset-backed
measurement yet of how often this happens on real, diverse phone photos —
only spot-checked against the handful of real captures tested live this
session.

---

## 4. Other known, pre-existing gaps (from HANDOFF.md, still open)

Carried over, not solved by anything done this session:

- **`lane_a_refine.py` (Groq secondary opinion)** is non-deterministic and
  free-tier rate-limited — observed multiple `429` responses this session,
  which silently falls back to raw Lane A (by design, so it never fails the
  request, but it means the same photo can get a different secondary read,
  or none, on different tries).
- **Print attacks (a physically printed photo held up to the camera)** are
  untested. Lane G targets screen moire specifically; a halftone-dot,
  paper-texture print signature is a different physical phenomenon and
  nothing in the system is built to detect it.
- **Confidence values are uncalibrated everywhere**
  (`confidence_is_calibrated = false`) — they represent raw lane agreement,
  not a statistically calibrated probability. The UI is required to label
  this; do not read a confidence number as "% chance this is real."
- **Real-time deepfake / live face-swap during video capture** — not
  evaluated at all; would need a virtual-camera + face-swap testing setup
  this session didn't have.

---

## Bottom line

The system is honest about uncertainty by design — it is built to abstain
(REVIEW) rather than guess, and across every case tested this session it
never produced a false ACCEPT. But "never falsely accepts" is not the same
as "accurate": expect a real, elevated REVIEW rate on genuine users until
Lane A is retrained and validated on real-world data, and treat Lane G's
screen-replay detection as a partial defence (catches some real attacks,
confirmed live) rather than a complete one (misses others, also confirmed
live) until it has real calibration data behind it.
