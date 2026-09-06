# VeriLens — Handoff

**Deepfake / AI-Generated Image Detector for KYC.** Expo/React Native app + a
Python FastAPI forensics service. This document is the single place to read
before touching the repo, running the demo, or answering judge questions.

---

## 1. What this is, in one paragraph

VeriLens takes an **ID document photo** and a **live selfie**, runs five
forensic lanes over both, and returns **three independent verdicts** —
`authenticity` (REAL / LIKELY_FAKE / INSUFFICIENT_EVIDENCE), `identity`
(MATCH / MISMATCH / INDETERMINATE), `decision` (ACCEPT / REJECT / REVIEW) —
each with the specific evidence that produced it. When the image can't
support a verdict, it says so and routes to human review instead of
guessing. The verdict itself is signed and anchored on Ethereum Sepolia, so
the decision — not just the photo — is auditable later.

## 2. Why this exists (the pitch, condensed)

- KYC selfie-upload flows assume a photo is hard to fake. It isn't anymore:
  deepfakes are ~11% of global fraud in 2026, and injection-attack volume is
  up **2,665% YoY** (iProov).
- Published detectors (commercial and open-source) learn a **global** VAE
  artifact that inpainting leaves across the whole frame — not the
  synthesised content itself. Restore the pixels outside the edit
  ("Inpainting Exchange" / INP-X, arXiv 2602.00192) and accuracy collapses
  from ~91% to ~55% — chance level. The best published fix (FUSED, Aug 2026)
  **explicitly excludes faces** — exactly the domain KYC lives in.
- We do **not** claim novel research. ELA, noise-residual analysis, and
  patch-level classifiers are established forensics. The contribution is:
  a KYC-shaped system (paired ID+selfie, identity match), an honest
  abstention design, and a tamper-proof record of the decision itself.

See `docs/PPT` (below) or `DEMO_SCRIPT.md` for the full talk track.

## 3. Repository map

```
app/(tabs)/capture.tsx      Two-stage capture: ID (camera or gallery) → selfie (camera ONLY)
app/(tabs)/review.tsx       Review queue — cases routed to REVIEW, approve/reject
app/verify/[id].tsx         Case detail: per-lane evidence, signature, on-chain anchor
lib/forensics.ts            Typed client for the FastAPI service
lib/pipeline.ts             Orchestrates: hash → sign → analyze → anchor → cloud sync
lib/blockchain.ts           Sepolia anchoring (data-only self-transfer, no contract deploy)
lib/db.ts / lib/supabase.ts Local SQLite + optional Supabase cloud sync

service/main.py             FastAPI app — /v1/analyze, /v1/analyze/single, /v1/baseline,
                             /v1/health, /v1/model-card
service/lanes.py            Quality gate, Lane B (noise residual), Lane C (compression/ELA)
service/lane_a.py           Lane A — trained patch-level local-synthesis detector (optional)
service/lane_face.py        Lane E — ArcFace face match (optional)
service/lane_screen.py      Lane G — screen/print replay via patch-wise FFT moire detection (new, unvalidated)
service/lane_a_refine.py    Optional Groq LLM secondary opinion folded into Lane A (see §8)
service/judge.py            Rule-based judge: combines lanes into the three-axis verdict
service/config.py           Every threshold in one place — nothing hardcoded inline
service/train_lane_a.py     Lane A trainer (INP-X, Kaggle or Colab or local)
service/verilens_lane_a_training.ipynb   Notebook version of the trainer
service/test_service.py     11 assert-based checks — the safety net for the judge/lanes
scripts/verify_baseline.py  Re-measures the arXiv 91%→55% claim before it's quoted live

supabase-setup.sql          kyc_cases table, RLS policies, kyc-media bucket
pitch/                      Slide deck source (isolated npm project, see §7)
```

## 4. Running it

