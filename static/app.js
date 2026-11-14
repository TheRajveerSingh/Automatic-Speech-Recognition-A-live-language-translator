// Voice Translator front-end: record -> upload -> read streamed progress -> show results.
const $ = (id) => document.getElementById(id);
const els = {
  source: $("source"), target: $("target"), swap: $("swap"), recorder: $("recorder"), mic: $("mic"),
  wave: $("wave"), timer: $("timer"), hint: $("hint"), file: $("file"), steps: $("steps"),
  transcript: $("transcript"), detected: $("detected"), editBox: $("edit-box"), editBtn: $("edit-btn"),
  retranslateBtn: $("retranslate-btn"), confRow: $("conf-row"), confBar: $("conf-bar"), confVal: $("conf-val"),
  legend: $("legend"), translation: $("translation"), targetBadge: $("target-badge"), player: $("player"),
  play: $("play"), playBar: $("play-bar"), audio: $("audio"), download: $("download"), copy: $("copy"),
  status: $("status"), statusText: $("status-text"), toast: $("toast"), voice: $("voice"), preview: $("preview"),
  rate: $("rate"), pitch: $("pitch"), rateVal: $("rate-val"), pitchVal: $("pitch-val"), voiceNote: $("voice-note"),
};

let LANGS = {};          // code -> name
let lastResult = null;   // last recognition result (for edit / swap)
let busy = false;

// ------------------------------------------------------------- helpers
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch {} },
};
const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmtMs = (ms) => (ms >= 1000 ? (ms / 1000).toFixed(1) + " s" : ms + " ms");

function toast(msg, ok = false) {
  els.toast.textContent = msg;
  els.toast.style.background = ok ? "var(--ok)" : "";
  els.toast.hidden = false;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => (els.toast.hidden = true), 6000);
}

function setBusy(on) {
  busy = on;
  els.recorder.classList.toggle("busy", on);
  els.editBtn.disabled = on || !lastResult;
  els.retranslateBtn.disabled = on;
}

// ------------------------------------------------------------- pages (tabs)
const PAGES = ["translate", "hood", "bench", "talk", "summary"];
const pageHooks = {}; // other scripts register: pageHooks.bench = () => {...}
function showPage() {
  const want = location.hash.slice(1);
  const page = PAGES.includes(want) && $("page-" + want) ? want : "translate";
  for (const p of PAGES) { const el = $("page-" + p); if (el) el.hidden = p !== page; }
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.page === page));
  if (page === "hood") requestAnimationFrame(() => Hood.show());
  if (pageHooks[page]) requestAnimationFrame(pageHooks[page]);
}
window.addEventListener("hashchange", showPage);

// ------------------------------------------------------------- setup
async function init() {
  const langs = await (await fetch("/api/languages")).json();
  for (const { code, name } of langs) {
    LANGS[code] = name;
    els.source.add(new Option(name, code));
    els.target.add(new Option(name, code));
  }
  els.source.value = store.get("source") || "auto";
  els.target.value = store.get("target") || "hi";
  els.rate.value = store.get("rate") || 0;
  els.pitch.value = store.get("pitch") || 0;
  updateSliders();
  els.source.onchange = () => store.set("source", els.source.value);
  els.target.onchange = () => { store.set("target", els.target.value); loadVoices(); };
  await loadVoices();
  showPage();
  pollStatus();
}

async function pollStatus() {
  try {
    const s = await (await fetch("/api/status")).json();
    if (s.error) {
      els.status.className = "status error";
      els.statusText.textContent = "Model error - see server log";
      return;
    }
    const ready = s.asr_ready && s.llm_ready;
    els.status.className = "status" + (ready ? " ready" : "");
    els.statusText.textContent = ready
      ? `Whisper ${s.asr_model} · ${s.device === "cuda" ? "GPU" : "CPU"} · ${s.llm_model}`
      : s.asr_ready ? "Loading translator…" : "Loading Whisper…";
    els.status.title = els.statusText.textContent;
    const cloneWasHidden = $("add-voice").hidden;
    $("add-voice").hidden = !s.clone_available;
    if (s.clone_available && cloneWasHidden) loadVoices(); // show saved own voices
    if (!ready) setTimeout(pollStatus, 1500);
  } catch {
    els.status.className = "status error";
    els.statusText.textContent = "Server offline";
    setTimeout(pollStatus, 3000);
  }
}

