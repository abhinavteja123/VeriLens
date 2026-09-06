const pptxgen = require("pptxgenjs");
const path = require("path");

const ICON_DIR = path.join(__dirname, "icons_yb");
const iconB = (name) => path.join(ICON_DIR, `${name}_blk.png`); // black icon, sits on yellow
const iconW = (name) => path.join(ICON_DIR, `${name}_wht.png`); // white icon, sits on charcoal

// ---- palette: yellow / black, committed dark throughout ----
const BLACK    = "0A0A0A";  // canvas
const CHARCOAL = "1B1B1B";  // card fill
const CHARCOAL2= "242424";  // slightly lighter card, for alternating rows
const YELLOW   = "FFC627";  // primary accent — badges, numbers, emphasis
const YELLOW_DK= "C99A0E";  // darker yellow for subtle strokes
const WHITE    = "FFFFFF";
const MUTED    = "9A9A9A";  // secondary text
const MUTED_DK = "6B6B6B";
const RED      = "E8483A";  // reject/alert, used sparingly
const GREEN    = "3FBE6B";  // used sparingly for "real/accept" contrast against yellow

const FONT_HEAD = "Cambria";
const FONT_BODY = "Calibri";

const TOTAL_SLIDES = 8;

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";
const PW = 13.33, PH = 7.5;

pres.defineSlideMaster({ title: "DARK", background: { color: BLACK }, objects: [] });

// ---------- helpers ----------

function badge(slide, { x, y, d = 0.6, style = "yellow", iconName, iconScale = 0.56 }) {
  const bg = style === "yellow" ? YELLOW : CHARCOAL2;
  const iconPath = style === "yellow" ? iconB(iconName) : iconW(iconName);
  slide.addShape("ellipse", { x, y, w: d, h: d, fill: { color: bg }, line: style === "yellow" ? { type: "none" } : { color: YELLOW_DK, width: 1 } });
  const isz = d * iconScale;
  slide.addImage({ path: iconPath, x: x + (d - isz) / 2, y: y + (d - isz) / 2, w: isz, h: isz });
}

function pageNum(slide, n) {
  slide.addText(`${n} / ${TOTAL_SLIDES}`, { x: PW - 1.1, y: PH - 0.42, w: 0.9, h: 0.3, fontFace: FONT_BODY, fontSize: 10, color: MUTED_DK, align: "right", isTextBox: true, margin: 0 });
}

function kicker(slide, text, { x = 0.6, y = 0.5 } = {}) {
  slide.addText(text.toUpperCase(), { x, y, w: 9, h: 0.35, fontFace: FONT_BODY, fontSize: 13, bold: true, color: YELLOW, charSpacing: 2, isTextBox: true, margin: 0 });
}

function title(slide, text, { x = 0.6, y = 0.86, w = 11.5, size = 32 } = {}) {
  slide.addText(text, { x, y, w, h: 1.4, fontFace: FONT_HEAD, fontSize: size, bold: true, color: WHITE, isTextBox: true, margin: 0, lineSpacingMultiple: 1.05 });
}

function cornerFrame(slide, { x, y, w, h, len = 0.4, thick = 0.03 }) {
  const c = YELLOW_DK;
  slide.addShape("rect", { x, y, w: len, h: thick, fill: { color: c }, line: { type: "none" } });
  slide.addShape("rect", { x, y, w: thick, h: len, fill: { color: c }, line: { type: "none" } });
  slide.addShape("rect", { x: x + w - len, y, w: len, h: thick, fill: { color: c }, line: { type: "none" } });
  slide.addShape("rect", { x: x + w - thick, y, w: thick, h: len, fill: { color: c }, line: { type: "none" } });
  slide.addShape("rect", { x, y: y + h - thick, w: len, h: thick, fill: { color: c }, line: { type: "none" } });
  slide.addShape("rect", { x, y: y + h - len, w: thick, h: len, fill: { color: c }, line: { type: "none" } });
  slide.addShape("rect", { x: x + w - len, y: y + h - thick, w: len, h: thick, fill: { color: c }, line: { type: "none" } });
  slide.addShape("rect", { x: x + w - thick, y: y + h - len, w: thick, h: len, fill: { color: c }, line: { type: "none" } });
}

