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
  slide.addText(`${n} / 10`, { x: PW - 1.1, y: PH - 0.42, w: 0.9, h: 0.3, fontFace: FONT_BODY, fontSize: 10, color: MUTED_DK, align: "right", isTextBox: true, margin: 0 });
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

// =====================================================================
// SLIDE 1 — TITLE
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
// SLIDE 2 — THE PROBLEM
// =====================================================================
{
  const s = pres.addSlide({ masterName: "DARK" });
  kicker(s, "The Problem");
  title(s, "KYC identity checks were built for a world\nwhere a photo was hard to fake.", { size: 30 });
  s.addText("That world is gone.", { x: 0.6, y: 2.28, w: 8, h: 0.5, fontFace: FONT_BODY, fontSize: 16, italic: true, color: YELLOW, isTextBox: true, margin: 0 });

  const stats = [
    { num: "11%", label: "of all global fraud in 2026 is deepfake-driven — up from 7% in 2024" },
    { num: "+2,665%", label: "YoY surge in native virtual-camera injection attacks (iProov, 2026)" },
    { num: "$20/mo", label: "buys real-time face-swap + camera injection as fraud-as-a-service" },
  ];
  const gap = 0.35, cw = (11.13 - gap * 2) / 3, cy = 3.1, ch = 2.4;
  stats.forEach((st, i) => statCallout(s, { x: 0.6 + i * (cw + gap), y: cy, w: cw, h: ch, num: st.num, label: st.label }));

  s.addText(
    "Every hackathon team will show a photo, and a percentage. That answers the wrong question — the real attack is " +
    "injecting a synthetic image at the exact point a bank trusts the camera.",
    { x: 0.6, y: 5.85, w: 11.1, h: 0.9, fontFace: FONT_BODY, fontSize: 13.5, color: MUTED, isTextBox: true, margin: 0, lineSpacingMultiple: 1.3 }
  );
  pageNum(s, 2);
}

// =====================================================================
// SLIDE 3 — WHAT EVERYONE ELSE BUILDS
// =====================================================================
{
  const s = pres.addSlide({ masterName: "DARK" });
  kicker(s, "The Crowded Field");
  title(s, "What a generic detector looks like", { size: 30 });

  const rows = [
    { icon: "eyeslash", h: "One image in", d: "No pairing to an identity document — detects a photo, not a KYC applicant." },
    { icon: "question", h: "One opaque number out", d: "“87% fake.” No region, no signal, nothing a compliance officer can act on." },
    { icon: "xmark", h: "Forced binary guess", d: "Blurry or compressed input still gets a confident verdict — no way to say “unsure.”" },
    { icon: "warning", h: "Blind to the real attack", d: "Global-artifact detectors miss local edits — exactly what fraudsters use (next slide)." },
  ];
  const rowH = 1.0, startY = 2.1;
  rows.forEach((r, i) => {
    const y = startY + i * (rowH + 0.14);
    s.addShape("roundRect", { x: 0.6, y, w: 11.13, h: rowH, rectRadius: 0.08, fill: { color: i % 2 ? CHARCOAL : CHARCOAL2 }, line: { type: "none" } });
    badge(s, { x: 0.85, y: y + (rowH - 0.54) / 2, d: 0.54, style: "dark", iconName: r.icon, iconScale: 0.55 });
    s.addText(r.h, { x: 1.65, y: y + 0.1, w: 4.3, h: 0.4, fontFace: FONT_BODY, fontSize: 15, bold: true, color: WHITE, isTextBox: true, margin: 0 });
    s.addText(r.d, { x: 6.0, y: y + 0.08, w: 5.5, h: rowH - 0.18, fontFace: FONT_BODY, fontSize: 12, color: MUTED, isTextBox: true, margin: 0, valign: "middle", lineSpacingMultiple: 1.15 });
  });
  pageNum(s, 3);
}

