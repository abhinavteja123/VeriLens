# VeriLens — fix real→REVIEW and the screen-replay false ACCEPTs

## Context

The system cannot separate a genuine capture from a replayed one. Genuine pairs
land on REVIEW; when thresholds get tuned to catch a fake, genuine captures start
reading LIKELY_FAKE. Every fix so far was a threshold hand-tuned against one or
two live captures, which is why fixing one case keeps breaking another — there is
no measurement, so a regression is invisible until a demo.

Retraining Lane A is off the table: the 9-hour run already happened and regressed
the checkpoint (`weights/lane_a.pt` now reports `val_acc_exchanged=0.663`; the
backup at `lane_a.pt.orig-backup` reports 0.993 but is the checkpoint with the
documented >0.95 false positives on real photos). Neither is usable.

**This plan is written against measured results, not assumptions.** Six real
`kyc_cases` pairs pulled from the `kyc-media` bucket were run through the current
pipeline in-process, and every image was also put through the Groq VLM. The
numbers below are verbatim from those runs.

Target outcomes:
1. A genuine pair → **ACCEPT**.
2. An AI-generated / manipulated capture → **REJECT**.
3. A photo of a screen → **REJECT** (or REVIEW at worst). Never ACCEPT.

---

## Ground truth of the sample set (visually labelled from the bucket images)

| case | ID image | selfie | correct verdict |
|---|---|---|---|
| `mtog7qvp9bs3ng` | **screen replay** — laptop, WhatsApp Web chrome | genuine | REJECT |
| `mtooj6s07t9bt9` | **screen replay** | **screen replay** — macOS Photos, filmstrip visible | REJECT |
| `mtosdrgjxy16vn` | genuine paper Aadhaar, **back side (no face)** | genuine | REVIEW — ask for the front |
| `mtotdsyygxr48f` | **screen replay** | genuine | REJECT |
| `mtotin2bx81n9y` | **screen replay** | genuine, **different person** | REJECT |
| `mtowju5afd5obu` | genuine physical PVC card | genuine | **ACCEPT** |

Four of six ID images are photos of a laptop screen. **The ID image, not the
selfie, is the dominant replay attack surface in the real data.**

---

## Measured baseline — what the current pipeline actually returns

```
case             ID lanes (A/B/C/G)          selfie lanes (A/B/C/G)      verdict
mtog7qvp9bs3ng   0.00 0.00 0.01 0.381        0.88 0.05 0.04 0.000        ACCEPT      <- FALSE ACCEPT
mtooj6s07t9bt9   0.00 0.00 0.03 0.111        0.21 0.00 0.02 0.097        REVIEW
mtosdrgjxy16vn   0.56 0.00 0.03 0.463        0.30 0.28 0.12 0.000        REVIEW      (ok, no face on card back)
mtotdsyygxr48f   0.00 0.09 0.10 0.139        0.44 0.24 0.16 0.000        ACCEPT      <- FALSE ACCEPT
mtotin2bx81n9y   0.00 0.00 0.04 0.140        0.03 0.17 0.13 0.000        REJECT      (right answer, identity only)
mtowju5afd5obu   0.87 0.00 0.03 0.264        0.02 0.34 0.01 0.000        REVIEW      <- should ACCEPT
```

**Two false ACCEPTs on screen-replayed IDs.** HANDOFF.md's headline claim —
"across every test case in this session, the system never produced a false
ACCEPT" — is falsified by the user's own bucket data.

### Finding 1 — Lane G is anti-correlated on ID images
Lane G scores **higher on the two genuine physical cards (0.463, 0.264)** than on
three of the four actual screen replays (0.111, 0.139, 0.140). A laminated card
surface plus guilloche printing produces stronger periodicity than a modern
high-DPI screen does. Lane G cannot be the screen detector for ID documents —
this is physics (LIMITATIONS.md §2b already predicted it), not a tuning problem.
On selfies it points the right way but is far too weak: 0.000 across five genuine
selfies, 0.097 on the confirmed replay — under the 0.15 hard-fail bar.