function statCallout(slide, { x, y, w, h, num, label, numColor = YELLOW }) {
  slide.addShape("roundRect", { x, y, w, h, rectRadius: 0.09, fill: { color: CHARCOAL }, line: { color: "2E2E2E", width: 0.75 } });
  slide.addText(num, { x: x + 0.28, y: y + 0.16, w: w - 0.56, h: h * 0.55, fontFace: FONT_HEAD, fontSize: 40, bold: true, color: numColor, isTextBox: true, margin: 0 });
  slide.addText(label, { x: x + 0.28, y: y + h * 0.58, w: w - 0.56, h: h * 0.38, fontFace: FONT_BODY, fontSize: 12.5, color: MUTED, isTextBox: true, margin: 0, valign: "top", lineSpacingMultiple: 1.15 });
}

// a dashed-look placeholder box for content the user will paste in by hand
function pastePlaceholder(slide, { x, y, w, h, label }) {
  slide.addShape("roundRect", { x, y, w, h, rectRadius: 0.1, fill: { color: CHARCOAL }, line: { color: YELLOW_DK, width: 1.25, dashType: "dash" } });
  slide.addText(label, { x, y: y + h / 2 - 0.25, w, h: 0.5, fontFace: FONT_BODY, fontSize: 13, italic: true, color: MUTED_DK, align: "center", isTextBox: true, margin: 0 });
}

// =====================================================================
// SLIDE 1 — TITLE (unchanged)
// =====================================================================
{
  const s = pres.addSlide({ masterName: "DARK" });
  cornerFrame(s, { x: 0.55, y: 0.55, w: PW - 1.1, h: PH - 1.1, len: 0.42 });

  badge(s, { x: PW / 2 - 0.45, y: 1.25, d: 0.9, style: "yellow", iconName: "shield", iconScale: 0.56 });

  s.addText("VERILENS", { x: 0, y: 2.42, w: PW, h: 1.1, fontFace: FONT_HEAD, fontSize: 56, bold: true, color: WHITE, align: "center", isTextBox: true, margin: 0, charSpacing: 3 });
  s.addText("Deepfake / AI-Generated Image Detector for KYC", { x: 0, y: 3.58, w: PW, h: 0.55, fontFace: FONT_BODY, fontSize: 20, color: YELLOW, align: "center", isTextBox: true, margin: 0 });
  s.addText("A forensic evidence system for identity checks — per-lane reasoning,\nan honest “I don’t know,” and a tamper-proof audit trail.", {
    x: PW / 2 - 4.3, y: 4.32, w: 8.6, h: 0.8, fontFace: FONT_BODY, fontSize: 14, color: MUTED, align: "center", isTextBox: true, margin: 0, lineSpacingMultiple: 1.25,
  });

  s.addShape("rect", { x: PW / 2 - 1.6, y: 5.5, w: 3.2, h: 0.013, fill: { color: "2E2E2E" }, line: { type: "none" } });
  s.addText("Track: Deepfake / AI-Generated Image Detector for KYC  ·  Cybersecurity", { x: 0, y: 5.7, w: PW, h: 0.4, fontFace: FONT_BODY, fontSize: 12.5, color: MUTED, align: "center", isTextBox: true, margin: 0 });
  s.addText("IEEE Gen-AI Hackathon", { x: 0, y: 6.8, w: PW, h: 0.35, fontFace: FONT_BODY, fontSize: 11, color: MUTED_DK, align: "center", isTextBox: true, margin: 0 });
}

