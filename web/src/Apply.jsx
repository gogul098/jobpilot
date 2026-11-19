import { useEffect, useState } from "react";
import { api } from "./api.js";

const STATUSES = ["Saved", "Applied", "Emailed", "Interview", "Offer", "Rejected"];
const TKEY = "jp_tracker";

/** Applications you're tracking. Kept only in this browser; the server stores nothing. */
export function useTracker() {
  const [items, setItems] = useState(() => {
    try { return JSON.parse(localStorage.getItem(TKEY) || "[]"); } catch { return []; }
  });
  useEffect(() => { try { localStorage.setItem(TKEY, JSON.stringify(items)); } catch { /* private mode */ } }, [items]);
  const upsert = (job, status) => setItems((xs) => {
    const key = job.id || `${job.company}|${job.title}`.toLowerCase();
    const rest = xs.filter((x) => x.key !== key);
    const old = xs.find((x) => x.key === key);
    return [{ key, title: job.title, company: job.company, url: job.url || "", status,
              updated: new Date().toISOString().slice(0, 10), added: old?.added || new Date().toISOString().slice(0, 10) }, ...rest];
  });
  const setStatus = (key, status) => setItems((xs) => xs.map((x) => (x.key === key ? { ...x, status, updated: new Date().toISOString().slice(0, 10) } : x)));
  const remove = (key) => setItems((xs) => xs.filter((x) => x.key !== key));
  const has = (id) => items.find((x) => x.key === id);
  return { items, upsert, setStatus, remove, has };
}

export function ApplyDesk({ token, jobId, analysis, tracker, busy, hasRevised, onTailor }) {
  return (
    <section className="apply-desk">
      <div className="section-head">
        <h2>Apply</h2>
        <p>Email this company with your resume attached, and find similar openings. You open LinkedIn and submit
          yourself: bots that apply for you get LinkedIn accounts banned.</p>
      </div>
      <div className="grid-2">
        <EmailComposer token={token} jobId={jobId} jd={analysis.jd} tracker={tracker} busy={busy} hasRevised={hasRevised} />
        <SimilarJobs token={token} jobId={jobId} tracker={tracker} onTailor={onTailor} />
      </div>
    </section>
  );
}