### Finding 2 — Lane A is anti-correlated everywhere
0.87 and 0.56 on the two **genuine** cards; 0.00 on all four screen replays. It
also single-handedly caused the one genuinely-good pair to fail. Measured on
`mtowju5afd5obu`'s ID image, usable lanes are `A=0.867@0.50, C=0.027@0.70,
G=0.264@0.40`, giving `agg=0.3490` and `spread=0.3622`. The aggregate is *below*
`real_below=0.35`, so the uncertainty band is not what fires — **Gate 3
(disagreement) is**: `spread 0.3622 > max_disagreement 0.28`, and because only
Lane C clears `core_disagreement_min_confidence=0.55`, the core-lane carve-out
falls back to the all-lane spread (`judge.py:200-201`) and Lane A's 0.867 outlier
counts in full. Remove Lane A from the vote and it becomes `agg=0.1130,
spread=0.1142` → REAL → ACCEPT.

### Finding 3 — Lanes B and C carry no replay signal at all
Across all twelve images, B and C scored between 0.00 and 0.34 with no separation
between the replay and genuine classes. They are splice/ELA detectors; a
re-photographed screen is a genuine single-capture photo of a different subject,
so there is nothing for them to find. This is expected, not a bug.

### Finding 4 — the VLM separates the classes cleanly
Same images through `qwen/qwen3.8-27b` (verified live on the configured key):

| image | truth | `screen_replay` | `print_replay` | cues returned |
|---|---|---|---|---|
| `mtog7qvp9bs3ng/id` | replay | **1.00** | 0.00 | browser_tabs, window_chrome, thumbnail_filmstrip, screen_glare |
| `mtotdsyygxr48f/id` | replay | **1.00** | 0.00 | browser_tabs, window_chrome, cursor, backlight_glow |
| `mtooj6s07t9bt9/selfie` | replay | **1.00** | 0.00 | browser_tabs, app_ui, thumbnail_filmstrip |
| `mtog7qvp9bs3ng/selfie` | genuine | 0.05 | 0.05 | natural_illumination, realistic_texture |
| `mtowju5afd5obu/id` | genuine PVC | 0.05 | 0.10 | depth of field, no bezels, hologram reflects naturally |
| `mtosdrgjxy16vn/id` | genuine paper | 0.05 | **0.95** | halftone dots, paper fibre, page curl |

**Screen replay: 6/6, including the high-DPI case Lane G scores 0.097 on.** The
single `print_replay` false positive is definitional, not a model error — a
genuine paper Aadhaar really does have halftone dots and paper fibre. Therefore:
**`print_replay` must never hard-fail an ID image**, exactly as Lane G's guilloche
problem taught. On a selfie it is valid; nobody's live selfie is printed paper.

### Finding 5 — no regression harness
The meta-cause. Every threshold in `config.py` carries a comment naming the single
live capture it was tuned against.

---

## Design decisions (each follows from a measurement above)

1. **Lane H (VLM) becomes a required lane on both images.** Measured: it is the
   only lane with signal on this data. Not optional, not a hidden nudge.
2. **Lane A stops voting.** Anti-correlated, and demonstrably the cause of the one
   genuine pair failing. It keeps running and stays visible in the API and UI as
   evidence — it just leaves the weighted average and the disagreement gate.
3. **Lane G keeps its current wiring, untouched.** It stays evidence-only on the
   ID (already true) and keeps its selfie hard-gate (0.000 across five genuine
   selfies — no measured false-positive risk to fix). Do **not** lower its
   threshold to chase the 0.097 replay; that is inside the noise floor and Lane H
   already catches that case. No new code here.
4. **The ID image keeps a veto, but only via Lane H and the quality gate — never
   via A/B/C/G.** Four of six attacks arrive through the ID image, so removing its
   veto entirely would be exactly backwards; but its pixel-forensic lanes are
   measurably invalid on documents (Lane C scored 0.992 on a genuine Aadhaar).
5. **Asymmetric replay rules**, straight from Finding 4:
   - ID image: `screen_replay` hard-fails; `print_replay` is ignored.
   - Selfie: both `screen_replay` and `print_replay` hard-fail.
6. **Cache every VLM call by image sha256.** This is what makes the same photo
   return the same verdict twice — the direct fix for "sometimes REVIEW, sometimes
   not."

---

## Stage 0 — regression harness (first; nothing else lands without it)

**New: `service/scripts/regression.py`.** Model it on the in-process pattern at
`service/scripts/verify_baseline.py:40-45` — import lanes and judge directly, do
not go over HTTP.

Bucket layout for the eval set (`kyc-media` is already public per
`supabase-setup.sql:100-102`):

```
kyc-media/eval/<label>/<case>/id.jpg
kyc-media/eval/<label>/<case>/selfie.jpg
    labels: real | screen_replay | ai_fake | print_replay | no_face