// =====================================================================
// SLIDE 2 — WHY THIS (simple, plain-language motivation)
// =====================================================================
{
  const s = pres.addSlide({ masterName: "DARK" });
  kicker(s, "Why This Matters");
  title(s, "A photo used to prove you were real.\nNot anymore.", { size: 30 });

  const stats = [
    { num: "11%", label: "of all fraud today is driven by deepfakes" },
    { num: "2,665%", label: "more fake-camera attacks than just last year" },
    { num: "$20/mo", label: "buys anyone a ready-made face-swap tool" },
  ];
  const gap = 0.35, cw = (11.13 - gap * 2) / 3, cy = 2.6, ch = 2.3;
  stats.forEach((st, i) => statCallout(s, { x: 0.6 + i * (cw + gap), y: cy, w: cw, h: ch, num: st.num, label: st.label }));

  s.addText(
    "Anyone can now fake a face on camera, cheaply and convincingly. A KYC check that only asks " +
    "“does this photo look real?” is asking the wrong question — VeriLens is built to answer the " +
    "right one: can this applicant be trusted?",
    { x: 0.6, y: 5.25, w: 11.1, h: 1.1, fontFace: FONT_BODY, fontSize: 14, color: MUTED, isTextBox: true, margin: 0, lineSpacingMultiple: 1.35 }
  );
  pageNum(s, 2);
}

// =====================================================================
// SLIDE 3 — HOW IT WORKS (5 simple steps)
// =====================================================================
{
  const s = pres.addSlide({ masterName: "DARK" });
  kicker(s, "How It Works");
  title(s, "One check. Five simple steps.", { size: 30 });

  const layers = [
    { icon: "layercapture", h: "1. Capture", d: "Take a photo of your ID, then a live selfie." },
    { icon: "layergate", h: "2. Quality Check", d: "Blurry or broken photos are stopped right away — before any test runs." },
    { icon: "layerlanes", h: "3. Six Checks", d: "Six different tests look for signs of fakery, all at the same time." },
    { icon: "layerjudge", h: "4. Judge", d: "If the tests agree, we decide. If they disagree, a person reviews it instead of guessing." },
    { icon: "layerchain", h: "5. Verdict + Record", d: "The result is signed and saved on the blockchain — nobody can quietly change it later." },
  ];

  const startX = 0.6, barW = 11.13, barH = 0.92, gapY = 0.145, startY = 2.05;
  layers.forEach((l, i) => {
    const y = startY + i * (barH + gapY);
    const indent = i * 0.16;
    s.addShape("roundRect", { x: startX + indent, y, w: barW - indent, h: barH, rectRadius: 0.08, fill: { color: i % 2 ? CHARCOAL : CHARCOAL2 }, line: { color: YELLOW_DK, width: i === 2 ? 1.25 : 0 } });
    badge(s, { x: startX + indent + 0.18, y: y + (barH - 0.56) / 2, d: 0.56, style: "yellow", iconName: l.icon, iconScale: 0.55 });
    s.addText(l.h, { x: startX + indent + 0.9, y: y + 0.12, w: 2.6, h: barH - 0.24, fontFace: FONT_BODY, fontSize: 14, bold: true, color: WHITE, isTextBox: true, margin: 0, valign: "middle" });
    s.addText(l.d, { x: startX + indent + 3.6, y: y + 0.1, w: barW - indent - 3.85, h: barH - 0.2, fontFace: FONT_BODY, fontSize: 11.3, color: MUTED, isTextBox: true, margin: 0, valign: "middle", lineSpacingMultiple: 1.18 });
  });
  pageNum(s, 3);
}