// =====================================================================
// SLIDE 4 — THE RESEARCH GAP
// =====================================================================
{
  const s = pres.addSlide({ masterName: "DARK" });
  kicker(s, "The Insight We Build On");
  title(s, "Published detectors don’t fail randomly.\nThey fail in one specific, documented way.", { size: 27, w: 12 });

  badge(s, { x: 0.6, y: 2.35, d: 0.6, style: "yellow", iconName: "flask" });
  s.addText("arXiv 2602.00192 — “AI-Generated Image Detectors Overrely on Global Artifacts”", { x: 1.42, y: 2.4, w: 10.8, h: 0.55, fontFace: FONT_BODY, fontSize: 14.5, bold: true, color: WHITE, isTextBox: true, margin: 0 });
  s.addText(
    "Detectors learn a global VAE spectral shift left across the WHOLE image by inpainting — not the synthesised content itself. " +
    "“Inpainting Exchange” (INP-X) restores original pixels outside the edited region, isolating that shortcut.",
    { x: 1.42, y: 2.95, w: 10.7, h: 0.7, fontFace: FONT_BODY, fontSize: 12.5, color: MUTED, isTextBox: true, margin: 0, lineSpacingMultiple: 1.25 }
  );

  const cy = 3.95, ch = 1.55, cw = 5.35, gap = 0.5;
  s.addShape("roundRect", { x: 0.6, y: cy, w: cw, h: ch, rectRadius: 0.1, fill: { color: CHARCOAL }, line: { color: "2E2E2E", width: 0.75 } });
  s.addText("Standard inpainting", { x: 0.9, y: cy + 0.16, w: cw - 0.6, h: 0.35, fontFace: FONT_BODY, fontSize: 12.5, color: MUTED, isTextBox: true, margin: 0 });
  s.addText("~91%", { x: 0.9, y: cy + 0.5, w: cw - 0.6, h: 0.9, fontFace: FONT_HEAD, fontSize: 46, bold: true, color: YELLOW, isTextBox: true, margin: 0 });
  s.addText("Sightengine & Hive accuracy", { x: 0.9, y: cy + ch - 0.35, w: cw - 0.6, h: 0.3, fontFace: FONT_BODY, fontSize: 10.5, color: MUTED, isTextBox: true, margin: 0 });

  s.addShape("roundRect", { x: 0.6 + cw + gap, y: cy, w: cw, h: ch, rectRadius: 0.1, fill: { color: CHARCOAL }, line: { color: "2E2E2E", width: 0.75 } });
  s.addText("On INP-X exchanged images", { x: 0.9 + cw + gap, y: cy + 0.16, w: cw - 0.6, h: 0.35, fontFace: FONT_BODY, fontSize: 12.5, color: MUTED, isTextBox: true, margin: 0 });
  s.addText("~55%", { x: 0.9 + cw + gap, y: cy + 0.5, w: cw - 0.6, h: 0.9, fontFace: FONT_HEAD, fontSize: 46, bold: true, color: RED, isTextBox: true, margin: 0 });
  s.addText("Chance level — a coin flip", { x: 0.9 + cw + gap, y: cy + ch - 0.35, w: cw - 0.6, h: 0.3, fontFace: FONT_BODY, fontSize: 10.5, color: MUTED, isTextBox: true, margin: 0 });

  s.addText(
    "The best fix published (FUSED, Aug 2026) explicitly excludes face manipulation. Faces are exactly what KYC checks — and " +
    "the paper shows faces have the narrowest global-artifact shortcut, i.e. the domain where this blind spot matters most.",
    { x: 0.6, y: 5.75, w: 11.1, h: 0.85, fontFace: FONT_BODY, fontSize: 12.5, color: YELLOW, isTextBox: true, margin: 0, lineSpacingMultiple: 1.3, italic: true }
  );
  pageNum(s, 4);
}

