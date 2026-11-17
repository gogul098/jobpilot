const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
let jobId = null, source = null, analysis = null;

try { $("token").value = localStorage.getItem("jp_token") || ""; } catch {}
$("token").addEventListener("change", () => { try { localStorage.setItem("jp_token", $("token").value); } catch {} });
const token = () => $("token").value.trim();
const api = (path, opts = {}) => fetch(path, { ...opts, headers: { ...(opts.headers || {}), "X-App-Token": token() } });

function showErr(msg) { $("err").textContent = msg; $("err").hidden = !msg; }

$("go").onclick = async () => {
  showErr("");
  const jd = $("jd").value.trim(), file = $("tex").files[0];
  if (!jd) return showErr("Paste a job description.");
  if (!file) return showErr("Choose your resume's .tex file.");
  const fd = new FormData();
  fd.append("jd_text", jd);
  fd.append("tex_file", file);
  $("go").disabled = true;
  if (jobId) api(`/api/jobs/${jobId}`, { method: "DELETE" }).catch(() => {});
  ["jdcard", "scorecard", "revcard", "resultcard"].forEach((id) => ($(id).hidden = true));
  const r = await api("/api/analyze", { method: "POST", body: fd });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) { $("go").disabled = false; return showErr(body.detail || `Error ${r.status}`); }
  jobId = body.job_id;
  listen(onAnalyzed, "analyzed", body.from);
};

// The stream starts at this request's own events (`from`), so older runs never interfere.
function listen(onDone, wantStage, from = 0) {
  $("progress").hidden = false;
  $("steps").innerHTML = "";
  if (source) source.close();
  source = new EventSource(`/api/jobs/${jobId}/events?from=${from}&token=${encodeURIComponent(token())}`);
  const seen = new Set();
  source.onmessage = (e) => {
    const ev = JSON.parse(e.data);
    if (seen.has(ev.t)) return;
    seen.add(ev.t);
    if (ev.status === "queued") $("steps").innerHTML = "";
    if (ev.status === "done" && ev.stage !== wantStage) return;
    if (ev.status === "running" || ev.status === "waiting" || ev.status === "queued") {
      [...$("steps").children].forEach((li) => li.classList.add("done"));
      const li = document.createElement("li");
      li.textContent = ev.message || ev.stage;
      $("steps").appendChild(li);
    } else if (ev.status === "failed") {
      const li = document.createElement("li");
      li.className = "failed";
      li.textContent = "Failed: " + ev.message;
      $("steps").appendChild(li);
      source.close(); $("go").disabled = false; $("apply").disabled = false;
    } else if (ev.status === "done") {
      [...$("steps").children].forEach((li) => li.classList.add("done"));
      source.close();
      onDone(ev);
    }
  };
}

async function fetchJob() { return (await api(`/api/jobs/${jobId}`)).json(); }

async function onAnalyzed(ev) {
  if (ev.stage !== "analyzed") return;
  $("go").disabled = false;
  const data = await fetchJob();
  analysis = data.analysis;
  renderJD(analysis.jd);
  renderScore($("scorecard"), "ATS score (current resume)", analysis.score_before);
  renderRevisions(analysis);
}

function chips(list, cls = "") { return `<div class="chips">${list.map((x) => `<span class="chip ${cls}">${esc(x)}</span>`).join("")}</div>`; }

