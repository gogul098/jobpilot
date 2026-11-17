// Thin client for the JobPilot backend (FastAPI on Render).
const BASE = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");
const KEY = "jp_token";

export const getToken = () => {
  try { return localStorage.getItem(KEY) || ""; } catch { return ""; }
};
export const setToken = (t) => {
  try { localStorage.setItem(KEY, t); } catch { /* private mode: keep in memory only */ }
};

async function call(path, opts = {}, token) {
  let r;
  try {
    r = await fetch(BASE + path, { ...opts, headers: { ...(opts.headers || {}), "X-App-Token": token } });
  } catch {
    throw new Error("Can't reach the server. On Render's free plan it sleeps when idle: wait 30-60 seconds and try again.");
  }
  const body = await r.json().catch(() => ({}));
  if (r.status === 401) throw new Error("Access token is wrong or missing. Copy APP_TOKEN from Render > jobpilot > Environment.");
  if (!r.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Server error ${r.status}`);
  return body;
}

const json = (data) => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });

export const api = {
  analyze(token, jdText, file) {
    const fd = new FormData();
    fd.append("jd_text", jdText);
    fd.append("tex_file", file);
    return call("/api/analyze", { method: "POST", body: fd }, token);
  },
  suggest: (token, id, confirmed) => call(`/api/jobs/${id}/suggest`, json({ confirmed_skills: confirmed }), token),
  apply: (token, id, edits) => call(`/api/jobs/${id}/apply`, json({ edits }), token),
  job: (token, id) => call(`/api/jobs/${id}`, {}, token),
  remove: (token, id) => call(`/api/jobs/${id}`, { method: "DELETE" }, token),
  health: () => fetch(BASE + "/api/health").then((r) => r.ok).catch(() => false),
  fileUrl: (token, id, name) =>
    `${BASE}/api/jobs/${id}/files/${name}?token=${encodeURIComponent(token)}&v=${Date.now()}`,

  /** Stream progress events for one request. Resolves with the final "done" event. */
  watch(token, id, from, wantStage, onStep) {
    return new Promise((resolve, reject) => {
      const es = new EventSource(`${BASE}/api/jobs/${id}/events?from=${from}&token=${encodeURIComponent(token)}`);
      const seen = new Set();
      es.onmessage = (e) => {
        const ev = JSON.parse(e.data);
        if (seen.has(ev.t)) return;
        seen.add(ev.t);
        if (ev.status === "failed") { es.close(); reject(new Error(ev.message)); }
        else if (ev.status === "done") { if (ev.stage === wantStage) { es.close(); resolve(ev); } }
        else onStep(ev);
      };
      // EventSource reconnects by itself; the server replays history from `from`.
    });
  },
};