els.swap.onclick = () => {
  const src = els.source.value === "auto" ? lastResult?.language : els.source.value;
  if (!src || !LANGS[src]) return toast("Record something first so I know the spoken language.");
  els.source.value = els.target.value;
  els.target.value = src;
  els.source.onchange(); els.target.onchange();
};

// ------------------------------------------------------------- voices
async function loadVoices() {
  const lang = els.target.value;
  const voices = await (await fetch(`/api/voices?lang=${lang}`)).json();
  els.voice.innerHTML = "";
  const groups = {};
  for (const v of voices) {
    const g = v.engine === "clone" ? "My voices" : `Neural voices · ${v.locale}`;
    if (!groups[g]) { groups[g] = document.createElement("optgroup"); groups[g].label = g; }
    const label = v.engine === "clone" ? `${v.name}${v.supported ? "" : " (not available for this language)"}` : `${v.name} · ${v.gender}${v.default ? " (default)" : ""}`;
    const opt = new Option(label, v.id);
    opt.disabled = v.engine === "clone" && !v.supported;
    groups[g].append(opt);
  }
  // own voices first, then the main locale, then the rest
  Object.keys(groups).sort((a, b) => (b === "My voices") - (a === "My voices")).forEach((g) => els.voice.append(groups[g]));
  const saved = store.get("voice:" + lang);
  const pick = voices.find((v) => v.id === saved && !(v.engine === "clone" && !v.supported)) || voices.find((v) => v.default) || voices[0];
  if (pick) els.voice.value = pick.id;
}
els.voice.onchange = () => store.set("voice:" + els.target.value, els.voice.value);

function updateSliders() {
  const r = +els.rate.value, p = +els.pitch.value;
  els.rateVal.textContent = (r >= 0 ? "+" : "") + r + "%";
  els.pitchVal.textContent = (p >= 0 ? "+" : "") + p + " Hz";
}
els.rate.oninput = els.pitch.oninput = () => { updateSliders(); store.set("rate", els.rate.value); store.set("pitch", els.pitch.value); };

const voiceSettings = () => ({ voice: els.voice.value, rate: +els.rate.value, pitch: +els.pitch.value });

els.preview.onclick = async () => {
  els.preview.disabled = true;
  try {
    const translated = els.translation.querySelector(".placeholder") ? null : els.translation.textContent;
    const r = await fetch("/api/preview", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lang: els.target.value, text: translated, ...voiceSettings() }),
    });
    if (!r.ok) throw new Error("Preview failed - see the server window for details");
    const res = await r.json();
    if (res.fallback) toast(`Preview used ${res.voice} because ${res.fallback_reason}.`);
    new Audio(res.audio_url).play();
  } catch (e) { toast(e.message); } finally { els.preview.disabled = false; }
};

// ------------------------------------------------------------- recording
let mediaRec, chunks, stream, audioCtx, analyser, raf, t0, timerInt;

async function startRecording() {
  try {
    // Browser processing is OFF on purpose: our own Python front-end cleans the audio.
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false, channelCount: 1 },
    });
  } catch {
    return toast("Microphone access was blocked. Allow it in the browser's address bar.");
  }
  audioCtx = new AudioContext();
  analyser = audioCtx.createAnalyser();
  analyser.fftSize = 2048;
  audioCtx.createMediaStreamSource(stream).connect(analyser);

  chunks = [];
  mediaRec = new MediaRecorder(stream);
  mediaRec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  mediaRec.onstop = () => submit(new Blob(chunks, { type: mediaRec.mimeType }), "recording.webm");
  mediaRec.start();

  els.recorder.classList.add("recording");
  els.mic.setAttribute("aria-label", "Stop recording");
  els.hint.textContent = "Listening… click to stop";
  t0 = Date.now();
  timerInt = setInterval(() => {
    const s = Math.floor((Date.now() - t0) / 1000);
    els.timer.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
    if (s >= 60) stopRecording(); // keep requests short
  }, 250);
  drawWave();
}