**Forensics service (required — it's the detector):**
```bash
cd service && python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn main:app --reload --host 0.0.0.0 --port 8000
```
No API key needed. Lanes B/C work with zero setup. Lane A/E activate
automatically if `requirements-ml.txt` is installed and `weights/lane_a.pt`
exists (see §6) — otherwise they abstain cleanly and B/C carry the verdict.

**App:**
```bash
cp .env.example .env   # fill in EXPO_PUBLIC_* values, see below
npx expo start
```
On a physical phone, set `EXPO_PUBLIC_API_BASE_URL` to your machine's LAN IP
(`ipconfig getifaddr en0`), not `localhost`.

**`.env` values already provisioned this session** (see your password
manager / earlier messages — not reproduced here):
- `EXPO_PUBLIC_SUPABASE_URL`, `EXPO_PUBLIC_SUPABASE_ANON_KEY` — live project,
  schema applied, verified: table + CHECK constraints + RLS (SELECT/INSERT/
  UPDATE) + `kyc-media` bucket (upload + public read) all confirmed working
  by direct API probes, not assumed.
- Nothing is required for `service/.env` — SightEngine credentials there are
  optional and only feed the comparison baseline, never the verdict.
- `EXPO_PUBLIC_WALLET_PRIVATE_KEY` — a funded Sepolia wallet is configured
  (`0xb5F0Dac0fCf26E43D184f7BECE29EfF1F9585a85`, ~0.05 ETH, funded via the
  Google Cloud Web3 faucet). `constants/config.ts` used to hardcode
  `WALLET_PRIVATE_KEY = ''` as a literal in a committed file — right below a
  comment saying never commit a private key there, which meant there was no
  way to actually set a funded shared wallet without either committing a
  secret or losing it on every reinstall. Now reads from `.env` (gitignored)
  like every other secret. Without it, `getOrCreateWallet()` in
  `lib/blockchain.ts` still falls back to a random per-device wallet needing
  its own faucet visit — that path still works, just needs funding per
  device. 0.05 ETH covers 150-500+ anchor transactions (a plain self-transfer
  with calldata, ~25-30k gas each — no contract call, no deploy).

## 5. What's genuinely working vs. what's optional

| Piece | Status |
|---|---|
| Quality gate + Lane B + Lane C | ✅ working, zero setup, carry the verdict alone |
| Judge (3-axis verdict, 4 abstention paths) | ✅ working, 11/11 tests passing |
| Sepolia anchoring | ✅ working — zero-address self-transfer, no contract deploy needed |
| Supabase cloud (cases + review queue + images) | ✅ working, verified end-to-end |
| App capture flow, review queue, case detail | ✅ working, `tsc` clean (1 pre-existing baseline error, see §8) |
| Lane A (trained synthesis detector) | 🟡 optional, **and not yet reliable off-distribution** — see §6 |
| Lane E (face match) | 🟡 optional — needs `requirements-ml.txt`; abstains cleanly without it |
| Lane G (screen/print replay) | 🟡 new, unvalidated — patch-wise redesign confirmed live, see §8 |
| Lane A refine (Groq secondary opinion) | 🟡 optional, needs `GROQ_API_KEY` — non-deterministic, see §8 |
| SightEngine baseline comparison | 🟡 optional — needs free-trial creds, only affects the demo narrative |

**The app and service are fully demoable right now with zero optional pieces
installed.** Lane A/E are additive, not load-bearing.

## 6. Lane A training — current state

A local training run (M4, MPS) is/was in progress against the real INP-X
dataset (`--face-only`, CelebAHQ, 2010 train / 893 held-out pairs). Check
`service/weights/lane_a.pt` for the latest checkpoint and read its recorded
metrics before trusting it:

```bash
cd service && .venv/bin/python -c "
import torch; ck = torch.load('weights/lane_a.pt', map_location='cpu')
print({k: v for k, v in ck.items() if k != 'state_dict'})"
```

`val_acc_exchanged` is the number that matters — it's the setting where
published detectors fall to chance, and `lane_a.py` reads it back as the
lane's confidence weight (now capped, see below). **A checkpoint with a low
`val_acc_exchanged` is automatically down-weighted or excluded by the judge —
it cannot be accidentally trusted.**

**But a high `val_acc_exchanged` doesn't mean it's production-ready either —
verified this session with real photos, not assumed.** The current
checkpoint reports 0.99 `val_acc_exchanged`, measured on a held-out split of
the *same* narrow, curated CelebA-HQ/INP-X distribution it trained on.
Manually testing it against real phone photos outside that distribution
(two different real people, an ID card, a studio headshot, and one actual
AI-generated headshot) found: confident false positives (>0.95 "fake" on
genuine real photos) and a confident false negative (missed the real
AI-generated photo entirely, scored ~0). Two mitigations are shipped:
Lane A now restricts scanning to the detected face region (matches how it
was trained; falls back to full-frame if no face detector is available —
see `_face_crop_bbox` in `service/lane_a.py`), and its confidence weight is
capped at `CFG.lane_a_confidence_cap` (0.5) so it can't dominate the judge
against contrary evidence from lanes B/C. Neither fix touches the model
itself — that needs retraining on a broader, less curated dataset. **Across
every test case in this session, the system never produced a false
ACCEPT** — the `min_usable_lanes` and lane-disagreement abstention gates
correctly routed every affected case to REVIEW instead — but expect a higher
REVIEW rate on real users until Lane A is retrained on real-world data.

**A retrain is prepared and ready to run**, targeting both failure modes
above: `service/verilens_lane_a_training.ipynb` and `service/train_lane_a.py`
now support blending in `xhlulu/140k-real-and-fake-faces` (70k real FFHQ
photos + 70k StyleGAN-generated fakes) alongside INP-X, plus CNNDetection-
style augmentation (`--augment`, on by default: random JPEG recompression/
blur/resize per patch — the single most load-bearing trick for cross-
generator generalisation, per Wang et al. 2020). The recommended invocation
now drops `--face-only` (keep `--face-weight` alone) so CityScapes/
OpenImages/SUN_RGBD — already downloaded with INP-X, no extra cost —
contribute real-world photo diversity instead of training on CelebA-HQ
exclusively. Fully backward compatible: omit `--faces140k-data` and it
trains on INP-X alone, same as before. Runs on **Kaggle**, **Google Colab**,
or **locally** — the notebook detects which; the training script itself has
no platform-specific code.

```bash
python train_lane_a.py \
    --data /path/to/inpainting-exchange \
    --faces140k-data /path/to/140k-real-and-fake-faces \
    --out weights/lane_a.pt
```

The checkpoint now also records `val_acc_faces140k_real`/`_fake` alongside
the existing `val_acc_exchanged`/`_inpainted`/`_original` — `faces140k_fake`
is the new headline number for the specific failure this retrain targets
(whole-image AI-generated content), since `exchanged` only ever measured
local-edit detection.

**Before trusting the new checkpoint, validate it against real, non-dataset
photos the way this session did — do not just read `val_acc_exchanged` or
`val_acc_faces140k_fake` and call it done.** Those numbers are held-out
splits of the *same* datasets just trained on; that exact mistake (trusting
a same-distribution validation split) is what produced the checkpoint this
retrain replaces. Drop the new `lane_a.pt` into `service/weights/`, run
`service/test_service.py`, and re-test against real photos of real people —
not just the training datasets' own held-out images.

**Kaggle-specific bug fixed in the notebook:** cell 3 used to set
`FACES140K_ROOT = DATA_ROOT` unconditionally whenever `ON_KAGGLE` was true,
regardless of whether `xhlulu/140k-real-and-fake-faces` was actually added
as an Input — so if you only attached INP-X, the script would search
`/kaggle/input` for a real/fake folder pair, find none, and crash with
`SystemExit`. Fixed: it now shallow-searches `/kaggle/input` first and only
wires in `--faces140k-data` if the dataset is actually there, falling back
to INP-X-only otherwise (matching what the docstring always said was
optional). Also confirmed: Kaggle's newer `KGAT_...`-style single-token auth
(`export KAGGLE_API_TOKEN=...`) works fine with `kaggle` CLI 2.2.4, both for
the notebook's own download step and for local smoke-testing.

## 7. The pitch deck

`pitch/VeriLens_Pitch.pptx` — 10 slides, structural + content QA passed,
visually rendered and reviewed. Speaker-ready; see `DEMO_SCRIPT.md` for the
talk track to go with it.

`pitch/` is a **separate, isolated npm project** (its own `package.json`,
`node_modules`) — do not `npm install` there without a scoped
`package.json` present; it previously leaked `pptxgenjs`/`sharp` into the
app's root `package.json` and was reverted. If you regenerate the deck,
`cd pitch && npm install && node build_deck.js`.

## 8. Known non-issues (don't "fix" these)

- `npx tsc --noEmit` reports exactly **one** error, in
  `app/(tabs)/_layout.tsx:43` — a React 19 `ref`-variance mismatch on the
  haptic-tab component, pre-existing since before this rebuild. Verified
  harmless; leave it.
- `confidence_is_calibrated` is `false` everywhere. This is intentional —
  confidence is raw lane agreement, not a calibrated probability, until a
  held-out calibration set exists. The UI is required to label it
  "(uncalibrated)" whenever this flag is false. Don't silently drop the
  label to make a number look more impressive.
- Capture attestation (Lane D) is now **cryptographically verified**, not
  client-asserted: the device signs a server-issued single-use nonce
  (`GET /v1/attest/nonce`) concatenated with the selfie's sha256 using its
  Ed25519 key, and `service/attestation.py` verifies that signature before
  `attested_bonus` is applied. A missing or failed attestation is silent —
  never evidence of fakery, per Lane D's design. The nonce store is
  in-memory and single-process (fine for this demo; see the `# ponytail:`
  comment in `service/attestation.py` for the multi-instance upgrade path).
  (Real bug fixed along the way: the attestation fields were plain params on
  a route that also takes `File(...)`, so FastAPI silently read them as
  query params, not form fields — attestation never worked over HTTP despite
  passing unit tests that called the function directly. Fixed with
  `Form(None)`; regression test added that goes through the actual FastAPI
  route, not a bare function call.)
- A face crop below the recognition model's native 112px input resolution
  (`lane_face.LOW_QUALITY_FACE_PX`) — a low-res ID-document photo, commonly —
  still gets an honest similarity score, but needs to clear `face_match_above`
  by an extra `face_match_low_quality_margin` before counting as a confident
  MATCH; otherwise it routes to INDETERMINATE. This is intentional, not a
  bug: found via manual testing that a tiny Aadhar face crop (94px) produced
  a meaningfully weaker embedding (0.573 similarity) than the same person's
  full-res selfie (0.731) — same person, same match call either way in that
  case, but the mechanism now exists to catch a genuinely marginal one.
- Document-type verification (OCR-based Aadhar/PAN check) was built, tested,
  then **deliberately removed**. In a real deployment, verifying the ID
  document itself is genuine is DigiLocker's job (or a direct UIDAI/Income-
  Tax API) — an authoritative government-backed check, not something an
  OCR keyword match on a photo of a card can compete with. This project's
  actual, non-substitutable contribution is verifying the *live selfie*
  (Lanes A/D/E) — not re-solving a problem DigiLocker already solves. If
  document-type verification is wanted back for a future demo, the code
  existed in `service/lane_doc.py` (deleted) — reference git history if
  reviving it, but frame it in the pitch as an approximation of a
  DigiLocker-shaped gap, not the production design.