// =====================================================================
// SLIDE 5 — THE PROCESS, AS LAYERS  (reworked: horizontal layer stack)
// =====================================================================
{
  const s = pres.addSlide({ masterName: "DARK" });
  kicker(s, "How It Works — Layer by Layer");
  title(s, "One request. Five ordered layers.", { size: 30 });

  const layers = [
    { icon: "layercapture", h: "1. Capture", d: "ID document photo + live selfie. Selfie is camera-only — no gallery path." },
    { icon: "layergate", h: "2. Quality Gate", d: "Resolution, blur, JPEG quality checked first. Unreadable input is rejected before any lane runs." },
    { icon: "layerlanes", h: "3. Detection Lanes", d: "Six independent forensic checks run in parallel — synthesis, noise, compression, attestation, face match, replay detection." },
    { icon: "layerjudge", h: "4. Judge", d: "Cross-checks which lanes agree. Disagreement or low coverage → abstain, not guess." },
    { icon: "layerchain", h: "5. Verdict + Anchor", d: "Three-axis verdict returned, signed, and anchored on Sepolia — the decision is now auditable." },
  ];

  const startX = 0.6, barW = 11.13, barH = 0.92, gapY = 0.145, startY = 2.05;
  layers.forEach((l, i) => {
    const y = startY + i * (barH + gapY);
    const indent = i * 0.16; // each layer nudges right — reads as a pipeline, not a list
    s.addShape("roundRect", { x: startX + indent, y, w: barW - indent, h: barH, rectRadius: 0.08, fill: { color: i % 2 ? CHARCOAL : CHARCOAL2 }, line: { color: YELLOW_DK, width: i === 2 ? 1.25 : 0 } });
    badge(s, { x: startX + indent + 0.18, y: y + (barH - 0.56) / 2, d: 0.56, style: "yellow", iconName: l.icon, iconScale: 0.55 });
    s.addText(l.h, { x: startX + indent + 0.9, y: y + 0.12, w: 2.6, h: barH - 0.24, fontFace: FONT_BODY, fontSize: 14, bold: true, color: WHITE, isTextBox: true, margin: 0, valign: "middle" });
    s.addText(l.d, { x: startX + indent + 3.6, y: y + 0.1, w: barW - indent - 3.85, h: barH - 0.2, fontFace: FONT_BODY, fontSize: 11.3, color: MUTED, isTextBox: true, margin: 0, valign: "middle", lineSpacingMultiple: 1.18 });
  });
  pageNum(s, 5);
}

