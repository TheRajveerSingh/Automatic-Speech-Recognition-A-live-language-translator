// Voice lab: generate a reading script, record it, quality-check it, build a cloned voice.
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const fmtMs = (ms) => (ms >= 1000 ? (ms / 1000).toFixed(1) + " s" : ms + " ms");
  const modal = $("voice-modal");
  let script = null, rec = null, current = 0, newVoice = null;

  // ------------------------------------------------------------ open / close
  async function open() {
    modal.hidden = false;
    showStep("record");
    if (!$("vl-name").value) $("vl-name").value = "My voice";
    await refreshSaved();
    if (!script) generate();
  }
  function close() {
    stopRecording(true);
    modal.hidden = true;
  }
  $("add-voice").onclick = open;
  $("vl-close").onclick = close;
  modal.addEventListener("click", (e) => { if (e.target === modal) close(); });
  document.addEventListener("keydown", (e) => {
    if (modal.hidden) return;
    if (e.key === "Escape") close();
    if (e.key === "Enter" && rec && e.target.tagName !== "INPUT") { e.preventDefault(); nextLine(); }
  });

  function showStep(s) {
    $("vl-step-record").hidden = s !== "record";
    $("vl-step-result").hidden = s !== "result";
  }

  // ------------------------------------------------------------ saved voices
  async function refreshSaved() {
    const r = await (await fetch("/api/my-voices")).json();
    $("vl-langs").textContent = `Your cloned voice can speak: ${r.languages.join(", ")}. Other languages fall back to a neural voice.`;
    $("vl-saved").innerHTML = r.voices.length
      ? "<h3>Your saved voices</h3>" + r.voices.map((v) => `<div class="saved-voice"><b>${esc(v.name)}</b>
          <small>${v.created} · ${v.seconds}s · read ${Math.round(v.accuracy * 100)}% · SNR ${Math.round(v.snr_db)} dB</small>
          <button class="btn ghost" data-del="${v.id}">Delete</button></div>`).join("")
      : "";
    $("vl-saved").querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => {
      if (!confirm("Delete this voice and its recording?")) return;
      await fetch(`/api/my-voices/${b.dataset.del}`, { method: "DELETE" });
      await refreshSaved(); await loadVoices();
    }));
  }

  // ------------------------------------------------------------ script
  async function generate() {
    const lang = $("vl-lang").value;
    script = await (await fetch(`/api/voice-script?lang=${lang}&seed=${Math.floor(Math.random() * 1e9)}`)).json();
    $("vl-script").hidden = false;
    $("vl-stats").innerHTML = [
      `${script.lines.length} lines`, `${script.words} words`, `≈ ${script.est_seconds} s to read`,
      `covers ${script.coverage.covered}/${script.coverage.total} ${script.coverage.unit}`,
      "statements + question + exclamation + numbers",
    ].map((s) => `<span>${s}</span>`).join("");
    $("vl-lines").lang = lang;
    $("vl-lines").innerHTML = script.lines.map((l) => `<li>${esc(l.text)}<small>${l.kind}</small></li>`).join("");
  }
  $("vl-generate").onclick = generate;
  $("vl-reroll").onclick = generate;
  $("vl-lang").onchange = generate;

  function highlight(i) {
    const items = [...$("vl-lines").children];
    items.forEach((li, k) => { li.classList.toggle("current", k === i); li.classList.toggle("read", k < i); });
    items[i]?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
  function nextLine() {
    if (current < script.lines.length - 1) highlight(++current);
    else stopRecording();
  }
  $("vl-next").onclick = nextLine;

  // ------------------------------------------------------------ recording
  async function startRecording() {
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false, channelCount: 1 } });
    } catch { return toast("Microphone access was blocked."); }
    const ctx = new AudioContext(), analyser = ctx.createAnalyser();
    analyser.fftSize = 1024;
    ctx.createMediaStreamSource(stream).connect(analyser);
    const mr = new MediaRecorder(stream), chunks = [];
    mr.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    rec = { stream, ctx, analyser, mr, chunks, t0: performance.now(), raf: 0, cancelled: false };
    mr.onstop = () => { if (!rec.cancelled) upload(new Blob(chunks, { type: mr.mimeType })); rec = null; };
    mr.start();

    current = 0;
    $("vl-lines").classList.add("live"); highlight(0);
    $("vl-record").textContent = "■ Stop & check"; $("vl-record").classList.add("recording");
    $("vl-next").hidden = false; $("vl-reroll").disabled = $("vl-generate").disabled = $("vl-lang").disabled = true;

    const buf = new Uint8Array(analyser.fftSize);
    const tick = () => {
      if (!rec) return;
      const s = (performance.now() - rec.t0) / 1000;
      $("vl-timer").textContent = s.toFixed(1) + " s";
      const bar = $("vl-prog");
      bar.style.width = Math.min(100, (s / 40) * 100) + "%";
      bar.style.background = s >= 20 ? "var(--ok)" : s >= 10 ? "var(--warn)" : "var(--err)";
      analyser.getByteTimeDomainData(buf);
      let peak = 0; for (const v of buf) peak = Math.max(peak, Math.abs(v - 128) / 128);
      $("vl-level").style.width = Math.min(100, peak * 140) + "%";
      $("vl-level").style.background = peak > 0.95 ? "var(--err)" : "var(--ok)"; // red = clipping
      if (s >= 75) return stopRecording();
      rec.raf = requestAnimationFrame(tick);
    };
    tick();
  }

  function stopRecording(cancel = false) {
    if (!rec) return;
    rec.cancelled = cancel;
    cancelAnimationFrame(rec.raf);
    rec.mr.stop(); rec.stream.getTracks().forEach((t) => t.stop()); rec.ctx.close();
    $("vl-lines").classList.remove("live");
    $("vl-record").textContent = "● Start recording"; $("vl-record").classList.remove("recording");
    $("vl-next").hidden = true; $("vl-reroll").disabled = $("vl-generate").disabled = $("vl-lang").disabled = false;
    $("vl-level").style.width = "0";
  }
  $("vl-record").onclick = () => (rec ? stopRecording() : startRecording());

  // ------------------------------------------------------------ upload + live results
  async function upload(blob) {
    showStep("result");
    newVoice = null;
    document.querySelectorAll("#vl-steps li").forEach((li) => { li.className = ""; li.querySelector("em").textContent = ""; });
    $("vl-checks").innerHTML = ""; $("vl-diff-wrap").hidden = true; $("vl-test").hidden = true; $("vl-use").hidden = true;
    $("vl-profile-sub").textContent = "XTTS-v2 speaker embedding + style latents";
    const fd = new FormData();
    fd.append("audio", blob, "voice.webm");
    fd.append("name", $("vl-name").value || "My voice");
    fd.append("lang", script.lang);
    fd.append("script", script.lines.map((l) => l.text).join(" "));
    try {
      const r = await fetch("/api/enroll", { method: "POST", body: fd });
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
          if (line) onEvent(JSON.parse(line));
        }
      }
    } catch (e) { toast(e.message); }
  }

  function onEvent(ev) {
    const li = document.querySelector(`#vl-steps [data-s="${ev.stage}"]`);
    if (li) {
      li.className = ev.status;
      if (ev.ms != null) li.querySelector("em").textContent = fmtMs(ev.ms);
    }
    if (ev.status === "error") return toast(ev.error);
    if (ev.stage === "profile" && ev.status === "running" && ev.first_time)
      $("vl-profile-sub").textContent = "Loading XTTS-v2 (first time: downloads ~1.9 GB - this can take a few minutes)…";
    if (ev.stage === "check" && ev.status === "done") renderChecks(ev);
    if (ev.stage === "profile" && ev.status === "done")
      $("vl-profile-info").textContent = `Voice profile: speaker embedding of ${ev.speaker_embedding_size} numbers + style latents ${ev.gpt_latent_shape.join("×")}, computed in ${fmtMs(ev.ms)}.`;
    if (ev.stage === "test" && ev.status === "done") {
      $("vl-test").hidden = false; $("vl-audio").src = ev.audio_url; $("vl-audio").play().catch(() => {});
      const pct = Math.round(ev.similarity * 100);
      $("vl-checks").insertAdjacentHTML("beforeend",
        `<div class="check ${ev.similarity >= 0.35 ? "pass" : "warn"}"><dt>Voice similarity</dt><dd>${pct}%</dd>
         <small>speaker-embedding cosine, you vs the clone. Different people score ~10-20%, clones ~40-50%</small></div>`);
    }
    if (ev.stage === "complete" && ev.status === "done") { newVoice = ev.voice; $("vl-use").hidden = false; refreshSaved(); }
  }

  function renderChecks(ev) {
    $("vl-checks").innerHTML = ev.checks.map((c) =>
      `<div class="check ${c.status}"><dt>${c.name}</dt><dd>${c.value}</dd><small>${esc(c.detail)}</small></div>`).join("");
    $("vl-diff-wrap").hidden = false;
    $("vl-diff").lang = script.lang;
    $("vl-diff").innerHTML = ev.errors.alignment.map((a) => {
      if (a.op === "ok") return `<span class="d-ok">${esc(a.ref)}</span>`;
      if (a.op === "sub") return `<span class="d-sub" title="heard “${esc(a.hyp)}”">${esc(a.ref)} → ${esc(a.hyp)}</span>`;
      if (a.op === "del") return `<span class="d-del" title="not heard">${esc(a.ref)}</span>`;
      return `<span class="d-ins" title="extra word">+${esc(a.hyp)}</span>`;
    }).join("");
  }

  window.VoiceLab = { open, upload }; // also handy for testing from the browser console
  $("vl-retry").onclick = () => { showStep("record"); };
  $("vl-use").onclick = async () => {
    await loadVoices();
    const opt = [...$("voice").options].find((o) => o.value === newVoice.id);
    if (opt && !opt.disabled) { $("voice").value = newVoice.id; $("voice").onchange(); toast(`Now speaking as “${newVoice.name}”`, true); }
    else toast(`Saved! ${newVoice.name} can't speak ${$("target").selectedOptions[0].text} - pick a supported language.`, true);
    close();
  };
})();