// =====================================================================
// SLIDE 4 — THE SIX CHECKS (lanes, plain language)
// =====================================================================
{
  const s = pres.addSlide({ masterName: "DARK" });
  kicker(s, "The Six Checks");
  title(s, "Six checks. Each looks for a different kind of fake.", { size: 26, w: 12 });

  const lanes = [
    { icon: "layers", n: "A", h: "Local Synthesis", d: "Looks for AI-edited or pasted parts of the photo." },
    { icon: "magnify", n: "B", h: "Noise Residual", d: "Real cameras leave tiny noise. AI images are too clean." },
    { icon: "code", n: "C", h: "Compression / ELA", d: "Checks if part of the photo was edited and re-saved." },
    { icon: "camera", n: "D", h: "Capture Attestation", d: "Proves the selfie was really taken live, right now." },
    { icon: "usershield", n: "E", h: "Face Match", d: "Checks the selfie is the same person as the ID photo." },
    { icon: "mobile", n: "G", h: "Replay Detection", d: "Catches someone holding up a screen or printout instead of a real face." },
  ];
  const cw = 1.74, gap = 0.115, startX = 0.6, cy = 2.05, ch = 2.85;
  lanes.forEach((l, i) => {
    const x = startX + i * (cw + gap);
    s.addShape("roundRect", { x, y: cy, w: cw, h: ch, rectRadius: 0.09, fill: { color: CHARCOAL }, line: { color: "2E2E2E", width: 0.75 } });
    badge(s, { x: x + (cw - 0.54) / 2, y: cy + 0.22, d: 0.54, style: "yellow", iconName: l.icon, iconScale: 0.54 });
    s.addText(`LANE ${l.n}`, { x: x + 0.12, y: cy + 0.9, w: cw - 0.24, h: 0.28, fontFace: FONT_BODY, fontSize: 10, bold: true, color: YELLOW, align: "center", isTextBox: true, margin: 0, charSpacing: 1 });
    s.addText(l.h, { x: x + 0.12, y: cy + 1.16, w: cw - 0.24, h: 0.55, fontFace: FONT_BODY, fontSize: 12.5, bold: true, color: WHITE, align: "center", isTextBox: true, margin: 0 });
    s.addText(l.d, { x: x + 0.14, y: cy + 1.72, w: cw - 0.28, h: ch - 1.9, fontFace: FONT_BODY, fontSize: 9, color: MUTED, align: "center", isTextBox: true, margin: 0, lineSpacingMultiple: 1.15 });
  });

  s.addText("▼", { x: 0, y: cy + ch + 0.06, w: PW, h: 0.3, fontFace: FONT_BODY, fontSize: 16, color: YELLOW, align: "center", isTextBox: true, margin: 0 });
  const jy = cy + ch + 0.4, jh = 0.85;
  s.addShape("roundRect", { x: 0.6, y: jy, w: 11.13, h: jh, rectRadius: 0.1, fill: { color: YELLOW }, line: { type: "none" } });
  badge(s, { x: 0.85, y: jy + (jh - 0.5) / 2, d: 0.5, style: "dark", iconName: "scale", iconScale: 0.55 });
  s.addText("One Judge Decides", { x: 1.55, y: jy + 0.12, w: 3.4, h: 0.3, fontFace: FONT_BODY, fontSize: 13, bold: true, color: BLACK, isTextBox: true, margin: 0 });
  s.addText("Weighs all six checks together — and says exactly which ones agreed or disagreed, and why.", { x: 1.55, y: jy + 0.42, w: 9.9, h: 0.35, fontFace: FONT_BODY, fontSize: 11, color: "3A3A3A", isTextBox: true, margin: 0 });
  pageNum(s, 4);
}