function stopRecording() {
  if (!mediaRec || mediaRec.state !== "recording") return;
  mediaRec.stop();
  stream.getTracks().forEach((t) => t.stop());
  clearInterval(timerInt);
  cancelAnimationFrame(raf);
  audioCtx.close();
  els.recorder.classList.remove("recording");
  els.mic.setAttribute("aria-label", "Start recording");
  els.timer.textContent = "0:00";
  els.hint.innerHTML = "Click the mic or press <kbd>Space</kbd> to record";
  clearWave();
}

function drawWave() {
  const c = els.wave, ctx = c.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  c.width = c.clientWidth * dpr; c.height = c.clientHeight * dpr;
  const data = new Uint8Array(analyser.fftSize);
  const color = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim();
  const bars = 64, history = new Array(bars).fill(0);
  const loop = () => {
    analyser.getByteTimeDomainData(data);
    let sum = 0;
    for (const v of data) sum += ((v - 128) / 128) ** 2;
    history.push(Math.min(1, Math.sqrt(sum / data.length) * 4));
    history.shift();
    ctx.clearRect(0, 0, c.width, c.height);
    ctx.fillStyle = color;
    ctx.globalAlpha = 0.35;
    const w = c.width / bars;
    history.forEach((v, i) => {
      const h = Math.max(3 * dpr, v * c.height * 0.85);
      ctx.beginPath();
      ctx.roundRect(i * w + w * 0.2, (c.height - h) / 2, w * 0.6, h, w * 0.3);
      ctx.fill();
    });
    raf = requestAnimationFrame(loop);
  };
  loop();
}
function clearWave() { const c = els.wave; c.getContext("2d").clearRect(0, 0, c.width, c.height); }

els.mic.onclick = () => (mediaRec?.state === "recording" ? stopRecording() : !busy && startRecording());
document.addEventListener("keydown", (e) => {
  if (e.code !== "Space" || e.repeat || ["TEXTAREA", "SELECT", "INPUT", "BUTTON"].includes(e.target.tagName)) return;
  if (!$("page-translate").hidden && !document.querySelector(".modal:not([hidden])")) { e.preventDefault(); els.mic.click(); }
});
els.file.onchange = () => { if (els.file.files[0] && !busy) submit(els.file.files[0], els.file.files[0].name); els.file.value = ""; };

// ------------------------------------------------------------- talking to the server
function resetSteps(from = "preprocess") {
  let hit = false;
  for (const li of els.steps.children) {
    if (li.dataset.stage === from) hit = true;
    if (hit) { li.className = ""; li.querySelector(".ms").textContent = ""; }
  }
}

async function streamEvents(response) {
  // The server sends one JSON object per line as each stage progresses.
  const reader = response.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let nl;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (line) handleEvent(JSON.parse(line));
    }
  }
}

async function submit(blob, name) {
  setBusy(true);
  resetSteps();
  clearResults();
  const fd = new FormData();
  fd.append("audio", blob, name);
  fd.append("target", els.target.value);
  fd.append("source", els.source.value);
  const v = voiceSettings();
  fd.append("voice", v.voice); fd.append("rate", v.rate); fd.append("pitch", v.pitch);
  try {
    const r = await fetch("/api/process", { method: "POST", body: fd });
    if (!r.ok) throw new Error(`Server error ${r.status}`);
    await streamEvents(r);
  } catch (e) {
    toast(e.message);
  } finally {
    setBusy(false);
  }
}

async function retranslate() {
  const text = els.editBox.value.trim();
  if (!text) return;
  lastResult.text = text;
  lastResult.words = null; // edited text has no per-word confidence
  renderTranscript(lastResult);
  closeEditor();
  setBusy(true);
  resetSteps("translate");
  try {
    const r = await fetch("/api/retranslate", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, source: lastResult.language, target: els.target.value, ...voiceSettings() }),
    });
    await streamEvents(r);
  } catch (e) { toast(e.message); } finally { setBusy(false); }
}

