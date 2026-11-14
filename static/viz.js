// Charts + the "Under the hood" page. Plain canvas, no libraries.
(function () {
  const $ = (id) => document.getElementById(id);
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const fmtMs = (ms) => (ms >= 1000 ? (ms / 1000).toFixed(2) + " s" : Math.round(ms) + " ms");
  const fmtHz = (f) => (f >= 1000 ? f / 1000 + "k" : String(f));
  let displayNames;
  try { displayNames = new Intl.DisplayNames(["en"], { type: "language" }); } catch {}
  const langName = (c) => { try { return displayNames.of(c); } catch { return c; } };

  // ------------------------------------------------------------ canvas helpers
  function setup(canvas) {
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth, h = canvas.clientHeight;
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.font = '10px "JetBrains Mono", monospace';
    return { ctx, w, h };
  }

  function niceStep(range, target = 6) {
    const raw = range / target, p = 10 ** Math.floor(Math.log10(raw));
    return [1, 2, 5, 10].map((m) => m * p).find((s) => s >= raw);
  }
  const ticks = (min, max, n) => { const s = niceStep(max - min, n), out = []; for (let v = Math.ceil(min / s) * s; v <= max + 1e-9; v += s) out.push(+v.toFixed(6)); return out; };

  function axes(ctx, w, h, { x, y, pad = { l: 40, r: 10, t: 8, b: 20 } }) {
    const X0 = pad.l, X1 = w - pad.r, Y0 = pad.t, Y1 = h - pad.b;
    const sx = x.log
      ? (v) => X0 + (Math.log(v / x.min) / Math.log(x.max / x.min)) * (X1 - X0)
      : (v) => X0 + ((v - x.min) / (x.max - x.min)) * (X1 - X0);
    const sy = (v) => Y1 - ((Math.max(y.min, Math.min(y.max, v)) - y.min) / (y.max - y.min)) * (Y1 - Y0);
    ctx.strokeStyle = css("--line"); ctx.fillStyle = css("--muted"); ctx.lineWidth = 1;
    ctx.textAlign = "right"; ctx.textBaseline = "middle";
    for (const t of y.ticks || []) { const yy = sy(t); ctx.beginPath(); ctx.moveTo(X0, yy); ctx.lineTo(X1, yy); ctx.stroke(); ctx.fillText((y.fmt || String)(t), X0 - 5, yy); }
    ctx.textAlign = "center"; ctx.textBaseline = "top";
    for (const t of x.ticks || []) ctx.fillText((x.fmt || String)(t), sx(t), Y1 + 5);
    return { sx, sy, X0, X1, Y0, Y1 };
  }

  function path(ctx, pts, color, width = 1.5, dash) {
    ctx.save(); ctx.strokeStyle = color; ctx.lineWidth = width; if (dash) ctx.setLineDash(dash);
    ctx.beginPath(); pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.stroke(); ctx.restore();
  }

  function hline(ctx, a, yv, color, label, below = false) {
    const y = a.sy(yv);
    path(ctx, [[a.X0, y], [a.X1, y]], color, 1.5, [5, 4]);
    if (label) {
      ctx.fillStyle = color; ctx.textAlign = "right"; ctx.textBaseline = below ? "top" : "bottom";
      ctx.fillText(label, a.X1 - 2, below ? y + 2 : y - 2);
    }
  }

  function b64bytes(s) { const bin = atob(s), out = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i); return out; }

  // magma-like colour map (dark -> purple -> orange -> pale yellow)
  const LUT = (() => {
    const stops = [[0, 0, 4], [40, 15, 100], [120, 30, 125], [200, 55, 100], [245, 110, 70], [252, 190, 110], [252, 253, 191]];
    const lut = [];
    for (let i = 0; i < 256; i++) {
      const t = (i / 255) * (stops.length - 1), k = Math.min(stops.length - 2, Math.floor(t)), f = t - k;
      lut.push(stops[k].map((c, j) => Math.round(c + (stops[k + 1][j] - c) * f)));
    }
    return lut;
  })();
  const lutColor = (v) => { const c = LUT[Math.max(0, Math.min(255, Math.round(v)))]; return `rgb(${c[0]},${c[1]},${c[2]})`; };

  // Slaney mel scale: fraction of the mel axis where a frequency lands (for y-axis labels)
  const MAX_MEL = 45.245640471924965;
  const hzToFrac = (f) => (f < 1000 ? f / (200 / 3) : 15 + Math.log(f / 1000) / (Math.log(6.4) / 27)) / MAX_MEL;

  // ------------------------------------------------------------ individual charts
  function drawWave(canvas, v) {
    const { ctx, w, h } = setup(canvas);
    const d = v.duration;
    const a = axes(ctx, w, h, { x: { min: 0, max: d, ticks: ticks(0, d, 8), fmt: (t) => t + "s" }, y: { min: -1, max: 1, ticks: [-1, 0, 1] } });
    ctx.fillStyle = css("--trim");
    ctx.fillRect(a.X0, a.Y0, a.sx(v.trim[0]) - a.X0, a.Y1 - a.Y0);
    ctx.fillRect(a.sx(v.trim[1]), a.Y0, a.X1 - a.sx(v.trim[1]), a.Y1 - a.Y0);
    const draw = (env, color, alpha) => {
      ctx.save(); ctx.strokeStyle = color; ctx.globalAlpha = alpha; ctx.lineWidth = Math.max(1, (a.X1 - a.X0) / env.min.length);
      ctx.beginPath();
      env.min.forEach((mn, i) => { const x = a.X0 + ((i + 0.5) / env.min.length) * (a.X1 - a.X0); ctx.moveTo(x, a.sy(mn)); ctx.lineTo(x, a.sy(env.max[i])); });
      ctx.stroke(); ctx.restore();
    };
    draw(v.clean, css("--accent"), 0.75);
    draw(v.raw, css("--muted"), 0.6);
  }

  function drawSpectrum(canvas, v) {
    const { ctx, w, h } = setup(canvas);
    const all = v.spectrum_before.concat(v.spectrum_after).filter((x) => x > -150);
    const ymax = Math.ceil(Math.max(...all) / 10) * 10, ymin = Math.max(ymax - 90, Math.floor(Math.min(...all) / 10) * 10);
    const a = axes(ctx, w, h, {
      x: { min: 20, max: 8000, log: true, ticks: [50, 100, 200, 500, 1000, 2000, 5000], fmt: fmtHz },
      y: { min: ymin, max: ymax, ticks: ticks(ymin, ymax, 4), fmt: (t) => t },
    });
    ctx.fillStyle = css("--trim");
    ctx.fillRect(a.X0, a.Y0, a.sx(v.highpass_hz) - a.X0, a.Y1 - a.Y0);
    const pts = (arr) => arr.map((db, i) => [a.sx(v.freqs[i]), a.sy(db)]);
    path(ctx, pts(v.spectrum_before), css("--muted"), 1.5);
    path(ctx, pts(v.spectrum_after), css("--accent"), 2);
    // filter response on its own scale: 0 dB at top, -60 dB at bottom
    const fy = (db) => a.Y0 + (Math.min(0, Math.max(-60, db)) / -60) * (a.Y1 - a.Y0);
    path(ctx, v.filter_db.map((db, i) => [a.sx(v.freqs[i]), fy(db)]), css("--warn"), 1.5, [5, 4]);
    ctx.fillStyle = css("--warn"); ctx.textAlign = "left"; ctx.textBaseline = "top";
    ctx.fillText(`${v.highpass_hz} Hz cut`, a.sx(v.highpass_hz) + 4, a.Y0 + 2);
  }

  function drawVad(canvas, v) {
    const { ctx, w, h } = setup(canvas);
    const n = v.frame_db.length, ymin = Math.floor((v.noise_db - 20) / 10) * 10;
    const a = axes(ctx, w, h, { x: { min: 0, max: n, ticks: [] }, y: { min: ymin, max: 0, ticks: ticks(ymin, 0, 4) } });
    const bw = (a.X1 - a.X0) / n;
    v.frame_db.forEach((db, i) => {
      ctx.fillStyle = v.speech[i] ? css("--ok") : css("--line2");
      const y = a.sy(db);
      ctx.fillRect(a.X0 + i * bw, y, Math.max(1, bw - 0.5), a.Y1 - y);
    });
    hline(ctx, a, v.threshold_db, css("--err"), `threshold ${v.threshold_db} dB`);
    hline(ctx, a, v.noise_db, css("--muted"), `noise ${v.noise_db} dB`, true);
    ctx.fillStyle = css("--muted"); ctx.textAlign = "center"; ctx.textBaseline = "top";
    ctx.fillText(`${n} frames × ${v.frame_ms} ms`, (a.X0 + a.X1) / 2, a.Y1 + 5);
  }

  function drawFrame(canvas, ex) {
    const { ctx, w, h } = setup(canvas);
    const m = Math.max(...ex.samples.map(Math.abs)) || 1;
    const a = axes(ctx, w, h, { x: { min: 0, max: 400, ticks: [0, 200, 400] }, y: { min: -m, max: m, ticks: [0] }, pad: { l: 10, r: 10, t: 6, b: 18 } });
    const n = ex.samples.length;
    path(ctx, ex.window.map((wv, i) => [a.sx((i / (n - 1)) * 400), a.sy(wv * m)]), css("--warn"), 1.2, [4, 3]);
    path(ctx, ex.samples.map((s, i) => [a.sx((i / (n - 1)) * 400), a.sy(s)]), css("--accent"), 1.5);
  }

  function drawPower(canvas, ex) {
    const { ctx, w, h } = setup(canvas);
    const ymax = Math.ceil(Math.max(...ex.power_db) / 10) * 10, ymin = ymax - 80;
    const a = axes(ctx, w, h, { x: { min: 0, max: 8000, ticks: [0, 2000, 4000, 6000, 8000], fmt: fmtHz }, y: { min: ymin, max: ymax, ticks: ticks(ymin, ymax, 3) }, pad: { l: 30, r: 8, t: 6, b: 18 } });
    const pts = ex.power_db.map((db, i) => [a.sx((i / 200) * 8000), a.sy(db)]);
    ctx.save(); ctx.fillStyle = css("--accent"); ctx.globalAlpha = 0.25; ctx.beginPath(); ctx.moveTo(a.X0, a.Y1);
    pts.forEach(([x, y]) => ctx.lineTo(x, y)); ctx.lineTo(a.X1, a.Y1); ctx.fill(); ctx.restore();
    path(ctx, pts, css("--accent"), 1.2);
  }

  function drawFilters(canvas, mel) {
    const { ctx, w, h } = setup(canvas);
    const { rows, cols } = mel.filters, data = b64bytes(mel.filters.data);
    const a = axes(ctx, w, h, { x: { min: 0, max: 8000, ticks: [0, 2000, 4000, 6000, 8000], fmt: fmtHz }, y: { min: 0, max: 255, ticks: [] }, pad: { l: 10, r: 8, t: 6, b: 18 } });
    for (let r = 0; r < rows; r += 4) {
      const pts = [];
      for (let c = 0; c < cols; c++) pts.push([a.sx((c / (cols - 1)) * 8000), a.sy(data[r * cols + c])]);
      path(ctx, pts, `hsl(${250 - (r / rows) * 220} 75% 60%)`, 1.2);
    }
  }

  function drawMelVec(canvas, mel) {
    const { ctx, w, h } = setup(canvas);
    const vals = mel.example.log_mel, s = mel.spectrogram;
    const a = axes(ctx, w, h, { x: { min: 0, max: vals.length, ticks: [0, 32, 64, 96, 128].filter((t) => t <= vals.length) }, y: { min: s.min, max: s.max, ticks: [s.min, s.max].map((v) => +v.toFixed(1)) }, pad: { l: 30, r: 8, t: 6, b: 18 } });
    const bw = (a.X1 - a.X0) / vals.length;
    vals.forEach((v, i) => {
      ctx.fillStyle = lutColor(((v - s.min) / (s.max - s.min)) * 255);
      const y = a.sy(v); ctx.fillRect(a.X0 + i * bw, y, Math.max(1, bw - 0.3), a.Y1 - y);
    });
  }

  let melImage = null; // cached offscreen render of the spectrogram
  function drawMel(canvas, mel, words, progress = 1, highlight = -1) {
    const { ctx, w, h } = setup(canvas);
    const s = mel.spectrogram, pad = { l: 44, r: 10, t: 26, b: 20 };
    const X0 = pad.l, X1 = w - pad.r, Y0 = pad.t, Y1 = h - pad.b;
    if (!melImage || melImage.key !== s.data.length + s.cols) {
      const data = b64bytes(s.data), off = document.createElement("canvas");
      off.width = s.cols; off.height = s.rows;
      const img = off.getContext("2d").createImageData(s.cols, s.rows);
      for (let r = 0; r < s.rows; r++) for (let c = 0; c < s.cols; c++) {
        const col = LUT[data[r * s.cols + c]], o = ((s.rows - 1 - r) * s.cols + c) * 4; // low pitch at bottom
        img.data[o] = col[0]; img.data[o + 1] = col[1]; img.data[o + 2] = col[2]; img.data[o + 3] = 255;
      }
      off.getContext("2d").putImageData(img, 0, 0);
      melImage = { canvas: off, key: s.data.length + s.cols };
    }
    ctx.imageSmoothingEnabled = true;
    ctx.drawImage(melImage.canvas, X0, Y0, X1 - X0, Y1 - Y0);
    const dur = (mel.frames * mel.hop_ms) / 1000, sx = (t) => X0 + (t / dur) * (X1 - X0);
    if (progress < 1) { // dim the part the replay hasn't reached
      ctx.fillStyle = "rgba(10,12,20,.72)"; ctx.fillRect(sx(progress * dur), Y0, X1 - sx(progress * dur), Y1 - Y0);
      path(ctx, [[sx(progress * dur), Y0 - 4], [sx(progress * dur), Y1]], css("--accent"), 2);
    }
    // axes labels
    ctx.fillStyle = css("--muted"); ctx.textAlign = "right"; ctx.textBaseline = "middle";
    for (const f of [0, 500, 1000, 2000, 4000, 8000]) ctx.fillText(fmtHz(f) + "Hz", X0 - 5, Y1 - hzToFrac(f) * (Y1 - Y0));
    ctx.textAlign = "center"; ctx.textBaseline = "top";
    for (const t of ticks(0, dur, 8)) ctx.fillText(t + "s", sx(t), Y1 + 5);
    // words Whisper found, placed at their timestamps
    (words || []).forEach((wd, i) => {
      if (wd.start > progress * dur) return;
      const x0 = sx(wd.start), x1 = sx(Math.min(wd.end, dur));
      ctx.fillStyle = wd.low ? "rgba(240,160,32,.22)" : "rgba(255,255,255,.08)";
      ctx.fillRect(x0, Y0, Math.max(1, x1 - x0), Y1 - Y0);
      path(ctx, [[x0, Y0], [x0, Y1]], "rgba(255,255,255,.35)", 1);
      ctx.font = (i === highlight ? "600 " : "500 ") + '11px Inter, "Nirmala UI", sans-serif';
      ctx.fillStyle = wd.low ? css("--warn") : css("--text");
      ctx.textAlign = "left"; ctx.textBaseline = "top";
      ctx.fillText(wd.word.trim(), x0 + 2, 1 + (i % 2) * 12); // alternate rows so labels don't collide
    });
  }

  function drawOut(canvas, env, duration) {
    const { ctx, w, h } = setup(canvas);
    const a = axes(ctx, w, h, { x: { min: 0, max: duration, ticks: ticks(0, duration, 8), fmt: (t) => t + "s" }, y: { min: -1, max: 1, ticks: [-1, 0, 1] } });
    ctx.strokeStyle = css("--accent"); ctx.lineWidth = Math.max(1, (a.X1 - a.X0) / env.min.length);
    ctx.beginPath();
    env.min.forEach((mn, i) => { const x = a.X0 + ((i + 0.5) / env.min.length) * (a.X1 - a.X0); ctx.moveTo(x, a.sy(mn)); ctx.lineTo(x, a.sy(env.max[i])); });
    ctx.stroke();
  }

  // ------------------------------------------------------------ the page
  const numbers = (el, rows) => { $(el).innerHTML = rows.map(([k, v, cls]) => `<div><dt>${k}</dt><dd class="${cls || ""}">${v}</dd></div>`).join(""); };
  const D = {};       // data from the latest run, by stage
  let anim = null;    // replay animation handle
  let pendingReplay = false;
  const visible = () => !$("page-hood").hidden;

  function reset() {
    for (const k of Object.keys(D)) delete D[k];
    melImage = null;
    cancelAnimationFrame(anim);
    $("hood-body").hidden = true; $("hood-empty").hidden = false; $("replay").disabled = true;
    $("p-out").textContent = ""; $("tokens").innerHTML = ""; $("word-table").innerHTML = ""; $("segments").innerHTML = "";
  }

  function onEvent(ev) {
    if (ev.stage === "preprocess" && ev.status === "running") reset();
    if (ev.stage === "translate" && ev.status === "running") { $("p-out").textContent = ""; $("p-out").classList.add("caret"); delete D.translate; delete D.speak; }
    if (ev.stage === "translate" && ev.status === "token") { $("p-out").textContent += ev.delta; return; }
    if (ev.status !== "done") return;
    D[ev.stage] = ev;
    $("hood-body").hidden = false; $("hood-empty").hidden = true;
    if (ev.stage === "recognize") { $("replay").disabled = false; pendingReplay = true; }
    if (visible()) render(ev.stage);
  }

  function render(stage) {
    renderTimeline();
    if (stage === "preprocess") renderClean();
    if (stage === "features") renderFeatures();
    if (stage === "recognize") { renderLang(); if (pendingReplay) replay(); else renderDecode(1); }
    if (stage === "translate") renderTranslate();
    if (stage === "speak") renderSpeak();
  }

  function renderAll() {
    if (!D.preprocess) return;
    ["preprocess", "features", "recognize", "translate", "speak"].forEach((s) => D[s] && render(s));
  }

  function renderTimeline() {
    const parts = [
      ["Clean audio", D.preprocess?.ms, "#17a673"],
      ["Log-Mel", D.features?.ms, "#e08a1e"],
      ["Whisper decode", D.recognize && D.features ? D.recognize.ms - D.features.ms : D.recognize?.ms, "#5b5bf0"],
      ["LLM translate", D.translate?.ms, "#b04fd8"],
      ["Speech synth", D.speak?.ms, "#e04b5a"],
    ].filter((p) => p[1] != null);
    const total = parts.reduce((s, p) => s + p[1], 0);
    $("timeline").innerHTML = parts.map(([n, ms, c]) => `<div style="flex:${Math.max(ms, total * 0.04)};background:${c}" title="${n}: ${fmtMs(ms)}">${n} · ${fmtMs(ms)}</div>`).join("");
  }

  function renderClean() {
    const p = D.preprocess, v = p.viz, r = p.report;
    $("hp-hz").textContent = v.highpass_hz; $("vad-ms").textContent = v.frame_ms;
    drawWave($("c-wave"), v); drawSpectrum($("c-spectrum"), v); drawVad($("c-vad"), v);
    numbers("n-clean", [
      ["Recorded", r.input_seconds + " s"],
      ["DC offset removed", v.dc_offset],
      ["Peak after filter", v.peak_before],
      ["Gain applied", (r.gain_db >= 0 ? "+" : "") + r.gain_db + " dB"],
      ["Noise floor", r.noise_floor_db + " dBFS"],
      ["Speech threshold", v.threshold_db + " dBFS"],
      ["Speech level", r.speech_level_db + " dBFS"],
      ["Signal-to-noise", r.snr_db + " dB", r.snr_db >= 20 ? "good" : ""],
      ["Speech frames", `${v.speech_frames} / ${v.total_frames}`],
      ["Kept after trim", `${v.trim[0]}–${v.trim[1]} s`],
      ["Clipping", r.clipped ? "yes ⚠" : "none", r.clipped ? "" : "good"],
      ["Front-end time", fmtMs(p.ms)],
    ]);
  }

  function renderFeatures() {
    const m = D.features.mel, ex = m.example;
    document.querySelectorAll(".n-mels").forEach((e) => (e.textContent = m.n_mels));
    const steps = [
      ["Input", `${m.samples.toLocaleString()} samples @16 kHz`],
      ["Frames", `${m.win_ms} ms window, ${m.hop_ms} ms hop`],
      ["Window", "Hann"],
      ["FFT", `${m.frames} × ${m.fft_bins} bins`],
      ["Mel filters", `${m.fft_bins} → ${m.n_mels} bands`],
      ["log₁₀", `floor = max − 8 (${m.clamp_floor})`],
      ["Scale", "(x + 4) / 4"],
      ["Pad", `${m.frames} → ${m.padded_to_frames} frames (30 s)`],
    ];
    $("mel-chain").innerHTML = steps.map(([b, s], i) => (i ? '<li class="arrow">→</li>' : "") + `<li><b>${b}</b><span>${s}</span></li>`).join("");
    $("frame-label").textContent = `(frame #${ex.frame} at ${ex.time_s} s)`;
    drawFrame($("c-frame"), ex); drawPower($("c-power"), ex); drawFilters($("c-filters"), m); drawMelVec($("c-melvec"), m);
    drawMel($("c-mel"), m, D.recognize?.words, 1);
    const diff = m.max_abs_diff_vs_whisper;
    numbers("n-mel", [
      ["Matrix shape", `${m.n_mels} × ${m.frames}`],
      ["Numbers computed", (m.n_mels * m.frames).toLocaleString()],
      ["FFTs run", m.frames.toLocaleString()],
      ["Value range", `${m.spectrogram.min} … ${m.spectrogram.max}`],
      ["Matches Whisper's code", diff < 1e-4 ? `✓ identical (Δ ${diff.toExponential(0)})` : `Δ ${diff.toFixed(4)}`, diff < 1e-4 ? "good" : ""],
      ["Time", fmtMs(D.features.ms)],
    ]);
  }

  function renderLang() {
    const r = D.recognize;
    $("n-langs").textContent = r.languages_considered;
    $("lang-bars").innerHTML = r.language_candidates.map((c) =>
      `<div class="bar"><span>${esc(langName(c.code))}</span><div class="track"><div class="fill" data-w="${c.prob * 100}"></div></div><span class="v">${(c.prob * 100).toFixed(c.prob < 0.01 ? 2 : 1)}%</span></div>`).join("");
    requestAnimationFrame(() => document.querySelectorAll("#lang-bars .fill").forEach((f) => (f.style.width = Math.max(0.5, f.dataset.w) + "%")));
  }

  function tokenList(r) {
    const head = ["<|startoftranscript|>", `<|${r.language}|>`, "<|transcribe|>"].map((t) => ({ text: t, special: true }));
    const body = r.segments.flatMap((s) => s.tokens.map((t) => ({ text: t.text, id: t.id })));
    return head.concat(body, [{ text: "<|endoftext|>", special: true }]);
  }

  function renderDecode(progress) {
    const r = D.recognize; if (!r) return;
    $("n-vocab").textContent = r.decoding.vocab_size.toLocaleString();
    $("n-beam").textContent = r.decoding.beam_size;
    $("n-lowthr").textContent = Math.round(r.decoding.low_confidence_threshold * 100) + "%";
    const toks = tokenList(r), nTok = Math.ceil(progress * toks.length);
    const tokEl = $("tokens");
    if (tokEl.children.length > nTok) tokEl.innerHTML = "";
    for (let i = tokEl.children.length; i < nTok; i++) {
      const t = toks[i];
      tokEl.insertAdjacentHTML("beforeend", `<span class="tok${t.special ? " special" : ""}"><span>${esc(t.text)}</span><small>${t.special ? "special" : "#" + t.id}</small></span>`);
    }
    const dur = D.features ? (D.features.mel.frames * D.features.mel.hop_ms) / 1000 : 1e9;
    const shown = r.words.filter((w) => w.start <= progress * dur);
    const wt = $("word-table");
    if (wt.children.length > shown.length) wt.innerHTML = "";
    for (let i = wt.children.length; i < shown.length; i++) {
      const w = shown[i], pct = Math.round(w.prob * 100), col = pct >= 80 ? "var(--ok)" : pct >= 60 ? "var(--warn)" : "var(--err)";
      wt.insertAdjacentHTML("beforeend", `<div class="wcell${w.low ? " low" : ""}"><b>${esc(w.word.trim())}</b><small>${w.start.toFixed(2)}–${w.end.toFixed(2)} s · ${pct}%</small><div class="meter"><i style="width:${pct}%;background:${col}"></i></div></div>`);
    }
    if (D.features) drawMel($("c-mel"), D.features.mel, r.words, progress);
    if (progress >= 1) {
      $("segments").innerHTML = r.segments.map((s, i) => `<div class="seg"><p><b>Segment ${i + 1}</b> · ${s.start}–${s.end} s · “${esc(s.text)}”</p><dl class="numbers">
        <div><dt>avg log-prob</dt><dd>${s.avg_logprob}</dd></div>
        <div><dt>avg token prob</dt><dd>${Math.round(s.avg_token_prob * 100)}%</dd></div>
        <div><dt>compression ratio</dt><dd class="${s.compression_ratio < 2.4 ? "good" : ""}">${s.compression_ratio} ${s.compression_ratio < 2.4 ? "✓" : "⚠"}</dd></div>
        <div><dt>no-speech prob</dt><dd>${(s.no_speech_prob * 100).toFixed(1)}%</dd></div>
        <div><dt>temperature used</dt><dd>${s.temperature}${s.temperature > 0 ? " (fallback)" : " (greedy-safe)"}</dd></div>
        <div><dt>text / special tokens</dt><dd>${s.tokens.length} / ${s.special_tokens}</dd></div></dl></div>`).join("");
    }
  }

  function replay() {
    pendingReplay = false;
    cancelAnimationFrame(anim);
    $("tokens").innerHTML = ""; $("word-table").innerHTML = ""; $("segments").innerHTML = "";
    const start = performance.now(), dur = Math.min(6000, Math.max(2500, (D.recognize?.words.length || 10) * 220));
    const step = (now) => {
      const p = Math.min(1, (now - start) / dur);
      renderDecode(p);
      if (p < 1) anim = requestAnimationFrame(step);
    };
    anim = requestAnimationFrame(step);
  }

  function renderTranslate() {
    const t = D.translate;
    $("llm-name").textContent = t.stats?.model || "the LLM";
    $("p-system").textContent = t.system_prompt;
    $("p-user").textContent = t.input;
    $("p-out").textContent = t.text; $("p-out").classList.remove("caret");
    $("p-out").lang = t.target;
    if (t.skipped) return numbers("n-translate", [["Skipped", "source = target"]]);
    const s = t.stats;
    numbers("n-translate", [
      ["Prompt tokens read", s.prompt_tokens], ["Tokens generated", s.output_tokens],
      ["Speed", s.tokens_per_s + " tok/s"], ["Reading prompt", fmtMs(s.prompt_ms)],
      ["Generating", fmtMs(s.generate_ms)], ["Model load", fmtMs(s.load_ms)], ["Temperature", s.temperature],
    ]);
  }

  function renderSpeak() {
    const s = D.speak;
    drawOut($("c-out"), s.envelope, s.duration);
    numbers("n-speak", [
      ["Engine", s.engine], ["Voice", s.voice + (s.fallback ? " (fallback)" : "")], ["Characters in", s.characters],
      ["Audio out", s.duration + " s"], ["Speed", (s.rate >= 0 ? "+" : "") + s.rate + "%"], ["Pitch", (s.pitch >= 0 ? "+" : "") + s.pitch + " Hz"],
      ["Synthesis time", fmtMs(s.ms)], ["Real-time factor", (s.ms / 1000 / s.duration).toFixed(2) + "×"],
    ]);
  }

  $("replay").onclick = replay;
  let rt;
  window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => visible() && renderAll(), 150); });
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", () => visible() && renderAll());

  window.Hood = { onEvent, renderAll, reset, show: () => { renderAll(); } };
  window.Viz = { setup, axes, ticks, path, css, esc }; // shared drawing helpers for other pages
})();