// =====================================================================
// SLIDE 6 — FIVE LANES, DETAIL
// =====================================================================
{
  const s = pres.addSlide({ masterName: "DARK" });
  kicker(s, "Layer 3, Expanded");
  title(s, "Six independent lanes. One accountable judge.", { size: 28 });

  const lanes = [
    { icon: "layers", n: "A", h: "Local Synthesis", d: "Patch-level, trained on INP-X exchanged images — reads content, not the global shortcut." },
    { icon: "magnify", n: "B", h: "Noise Residual", d: "Flags regions unnaturally clean for their detail level — the signature of generated content." },
    { icon: "code", n: "C", h: "Compression / ELA", d: "Recompression error inconsistent with local detail — catches splices and pasted portraits." },
    { icon: "camera", n: "D", h: "Capture Attestation", d: "Signed, single-use nonce proves live capture — absence is never evidence of fakery." },
    { icon: "usershield", n: "E", h: "Face Match", d: "ArcFace similarity between the ID photo and the selfie — the identity axis." },
    { icon: "mobile", n: "G", h: "Replay Detection", d: "Patch-wise frequency analysis catches a screen or printout held up to the camera." },
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
  s.addText("Rule-based Judge", { x: 1.55, y: jy + 0.12, w: 3.4, h: 0.3, fontFace: FONT_BODY, fontSize: 13, bold: true, color: BLACK, isTextBox: true, margin: 0 });
  s.addText("Cross-checks usable lanes · abstains on disagreement — explainable by construction, not a black box", { x: 1.55, y: jy + 0.42, w: 9.9, h: 0.35, fontFace: FONT_BODY, fontSize: 11, color: "3A3A3A", isTextBox: true, margin: 0 });
  pageNum(s, 6);
}

// =====================================================================
// SLIDE 7 — THREE-AXIS VERDICT + ABSTENTION
// =====================================================================
{
  const s = pres.addSlide({ masterName: "DARK" });
  kicker(s, "The Output");
  title(s, "Three independent axes. Never one blended score.", { size: 29 });
  s.addText("“A real photo of the wrong person” and “an AI selfie of the right person” are different failures.", { x: 0.6, y: 1.78, w: 11.5, h: 0.4, fontFace: FONT_BODY, fontSize: 13, italic: true, color: MUTED, isTextBox: true, margin: 0 });

  const axes = [
    { icon: "check", label: "AUTHENTICITY", vals: ["REAL", "LIKELY_FAKE", "INSUFFICIENT_EVIDENCE"] },
    { icon: "usershield", label: "IDENTITY", vals: ["MATCH", "MISMATCH", "INDETERMINATE"] },
    { icon: "gavel", label: "DECISION", vals: ["ACCEPT", "REJECT", "REVIEW"] },
  ];
  const cw = 3.55, gap = 0.24, cy = 2.35, ch = 2.05;
  axes.forEach((a, i) => {
    const x = 0.6 + i * (cw + gap);
    s.addShape("roundRect", { x, y: cy, w: cw, h: ch, rectRadius: 0.1, fill: { color: CHARCOAL }, line: { color: "2E2E2E", width: 0.75 } });
    badge(s, { x: x + 0.2, y: cy + 0.2, d: 0.48, style: "yellow", iconName: a.icon, iconScale: 0.55 });
    s.addText(a.label, { x: x + 0.82, y: cy + 0.24, w: cw - 1.0, h: 0.4, fontFace: FONT_BODY, fontSize: 13, bold: true, color: WHITE, isTextBox: true, margin: 0, valign: "middle" });
    a.vals.forEach((v, j) => s.addText(v, { x: x + 0.22, y: cy + 0.82 + j * 0.38, w: cw - 0.44, h: 0.34, fontFace: FONT_BODY, fontSize: 11.5, color: MUTED, isTextBox: true, margin: 0 }));
  });

  s.addShape("roundRect", { x: 0.6, y: cy + ch + 0.28, w: 11.13, h: 1.5, rectRadius: 0.1, fill: { color: CHARCOAL2 }, line: { color: YELLOW, width: 1.25 } });
  badge(s, { x: 0.85, y: cy + ch + 0.46, d: 0.58, style: "yellow", iconName: "question", iconScale: 0.55 });
  s.addText("Abstention is a feature, not a gap.", { x: 1.65, y: cy + ch + 0.4, w: 9.9, h: 0.4, fontFace: FONT_BODY, fontSize: 15, bold: true, color: WHITE, isTextBox: true, margin: 0 });
  s.addText(
    "Four independent triggers route to review: unreadable image quality, too few usable lanes, lane disagreement, or a score inside the " +
    "uncertainty band. A confidently wrong reject locks a real person out of their bank account — refusing to guess is the correct output.",
    { x: 1.65, y: cy + ch + 0.75, w: 9.9, h: 0.85, fontFace: FONT_BODY, fontSize: 11.3, color: MUTED, isTextBox: true, margin: 0, lineSpacingMultiple: 1.25 }
  );
  pageNum(s, 7);
}

// =====================================================================
// SLIDE 8 — DEMO FLOW
// =====================================================================
{
  const s = pres.addSlide({ masterName: "DARK" });
  kicker(s, "How A Check Actually Runs");
  title(s, "One KYC check, start to finish", { size: 30 });

  const steps = [
    { icon: "idcard", h: "ID Document", d: "Photo of the ID card. Gallery import allowed." },
    { icon: "camera", h: "Live Selfie", d: "Camera-only — no gallery path. Blocks the injection attack." },
    { icon: "layers", h: "Forensic Lanes", d: "Quality gate, then lanes run in parallel on both images." },
    { icon: "gavel", h: "Verdict + Reasons", d: "Three axes, per-lane evidence, confidence labelled uncalibrated." },
    { icon: "link", h: "Anchored", d: "Verdict digest signed + anchored on Sepolia. Auditable, forever." },
  ];
  const cw = 2.02, gap = 0.135, startX = 0.6, cy = 2.2, ch = 2.9;
  steps.forEach((st, i) => {
    const x = startX + i * (cw + gap);
    s.addShape("roundRect", { x, y: cy, w: cw, h: ch, rectRadius: 0.09, fill: { color: CHARCOAL }, line: { color: "2E2E2E", width: 0.75 } });
    s.addText(`${i + 1}`, { x: x + 0.12, y: cy + 0.12, w: 0.5, h: 0.4, fontFace: FONT_HEAD, fontSize: 16, bold: true, color: MUTED_DK, isTextBox: true, margin: 0 });
    badge(s, { x: x + (cw - 0.54) / 2, y: cy + 0.55, d: 0.54, style: "yellow", iconName: st.icon, iconScale: 0.54 });
    s.addText(st.h, { x: x + 0.12, y: cy + 1.28, w: cw - 0.24, h: 0.5, fontFace: FONT_BODY, fontSize: 12.5, bold: true, color: WHITE, align: "center", isTextBox: true, margin: 0 });
    s.addText(st.d, { x: x + 0.14, y: cy + 1.8, w: cw - 0.28, h: ch - 1.95, fontFace: FONT_BODY, fontSize: 9, color: MUTED, align: "center", isTextBox: true, margin: 0, lineSpacingMultiple: 1.15 });
    if (i < steps.length - 1) s.addText("›", { x: x + cw + 0.005, y: cy + ch / 2 - 0.25, w: 0.13, h: 0.5, fontFace: FONT_BODY, fontSize: 20, bold: true, color: YELLOW_DK, align: "center", isTextBox: true, margin: 0 });
  });

  s.addText(
    "Same app, same image, side by side: /v1/baseline runs a commercial detector and our judge together — the comparison the live demo turns on.",
    { x: 0.6, y: cy + ch + 0.3, w: 11.1, h: 0.5, fontFace: FONT_BODY, fontSize: 12.5, italic: true, color: MUTED, isTextBox: true, margin: 0 }
  );
  pageNum(s, 8);
}

// =====================================================================
// SLIDE 9 — AUDIT TRAIL + HONESTY (combined)
// =====================================================================
{
  const s = pres.addSlide({ masterName: "DARK" });
  kicker(s, "The Audit Trail & What We Don’t Claim");
  title(s, "The verdict is tamper-proof — and we say what it isn’t.", { size: 25, w: 12.1 });

  // left: audit trail items
  const left = 0.6, lw = 5.5, iy0 = 2.1;
  const items = [
    { icon: "fingerprint", h: "SHA-256 + Ed25519", d: "Both images hashed and signed by a per-device key at capture." },
    { icon: "cube", h: "Verdict digest anchored", d: "Hash of {hashes + authenticity + identity + decision + confidence + time} — not just the photo hash." },
    { icon: "link", h: "Ethereum Sepolia", d: "Data-only self-transfer, ABI-encoded payload. No contract deploy required." },
  ];
  let iy = iy0;
  items.forEach((it) => {
    badge(s, { x: left, y: iy, d: 0.46, style: "yellow", iconName: it.icon, iconScale: 0.55 });
    s.addText(it.h, { x: left + 0.65, y: iy - 0.02, w: lw - 0.65, h: 0.32, fontFace: FONT_BODY, fontSize: 12.5, bold: true, color: WHITE, isTextBox: true, margin: 0 });
    s.addText(it.d, { x: left + 0.65, y: iy + 0.3, w: lw - 0.65, h: 0.55, fontFace: FONT_BODY, fontSize: 10.3, color: MUTED, isTextBox: true, margin: 0, lineSpacingMultiple: 1.18 });
    iy += 0.92;
  });

  // right: what we don't claim (honesty cards, stacked)
  const rx = 6.55, rw = 5.2;
  const claims = [
    { icon: "info", h: "No novelty claim", d: "Established forensics. Our contribution is the KYC-specific system, not a new algorithm." },
    { icon: "scale", h: "Confidence uncalibrated", d: "Flagged false until validated — never shown as a real probability." },
    { icon: "eyeslash", h: "Trained lane still calibrating", d: "Confidence capped until validated on real-world photos, not just its own training set — a broader retrain is in progress." },
  ];
  let ry = 2.1;
  claims.forEach((c) => {
    s.addShape("roundRect", { x: rx, y: ry, w: rw, h: 1.28, rectRadius: 0.08, fill: { color: CHARCOAL }, line: { type: "none" } });
    badge(s, { x: rx + 0.18, y: ry + 0.18, d: 0.44, style: "dark", iconName: c.icon, iconScale: 0.55 });
    s.addText(c.h, { x: rx + 0.75, y: ry + 0.14, w: rw - 0.95, h: 0.32, fontFace: FONT_BODY, fontSize: 12, bold: true, color: YELLOW, isTextBox: true, margin: 0 });
    s.addText(c.d, { x: rx + 0.75, y: ry + 0.46, w: rw - 0.95, h: 0.75, fontFace: FONT_BODY, fontSize: 9.8, color: MUTED, isTextBox: true, margin: 0, lineSpacingMultiple: 1.18 });
    ry += 1.42;
  });
  pageNum(s, 9);
}

// =====================================================================
// SLIDE 10 — WHY WE STAND OUT / CLOSING
// =====================================================================
{
  const s = pres.addSlide({ masterName: "DARK" });
  kicker(s, "Why VeriLens Stands Out");
  title(s, "Others tell you if an image looks fake.\nWe tell you whether to trust the applicant.", { size: 27, w: 12, y: 1.15 });

  const pts = [
    { icon: "idcard", t: "ID + selfie, face-matched — real KYC, not a generic upload box" },
    { icon: "flask", t: "Targets a documented, published blind spot — not a vague novelty claim" },
    { icon: "gavel", t: "Per-lane reasoning and honest abstention — never a forced guess" },
    { icon: "link", t: "The decision itself is signed and anchored — a real audit trail" },
  ];
  let py = 3.15;
  pts.forEach((p) => {
    badge(s, { x: 0.7, y: py, d: 0.46, style: "yellow", iconName: p.icon, iconScale: 0.55 });
    s.addText(p.t, { x: 1.35, y: py + 0.02, w: 10.7, h: 0.42, fontFace: FONT_BODY, fontSize: 14, color: WHITE, isTextBox: true, margin: 0, valign: "middle" });
    py += 0.6;
  });

  s.addShape("rect", { x: PW / 2 - 1.6, y: 5.85, w: 3.2, h: 0.013, fill: { color: "2E2E2E" }, line: { type: "none" } });
  s.addText("Thank you — questions welcome.", { x: 0, y: 6.15, w: PW, h: 0.5, fontFace: FONT_HEAD, fontSize: 18, bold: true, color: YELLOW, align: "center", isTextBox: true, margin: 0 });
  pageNum(s, 10);
}

pres.writeFile({ fileName: path.join(__dirname, "VeriLens_Pitch.pptx") }).then(() => console.log("written VeriLens_Pitch.pptx"));
