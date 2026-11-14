// Conversation mode: two people, two languages. Push-to-talk, or hands-free with our own in-browser VAD.
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = window.Viz.esc;
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch {} },
  };
  let langs = {}, mode = "ptt", busy = false, ready = false;
  const turns = []; // kept for export

  // ------------------------------------------------------------ microphone -> raw PCM (AudioWorklet)
  // We capture raw samples (not MediaRecorder) so the VAD can keep a 300 ms "pre-roll" and the
  // first syllable of every sentence survives, then we encode a WAV file ourselves.
  const WORKLET = `class Tap extends AudioWorkletProcessor {
    process(inputs) { const ch = inputs[0][0]; if (ch) this.port.postMessage(ch.slice(0)); return true; }
  } registerProcessor("tap", Tap);`;
  let cap = null;

  async function openMic() {
    if (cap) return cap;
    // echoCancellation ON here: in a conversation the translation plays from the speakers
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: false, autoGainControl: false, channelCount: 1 } });
    const ctx = new AudioContext();
    await ctx.audioWorklet.addModule(URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" })));
    const node = new AudioWorkletNode(ctx, "tap");
    const mute = ctx.createGain(); mute.gain.value = 0;  // keeps the graph running without playing the mic
    ctx.createMediaStreamSource(stream).connect(node); node.connect(mute).connect(ctx.destination);
    node.port.onmessage = (e) => onSamples(e.data);
    cap = { ctx, stream, sr: ctx.sampleRate };
    return cap;
  }
  function closeMic() {
    if (!cap) return;
    cap.stream.getTracks().forEach((t) => t.stop()); cap.ctx.close(); cap = null;
  }

  function encodeWav(chunks, sr) {
    const n = chunks.reduce((s, c) => s + c.length, 0), buf = new ArrayBuffer(44 + n * 2), v = new DataView(buf);
    const str = (o, s) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
    str(0, "RIFF"); v.setUint32(4, 36 + n * 2, true); str(8, "WAVEfmt "); v.setUint32(16, 16, true);
    v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, sr, true); v.setUint32(28, sr * 2, true);
    v.setUint16(32, 2, true); v.setUint16(34, 16, true); str(36, "data"); v.setUint32(40, n * 2, true);
    let o = 44;
    for (const c of chunks) for (const x of c) { v.setInt16(o, Math.max(-1, Math.min(1, x)) * 0x7fff, true); o += 2; }
    return new Blob([buf], { type: "audio/wav" });
  }

  function onSamples(chunk) {
    if (ptt.active) ptt.chunks.push(chunk);
    if (mode === "auto" && auto.on) vadFeed(chunk);
  }

  // ------------------------------------------------------------ push to talk
  const ptt = { active: false, side: null, chunks: [] };
  async function toggleSide(side) {
    if (ptt.active) {
      if (ptt.side !== side) return;
      ptt.active = false;
      $(`tk-btn-${side}`).classList.remove("recording");
      const seconds = ptt.chunks.reduce((s, c) => s + c.length, 0) / cap.sr;
      if (seconds < 0.5) return toast("Too short - press, speak, then press again.");
      submitTurn(encodeWav(ptt.chunks, cap.sr), side);
      return;
    }
    if (busy) return toast("Wait for the current translation to finish.");
    try { await openMic(); } catch { return toast("Microphone access was blocked."); }
    Object.assign(ptt, { active: true, side, chunks: [] });
    $(`tk-btn-${side}`).classList.add("recording");
  }
  $("tk-btn-a").onclick = () => toggleSide("a");
  $("tk-btn-b").onclick = () => toggleSide("b");

  // ------------------------------------------------------------ hands-free: our voice activity detector
  const FRAME_S = 0.02, PRE_FRAMES = 15, START_FRAMES = 5, END_FRAMES = 45, MAX_S = 30, MIN_SPEECH_S = 0.4;
  const auto = { on: false, buf: [], bufLen: 0, floor: null, warm: [], speaking: false, above: 0, below: 0,
                 pre: [], utter: [], paused: false, lastUi: 0 };

  function vadFeed(chunk) {
    auto.buf.push(chunk); auto.bufLen += chunk.length;
    const need = Math.round(cap.sr * FRAME_S);
    while (auto.bufLen >= need) {  // re-slice 128-sample chunks into 20 ms frames
      const f = new Float32Array(need); let o = 0;
      while (o < need) {
        const c = auto.buf[0], take = Math.min(c.length, need - o);
        f.set(c.subarray(0, take), o); o += take;
        if (take === c.length) auto.buf.shift(); else auto.buf[0] = c.subarray(take);
      }
      auto.bufLen -= need;
      vadFrame(f);
    }
  }

  function vadFrame(f) {
    let s = 0; for (const x of f) s += x * x;
    const db = 10 * Math.log10(s / f.length + 1e-12);
    // adaptive noise floor: learn it for 0.5 s, then follow it (falls fast, rises slowly) while nobody speaks
    if (auto.floor === null) { auto.warm.push(db); if (auto.warm.length >= 25) auto.floor = auto.warm.reduce((a, b) => a + b) / 25; return; }
    if (!auto.speaking && !auto.paused) auto.floor = db < auto.floor ? auto.floor * 0.9 + db * 0.1 : Math.min(auto.floor + 0.05, db);
    const startThr = Math.max(auto.floor + 12, -50), endThr = Math.max(auto.floor + 7, -55);
    drawVad(db, startThr);
    if (auto.paused) return;
    if (!auto.speaking) {
      auto.pre.push(f); if (auto.pre.length > PRE_FRAMES) auto.pre.shift();
      if (db > startThr) {
        if (++auto.above >= START_FRAMES) { auto.speaking = true; auto.utter = auto.pre.slice(); auto.below = 0; setState("speech", "Hearing speech…"); }
      } else auto.above = 0;
    } else {
      auto.utter.push(f);
      auto.below = db < endThr ? auto.below + 1 : 0;
      const dur = auto.utter.length * FRAME_S;
      if (auto.below >= END_FRAMES || dur >= MAX_S) {
        const frames = auto.utter, speech = dur - auto.below * FRAME_S;
        Object.assign(auto, { speaking: false, utter: [], above: 0, pre: [] });
        if (speech >= MIN_SPEECH_S) submitTurn(encodeWav(frames, cap.sr), "auto");
        else setState("listening", "Listening…");
      }
    }
  }

  const dbToPct = (db) => Math.max(0, Math.min(100, ((db + 80) / 80) * 100)); // -80..0 dBFS
  function drawVad(db, thr) {
    const now = performance.now(); if (now - auto.lastUi < 50) return; auto.lastUi = now;
    $("tk-level").style.width = dbToPct(db) + "%";
    $("tk-level").classList.toggle("speech", auto.speaking);
    $("tk-thr").style.left = dbToPct(thr) + "%";
    $("tk-floor").style.left = dbToPct(auto.floor) + "%";
    $("tk-db").textContent = `${db.toFixed(0)} dB · floor ${auto.floor.toFixed(0)} · trigger ${thr.toFixed(0)}`;
  }
  function setState(cls, text) { $("tk-state-dot").className = "state-dot " + cls; $("tk-state").textContent = text; }

  async function toggleListening() {
    if (auto.on) {
      auto.on = false; $("tk-listen").textContent = "● Start listening"; $("tk-listen").classList.remove("on");
      setState("", "Not listening"); $("tk-level").style.width = "0"; return;
    }
    try { await openMic(); } catch { return toast("Microphone access was blocked."); }
    Object.assign(auto, { on: true, buf: [], bufLen: 0, floor: null, warm: [], speaking: false, above: 0, below: 0, pre: [], utter: [], paused: busy });
    $("tk-listen").textContent = "■ Stop listening"; $("tk-listen").classList.add("on");
    setState("listening", "Measuring room noise…");
    setTimeout(() => auto.on && !auto.speaking && !busy && setState("listening", "Listening…"), 600);
  }
  $("tk-listen").onclick = toggleListening;

  // ------------------------------------------------------------ one turn: upload, stream results into a chat bubble
  async function submitTurn(blob, side) {
    busy = true; auto.paused = true;
    const listening = () => mode === "auto" && auto.on;
    if (listening()) setState("busy", "Translating…");
    const la = $("tk-lang-a").value, lb = $("tk-lang-b").value;
    const turn = { side: side === "auto" ? null : side, src: null, tgt: null, orig: "", trans: "", audio: null };
    const el = document.createElement("div");
    el.className = "bubble " + (turn.side || "pending");
    el.innerHTML = `<div class="meta"><span class="m-who">${turn.side ? "Person " + turn.side.toUpperCase() : "Detecting speaker…"}</span><span class="m-det"></span></div>
      <p class="orig"></p><div class="trans"></div><div class="foot"><span class="status">Listening to the clip…</span></div>`;
    $("tk-empty").hidden = true;
    $("tk-chat").append(el); el.scrollIntoView({ block: "end", behavior: "smooth" });
    const q = (s) => el.querySelector(s);

    const fd = new FormData();
    fd.append("audio", blob, "turn.wav"); fd.append("lang_a", la); fd.append("lang_b", lb); fd.append("side", side);
    fd.append("voice_a", $("tk-voice-a").value); fd.append("voice_b", $("tk-voice-b").value);
    let audioUrl = null;
    try {
      const r = await fetch("/api/talk", { method: "POST", body: fd });
      if (!r.ok) throw new Error((await r.json()).detail || `Server error ${r.status}`);
      const reader = r.body.getReader(), dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let nl;
        while ((nl = buf.indexOf("\n")) >= 0) {
          const line = buf.slice(0, nl).trim(); buf = buf.slice(nl + 1);
          if (!line) continue;
          const ev = JSON.parse(line);
          if (ev.status === "error") throw new Error(ev.error);
          if (ev.stage === "detect") {
            turn.side = ev.side; turn.src = ev.language; turn.tgt = ev.side === "a" ? lb : la;
            el.className = "bubble " + ev.side;
            q(".m-who").textContent = `Person ${ev.side.toUpperCase()} · ${langs[turn.src]} → ${langs[turn.tgt]}`;
            if (ev.method === "auto") {
              const other = ev.side === "a" ? lb : la;
              q(".m-det").textContent = `detected ${langs[turn.src]} ${Math.round(ev.scores[turn.src] * 100)}% vs ${langs[other]} ${Math.round(ev.scores[other] * 100)}%`;
              q(".m-det").title = `Whisper's overall top guess: ${ev.whisper_top.code} ${Math.round(ev.whisper_top.prob * 100)}%`;
            }
            q(".status").textContent = "Recognising…";
          }
          if (ev.stage === "recognize" && ev.status === "done") { turn.orig = ev.text; q(".orig").textContent = ev.text; q(".orig").lang = turn.src; q(".status").textContent = "Translating…"; }
          if (ev.stage === "translate" && ev.status === "token") { q(".trans").textContent += ev.delta; }
          if (ev.stage === "translate" && ev.status === "done") { turn.trans = ev.text; q(".trans").textContent = ev.text; q(".trans").lang = turn.tgt; q(".status").textContent = "Speaking…"; }
          if (ev.stage === "speak" && ev.status === "done") {
            audioUrl = turn.audio = ev.audio_url;
            q(".foot").innerHTML = `<button class="icon-btn" aria-label="Play again"><svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z" fill="currentColor"/></svg></button>
              <span>${esc(ev.voice)}${ev.fallback ? " (fallback)" : ""} · ${(ev.total_ms / 1000).toFixed(1)} s total</span>`;
            q(".foot button").onclick = () => new Audio(audioUrl).play();
          }
        }
      }
      turns.push(turn);
    } catch (e) {
      q(".status").textContent = "⚠ " + e.message; q(".status").style.color = "var(--err)";
      if (!turn.side) el.className = "bubble pending";
    }
    // play the translation, and only then listen again (so we don't translate our own speaker)
    const resume = () => { busy = false; auto.paused = false; if (listening()) setState("listening", "Listening…"); };
    if (audioUrl) {
      if (listening()) setState("playing", "Playing translation…");
      const a = new Audio(audioUrl);
      a.onended = a.onerror = () => setTimeout(resume, 300);
      a.play().catch(resume);
    } else resume();
  }

  // ------------------------------------------------------------ setup: languages, voices, mode
  async function loadVoiceSelect(sel, listenerLang, key) {
    const voices = await (await fetch(`/api/voices?lang=${listenerLang}`)).json();
    sel.innerHTML = voices.map((v) => {
      const label = v.engine === "clone" ? `★ ${v.name} (your voice)` : `${v.name} · ${v.gender}`;
      return `<option value="${v.id}" ${v.engine === "clone" && !v.supported ? "disabled" : ""}>${esc(label)}${v.engine === "clone" && !v.supported ? " - n/a" : ""}</option>`;
    }).join("");
    const saved = store.get(key);
    const myVoice = voices.find((v) => v.engine === "clone" && v.supported);
    if (saved && [...sel.options].some((o) => o.value === saved && !o.disabled)) sel.value = saved;
    else if (sel.id === "tk-voice-a" && myVoice) sel.value = myVoice.id; // Person A = you, in your own voice
    else sel.value = (voices.find((v) => v.default) || voices[0]).id;
  }
  async function refresh() {
    const la = $("tk-lang-a").value, lb = $("tk-lang-b").value;
    if (la === lb) { toast("Pick two different languages."); }
    store.set("talk:a", la); store.set("talk:b", lb);
    $("tk-btn-a-lang").textContent = `${langs[la]} → ${langs[lb]}`;
    $("tk-btn-b-lang").textContent = `${langs[lb]} → ${langs[la]}`;
    await Promise.all([loadVoiceSelect($("tk-voice-a"), lb, `talk:voice-a:${lb}`), loadVoiceSelect($("tk-voice-b"), la, `talk:voice-b:${la}`)]);
  }
  $("tk-voice-a").onchange = () => store.set(`talk:voice-a:${$("tk-lang-b").value}`, $("tk-voice-a").value);
  $("tk-voice-b").onchange = () => store.set(`talk:voice-b:${$("tk-lang-a").value}`, $("tk-voice-b").value);
  $("tk-lang-a").onchange = refresh; $("tk-lang-b").onchange = refresh;
  $("tk-swap").onclick = () => { const a = $("tk-lang-a").value; $("tk-lang-a").value = $("tk-lang-b").value; $("tk-lang-b").value = a; refresh(); };

  const HELP = {
    ptt: "Press your button, speak, press it again. Each person has their own button, so the app always knows who is talking - most reliable in noisy places.",
    auto: "Just talk - no buttons. Our in-browser voice detector notices when someone starts and stops speaking, Whisper decides which of the two languages it heard, and the translation is played for the other person. Listening pauses while the translation plays.",
  };
  function setMode(m) {
    if (ptt.active) return;
    mode = m;
    document.querySelectorAll("#page-talk .seg-toggle button").forEach((b) => b.classList.toggle("on", b.dataset.mode === m));
    $("tk-ptt").hidden = m !== "ptt"; $("tk-auto").hidden = m !== "auto";
    $("tk-mode-help").textContent = HELP[m];
    if (m !== "auto" && auto.on) toggleListening();
  }
  document.querySelectorAll("#page-talk .seg-toggle button").forEach((b) => (b.onclick = () => setMode(b.dataset.mode)));

  // ------------------------------------------------------------ export / clear
  $("tk-export").onclick = () => {
    if (!turns.length) return toast("Nothing to export yet.");
    const text = turns.map((t, i) => `${i + 1}. Person ${t.side.toUpperCase()} (${langs[t.src]}): ${t.orig}\n   → ${langs[t.tgt]}: ${t.trans}`).join("\n\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([`Conversation - ${new Date().toLocaleString()}\n\n${text}\n`], { type: "text/plain;charset=utf-8" }));
    a.download = `conversation-${new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-")}.txt`;
    a.click();
  };
  $("tk-clear").onclick = () => { turns.length = 0; $("tk-chat").querySelectorAll(".bubble").forEach((b) => b.remove()); $("tk-empty").hidden = false; };

  // stop the mic when leaving the tab
  window.addEventListener("hashchange", () => {
    if (location.hash !== "#talk") { if (auto.on) toggleListening(); if (!ptt.active) closeMic(); }
  });

  pageHooks.talk = async () => {
    if (ready) return;
    ready = true;
    const list = await (await fetch("/api/languages")).json();
    for (const { code, name } of list) {
      langs[code] = name;
      $("tk-lang-a").add(new Option(name, code)); $("tk-lang-b").add(new Option(name, code));
    }
    $("tk-lang-a").value = store.get("talk:a") || "en";
    $("tk-lang-b").value = store.get("talk:b") || "hi";
    setMode("ptt");
    await refresh();
  };
  window.Talk = { submitTurn, encodeWav }; // handy for testing from the console
})();