function renderJD(jd) {
  const rows = [["Company", jd.company], ["Location", jd.location], ["Mode", jd.work_mode], ["Type", jd.employment_type],
    ["Seniority", jd.seniority], ["Duration", jd.duration], ["Pay", jd.stipend_or_salary], ["Deadline", jd.deadline], ["Apply email", jd.apply_email]]
    .filter(([, v]) => v && v !== "unknown");
  const must = jd.hard_skills.filter((s) => s.importance === "must").map((s) => s.name);
  const nice = jd.hard_skills.filter((s) => s.importance !== "must").map((s) => s.name);
  let h = `<h2>${esc(jd.title)}</h2><dl class="kv">${rows.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join("")}</dl>`;
  if (must.length) h += `<label>Must-have skills</label>${chips(must, "must")}`;
  if (nice.length) h += `<label>Nice to have</label>${chips(nice)}`;
  if (jd.eligibility?.length) h += `<label>Eligibility</label><ul>${jd.eligibility.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;
  if (jd.responsibilities?.length) h += `<label>Responsibilities</label><ul>${jd.responsibilities.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;
  if (jd.interview_focus?.length) h += `<label>Prepare for</label><ul>${jd.interview_focus.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;
  if (jd.red_flags?.length) h += `<label>Red flags</label><ul class="err">${jd.red_flags.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;
  $("jdcard").innerHTML = h; $("jdcard").hidden = false;
}

function renderScore(el, title, rep) {
  let h = `<h2>${title}</h2><div class="big">${Math.round(rep.total)}<small>/100</small></div>`;
  for (const c of rep.components) {
    h += `<div class="comp"><h3><span>${esc(c.name)}</span><span>${c.score}/${c.max}</span></h3>
      <div class="bar"><i style="width:${(100 * c.score) / c.max}%"></i></div>
      <ul>${c.findings.map((f) => `<li>${esc(f)}</li>`).join("")}</ul></div>`;
  }
  if (rep.reword_gain || rep.locked) {
    h += `<div class="split"><div><b>+${rep.reword_gain}</b> available by rewording<br><span class="hint">job skills you list but never show in a bullet</span></div>
      <div><b>${rep.locked}</b> locked behind skills your resume doesn't show<br><span class="hint">only real skills can earn these, see below</span></div></div>`;
  }
  el.innerHTML = h; el.hidden = false;
}

function renderRevisions(a) {
  const box = $("revs");
  const before = Math.round(a.score_before.total);
  box.innerHTML = a.suggestions.length
    ? `<p class="projection">Accept all: <b>${before} → ~${Math.round(a.score_before.total + a.projected_gain)}</b> <span class="hint">(estimate; the exact score is computed from the rebuilt PDF)</span></p>`
    : `<p class="hint">No safe revisions for this job yet. Confirm any skills below that you really have, then regenerate.</p>`;
  for (const s of a.suggestions) {
    const d = document.createElement("div");
    d.className = "rev";
    const where = (s.context || s.section || s.kind).split(" | ")[0];
    d.innerHTML = `<header><input type="checkbox" checked data-id="${esc(s.id)}"><strong>${esc(where)}</strong>
      <span class="gain ${s.gain > 0 ? "pos" : ""}">${s.gain > 0 ? "+" + s.gain : "±0"}</span></header>
      <div class="meta">${esc(s.reason)}${s.keywords_added?.length ? " · shows " + esc(s.keywords_added.join(", ")) : ""}</div>
      <div class="old">${esc(s.old)}</div><textarea rows="3" data-id="${esc(s.id)}">${esc(s.new)}</textarea>`;
    box.appendChild(d);
  }
  let extra = "";
  if (a.rejected.length) {
    extra += `<details><summary>${a.rejected.length} suggestion(s) blocked by the fact check</summary>` +
      a.rejected.map((r) => `<div class="rev rejected"><div class="new">${esc(r.new)}</div><div class="why">Blocked: ${esc(r.rejected_because)}</div></div>`).join("") + `</details>`;
  }
  const skills = [...(a.confirmed_skills || []), ...(a.missing_skills || [])];
  if (skills.length) {
    extra += `<label>Job skills your resume doesn't show</label>
      <p class="hint">Tick only the ones you have really used. The rewrite will then work them into the right bullets.</p>
      <div class="chips">${skills.map((k) => `<label class="chip pick"><input type="checkbox" value="${esc(k)}" ${a.confirmed_skills?.includes(k) ? "checked" : ""}> ${esc(k)}</label>`).join("")}</div>
      <button id="resuggest" type="button" class="secondary">Regenerate with the ticked skills</button>`;
  }
  if (a.advice?.length) extra += `<label>Advice</label><ul>${a.advice.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;
  $("extra").innerHTML = extra;
  $("revcard").hidden = false;
  const rs = $("resuggest");
  if (rs) rs.onclick = async () => {
    const confirmed = [...document.querySelectorAll("#extra .pick input:checked")].map((x) => x.value);
    rs.disabled = true;
    const r = await api(`/api/jobs/${jobId}/suggest`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirmed_skills: confirmed }) });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) { rs.disabled = false; return alert(body.detail || `Error ${r.status}`); }
    listen(onAnalyzed, "analyzed", body.from);
  };
}

$("apply").onclick = async () => {
  const edits = {};
  document.querySelectorAll("#revs input[type=checkbox]:checked").forEach((cb) => {
    const ta = document.querySelector(`#revs textarea[data-id="${cb.dataset.id}"]`);
    edits[cb.dataset.id] = ta.value.trim();
  });
  if (!Object.keys(edits).length) return alert("Select at least one revision.");
  $("apply").disabled = true;
  const r = await api(`/api/jobs/${jobId}/apply`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ edits }) });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) { $("apply").disabled = false; return alert(body.detail || `Error ${r.status}`); }
  listen(onApplied, "applied", body.from);
};

async function onApplied(ev) {
  if (ev.stage !== "applied") return;
  $("apply").disabled = false;
  const { result } = await fetchJob();
  const before = Math.round(result.score_before), after = Math.round(result.score_after.total);
  const q = `?token=${encodeURIComponent(token())}&v=${Date.now()}`;
  const el = $("resultcard");
  el.innerHTML = `<h2>Revised resume</h2>
    <div class="delta">${before} → <span class="${after >= before ? "up" : ""}">${after}</span></div>
    <p class="links"><a href="/api/jobs/${jobId}/files/revised.pdf${q}" download="resume.pdf">Download PDF</a>
    <a href="/api/jobs/${jobId}/files/revised.tex${q}" download="resume.tex">Download .tex</a></p>
    <p class="hint">Files are temporary: they're deleted after an hour, or now with the button below.</p>
    <button id="done" type="button">Done, delete my files</button>
    <div id="after"></div><iframe src="/api/jobs/${jobId}/files/revised.pdf${q}" title="Revised resume PDF"></iframe>`;
  el.hidden = false;
  renderScore($("after"), "ATS score (revised)", result.score_after);
  $("done").onclick = async () => {
    await api(`/api/jobs/${jobId}`, { method: "DELETE" });
    jobId = null;
    ["progress", "jdcard", "scorecard", "revcard", "resultcard"].forEach((id) => ($(id).hidden = true));
    window.scrollTo({ top: 0, behavior: "smooth" });
  };
  el.scrollIntoView({ behavior: "smooth" });
}