function handleEvent(ev) {
  Hood.onEvent(ev);
  if (ev.stage === "translate" && ev.status === "token") {
    if (els.translation.querySelector(".placeholder")) { els.translation.textContent = ""; els.translation.classList.add("caret"); }
    els.translation.textContent += ev.delta;
    return;
  }
  const li = els.steps.querySelector(`[data-stage="${ev.stage}"]`);
  if (!li) return; // e.g. "features" is shown only under the hood
  li.className = ev.status;
  if (ev.ms != null) li.querySelector(".ms").textContent = fmtMs(ev.ms);
  if (ev.status === "error") return toast(ev.error);
  if (ev.stage === "translate" && ev.status === "running") {
    els.translation.innerHTML = '<p class="placeholder">Translating…</p>';
    els.player.hidden = true; els.voiceNote.hidden = true;
  }
  if (ev.status !== "done") return;

  if (ev.stage === "recognize") { lastResult = ev; renderTranscript(ev); }
  if (ev.stage === "translate") renderTranslation(ev);
  if (ev.stage === "speak") loadAudio(ev);
}

// ------------------------------------------------------------- rendering
function clearResults() {
  lastResult = null;
  els.transcript.innerHTML = '<p class="placeholder">Listening to your audio…</p>';
  els.translation.innerHTML = '<p class="placeholder">The translation will appear here.</p>';
  els.translation.classList.remove("caret");
  [els.detected, els.confRow, els.legend, els.player, els.targetBadge, els.voiceNote].forEach((e) => (e.hidden = true));
  closeEditor();
  els.audio.pause();
}

function renderTranscript(r) {
  els.transcript.innerHTML = r.words
    ? r.words.map((w) => `<span class="w${w.low ? " low" : ""}" title="${Math.round(w.prob * 100)}% confident">${esc(w.word)}</span>`).join("")
    : esc(r.text);
  els.detected.hidden = false;
  els.detected.textContent = `${LANGS[r.language] || r.language.toUpperCase()} · ${Math.round(r.language_probability * 100)}%`;
  els.detected.title = "Detected language. Other candidates: " +
    r.language_candidates.slice(1, 4).map((c) => `${c.code} ${Math.round(c.prob * 100)}%`).join(", ");
  if (r.words) {
    const pct = Math.round(r.confidence * 100);
    els.confRow.hidden = false;
    els.confBar.style.width = pct + "%";
    els.confBar.style.background = pct >= 80 ? "var(--ok)" : pct >= 60 ? "var(--warn)" : "var(--err)";
    els.confVal.textContent = pct + "%";
    els.legend.hidden = r.low_confidence_words === 0;
  }
  if (!LANGS[r.language]) toast(`Detected ${r.language}, which isn't in the language list - translation may be poor.`);
  els.editBtn.disabled = false;
}

function renderTranslation(ev) {
  els.translation.classList.remove("caret");
  els.translation.textContent = ev.text;
  els.translation.lang = ev.target;
  els.targetBadge.hidden = false;
  els.targetBadge.textContent = LANGS[ev.target] || ev.target;
}

function loadAudio(ev) {
  els.audio.src = ev.audio_url;
  els.download.href = ev.audio_url;
  els.player.hidden = false;
  els.voiceNote.hidden = false;
  els.voiceNote.textContent = ev.fallback
    ? `Used ${ev.voice} instead because ${ev.fallback_reason || "your voice isn't available"}.`
    : `Voice: ${ev.voice} · ${ev.engine}`;
  els.audio.play().catch(() => {}); // autoplay may be blocked; the play button still works
}

// ------------------------------------------------------------- editing
function openEditor() {
  els.editBox.value = lastResult.text;
  els.transcript.hidden = true;
  els.editBox.hidden = false;
  els.retranslateBtn.hidden = false;
  els.editBtn.textContent = "Cancel";
  els.editBox.focus();
}
function closeEditor() {
  els.transcript.hidden = false;
  els.editBox.hidden = true;
  els.retranslateBtn.hidden = true;
  els.editBtn.textContent = "Edit";
}
els.editBtn.onclick = () => (els.editBox.hidden ? openEditor() : closeEditor());
els.retranslateBtn.onclick = retranslate;

// ------------------------------------------------------------- player
els.play.onclick = () => (els.audio.paused ? els.audio.play() : els.audio.pause());
els.audio.onplay = () => els.player.classList.add("playing");
els.audio.onpause = els.audio.onended = () => els.player.classList.remove("playing");
els.audio.ontimeupdate = () => {
  els.playBar.style.width = (els.audio.currentTime / (els.audio.duration || 1)) * 100 + "%";
};
els.copy.onclick = async () => {
  try { await navigator.clipboard.writeText(els.translation.textContent); toast("Copied!", true); }
  catch { toast("Couldn't copy."); }
};

init();