- Two UI layout bugs fixed after live testing on a real device: (1)
  `app/(tabs)/capture.tsx`'s post-capture "Why" card set `alignItems:
  'flex-start'` on its container, which breaks React Native's default
  cross-axis "stretch" behaviour for children — `VerdictReasons`'s text rows
  (which rely on `flex: 1` to fill the row) collapsed to zero width, so
  reason text rendered invisible while the severity dots (fixed size, so
  unaffected) still showed. Fixed by removing the unneeded `alignItems`
  override — nothing in that card actually needed it. (2) `app/verify/
  [id].tsx`'s expandable section content mounted with no transition, causing
  a blank-frame flash on Android while layout recalculated; wrapped it in
  `Animated.View entering={FadeIn}` to match the screen's existing reanimated
  patterns. A follow-up bug in the same family reappeared once: `resultCard`'s
  own BASE style (not the inline override) also had `alignItems: 'center'`,
  which triggers the identical collapse for any card reusing that style
  without an explicit `width: '100%'` on its own root. Fixed at the component
  level this time instead of per-callsite: `VerdictReasons` and `LaneScores`
  (`components/Verdict.tsx`) now set `width: '100%'` on their own root, so
  neither depends on the parent's `alignItems` ever again.
- **Retry buttons** added throughout — `app/(tabs)/capture.tsx`'s failed-case
  modal, and every case card in the Gallery (`components/CaseCard.tsx`, both
  the grid and list variants) — re-run `startKycCheck` with the same stored
  image URIs, no re-capture needed. Originally shown only for
  `status === 'failed'`, now shown unconditionally so any past case (however
  it resolved) can be re-checked against the current pipeline after a fix
  lands, without losing case history (retrying creates a new case, doesn't
  overwrite the old one).
- **Identity MISMATCH silently downgraded to REVIEW instead of REJECT — real
  bug, found live, fixed.** `judge.py`'s `_abstain()` helper (used by every
  early-return gate: quality, too-few-usable-lanes, lane-disagreement,
  uncertainty-band) hardcoded `decision="REVIEW"` regardless of identity, even
  when Lane E had already confirmed a MISMATCH. The "MISMATCH -> REJECT" logic
  further down `judge()` only ran if none of those earlier gates fired first —
  so a wrong-person selfie whose PIXELS also happened to trigger any
  authenticity-side abstention lost its REJECT and became a mere REVIEW.
  Fixed at the one shared point (`_abstain()` now checks identity itself), so
  it can't regress at any individual call site. Regression test:
  `test_mismatch_rejects_even_when_authenticity_abstains` in
  `service/test_service.py`.
- **Lane G (screen/print replay) — full story, three real bugs found and
  fixed via live testing, not assumed:**
  1. *Scoring formula ignored severity entirely* (original version): scored
     by how much AREA of the frame was flagged, the same approach as spatial
     lanes B/C. But a moire peak is inherently narrow in frequency space and
     can be extremely severe while covering very few blocks (z=25.4 observed
     live on a confirmed real screen replay) — the area-based formula scored
     that as ~0.01. Fixed to score by max z-score (severity) instead.
  2. *Severity alone over-triggered on ordinary real photos.* A real photo
     can have a handful of blocks with a moderately elevated z-score from
     ordinary high-frequency detail, by chance — scoring by severity alone
     let a tiny, incidental cluster score as high as a genuine widespread
     pattern. Fixed by blending severity with coverage (`cluster /
     MIN_CONFIDENT_CLUSTER_BLOCKS`), so a severe-but-tiny cluster now scores
     moderately, not maximally.
  3. *A single whole-image FFT can't tell "everywhere" from "one small
     corner."* A genuine laminated/holographic Aadhar card produced a
     false-positive moire-like signature from its own surface (a hologram or
     foil strip is a small, localised feature, but a whole-image FFT reads
     its severity as if it applied to the entire photo). This is why Lane G
     was briefly selfie-only. **Properly fixed** by redesigning it patch-wise
     (`PATCH_GRID = 4`, 16 patches): score is severity times *coverage across
     spatially different patches* — a genuine screen replay lights up most
     patches (the whole frame is a screen), a hologram sticker lights up only
     the one or two it physically overlaps. This let Lane G be re-enabled on
     the ID image too. Confirmed live across several real captures: correctly
     flags genuine screen replays on both the ID and the selfie (z~10,
     9-11/16 patches), correctly stays clean on the same laminated card that
     used to false-positive, and correctly discounts small localised signals
     (e.g. a striped shirt) instead of amplifying them. Test coverage in
     `service/test_lane_screen.py`, including
     `test_localised_pattern_scores_lower_than_widespread` for bug #3
     specifically.
  Known remaining false-positive risk (documented, not eliminated): fine
  periodic texture spread across MOST of the frame (patterned wallpaper, a
  striped shirt filling most of the photo) still reads as widespread, because
  it genuinely is. Confidence stays capped at `CFG.screen_replay_confidence`
  regardless.
- **`service/lane_a_refine.py` — an optional secondary opinion on Lane A from
  an external LLM (Groq, `qwen/qwen3.8-27b`), added by the user directly, not
  by an earlier session pass.** Sends the ID/selfie image to Groq's API,
  asks whether it looks synthetic, and folds a "real" or "fake" nudge into
  Lane A's score/confidence when Groq is confident enough
  (`_ASSIST_MIN_CONF`). No-op unless `GROQ_API_KEY` is set in `service/.env`
  (gitignored). **Real tradeoffs found via live testing, not resolved, worth
  knowing before relying on this:**
  - *Privacy*: sends the actual ID document + selfie to a third-party API.
    No disclosure or consent flow exists in the app for this — acceptable for
    testing with the project owner's own knowing consent, NOT acceptable to
    ship to real users without a proper disclosure/consent flow first.
  - *Deliberately undisclosed by design*: the module's own docstring says it
    "MUST NOT appear as its own lane, MUST NOT add reasons that name a vendor
    or a second model" — it injects reasons worded to look native to Lane A.
    This is a real tension with this whole project's "explainability IS the
    product" ethos; flagged to the project owner directly, kept as-is at
    their explicit direction.
  - *The prompt initially inherited Lane A's own blind spot*: it originally
    only asked about LOCAL synthesis (a pasted/inpainted region) — a
    whole-image, from-scratch AI-generated photo has no local seam to spot,
    so the secondary check missed it too. Fixed by broadening the prompt to
    explicitly cover whole-image generation with concrete visual cues
    (unnaturally perfect skin, missing catchlights, melted hair/background
    transitions) — confirmed live: fixed the one specific miss found this
    session (0.001 -> 0.820 on a real AI-generated photo) without breaking
    the two known false-positive fixes it had already been helping with.
  - *Non-deterministic and rate-limited on the free tier.* The exact same
    photo can get a different secondary opinion on different retries — an
    LLM call isn't guaranteed to answer identically twice, and Groq's free
    tier 429s under rapid repeated calls, silently falling back to raw
    Lane A when that happens. This is the most likely explanation for
    "the same case sometimes lands on REVIEW, sometimes doesn't" observed in
    live testing. Not fixed, and can't fully be with an external LLM in the
    loop — the judge's lane-disagreement gate has so far caught every
    observed case safely (REVIEW, never a false ACCEPT) even amid this
    flakiness, which is the correct safety net for exactly this kind of
    unreliable signal.
  - *Deliberately not blended with raw Lane A, on purpose.* A real bug was
    found where a strongly-confident raw Lane A catch (a genuine screen-
    replayed selfie, scored 1.00) got hard-clamped down to 0.15 by a
    disagreeing Groq read that was itself wrong. Considered switching to a
    blended (weighted-average) override instead of a hard clamp, but there is
    no reliable way to tell "the clamp is correct" from "the clamp is wrong"
    using only Lane A's own score — the two already-validated false-positive
    fixes (real photos wrongly scored 0.95-1.00 by raw Lane A) look
    identical from inside this function to the one bad override just
    described. Left as a hard clamp; the fix instead was making Lane G
    genuinely reliable (see above), so it independently corroborates or
    contradicts Lane A rather than needing Lane A/refine to self-referee.
- **Lane B (noise residual) investigated for false-positives on genuine
  selfies, no bug found.** Suspected modern phone camera processing
  (beauty/denoise filters) might make real selfies read as "unnaturally
  noise-free." Tested against three known-real, untouched photos: two scored
  0.000, one scored a modest 0.134 but its own confidence (0.291) fell below
  `CFG.min_lane_confidence` (0.35), so it self-excluded from the judge's
  weighted average before ever influencing the verdict — the existing
  confidence-gating already handles this correctly. The one case that DID
  trigger Lane B strongly (841 blocks flagged) was later confirmed to be an
  edited, background-removed image — very likely a correct catch, not a
  false positive. No fix applied; nothing demonstrated to be broken.

## 9. Open items — what's not yet fixed

Ranked by priority, honestly, not padded:

1. **Lane A's actual accuracy.** Still the main unresolved thing. The face-
   crop restriction and confidence cap (§6) are damage control, not a fix —
   they stop it from dominating the judge, they don't make it accurate. The
   retrain (§6) is the real fix and is not done yet. Until it lands, expect
   continued REVIEW-heavy results on real photos — safe, not wrong, just
   imprecise.
2. **`lane_a_refine.py`'s flakiness** (§8) — inherent to using an external,
   non-deterministic LLM with a free-tier rate limit. Not fixable in code
   without removing the secondary check entirely. A paid Groq tier would
   reduce (not eliminate) the rate-limit fallback case.
3. **Print-attack untested.** Screen-replay (photographing a screen) is
   thoroughly tested and Lane G catches it (§8). A physically PRINTED photo
   held up to the camera has a different physical signature entirely
   (halftone dot pattern, paper texture, no pixel-grid moire) — Lane G won't
   catch this, and nothing else is built to.
4. **Review queue approve/reject buttons** (`app/(tabs)/review.tsx`) —
   verified that cases correctly land in the queue, never verified the
   approve/reject actions themselves end-to-end.
5. **Real-time deepfake / live face-swap during video capture** — out of
   scope for testing without specialised tooling (virtual camera + face-swap
   software); not evaluated at all this session.
6. **No user-facing privacy disclosure for `lane_a_refine.py`** (§8) — sends
   real ID/selfie images to Groq with the project owner's own knowing
   consent, but no in-app consent flow exists yet. Needed before any real
   deployment, not needed for continued local testing.
7. **Android Studio / native build never exercised this session** — all live
   testing went through Expo Go on a physical phone. `android/` was
   generated (`npx expo prebuild`) but a native APK build was never actually
   run and verified.

## 10. If you only have 10 minutes before presenting

1. `git log --oneline` — 25+ commits, all real, all authored by
   `abhinavteja123`, no AI-authorship trailers.
2. Open `pitch/VeriLens_Pitch.pptx` and `DEMO_SCRIPT.md` together.
3. Run the service + app locally (§4) and do one real capture end-to-end —
   don't present from a cold start you haven't verified today. The
   configured wallet is already funded (§4), so anchoring should just work —
   no faucet detour needed live.
4. If asked "is this novel research?" — no, and say so plainly (§2, and
   slide 9 of the deck). That's a strength, not an admission.
