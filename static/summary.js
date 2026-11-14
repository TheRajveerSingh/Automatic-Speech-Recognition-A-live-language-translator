// Summarize page: upload or record a long recording -> live transcript -> map-reduce summary.
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = window.Viz.esc;
  let file = null, fileName = "", objectUrl = null, ready = false, myVoiceId = null;
  let segments = [], summary = null, rec = null;
  const langs = {};

  const fmt = (s) => { s = Math.floor(s); const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
    return h ? `${h}:${String(m).padStart(2, "0")}:${String(x).padStart(2, "0")}` : `${m}:${String(x).padStart(2, "0")}`; };
  const fmtMs = (ms) => (ms >= 1000 ? (ms / 1000).toFixed(1) + " s" : ms + " ms");

  // ------------------------------------------------------------ choosing input
  function setFile(blob, name) {
    file = blob; fileName = name;
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = URL.createObjectURL(blob);
    $("sm-picked").hidden = false;
    $("sm-picked-name").textContent = `📄 ${name} · ${(blob.size / 1048576).toFixed(1)} MB`;
    const probe = new Audio(objectUrl);  // show the duration once the browser knows it
    probe.onloadedmetadata = () => { if (isFinite(probe.duration)) $("sm-picked-name").textContent += ` · ${fmt(probe.duration)}`; };
    $("sm-go").disabled = false;
  }
  $("sm-file").onchange = () => { if ($("sm-file").files[0]) setFile($("sm-file").files[0], $("sm-file").files[0].name); };
  $("sm-clear-file").onclick = () => { file = null; $("sm-picked").hidden = true; $("sm-go").disabled = true; $("sm-file").value = ""; };
  const drop = $("sm-drop");
  ["dragenter", "dragover"].forEach((e) => drop.addEventListener(e, (ev) => { ev.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((e) => drop.addEventListener(e, (ev) => { ev.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (ev) => { const f = ev.dataTransfer.files[0]; if (f) setFile(f, f.name); });

  $("sm-record").onclick = async () => {
    if (rec) { rec.mr.stop(); return; }
    let stream;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1 } }); }
    catch { return toast("Microphone access was blocked."); }
    const mr = new MediaRecorder(stream), chunks = [];
    mr.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    rec = { mr, t0: Date.now(), timer: setInterval(() => ($("sm-rec-timer").textContent = "recording " + fmt((Date.now() - rec.t0) / 1000)), 500) };
    mr.onstop = () => {
      clearInterval(rec.timer); stream.getTracks().forEach((t) => t.stop());
      setFile(new Blob(chunks, { type: mr.mimeType }), `recording-${new Date().toLocaleTimeString().replace(/\W/g, "")}.webm`);
      rec = null; $("sm-record").textContent = "● Record live"; $("sm-record").classList.remove("recording");
      $("sm-rec-timer").textContent = "no time limit";
    };
    mr.start(1000);
    $("sm-record").textContent = "■ Stop recording"; $("sm-record").classList.add("recording");
  };

  // ------------------------------------------------------------ running
  function step(s, status, ms) {
    const li = document.querySelector(`#sm-steps [data-s="${s}"]`);
    if (!li) return;
    li.className = status;
    if (ms != null) li.querySelector("em").textContent = fmtMs(ms);
  }

  $("sm-go").onclick = async () => {
    if (!file) return;
    $("sm-go").disabled = true;
    $("sm-progress").hidden = false; $("sm-results").hidden = true;
    document.querySelectorAll("#sm-steps li").forEach((li) => { li.className = ""; li.querySelector("em").textContent = ""; });
    $("sm-live").innerHTML = ""; $("sm-bar").style.width = "0";
    segments = []; summary = null;
    const speak = $("sm-speak").checked;
    document.querySelector('#sm-steps [data-s="speak"]').hidden = !speak;
    const fd = new FormData();
    fd.append("audio", file, fileName);
    fd.append("language", $("sm-lang").value); fd.append("summary_lang", $("sm-out").value);
    fd.append("speak", speak ? "true" : "false");
    fd.append("voice", speak && $("sm-myvoice").checked && myVoiceId ? myVoiceId : "");
    let tStart = performance.now(), duration = 0, sumStart = 0;
    try {
      const r = await fetch("/api/summarize", { method: "POST", body: fd });
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
          if (ev.status === "error") { step(ev.stage, "error", ev.ms); throw new Error(ev.error); }
          if (ev.status === "running") step(ev.stage, "running");
          if (ev.stage === "prepare" && ev.status === "done") {
            duration = ev.duration; step("prepare", "done", ev.ms);
            $("sm-prep-sub").textContent = `${fmt(duration)} of audio decoded and cleaned (gain ${ev.gain_db >= 0 ? "+" : ""}${ev.gain_db} dB)`;
            tStart = performance.now();
          }
          if (ev.stage === "transcribe" && ev.status === "info")
            $("sm-tr-sub").textContent = `${langs[ev.language] || ev.language} detected (${Math.round(ev.language_probability * 100)}%) · ${fmt(ev.speech_duration)} of speech after skipping silence`;
          if (ev.stage === "transcribe" && ev.status === "progress") {
            const s = ev.segment, el = (performance.now() - tStart) / 1000;
            const eta = ev.pct > 0.02 ? Math.max(0, el / ev.pct - el) : null;
            $("sm-bar").style.width = ev.pct * 80 + "%";
            $("sm-tr-sub").textContent = `${Math.round(ev.pct * 100)}% · ${(s.end / Math.max(el, 0.1)).toFixed(1)}× real time${eta != null ? ` · ~${fmt(eta)} left` : ""}`;
            $("sm-live").insertAdjacentHTML("beforeend", `<p><b>${fmt(s.start)}</b>${esc(s.text)}</p>`);
            if ($("sm-live").children.length > 60) $("sm-live").firstElementChild.remove();
            $("sm-live").scrollTop = $("sm-live").scrollHeight;
          }
          if (ev.stage === "transcribe" && ev.status === "done") {
            segments = ev.segments; step("transcribe", "done", ev.ms);
            $("sm-tr-sub").textContent = `${ev.words.toLocaleString()} words · ${segments.length} segments · ${ev.speed_x}× faster than real time`;
          }
          if (ev.stage === "summarize" && ev.status === "running") {
            sumStart = performance.now();
            $("sm-sum-sub").textContent = `map: ${ev.chunks} chunk${ev.chunks > 1 ? "s" : ""} of ~${ev.chunk_words} words…`;
          }
          if (ev.stage === "summarize" && ev.status === "map") {
            $("sm-bar").style.width = 80 + (ev.i / (ev.n + 1)) * 20 + "%";
            $("sm-sum-sub").textContent = `map ${ev.i}/${ev.n}: “${ev.part.title}”` + (ev.i === ev.n ? " · reduce: writing the final summary…" : "");
          }
          if (ev.stage === "summarize" && ev.status === "done") {
            summary = ev; step("summarize", "done", ev.ms); $("sm-bar").style.width = "100%";
            $("sm-sum-sub").textContent = `${ev.parts.length} chunk notes → final summary`;
            renderResults();
          }
          if (ev.stage === "speak" && ev.status === "done") {
            step("speak", "done", ev.ms);
            const b = $("sm-play-tldr"); b.hidden = false;
            b.textContent = `▶ Listen (${ev.voice}${ev.fallback ? ", fallback" : ""})`;
            b.onclick = () => new Audio(ev.audio_url).play();
          }
        }
      }
    } catch (e) { toast(e.message); }
    finally { $("sm-go").disabled = false; }
  };

  // ------------------------------------------------------------ results
  function seek(t) { const a = $("sm-audio"); a.currentTime = t; a.play().catch(() => {}); }

  function renderResults() {
    const s = summary;
    $("sm-results").hidden = false;
    $("sm-audio").src = objectUrl;
    $("sm-tldr").textContent = s.tldr; $("sm-tldr").lang = s.language;
    $("sm-play-tldr").hidden = true;
    $("sm-points").innerHTML = s.key_points.map((p) => `<li>${esc(p)}</li>`).join("") || "<li>–</li>";
    $("sm-actions").innerHTML = s.action_items.length
      ? s.action_items.map((a) => `<li><label><input type="checkbox" /><span>${esc(a)}</span></label></li>`).join("")
      : '<li class="explain sm">No tasks or commitments were mentioned.</li>';
    $("sm-chapters").innerHTML = s.chapters.map((c, i) => `<button class="chapter" data-i="${i}" data-t="${c.start}"><b>${fmt(c.start)}</b><span>${esc(c.title || "Part " + (i + 1))}</span></button>`).join("");
    $("sm-chapters").querySelectorAll(".chapter").forEach((b) => (b.onclick = () => seek(+b.dataset.t)));

    const calls = s.parts.length + 1;
    $("sm-how").innerHTML = [
      ["Transcript", `${s.transcript_words.toLocaleString()} words`],
      ["Chunks (map)", `${s.parts.length} × ~${Math.round(s.transcript_words / s.parts.length)} words`],
      ["LLM calls", calls],
      ["Final step read", `${s.reduce_input_words.toLocaleString()} words of notes`],
      ["Summary time", fmtMs(s.ms)],
    ].map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join("");
    $("sm-parts").innerHTML = s.parts.map((p, i) => `<div class="part"><header>chunk ${i + 1} · ${fmt(p.start)}–${fmt(p.end)} · ${p.words} words · ${fmtMs(p.stats.ms)}</header>
      <b>${esc(p.title)}</b><ul>${p.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>
      ${p.action_items.length ? `<small class="explain sm">Actions: ${p.action_items.map(esc).join("; ")}</small>` : ""}</div>`).join("");
    renderTranscript();
  }

  function renderTranscript() {
    const q = $("sm-search").value.trim().toLowerCase();
    const mark = (t) => (q ? esc(t).replace(new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi"), (m) => `<mark>${m}</mark>`) : esc(t));
    $("sm-transcript").innerHTML = segments.map((s, i) => (!q || s.text.toLowerCase().includes(q))
      ? `<button class="seg-line" data-i="${i}" data-t="${s.start}"><b>${fmt(s.start)}</b>${mark(s.text)}</button>` : "").join("")
      || '<p class="explain sm">No matches.</p>';
    $("sm-transcript").querySelectorAll(".seg-line").forEach((b) => (b.onclick = () => seek(+b.dataset.t)));
  }
  $("sm-search").oninput = renderTranscript;

  // follow playback: highlight the current transcript line and chapter
  $("sm-audio").ontimeupdate = () => {
    const t = $("sm-audio").currentTime;
    let cur = -1; segments.forEach((s, i) => { if (s.start <= t) cur = i; });
    document.querySelectorAll("#sm-transcript .seg-line").forEach((b) => {
      const on = +b.dataset.i === cur;
      if (on && !b.classList.contains("now")) b.scrollIntoView({ block: "nearest" });
      b.classList.toggle("now", on);
    });
    let ch = -1; (summary?.chapters || []).forEach((c, i) => { if (c.start <= t) ch = i; });
    document.querySelectorAll("#sm-chapters .chapter").forEach((b) => b.classList.toggle("now", +b.dataset.i === ch));
  };

  // ------------------------------------------------------------ exports
  function download(text, name, type = "text/plain") {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type: type + ";charset=utf-8" }));
    a.download = name; a.click();
  }
  const base = () => fileName.replace(/\.[^.]+$/, "") || "recording";
  $("sm-exp-md").onclick = () => {
    if (!summary) return;
    const md = `# Summary - ${fileName}\n\n**TL;DR:** ${summary.tldr}\n\n## Key points\n${summary.key_points.map((p) => `- ${p}`).join("\n")}\n\n` +
      `## Action items\n${summary.action_items.map((a) => `- [ ] ${a}`).join("\n") || "_none_"}\n\n## Chapters\n${summary.chapters.map((c) => `- **${fmt(c.start)}** ${c.title}`).join("\n")}\n\n` +
      `## Transcript\n${segments.map((s) => `**[${fmt(s.start)}]** ${s.text}`).join("\n\n")}\n`;
    download(md, `${base()}-summary.md`, "text/markdown");
  };
  $("sm-exp-txt").onclick = () => segments.length && download(segments.map((s) => `[${fmt(s.start)}] ${s.text}`).join("\n"), `${base()}-transcript.txt`);
  $("sm-exp-srt").onclick = () => {
    if (!segments.length) return;
    const ts = (t) => { const ms = Math.round(t * 1000), h = Math.floor(ms / 3600000), m = Math.floor((ms % 3600000) / 60000), s = Math.floor((ms % 60000) / 1000);
      return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")},${String(ms % 1000).padStart(3, "0")}`; };
    download(segments.map((s, i) => `${i + 1}\n${ts(s.start)} --> ${ts(s.end)}\n${s.text}\n`).join("\n"), `${base()}.srt`, "application/x-subrip");
  };

  pageHooks.summary = async () => {
    if (ready) return;
    ready = true;
    for (const { code, name } of await (await fetch("/api/languages")).json()) {
      langs[code] = name;
      $("sm-lang").add(new Option(name, code)); $("sm-out").add(new Option(name, code));
    }
    try {
      const mv = await (await fetch("/api/my-voices")).json();
      if (mv.available && mv.voices.length) { myVoiceId = "clone:" + mv.voices[0].id; $("sm-myvoice-row").hidden = false; }
    } catch {}
  };
  window.Summary = { setFile }; // handy for testing from the console
})();
