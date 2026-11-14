// Benchmark page: record a test set, run Whisper models over it, chart accuracy / speed / calibration.
(function () {
  const $ = (id) => document.getElementById(id);
  const { setup, axes, ticks, path, css, esc } = window.Viz;
  const pct = (x, d = 1) => (x * 100).toFixed(d) + "%";
  let lang = "en", prompts = [], idx = 0, rec = null, result = null, loaded = false;

  // ------------------------------------------------------------ tooltip (shared by all charts)
  const tip = $("tooltip");
  function hover(canvas) {
    canvas.onmousemove = (e) => {
      const r = canvas.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
      const hit = (canvas._hits || []).find((h) => x >= h.x - 4 && x <= h.x + h.w + 4 && y >= h.y - 4 && y <= h.y + h.h + 4);
      if (!hit) { tip.hidden = true; return; }
      tip.innerHTML = hit.html; tip.hidden = false;
      tip.style.left = Math.min(e.clientX + 14, innerWidth - tip.offsetWidth - 8) + "px";
      tip.style.top = e.clientY + 14 + "px";
    };
    canvas.onmouseleave = () => (tip.hidden = true);
  }

  // ------------------------------------------------------------ prompts + recording
  async function loadPrompts() {
    const r = await (await fetch(`/api/bench/prompts?lang=${lang}`)).json();
    prompts = r.prompts;
    renderModels(r.models);
    renderStats(r.stats);
    const firstTodo = prompts.findIndex((p) => !p.recorded);
    idx = firstTodo >= 0 ? firstTodo : 0;
    renderPrompt();
  }

  function renderStats(stats) {
    const done = prompts.filter((p) => p.recorded).length;
    $("bt-bar").style.width = (done / prompts.length) * 100 + "%";
    $("bt-count").textContent = `${done} / ${prompts.length} recorded · ${stats.count} total, ${Math.round(stats.seconds)} s of audio`;
    $("bt-list-title").textContent = `Recorded sentences (${stats.count})`;
    const items = prompts.filter((p) => p.recorded);
    $("bt-items").innerHTML = items.length ? items.map((p) => `<div class="bt-item">
        <small>${p.id}</small><span lang="${p.lang}">${esc(p.text)}</span><small>${p.recorded.seconds}s</small>
        <button class="icon-btn" data-play="${p.recorded.id}" aria-label="Play"><svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z" fill="currentColor"/></svg></button>
        <button class="icon-btn" data-del="${p.recorded.id}" aria-label="Delete"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg></button>
      </div>`).join("") : '<p class="explain sm">Nothing recorded in this language yet.</p>';
    $("bt-items").querySelectorAll("[data-play]").forEach((b) => (b.onclick = () => new Audio(`/api/bench/audio/${b.dataset.play}`).play()));
    $("bt-items").querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => {
      await fetch(`/api/bench/item/${b.dataset.del}`, { method: "DELETE" }); loadPrompts();
    }));
  }

  function renderPrompt() {
    const p = prompts[idx];
    $("bt-index").textContent = `Sentence ${idx + 1} of ${prompts.length}`;
    $("bt-text").textContent = p.text;
    $("bt-text").lang = p.lang;
    $("bt-done").hidden = !p.recorded;
    $("bt-record").textContent = p.recorded ? "● Re-record" : "● Record";
  }
  const move = (d) => { if (rec) return; idx = (idx + d + prompts.length) % prompts.length; renderPrompt(); };
  $("bt-prev").onclick = () => move(-1);
  $("bt-next").onclick = () => move(1);

  document.querySelectorAll(".seg-toggle button").forEach((b) => (b.onclick = () => {
    if (rec) return;
    document.querySelectorAll(".seg-toggle button").forEach((x) => x.classList.toggle("on", x === b));
    lang = b.dataset.lang; loadPrompts();
  }));

  async function startRec() {
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false, channelCount: 1 } });
    } catch { return toast("Microphone access was blocked."); }
    const ctx = new AudioContext(), an = ctx.createAnalyser(); an.fftSize = 1024;
    ctx.createMediaStreamSource(stream).connect(an);
    const mr = new MediaRecorder(stream), chunks = [];
    mr.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    rec = { stream, ctx, mr, t0: performance.now(), raf: 0 };
    const pid = prompts[idx].id;
    mr.onstop = () => save(new Blob(chunks, { type: mr.mimeType }), pid, (performance.now() - rec.t0) / 1000);
    mr.start();
    $("bt-card").classList.add("recording");
    $("bt-record").textContent = "■ Stop & save"; $("bt-record").classList.add("recording");
    const buf = new Uint8Array(an.fftSize);
    const tick = () => {
      if (!rec) return;
      $("bt-timer").textContent = ((performance.now() - rec.t0) / 1000).toFixed(1) + " s";
      an.getByteTimeDomainData(buf);
      let peak = 0; for (const v of buf) peak = Math.max(peak, Math.abs(v - 128) / 128);
      $("bt-level").style.width = Math.min(100, peak * 140) + "%";
      $("bt-level").style.background = peak > 0.95 ? "var(--err)" : "var(--ok)";
      rec.raf = requestAnimationFrame(tick);
    };
    tick();
  }
  function stopRec() {
    if (!rec) return;
    cancelAnimationFrame(rec.raf);
    rec.mr.stop(); rec.stream.getTracks().forEach((t) => t.stop()); rec.ctx.close();
    $("bt-card").classList.remove("recording"); $("bt-record").classList.remove("recording");
    $("bt-level").style.width = "0"; $("bt-timer").textContent = "";
  }
  async function save(blob, pid, seconds) {
    rec = null;
    renderPrompt();
    if (seconds < 0.8) return toast("That was too short - hold the recording until you finish the sentence.");
    const fd = new FormData(); fd.append("audio", blob, "rec.webm"); fd.append("prompt_id", pid);
    const r = await fetch("/api/bench/record", { method: "POST", body: fd });
    if (!r.ok) return toast("Couldn't save: " + ((await r.json()).detail || r.status));
    await loadPrompts();
    const next = prompts.findIndex((p, i) => i > prompts.findIndex((q) => q.id === pid) && !p.recorded);
    if (next >= 0) { idx = next; renderPrompt(); }
  }
  $("bt-record").onclick = () => (rec ? stopRec() : startRec());
  document.addEventListener("keydown", (e) => {
    if ($("page-bench").hidden || ["INPUT", "SELECT", "TEXTAREA", "BUTTON"].includes(e.target.tagName)) return;
    if (e.code === "Space") { e.preventDefault(); $("bt-record").click(); }
    if (e.key === "ArrowRight") move(1);
    if (e.key === "ArrowLeft") move(-1);
  });

  // ------------------------------------------------------------ running
  function renderModels(info) {
    if ($("bt-models").children.length) return;
    const defaults = ["tiny", "small", "large-v3-turbo"];
    $("bt-models").innerHTML = Object.entries(info).map(([m, d]) =>
      `<label class="model-pick"><input type="checkbox" value="${m}" ${defaults.includes(m) ? "checked" : ""}/><span><b>${m}</b><small>${d}</small></span></label>`).join("");
  }

  $("bt-run").onclick = async () => {
    const models = [...$("bt-models").querySelectorAll("input:checked")].map((i) => i.value);
    if (!models.length) return toast("Pick at least one model.");
    $("bt-run").disabled = true; $("bt-run-progress").hidden = false; $("bt-run-bar").style.width = "0";
    try {
      const r = await fetch("/api/bench/run", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ models, compare_cleaning: $("bt-compare").checked }) });
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
          if (ev.type === "status") $("bt-status").textContent = ev.message;
          if (ev.type === "progress") {
            $("bt-run-bar").style.width = (ev.done / ev.total) * 100 + "%";
            $("bt-status").textContent = `${ev.config} · ${ev.done}/${ev.total} · ${ev.utterance} WER ${pct(ev.wer, 0)}`;
          }
          if (ev.type === "config_done") $("bt-status").textContent = `✓ ${ev.name}: WER ${pct(ev.summary.wer)}`;
          if (ev.type === "error") throw new Error(ev.error);
          if (ev.type === "done") { $("bt-status").textContent = "Done!"; await loadResults(ev.result_id); }
        }
      }
    } catch (e) { toast(e.message); $("bt-status").textContent = ""; }
    finally { $("bt-run").disabled = false; }
  };

  // ------------------------------------------------------------ results
  async function loadResults(select) {
    const list = await (await fetch("/api/bench/results")).json();
    if (!list.length) { $("bt-results").hidden = true; return; }
    $("bt-run-select").innerHTML = list.map((r) => `<option value="${r.id}">${r.created} · ${r.utterances} recordings · ${r.configs.length} configs</option>`).join("");
    $("bt-run-select").value = select || list[0].id;
    await showResult($("bt-run-select").value);
  }
  $("bt-run-select").onchange = () => showResult($("bt-run-select").value);

  async function showResult(id) {
    result = await (await fetch(`/api/bench/results/${id}`)).json();
    $("bt-results").hidden = false;
    const cs = result.configs;
    const best = cs.reduce((a, b) => (b.summary.wer < a.summary.wer ? b : a));
    $("bt-table").innerHTML = `<thead><tr><th>Configuration</th><th>WER</th><th>Errors (sub/del/ins)</th><th>CER</th><th>RTF</th><th>Per sentence</th><th>Language ID</th><th>Avg confidence</th></tr></thead><tbody>` +
      cs.map((c) => { const s = c.summary; return `<tr class="${c === best ? "best" : ""}">
        <td><span class="sw" style="background:var(${c.cleaning ? "--s1" : "--s2"})"></span>${esc(c.name)}${c === best ? " ★" : ""}</td>
        <td>${pct(s.wer)}</td><td>${s.substitutions + s.deletions + s.insertions} (${s.substitutions}/${s.deletions}/${s.insertions}) of ${s.reference_words}</td>
        <td>${pct(s.cer)}</td><td>${s.rtf.toFixed(2)}</td><td>${s.avg_latency_s.toFixed(2)} s</td>
        <td>${pct(s.lid_accuracy, 0)}</td><td>${s.avg_confidence != null ? pct(s.avg_confidence, 0) : "–"}</td></tr>`; }).join("") + "</tbody>";

    // honest warnings: small samples make differences meaningless
    const warns = [];
    if (result.dataset.count < 20) warns.push(`Only <b>${result.dataset.count} recordings</b> - one word changes WER by a lot. Record 30+ for stable numbers.`);
    const byModel = {};
    cs.forEach((c) => ((byModel[c.model] = byModel[c.model] || {})[c.cleaning ? "on" : "off"] = c.summary));
    for (const [m, v] of Object.entries(byModel)) {
      if (!v.on || !v.off) continue;
      const eOn = v.on.substitutions + v.on.deletions + v.on.insertions, eOff = v.off.substitutions + v.off.deletions + v.off.insertions;
      const diff = Math.abs(eOn - eOff);
      if (diff <= Math.max(2, 0.1 * Math.max(eOn, eOff)))
        warns.push(`<b>${esc(m)}</b>: cleaned vs raw differ by only ${diff} word${diff === 1 ? "" : "s"} (${eOn} vs ${eOff}) - too small to call a real difference.`);
    }
    $("bt-warn").innerHTML = warns.join("<br>"); $("bt-warn").hidden = !warns.length;

    $("bt-cal-config").innerHTML = cs.map((c, i) => `<option value="${i}">${esc(c.name)}</option>`).join("");
    $("bt-cal-config").value = String(cs.indexOf(best));
    drawAll();
  }
  $("bt-cal-config").onchange = drawAll;

  function drawAll() {
    if (!result || $("page-bench").hidden) return;
    drawWer($("bt-chart-wer"), result.configs);
    drawSpeed($("bt-chart-speed"), result.configs);
    const c = result.configs[+$("bt-cal-config").value];
    drawCal($("bt-chart-cal"), c.summary, result.low_confidence_threshold);
    renderCalNumbers(c.summary, result.low_confidence_threshold);
    renderWorst(c);
  }

  function roundTop(ctx, x, y, w, h, r = 4) {
    ctx.beginPath(); ctx.roundRect(x, y, w, h, [Math.min(r, h), Math.min(r, h), 0, 0]); ctx.fill();
  }

  function drawWer(canvas, cs) {
    const { ctx, w, h } = setup(canvas);
    const models = [...new Set(cs.map((c) => c.model))];
    const maxW = Math.max(...cs.map((c) => c.summary.wer)) * 100;
    const ymax = Math.max(5, Math.ceil((maxW * 1.2) / 5) * 5);
    const a = axes(ctx, w, h, { x: { min: 0, max: models.length, ticks: [] }, y: { min: 0, max: ymax, ticks: ticks(0, ymax, 4), fmt: (t) => t + "%" }, pad: { l: 40, r: 10, t: 18, b: 22 } });
    const slot = (a.X1 - a.X0) / models.length, bw = Math.min(46, slot * 0.32), hits = [];
    models.forEach((m, i) => {
      const cx = a.X0 + slot * (i + 0.5);
      ctx.fillStyle = css("--muted"); ctx.textAlign = "center"; ctx.textBaseline = "top";
      ctx.fillText(m, cx, a.Y1 + 6);
      [true, false].forEach((cleaning, k) => {
        const c = cs.find((x) => x.model === m && x.cleaning === cleaning);
        if (!c) return;
        const v = c.summary.wer * 100, x = cx + (k === 0 ? -bw - 1 : 1), y = a.sy(v);  // 2px gap between bars
        ctx.fillStyle = css(cleaning ? "--s1" : "--s2");
        roundTop(ctx, x, y, bw, a.Y1 - y);
        ctx.fillStyle = css("--text"); ctx.textBaseline = "bottom";
        ctx.fillText(v.toFixed(1) + "%", x + bw / 2, y - 3);
        hits.push({ x, y, w: bw, h: a.Y1 - y, html: `<b>${esc(c.name)}</b><br>WER ${v.toFixed(1)}% · ${c.summary.substitutions + c.summary.deletions + c.summary.insertions} wrong words` });
      });
    });
    canvas._hits = hits; hover(canvas);
  }

  function drawSpeed(canvas, cs) {
    const { ctx, w, h } = setup(canvas);
    const xs = cs.map((c) => c.summary.avg_latency_s), ys = cs.map((c) => c.summary.wer * 100);
    const xmax = Math.max(0.5, Math.max(...xs) * 1.25), ymax = Math.max(5, Math.ceil((Math.max(...ys) * 1.2) / 5) * 5);
    const a = axes(ctx, w, h, { x: { min: 0, max: xmax, ticks: ticks(0, xmax, 5), fmt: (t) => t + "s" }, y: { min: 0, max: ymax, ticks: ticks(0, ymax, 4), fmt: (t) => t + "%" }, pad: { l: 40, r: 14, t: 10, b: 30 } });
    ctx.fillStyle = css("--muted"); ctx.textAlign = "center"; ctx.textBaseline = "bottom";
    ctx.fillText("seconds per sentence →", (a.X0 + a.X1) / 2, h - 1);
    const hits = [];
    cs.forEach((c, i) => {
      const x = a.sx(xs[i]), y = a.sy(ys[i]);
      ctx.beginPath(); ctx.arc(x, y, 6, 0, Math.PI * 2);
      ctx.fillStyle = css(c.cleaning ? "--s1" : "--s2"); ctx.fill();
      ctx.lineWidth = 2; ctx.strokeStyle = css("--card"); ctx.stroke(); // surface ring for overlaps
      if (c.cleaning) { ctx.fillStyle = css("--text"); ctx.textAlign = "center"; ctx.textBaseline = "bottom"; ctx.fillText(c.model, x, y - 9); }
      hits.push({ x: x - 7, y: y - 7, w: 14, h: 14, html: `<b>${esc(c.name)}</b><br>WER ${ys[i].toFixed(1)}% · ${xs[i].toFixed(2)} s per sentence` });
    });
    canvas._hits = hits; hover(canvas);
  }

  function drawCal(canvas, s, thr) {
    const { ctx, w, h } = setup(canvas);
    const a = axes(ctx, w, h, { x: { min: 0, max: 10, ticks: [0, 2, 4, 6, 8, 10], fmt: (t) => t * 10 + "%" }, y: { min: 0, max: 100, ticks: [0, 50, 100], fmt: (t) => t + "%" }, pad: { l: 40, r: 10, t: 16, b: 32 } });
    ctx.fillStyle = css("--muted"); ctx.textAlign = "center"; ctx.textBaseline = "bottom";
    ctx.fillText("confidence Whisper gave the word →", (a.X0 + a.X1) / 2, h - 1);
    const bw = (a.X1 - a.X0) / 10, hits = [];
    s.calibration.forEach((b, i) => {
      if (!b.count) return;
      const v = b.accuracy * 100, x = a.X0 + i * bw + 1, y = a.sy(v);
      ctx.fillStyle = css("--s1"); roundTop(ctx, x, y, bw - 2, a.Y1 - y);
      ctx.fillStyle = css("--muted"); ctx.textBaseline = "bottom"; ctx.fillText("n=" + b.count, x + bw / 2 - 1, y - 2);
      hits.push({ x, y, w: bw - 2, h: a.Y1 - y, html: `<b>${b.lo * 100}-${b.lo * 100 + 10}% confidence</b><br>${b.count} words, ${v.toFixed(0)}% actually correct` });
    });
    const tx = a.sx(thr * 10);
    path(ctx, [[tx, a.Y0 - 6], [tx, a.Y1]], css("--warn"), 1.5, [5, 4]);
    ctx.fillStyle = css("--text"); ctx.textAlign = "left"; ctx.textBaseline = "top";
    ctx.fillText(`highlight < ${Math.round(thr * 100)}%`, tx + 4, a.Y0 - 6);
    canvas._hits = hits; hover(canvas);
  }

  function renderCalNumbers(s, thr) {
    const h = s.highlight_at_current, b = s.best_threshold;
    const few = h.wrong_words < 5;
    $("bt-cal-numbers").innerHTML = [
      ["Words scored", s.calibration.reduce((n, x) => n + x.count, 0)],
      ["Actually wrong", h.wrong_words],
      [`Highlighted (< ${Math.round(thr * 100)}%)`, h.flagged],
      ["Highlights that were wrong", h.flagged ? pct(h.precision, 0) + " precision" : "–"],
      ["Wrong words caught", h.wrong_words ? pct(h.recall, 0) + " recall" : "–"],
      ["Best threshold for your voice", few ? "need more errors" : `${Math.round(b.threshold * 100)}% (F1 ${b.f1})`],
    ].map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join("") +
      (few ? `<div style="grid-column:1/-1"><dt>Note</dt><dd style="font:500 13px Inter,sans-serif">Only ${h.wrong_words} wrong words - too few to judge the highlights. That's a good problem to have!</dd></div>` : "");
  }

  function renderWorst(c) {
    $("bt-worst-label").textContent = `(${c.name})`;
    const worst = c.utterances.filter((u) => u.wer > 0).sort((a, b) => b.wer - a.wer).slice(0, 5);
    const ds = result.dataset.name;
    $("bt-worst").innerHTML = worst.length ? worst.map((u) => `<div class="worst">
        <header><b>${pct(u.wer, 0)} WER</b> ${u.prompt_id} · heard as ${esc(u.detected)}
          <button class="icon-btn" data-play="${u.id}" aria-label="Play recording"><svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z" fill="currentColor"/></svg></button></header>
        <div class="vl-diff" lang="${u.lang}">${u.alignment.map((o) =>
          o.op === "ok" ? `<span class="d-ok">${esc(o.ref)}</span>` :
          o.op === "sub" ? `<span class="d-sub">${esc(o.ref)} → ${esc(o.hyp)}</span>` :
          o.op === "del" ? `<span class="d-del">${esc(o.ref)}</span>` : `<span class="d-ins">+${esc(o.hyp)}</span>`).join("")}</div>
        <p class="explain sm" style="margin:8px 0 0">Whisper wrote: “${esc(u.hypothesis)}”</p></div>`).join("")
      : '<p class="explain">No mistakes at all in this configuration. 🎉</p>';
    $("bt-worst").querySelectorAll("[data-play]").forEach((b) => (b.onclick = () => new Audio(`/api/bench/audio/${b.dataset.play}?dataset=${encodeURIComponent(ds)}`).play()));
  }

  $("bt-copy").onclick = async () => {
    try { await navigator.clipboard.writeText(result.markdown); toast("Copied - paste it into your README!", true); }
    catch { toast("Couldn't copy."); }
  };

  let rt;
  window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(drawAll, 150); });

  pageHooks.bench = async () => {
    if (!loaded) { loaded = true; await loadPrompts(); await loadResults(); }
    else drawAll();
  };
})();