function EmailComposer({ token, jobId, jd, tracker, busy, hasRevised }) {
  const [gm, setGm] = useState(null);
  const [to, setTo] = useState(jd.apply_email || "");
  const [name, setName] = useState("");
  const [tone, setTone] = useState("warm");
  const [draft, setDraft] = useState(null);
  const [attach, setAttach] = useState(hasRevised ? "revised.pdf" : "original.pdf");
  const [state, setState] = useState("idle"); // idle | drafting | ready | sending | sent
  const [msg, setMsg] = useState("");

  useEffect(() => { api.gmailStatus(token).then(setGm).catch(() => setGm({ connected: false })); }, [token]);
  useEffect(() => { setAttach(hasRevised ? "revised.pdf" : "original.pdf"); }, [hasRevised]);

  async function makeDraft() {
    setMsg(""); setState("drafting");
    try {
      const { from } = await api.draftEmail(token, jobId, { to, recipient_name: name, tone });
      await api.watch(token, jobId, from, "email_drafted", () => {});
      const data = await api.job(token, jobId);
      setDraft(data.email);
      if (!to && data.email.to) setTo(data.email.to);
      setState("ready");
    } catch (e) { setMsg(e.message); setState(draft ? "ready" : "idle"); }
  }

  async function send() {
    setMsg(""); setState("sending");
    try {
      await api.sendEmail(token, jobId, { to, subject: draft.subject, body: draft.body, attachment: attach });
      tracker.upsert({ id: `email:${to}:${jd.title}`, title: jd.title, company: jd.company || to.split("@")[1] }, "Emailed");
      setState("sent");
    } catch (e) { setMsg(e.message); setState("ready"); }
  }

  const gmailLink = draft
    ? `https://mail.google.com/mail/?view=cm&fs=1&to=${encodeURIComponent(to)}&su=${encodeURIComponent(draft.subject)}&body=${encodeURIComponent(draft.body)}`
    : "";

  return (
    <article className="card composer">
      <span className="card-title">Email {jd.company || "the company"}</span>
      <div className="fields">
        <label>To<input type="text" inputMode="email" value={to} onChange={(e) => setTo(e.target.value)}
                        placeholder="recruiter@company.com" /></label>
        <label>Their name (optional)<input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="Priya" /></label>
      </div>
      <div className="seg" role="radiogroup" aria-label="Tone">
        {["warm", "formal"].map((t) => (
          <button key={t} role="radio" aria-checked={tone === t} className={tone === t ? "on" : ""} onClick={() => setTone(t)}>
            {t === "warm" ? "Warm" : "Formal"}
          </button>
        ))}
      </div>
      <button className="btn" onClick={makeDraft} disabled={busy || state === "drafting" || state === "sending"}>
        {state === "drafting" ? "Writing..." : draft ? "Write it again" : "Write the email"}
      </button>

      {draft && (
        <div className="draft">
          <label>Subject<input type="text" value={draft.subject} onChange={(e) => setDraft({ ...draft, subject: e.target.value })} /></label>
          <label>Message<textarea rows={14} value={draft.body} onChange={(e) => setDraft({ ...draft, body: e.target.value })} /></label>
          {draft.warnings?.length > 0 && (
            <ul className="warn">{draft.warnings.map((w, i) => <li key={i}>{w} Check it before sending.</li>)}</ul>
          )}
          <div className="attach">
            <span>Attach</span>
            <label><input type="radio" checked={attach === "revised.pdf"} disabled={!hasRevised} onChange={() => setAttach("revised.pdf")} /> Tailored resume{!hasRevised && " (build it above first)"}</label>
            <label><input type="radio" checked={attach === "original.pdf"} onChange={() => setAttach("original.pdf")} /> Original resume</label>
          </div>
          {gm?.connected ? (
            <button className="btn send" onClick={send} disabled={state === "sending" || state === "sent" || !to}>
              {state === "sending" ? "Sending..." : state === "sent" ? `Sent to ${to}` : `Send from ${gm.address || "your Gmail"}`}
            </button>
          ) : (
            <div className="fallback">
              <a className="btn ghost" href={gmailLink} target="_blank" rel="noreferrer">Open in Gmail</a>
              <p className="note">Gmail isn't connected, so attach the downloaded PDF yourself. To send with one click,
                connect Gmail (README: "Email setup").</p>
            </div>
          )}
          {state === "sent" && <p className="ok-msg">Sent with your resume attached. Added to your applications.</p>}
          {gm?.connected && <p className="note">Limit: {gm.daily_limit} emails a day, so Gmail doesn't flag you as spam.</p>}
        </div>
      )}
      {msg && <p className="error" role="alert">{msg}</p>}
    </article>
  );
}

function SimilarJobs({ token, jobId, tracker, onTailor }) {
  const [res, setRes] = useState(null);
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState("");

  async function find() {
    setMsg(""); setLoading(true);
    try { setRes(await api.similar(token, jobId)); } catch (e) { setMsg(e.message); }
    setLoading(false);
  }

  return (
    <article className="card similar">
      <span className="card-title">Similar jobs</span>
      <p className="note top">Ranked by how much of each job's skill list your resume already shows.</p>
      <div className="row">
        <button className="btn" onClick={find} disabled={loading}>{loading ? "Searching..." : res ? "Search again" : "Find similar jobs"}</button>
        {res && <a className="btn ghost" href={res.linkedin_search} target="_blank" rel="noreferrer">Search on LinkedIn</a>}
      </div>
      {msg && <p className="error" role="alert">{msg}</p>}
      {res && res.jobs.length === 0 && (
        <p className="note">{res.providers.length ? "No matches from the job APIs right now." : "No job API is connected yet, so only the LinkedIn search works. Add a JSearch or Adzuna key (README: \"Job search setup\")."}
          {res.errors?.length > 0 && <> Errors: {res.errors.join("; ")}</>}</p>
      )}
      <ul className="jobs">
        {res?.jobs.map((j) => {
          const tracked = tracker.has(j.id);
          return (
            <li key={j.id} className="job-row">
              <div className="job-top">
                <div>
                  <b>{j.title}</b>
                  <span>{j.company}{j.location && `, ${j.location}`}</span>
                  <small>{j.source}{j.posted && `, posted ${j.posted}`}</small>
                </div>
                <span className={`match ${j.match >= 70 ? "hi" : j.match >= 45 ? "mid" : "lo"}`} title="How much of this job's skill list your resume shows">{j.match}%</span>
              </div>
              {j.missing?.length > 0 && <p className="gap">You don't show: {j.missing.slice(0, 5).join(", ")}</p>}
              <div className="job-actions">
                {j.linkedin_url && <a className="btn small" href={j.linkedin_url} target="_blank" rel="noreferrer" onClick={() => tracker.upsert(j, "Saved")}>Apply on LinkedIn</a>}
                <a className={`btn small ${j.linkedin_url ? "ghost" : ""}`} href={j.url} target="_blank" rel="noreferrer" onClick={() => tracker.upsert(j, "Saved")}>Open job</a>
                <button className="btn small ghost" onClick={() => onTailor(`${j.title}\n${j.company}, ${j.location}\n\n${j.description}`)}>Tailor resume for this</button>
                <button className="btn small ghost" onClick={() => tracker.upsert(j, "Applied")} disabled={tracked?.status === "Applied"}>
                  {tracked?.status === "Applied" ? "Marked applied" : "I applied"}
                </button>
              </div>
            </li>
          );
        })}
      </ul>
    </article>
  );
}

export function Tracker({ tracker }) {
  if (!tracker.items.length) return null;
  return (
    <section className="card tracker">
      <span className="card-title">Your applications ({tracker.items.length})</span>
      <p className="note top">Saved in this browser only.</p>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Role</th><th>Company</th><th>Status</th><th>Updated</th><th><span className="sr">Remove</span></th></tr></thead>
          <tbody>
            {tracker.items.map((x) => (
              <tr key={x.key}>
                <td>{x.url ? <a href={x.url} target="_blank" rel="noreferrer">{x.title}</a> : x.title}</td>
                <td>{x.company}</td>
                <td>
                  <select value={x.status} onChange={(e) => tracker.setStatus(x.key, e.target.value)} className={`st-${x.status.toLowerCase()}`}>
                    {STATUSES.map((s) => <option key={s}>{s}</option>)}
                  </select>
                </td>
                <td>{x.updated}</td>
                <td><button className="x" aria-label={`Remove ${x.title}`} onClick={() => tracker.remove(x.key)}>×</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
