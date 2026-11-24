import { useEffect, useMemo, useRef, useState } from "react";
import { api, BUILT_IN_TOKEN, getToken, setToken } from "./api.js";
import { ApplyDesk, Tracker, useTracker } from "./Apply.jsx";

const STEPS = ["Paste the job", "Get scored", "Pick rewrites", "Download PDF"];
const COMPONENT_NAMES = {
  parseability: "Machine-readable",
  keywords: "Job keywords",
  sections: "Standard sections",
  bullets: "Bullet strength",
  length: "Length",
};

export default function App() {
  const [token, setTok] = useState(() => getToken());
  const [showKey, setShowKey] = useState(() => !getToken());
  const [jd, setJd] = useState("");
  const [file, setFile] = useState(null);
  const [phase, setPhase] = useState("idle"); // idle | analyzing | review | applying | done
  const [steps, setSteps] = useState([]);
  const [error, setError] = useState("");
  const [jobId, setJobId] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [result, setResult] = useState(null);
  const [picked, setPicked] = useState({}); // id -> text (selected revisions)
  const [skills, setSkills] = useState([]); // confirmed skills
  const [awake, setAwake] = useState(null);
  const resultRef = useRef(null);
  const tracker = useTracker();

  useEffect(() => { api.health().then(setAwake); }, []);
  useEffect(() => { if (phase === "done") resultRef.current?.scrollIntoView({ behavior: "smooth" }); }, [phase]);

  const stepIndex = { idle: 0, analyzing: 1, review: 2, applying: 3, done: 3 }[phase];
  const busy = phase === "analyzing" || phase === "applying";

  const saveToken = (t) => { setTok(t); setToken(t); };
  const onStep = (ev) => setSteps((s) => [...s, ev.message || ev.stage]);

  async function loadAnalysis(id) {
    const data = await api.job(token, id);
    const a = data.analysis;
    setAnalysis(a);
    setPicked(Object.fromEntries(a.suggestions.map((s) => [s.id, s.new])));
    setSkills(a.confirmed_skills || []);
    setPhase("review");
  }

  async function run(fn, nextPhase) {
    setError("");
    setSteps([]);
    setPhase(nextPhase);
    try { await fn(); } catch (e) { setError(e.message); setPhase(analysis && nextPhase !== "analyzing" ? "review" : "idle"); }
  }

  const analyze = () => run(async () => {
    if (!token) { setShowKey(true); throw new Error("Add your access token first (key button, top right)."); }
    if (!jd.trim()) throw new Error("Paste the job posting first.");
    if (!file) throw new Error("Add your resume's .tex file.");
    if (jobId) api.remove(token, jobId).catch(() => {});
    setAnalysis(null); setResult(null);
    const { job_id, from } = await api.analyze(token, jd, file);
    setJobId(job_id);
    await api.watch(token, job_id, from, "analyzed", onStep);
    await loadAnalysis(job_id);
  }, "analyzing");

  const resuggest = () => run(async () => {
    const { from } = await api.suggest(token, jobId, skills);
    await api.watch(token, jobId, from, "analyzed", onStep);
    await loadAnalysis(jobId);
  }, "analyzing");

  const applyEdits = () => run(async () => {
    if (!Object.keys(picked).length) throw new Error("Pick at least one rewrite.");
    const { from } = await api.apply(token, jobId, picked);
    await api.watch(token, jobId, from, "applied", onStep);
    const data = await api.job(token, jobId);
    setResult(data.result);
    setPhase("done");
  }, "applying");

  async function finish() {
    if (jobId) await api.remove(token, jobId).catch(() => {});
    setJobId(null); setAnalysis(null); setResult(null); setPicked({}); setSteps([]); setPhase("idle");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  return (
    <>
      <header className="topbar">
        <a className="logo" href="/" aria-label="JobPilot home">Job<span>Pilot</span></a>
        <div className="topbar-right">
          <span className={`server ${awake === null ? "" : awake ? "up" : "down"}`}
                title={awake === false ? "Server is asleep or unreachable; the first request wakes it" : "Server status"}>
            {awake === null ? "Checking server" : awake ? "Server ready" : "Server waking up"}
          </span>
          {!BUILT_IN_TOKEN && (
            <button className="btn small" onClick={() => setShowKey((v) => !v)} aria-expanded={showKey}>
              {token ? "Access key" : "Add access key"}
            </button>
          )}
        </div>
      </header>
      {showKey && !BUILT_IN_TOKEN && (
        <div className="keybar">
          <label htmlFor="tok">Access key (APP_TOKEN from Render)</label>
          <input id="tok" type="password" value={token} onChange={(e) => saveToken(e.target.value.trim())} placeholder="Paste it once; this browser remembers it" />
          <button className="btn small" onClick={() => setShowKey(false)}>Done</button>
        </div>
      )}

      <main>
        <section className="hero">
          <h1>Make your resume fit the job. Every claim stays true.</h1>
          <p className="lede">
            Paste a job posting and your LaTeX resume. You get the job broken down, an ATS score for your actual PDF,
            and rewrites you approve one by one. Nothing is invented, and nothing is kept after you're done.
          </p>
          <ol className="track" aria-label="Progress">
            {STEPS.map((s, i) => (
              <li key={s} className={i < stepIndex ? "past" : i === stepIndex ? "now" : ""}>
                <b>{i + 1}</b><span>{s}</span>
              </li>
            ))}
          </ol>
        </section>

        <section className="inputs">
          <div className="card posting">
            <span className="tape" aria-hidden="true" />
            <label htmlFor="jd" className="card-title">The job posting</label>
            <textarea id="jd" value={jd} onChange={(e) => setJd(e.target.value)} rows={12}
                      placeholder={"Paste the whole posting: title, requirements, eligibility, how to apply..."} />
            <div className="count">{jd.trim() ? `${jd.trim().split(/\s+/).length} words` : "Nothing pasted yet"}</div>
          </div>
          <Dropzone file={file} setFile={setFile} />
        </section>

        <div className="cta-row">
          <button className="btn big" onClick={analyze} disabled={busy}>
            {phase === "analyzing" ? "Scoring..." : analysis ? "Score again" : "Score my resume"}
          </button>
          {error && <p className="error" role="alert">{error}</p>}
        </div>

        {(busy || (steps.length > 0 && error)) && <Progress steps={steps} busy={busy} />}

        {analysis && (
          <>
            <section className="grid-2">
              <JobCard jd={analysis.jd} />
              <ScoreCard title="Your resume today" rep={analysis.score_before} />
            </section>
            <Revisions a={analysis} picked={picked} setPicked={setPicked} skills={skills} setSkills={setSkills}
                       onResuggest={resuggest} busy={busy} />
            <div className="applybar">
              <span>
                {Object.keys(picked).length} of {analysis.suggestions.length} rewrites picked
                {analysis.suggestions.length > 0 && (
                  <>; score now <b>{Math.round(analysis.score_before.total)}</b>, about <b>{Math.round(analysis.score_before.total + projected(analysis, picked))}</b> after</>
                )}
              </span>
              <button className="btn" onClick={applyEdits} disabled={busy || !Object.keys(picked).length}>
                {phase === "applying" ? "Building PDF..." : "Apply and build PDF"}
              </button>
            </div>
          </>
        )}

        {phase === "done" && result && (
          <section className="result" ref={resultRef}>
            <div className="card result-card">
              <div className="stamps">
                <Stamp value={result.score_before} label="before" muted />
                <span className="arrow" aria-hidden="true">⟶</span>
                <Stamp value={result.score_after.total} label="after" />
              </div>
              <div className="downloads">
                <a className="btn" href={api.fileUrl(token, jobId, "revised.pdf")} download="resume.pdf">Download PDF</a>
                <a className="btn ghost" href={api.fileUrl(token, jobId, "revised.tex")} download="resume.tex">Download .tex</a>
                <button className="btn ghost" onClick={finish}>Done, delete my files</button>
              </div>
              {result.skipped && Object.keys(result.skipped).length > 0 && (
                <p className="error">
                  {Object.keys(result.skipped).length} change{Object.keys(result.skipped).length > 1 ? "s" : ""} broke the LaTeX, so {Object.keys(result.skipped).length > 1 ? "they were" : "it was"} left out: {Object.entries(result.skipped).map(([id, why]) => `${(analysis?.suggestions.find((x) => x.id === id)?.context || id).split(" | ")[0]} (${why})`).join("; ")}
                </p>
              )}
              <p className="note">Your files are deleted when you press Done, or automatically after an hour.</p>
              <iframe title="Revised resume" src={api.fileUrl(token, jobId, "revised.pdf")} />
            </div>
            <ScoreCard title="Revised resume" rep={result.score_after} />
          </section>
        )}

        {analysis && jobId && (
          <ApplyDesk token={token} jobId={jobId} analysis={analysis} tracker={tracker} busy={busy}
                     hasRevised={phase === "done"}
                     onTailor={(text) => { setJd(text); window.scrollTo({ top: 0, behavior: "smooth" }); }} />
        )}

        <Tracker tracker={tracker} />
      </main>

      <footer>
        Scores come from your compiled PDF, not from an AI guess. Rewrites that add a number, tool or skill you don't have are blocked.
      </footer>
    </>
  );
}

function projected(a, picked) {
  // Sum of per-suggestion gains for the picked ones (an estimate; the server re-scores the real PDF).
  return a.suggestions.filter((s) => s.id in picked).reduce((t, s) => t + Math.max(0, s.gain), 0);
}

function Dropzone({ file, setFile }) {
  const [over, setOver] = useState(false);
  const input = useRef(null);
  const take = (f) => { if (f && /\.(tex|txt)$/i.test(f.name)) setFile(f); };
  return (
    <div className={`card folder ${over ? "over" : ""} ${file ? "has" : ""}`}
         onDragOver={(e) => { e.preventDefault(); setOver(true); }}
         onDragLeave={() => setOver(false)}
         onDrop={(e) => { e.preventDefault(); setOver(false); take(e.dataTransfer.files[0]); }}>
      <span className="tab" aria-hidden="true">resume.tex</span>
      <span className="card-title">Your resume</span>
      <button className="drop" onClick={() => input.current.click()}>
        {file ? (
          <><b>{file.name}</b><span>{(file.size / 1024).toFixed(1)} KB · click to swap</span></>
        ) : (
          <><b>Drop your .tex file here</b><span>or click to choose it. Overleaf: Menu, Download, Source.</span></>
        )}
      </button>
      <input ref={input} type="file" accept=".tex,.txt,text/x-tex,text/plain" hidden onChange={(e) => take(e.target.files[0])} />
      <p className="note">Works with Jake's Resume, Awesome-CV and plain itemize resumes. Your Skills section is never edited.</p>
    </div>
  );
}

function Progress({ steps, busy }) {
  return (
    <section className="card progress" aria-live="polite">
      <span className="card-title">{busy ? "Working on it" : "Stopped"}</span>
      <ul>
        {steps.map((s, i) => (
          <li key={i} className={i === steps.length - 1 && busy ? "now" : "ok"}>{s}</li>
        ))}
        {busy && steps.length === 0 && <li className="now">Sending to the server</li>}
      </ul>
    </section>
  );
}

function JobCard({ jd }) {
  const facts = [["Company", jd.company], ["Location", jd.location], ["Mode", jd.work_mode !== "unknown" && jd.work_mode],
    ["Type", jd.employment_type], ["Level", jd.seniority], ["Duration", jd.duration], ["Pay", jd.stipend_or_salary],
    ["Deadline", jd.deadline], ["Apply to", jd.apply_email]].filter(([, v]) => v);
  const must = jd.hard_skills.filter((s) => s.importance === "must");
  const nice = jd.hard_skills.filter((s) => s.importance !== "must");
  return (
    <article className="card job">
      <span className="card-title">What this job wants</span>
      <h2>{jd.title}</h2>
      {facts.length > 0 && <dl className="facts">{facts.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>}
      {must.length > 0 && <><h3>Must have</h3><div className="chips">{must.map((s) => <span className="chip must" key={s.name}>{s.name}</span>)}</div></>}
      {nice.length > 0 && <><h3>Nice to have</h3><div className="chips">{nice.map((s) => <span className="chip" key={s.name}>{s.name}</span>)}</div></>}
      <List title="Eligibility" items={jd.eligibility} />
      <List title="You'd be doing" items={jd.responsibilities} />
      <List title="Prepare for" items={jd.interview_focus} />
      <List title="Red flags" items={jd.red_flags} cls="flags" />
    </article>
  );
}

function List({ title, items, cls = "" }) {
  if (!items?.length) return null;
  return <><h3>{title}</h3><ul className={`list ${cls}`}>{items.map((x, i) => <li key={i}>{x}</li>)}</ul></>;
}

function verdict(score) {
  return score >= 85 ? "Shortlist ready" : score >= 70 ? "Close" : "Needs work";
}

function Stamp({ value, label, muted }) {
  const v = Math.round(value);
  return (
    <div className={`stamp ${muted ? "muted" : v >= 85 ? "good" : v >= 70 ? "mid" : "low"}`} aria-label={`${label}: ${v} out of 100`}>
      <b>{v}</b>
      <span>{muted ? label : verdict(v)}</span>
    </div>
  );
}

function ScoreCard({ title, rep }) {
  return (
    <article className="card score">
      <span className="card-title">{title}</span>
      <Stamp value={rep.total} label="ATS score" />
      <div className="meters">
        {rep.components.map((c) => (
          <div className="meter" key={c.name}>
            <div className="meter-head"><span>{COMPONENT_NAMES[c.name] || c.name}</span><b>{c.score}/{c.max}</b></div>
            <div className="bar"><i style={{ width: `${(100 * c.score) / c.max}%` }} /></div>
            <ul>{c.findings.map((f, i) => <li key={i}>{f}</li>)}</ul>
          </div>
        ))}
      </div>
      {(rep.reword_gain > 0 || rep.locked > 0) && (
        <div className="split">
          <div className="gainbox"><b>+{rep.reword_gain}</b><span>points you can win by rewording what you already list</span></div>
          <div className="lockbox"><b>{rep.locked}</b><span>points only skills you really have can win</span></div>
        </div>
      )}
    </article>
  );
}

function Revisions({ a, picked, setPicked, skills, setSkills, onResuggest, busy }) {
  const toggle = (s) => setPicked((p) => {
    const n = { ...p };
    if (s.id in n) delete n[s.id]; else n[s.id] = s.new;
    return n;
  });
  const edit = (id, text) => setPicked((p) => ({ ...p, [id]: text }));
  const allSkills = useMemo(() => [...new Set([...(a.confirmed_skills || []), ...(a.missing_skills || [])])], [a]);

  return (
    <section className="revisions">
      <div className="section-head">
        <h2>Rewrites for this job</h2>
        <p>Ranked by how much each one lifts your score. Untick any you don't like, or edit the new text before applying.</p>
      </div>

      {a.suggestions.length === 0 && (
        <div className="card empty">No safe rewrites yet. If you really have any of the skills below, tick them and rewrite again.</div>
      )}

      {a.suggestions.map((s) => {
        const on = s.id in picked;
        return (
          <article className={`card rev ${on ? "on" : "off"}`} key={s.id}>
            <header>
              <label className="check">
                <input type="checkbox" checked={on} onChange={() => toggle(s)} />
                <span>{(s.context || s.section || s.kind).split(" | ")[0]}</span>
              </label>
              <span className={`gain ${s.gain > 0 ? "pos" : ""}`}>{s.gain > 0 ? `+${s.gain}` : "±0"}</span>
            </header>
            <p className="why">{s.reason}{s.keywords_added?.length > 0 && <> Shows: {s.keywords_added.join(", ")}.</>}</p>
            <del>{s.old}</del>
            <textarea aria-label="New text" value={on ? picked[s.id] : s.new} disabled={!on}
                      onChange={(e) => edit(s.id, e.target.value)} rows={3} />
          </article>
        );
      })}

      {a.rejected.length > 0 && (
        <details className="card blocked">
          <summary>{a.rejected.length} rewrite{a.rejected.length > 1 ? "s" : ""} blocked by the fact check</summary>
          {a.rejected.map((r, i) => (
            <div className="blocked-item" key={i}><p>{r.new}</p><span>{r.rejected_because}</span></div>
          ))}
        </details>
      )}

      {allSkills.length > 0 && (
        <div className="card skills">
          <span className="card-title">Skills the job wants that your resume doesn't show</span>
          <p>Tick only what you have really used. The rewrite then works them into the right project bullets.</p>
          <div className="chips">
            {allSkills.map((k) => {
              const on = skills.includes(k);
              return (
                <button key={k} className={`chip toggle ${on ? "on" : ""}`} aria-pressed={on}
                        onClick={() => setSkills((x) => (on ? x.filter((y) => y !== k) : [...x, k]))}>
                  {on ? "✓ " : ""}{k}
                </button>
              );
            })}
          </div>
          <button className="btn ghost" onClick={onResuggest} disabled={busy}>Rewrite with these skills</button>
        </div>
      )}

      {a.advice?.length > 0 && (
        <div className="card advice">
          <span className="card-title">Advice for this job</span>
          <ul className="list">{a.advice.map((x, i) => <li key={i}>{x}</li>)}</ul>
        </div>
      )}
    </section>
  );
}