// =====================================================================
// SLIDE 5 — USER FLOW + EVALUATION KIT
// =====================================================================
{
  const s = pres.addSlide({ masterName: "DARK" });
  kicker(s, "User Flow & How We Test It");
  title(s, "What the user sees. How we prove it works.", { size: 27, w: 12 });

  const steps = [
    { icon: "idcard", h: "Scan ID", d: "Photo of the ID card." },
    { icon: "camera", h: "Take Selfie", d: "Camera only — no gallery uploads." },
    { icon: "layers", h: "Checks Run", d: "All six checks run together." },
    { icon: "gavel", h: "Get Result", d: "Accept, reject, or human review." },
    { icon: "link", h: "Saved On-Chain", d: "Signed and anchored — auditable." },
  ];
  const cw = 2.02, gap = 0.135, startX = 0.6, cy = 2.05, ch = 2.15;
  steps.forEach((st, i) => {
    const x = startX + i * (cw + gap);
    s.addShape("roundRect", { x, y: cy, w: cw, h: ch, rectRadius: 0.09, fill: { color: CHARCOAL }, line: { color: "2E2E2E", width: 0.75 } });
    s.addText(`${i + 1}`, { x: x + 0.12, y: cy + 0.1, w: 0.5, h: 0.35, fontFace: FONT_HEAD, fontSize: 15, bold: true, color: MUTED_DK, isTextBox: true, margin: 0 });
    badge(s, { x: x + (cw - 0.5) / 2, y: cy + 0.45, d: 0.5, style: "yellow", iconName: st.icon, iconScale: 0.54 });
    s.addText(st.h, { x: x + 0.1, y: cy + 1.08, w: cw - 0.2, h: 0.4, fontFace: FONT_BODY, fontSize: 12, bold: true, color: WHITE, align: "center", isTextBox: true, margin: 0 });
    s.addText(st.d, { x: x + 0.12, y: cy + 1.5, w: cw - 0.24, h: ch - 1.6, fontFace: FONT_BODY, fontSize: 8.8, color: MUTED, align: "center", isTextBox: true, margin: 0, lineSpacingMultiple: 1.15 });
    if (i < steps.length - 1) s.addText("›", { x: x + cw + 0.005, y: cy + ch / 2 - 0.25, w: 0.13, h: 0.5, fontFace: FONT_BODY, fontSize: 20, bold: true, color: YELLOW_DK, align: "center", isTextBox: true, margin: 0 });
  });

  const ey = cy + ch + 0.35, eh = 1.35;
  s.addShape("roundRect", { x: 0.6, y: ey, w: 11.13, h: eh, rectRadius: 0.1, fill: { color: CHARCOAL2 }, line: { color: YELLOW, width: 1.25 } });
  badge(s, { x: 0.85, y: ey + 0.2, d: 0.55, style: "yellow", iconName: "listcheck", iconScale: 0.55 });
  s.addText("Evaluation Kit — don't just take our word for it", { x: 1.6, y: ey + 0.16, w: 9.9, h: 0.4, fontFace: FONT_BODY, fontSize: 14.5, bold: true, color: WHITE, isTextBox: true, margin: 0 });
  s.addText(
    "The same photo runs through our system AND a popular commercial detector, side by side, in one screen — " +
    "so the comparison is live, not a claim on a slide.",
    { x: 1.6, y: ey + 0.55, w: 9.9, h: 0.7, fontFace: FONT_BODY, fontSize: 11.5, color: MUTED, isTextBox: true, margin: 0, lineSpacingMultiple: 1.25 }
  );
  pageNum(s, 5);
}