```

Seed it by copying the six cases above into their labelled folders — their
verdicts are already established in the ground-truth table.

- **Use `httpx` (already in `requirements.txt:9`). Do not add `supabase-py`.**
  List via `POST {SUPABASE_URL}/storage/v1/object/list/kyc-media` (body
  `{"prefix":"eval/","limit":1000}`, `apikey` + `Authorization: Bearer` = anon
  key); fetch from `{SUPABASE_URL}/storage/v1/object/public/kyc-media/<path>`.
- Add `SUPABASE_URL` / `SUPABASE_ANON_KEY` to `service/.env`; read them with the
  existing loader at `lane_a_refine.py:64-82` — **move that function to a shared
  module rather than copying it.**
- Cache downloads in `service/.eval_cache/`; gitignore it and `.vlm_cache/`.
  Support `--source local --dir <path>` so it runs offline.
- Output: a label × decision confusion matrix, plus a per-case row of every lane's
  score and confidence and which gate fired — so a regression names the lane that
  caused it, not just the verdict.
- **Exit non-zero on any false ACCEPT or any false REJECT.** These are the two
  conditions that must never regress.
- `--sweep` mode: grid-search `real_below`, `fake_above`,
  `face_match_low_quality_margin` over the labelled set and print the frontier, so
  final numbers come from measurement rather than the last capture someone tried.

Record the baseline matrix **before** any change — the table in this document is
that baseline; reproduce it and commit it.

---

## Stage 1 — Lane H, the VLM replay/synthesis lane

This is the load-bearing change. Do it first, because Findings 1–3 show nothing
else moves the numbers.

**New: `service/lane_h_vlm.py`.** Retire `lane_a_refine.py` and
`test_lane_a_refine.py` (git history keeps them).

- One call per image, returning
  `{"screen_replay": 0..1, "print_replay": 0..1, "synthetic": 0..1, "cues": [...]}`
  with `temperature: 0` and `response_format: {"type": "json_object"}`. The prompt
  used for the measurements above is the starting point — keep the explicit cue
  list (bezel, browser tabs, window chrome, cursor, taskbar, thumbnail filmstrip,
  screen glare, backlight glow, flat uniform illumination, refresh banding;
  halftone dots, paper fibre, page curl) and fold in the whole-image synthesis cues
  already written at `lane_a_refine.py:38-61`, which HANDOFF.md records fixed a
  real miss (0.001 → 0.820).
- Downscale to 1024px before encoding. **Note: token cost is a flat ~1850 per
  image regardless of resolution — measured — so this is for latency, not quota.**
- Returns `LaneResult("H", "Visual synthesis & replay check", …)` with visible
  reasons naming the actual cues returned, plus the raw three fields for the judge.
- Takes an `is_id_document: bool` so it can drop `print_replay` on the ID
  (Finding 4).
- **Disk cache at `service/.vlm_cache/<sha256>-<prompt_version>.json`.** Identical
  input then yields identical output, and harness reruns cost nothing.
- **429 handling:** parse the `try again in Xs` value from the error body, retry
  once, then **abstain with confidence 0.0 and an explicit reason** — never fall
  through to a silent guess. Free tier measured at 7000 input-tokens/min ≈ 1.8
  cases/min; the user will supply a fresh key if this binds.
- Confidence: start at a new `CFG.vlm_confidence_cap = 0.6`, final value from the
  harness sweep.
- Wire into `_analyze_one` (`main.py:103-150`) alongside the other lanes, and add
  the `screen_replay` result to the same hard-gate path as Lane G in
  `judge.py:145-166` (**OR**'d with it), respecting the asymmetric rule in Design
  Decision 5.
- Disclose in `/v1/model-card` that images go to a third-party API, and gate on
  `CFG.vlm_enabled`. (A full in-app consent flow stays open — HANDOFF.md §9 item 6.)

## Stage 2 — stop Lane A poisoning the aggregate

Add a `voting: bool = True` field to `LaneResult` (`lanes.py:~40`); return
`voting=False` from `lane_a.py`. In `judge.py:118`:
`usable = [r for r in lane_results if r.usable and r.voting]`. Reasons keep coming
from the full `lane_results` list as they already do, so Lane A stays fully
visible in `ImageAnalysis.lanes`.

Verify against the harness that `mtowju5afd5obu` moves REVIEW → ACCEPT (predicted
aggregate 0.351 → 0.117).

## Stage 3 — identity axis

Two smaller items, both measured:
- `mtowju5afd5obu` matched at similarity **0.5723** against a 0.53 bar; a genuine
  pair in `photos/` failed at **0.5287** against the same bar. The
  `face_match_low_quality_margin` of 0.15 is a razor's edge on real ID crops, which
  are always under 112px. Derive `face_match_above` and the margin from the
  harness sweep over the `real` pairs instead of from a single capture. Touches
  `judge.py:79-92`.
- `sim=None` (no face found on the ID — a card back, or a screen photo where the
  portrait is tiny) correctly routes to REVIEW. Add a specific reason telling the
  user to photograph the **front** of the card, so `no_face` cases are actionable
  rather than a generic abstain.

## Stage 4 — tests and documentation

- Extend `service/test_service.py` in its existing plain-assert style, adding each
  new function to the `__main__` runner list at `:505-530`:
  `test_lane_a_does_not_vote`,
  `test_lane_h_screen_replay_rejects_id_document`,
  `test_lane_h_print_replay_ignored_on_id_document` (pin the genuine paper Aadhaar
  case), `test_lane_h_print_replay_rejects_selfie`,
  `test_clean_pair_accepts` (pin `mtowju5afd5obu`'s lane values),
  `test_vlm_rate_limited_abstains_not_guesses`.
- Rewrite LIMITATIONS.md §1–3 and HANDOFF.md §5/§9 against the harness's measured
  matrix. **Correct HANDOFF.md's "never produced a false ACCEPT" claim explicitly**
  — it is false, and the two cases that break it are named above.

---

## Verification

```bash
cd service
.venv/bin/python test_service.py          # prints "all checks passed"
.venv/bin/python test_lane_screen.py
.venv/bin/python scripts/regression.py --source supabase
```

The regression run must reach this matrix, which is the definition of done:

| case | required decision |
|---|---|
| `mtog7qvp9bs3ng` | REJECT (was ACCEPT) |
| `mtooj6s07t9bt9` | REJECT (was REVIEW) |
| `mtosdrgjxy16vn` | REVIEW — no face on the card back |
| `mtotdsyygxr48f` | REJECT (was ACCEPT) |
| `mtotin2bx81n9y` | REJECT |
| `mtowju5afd5obu` | **ACCEPT** (was REVIEW) |

Zero false ACCEPT, zero false REJECT. Commit the before/after matrices in the
commit message.

Then end-to-end on device:

```bash
cd service && .venv/bin/uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

with `npx expo start` — one genuine pair (expect ACCEPT), one ID photographed off
a screen (expect REJECT), one selfie taken against a display (expect REJECT).

---

## Explicitly not doing

- **No Lane A retraining.** The 9-hour run already regressed the checkpoint.
- **No changes to `lane_screen.py`.** Lane G measured 0.000 across five genuine
  selfies — there is no false positive to fix, and Lane H covers what it misses.
  The striped-shirt risk in HANDOFF.md §8 stays documented, unfixed, unobserved.
- **No new dependencies.** `httpx`, `opencv`, `PIL`, `numpy` cover everything;
  `supabase-py` is unnecessary for a public bucket.
- **No dedicated print-attack detector.** Lane H's `print_replay` on the selfie is
  the only coverage (HANDOFF.md §9 item 3).
- **No in-app consent UI for Lane H.** Model-card disclosure only.