// =====================================================================
// SLIDE 6 — LANE A: DATASET & MODEL (core part)
// =====================================================================
{
  const s = pres.addSlide({ masterName: "DARK" });
  kicker(s, "Inside Lane A — Our Trained Model");
  title(s, "The one check we trained ourselves", { size: 29 });

  badge(s, { x: 0.6, y: 2.15, d: 0.55, style: "yellow", iconName: "robot" });
  s.addText("Model: EfficientNet-B0", { x: 1.35, y: 2.18, w: 10.3, h: 0.4, fontFace: FONT_BODY, fontSize: 16, bold: true, color: WHITE, isTextBox: true, margin: 0 });
  s.addText("A small, fast image classifier — light enough to run on a normal server, no GPU required.", { x: 1.35, y: 2.55, w: 10.3, h: 0.4, fontFace: FONT_BODY, fontSize: 12, color: MUTED, isTextBox: true, margin: 0 });

  s.addText("TRAINED ON", { x: 0.6, y: 3.25, w: 5, h: 0.3, fontFace: FONT_BODY, fontSize: 12, bold: true, color: YELLOW, charSpacing: 1.5, isTextBox: true, margin: 0 });

  const rows = [
    { icon: "cube", h: "INP-X (Inpainting-Exchange)", d: "Real photos with an AI-edited face pasted in — teaches the model to spot a local edit." },
    { icon: "usershield", h: "140k Real-and-Fake Faces", d: "70,000 real photos vs. 70,000 StyleGAN-generated faces — teaches whole-image AI generation." },
    { icon: "route", h: "Real-world photo mix", d: "CityScapes, OpenImages, SUN RGB-D — everyday photos, not just posed studio headshots." },
  ];
  let ry = 3.65;
  rows.forEach((r) => {
    badge(s, { x: 0.6, y: ry, d: 0.46, style: "dark", iconName: r.icon, iconScale: 0.55 });
    s.addText(r.h, { x: 1.25, y: ry - 0.02, w: 10.4, h: 0.32, fontFace: FONT_BODY, fontSize: 13, bold: true, color: WHITE, isTextBox: true, margin: 0 });
    s.addText(r.d, { x: 1.25, y: ry + 0.3, w: 10.4, h: 0.4, fontFace: FONT_BODY, fontSize: 10.8, color: MUTED, isTextBox: true, margin: 0, lineSpacingMultiple: 1.15 });
    ry += 0.85;
  });

  s.addShape("roundRect", { x: 0.6, y: ry + 0.15, w: 11.13, h: 0.75, rectRadius: 0.1, fill: { color: CHARCOAL }, line: { color: YELLOW_DK, width: 1 } });
  s.addText("Still learning: being retrained on more real-world photos to reduce mistakes — its confidence is deliberately capped until that's done.", {
    x: 0.9, y: ry + 0.15, w: 10.5, h: 0.75, fontFace: FONT_BODY, fontSize: 11.5, italic: true, color: YELLOW, isTextBox: true, margin: 0, valign: "middle", lineSpacingMultiple: 1.2,
  });
  pageNum(s, 6);
}

// =====================================================================
// SLIDE 7 — THE PAPER WE BUILD ON (image placeholder, 2-line caption)
// =====================================================================
{
  const s = pres.addSlide({ masterName: "DARK" });
  kicker(s, "The Research Behind It");
  title(s, "Why we test this way", { size: 30 });

  pastePlaceholder(s, { x: 0.6, y: 2.1, w: 11.13, h: 3.9, label: "[ paste paper figure / screenshot here ]" });

  s.addText(
    "arXiv 2602.00192 — most AI-photo detectors get fooled once an edit is pasted into a real photo, " +
    "not the AI content itself. That's the exact trick we built and test our checks against.",
    { x: 0.6, y: 6.15, w: 11.13, h: 0.85, fontFace: FONT_BODY, fontSize: 13, color: MUTED, isTextBox: true, margin: 0, lineSpacingMultiple: 1.3 }
  );
  pageNum(s, 7);
}

// =====================================================================
// SLIDE 8 — DEMO PHOTOS (placeholder)
// =====================================================================
{
  const s = pres.addSlide({ masterName: "DARK" });
  kicker(s, "Live Demo");
  title(s, "See it in action", { size: 32 });

  pastePlaceholder(s, { x: 0.6, y: 2.1, w: 11.13, h: 4.4, label: "[ paste demo screenshots / photos here ]" });

  s.addText("Real captures, real verdicts — from testing this build, not a mockup.", {
    x: 0.6, y: 6.65, w: 11.13, h: 0.4, fontFace: FONT_BODY, fontSize: 12, italic: true, color: MUTED, isTextBox: true, margin: 0,
  });
  pageNum(s, 8);
}

pres.writeFile({ fileName: path.join(__dirname, "VeriLens_Pitch.pptx") }).then(() => console.log("written VeriLens_Pitch.pptx"));
