// Upnext UI. Plain JS, no build step. Polls /api/state once a second.

const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const ICON = {
  play: '<svg viewBox="0 0 20 20"><path d="M6 4.5v11l9-5.5z" fill="currentColor" stroke="none"/></svg>',
  down: '<svg viewBox="0 0 20 20"><path d="M10 3.5v9m0 0-3.5-3.5M10 12.5l3.5-3.5M4.5 16h11"/></svg>',
  cc: '<svg viewBox="0 0 20 20"><rect x="2.5" y="4" width="15" height="12" rx="2"/><path d="M6 11h3M11 11h3M6 13.5h8"/></svg>',
  folder: '<svg viewBox="0 0 20 20"><path d="M3 6.5V15a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8a1 1 0 0 0-1-1h-6L8.5 5H4a1 1 0 0 0-1 1.5z"/></svg>',
  trash: '<svg viewBox="0 0 20 20"><path d="M4.5 6h11M8 6V4.5h4V6M6 6l.7 9.5h6.6L14 6"/></svg>',
  x: '<svg viewBox="0 0 20 20"><path d="M5.5 5.5l9 9m0-9-9 9"/></svg>',
  check: '<svg viewBox="0 0 20 20"><path d="M4.5 10.5l3.5 3.5 7.5-8"/></svg>',
  wait: '<svg viewBox="0 0 20 20"><circle cx="10" cy="10" r="6.5"/><path d="M10 6.5V10l2.5 1.5"/></svg>',
  next: '<svg viewBox="0 0 20 20"><path d="M5 4.5v11l7.5-5.5zM14.5 4.5v11" /></svg>',
  refresh: '<svg viewBox="0 0 20 20"><path d="M15.5 8A6 6 0 0 0 4.6 6.5M4.5 12a6 6 0 0 0 10.9 1.5M4.5 3.5v3h3M15.5 16.5v-3h-3"/></svg>',
};

const S = {
  page: "library",
  shows: [], sources: [], refreshing: false,
  show: null, season: null,
  jobs: [], auto: {},
  settings: null, drive: null, tools: null,
  videos: [], video: null, vinfo: null, results: null, searching: false, vfilter: "",
};

async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", headers: {} };
  if (opts.body !== undefined) { init.body = JSON.stringify(opts.body); init.headers["Content-Type"] = "application/json"; }
  const r = await fetch(path, init);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `Request failed (${r.status})`);
  return data;
}
function toast(msg, err = false) {
  const t = document.createElement("div");
  t.className = "toast" + (err ? " err" : "");
  t.textContent = msg;
  $("#toasts").append(t);
  setTimeout(() => t.remove(), err ? 6000 : 3500);
}
async function act(fn, ok) {
  try { const r = await fn(); if (ok) toast(ok); return r; } catch (e) { toast(e.message, true); }
}

const fmt = (sec) => { sec = Math.max(0, Math.round(sec)); const h = Math.floor(sec / 3600), m = Math.floor(sec / 60) % 60, s = sec % 60; return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`; };
const jobFor = (key) => S.jobs.find((j) => j.key === key);
const activeJob = (key) => { const j = jobFor(key); return j && (j.status === "running" || j.status === "queued") ? j : null; };
const hue = (s) => [...s].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);
const initials = (name) => name.replace(/^the\s+/i, "").split(/\s+/).slice(0, 2).map((w) => w[0]).join("").toUpperCase();

// ---- navigation ----------------------------------------------------------------
function go(page) {
  S.page = page;
  document.querySelectorAll(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.page === page));
  document.querySelectorAll(".page").forEach((p) => (p.hidden = p.id !== `page-${page}`));
  try { localStorage.setItem("upnext.page", page); } catch {}
  if (page === "settings") loadSettings();
  if (page === "subtitles") loadVideos();
  render();
}
document.querySelectorAll(".nav-item").forEach((b) => b.addEventListener("click", () => go(b.dataset.page)));

function render() {
  renderNow();
  if (S.page === "library") renderLibrary();
  if (S.page === "subtitles") renderSubtitles();
  if (S.page === "activity") renderActivity();
  if (S.page === "settings") renderSettings();
  const n = S.jobs.filter((j) => j.status === "running" || j.status === "queued").length;
  $("#activeCount").hidden = !n; $("#activeCount").textContent = n;
}

// ---- now playing ------------------------------------------------------------------
function renderNow() {
  const a = S.auto, el = $("#now");
  const now = a.now;
  if (!now) {
    el.className = "now idle";
    el.innerHTML = `<div><div class="now-eyebrow">Nothing playing</div><div class="hint">Press play on an episode, or open one in VLC. Upnext follows along and gets the next one ready.</div></div>
      <div class="now-actions"><label class="switch"><input type="checkbox" id="autoToggle" ${a.enabled !== false ? "checked" : ""}> Autopilot</label></div>`;
  } else {
    const info = now.info, pct = now.length ? (now.time / now.length) * 100 : 0;
    const credits = a.credits_at ? (a.credits_at / now.length) * 100 : 0;
    const title = info ? `<span class="code">${esc(`S${String(info.season).padStart(2, "0")}E${String(info.episode).padStart(2, "0")}`)}</span>${esc(info.series)}${info.title ? " · " + esc(info.title) : ""}` : esc(now.name);
    el.className = "now";
    el.innerHTML = `
      <div style="min-width:0"><div class="now-eyebrow">${now.playing ? "Now playing" : "Paused"} in VLC</div><div class="now-title">${title}</div></div>
      <div class="now-actions">
        <button class="btn small" id="playNext" ${a.next && (a.next.local) ? "" : "disabled"} title="Skip to the next episode">${ICON.next} Next</button>
        <label class="switch"><input type="checkbox" id="autoToggle" ${a.enabled !== false ? "checked" : ""}> Autopilot</label>
      </div>
      <div class="track"><i style="width:${pct}%"></i>${credits ? `<b style="width:${credits}%" title="Credits"></b>` : ""}</div>
      <div class="now-meta num">
        <span><strong>${fmt(now.remaining)}</strong> left</span>
        ${a.credits_at ? `<span>Credits at <strong>${fmt(now.length - a.credits_at)}</strong></span>` : ""}
        ${nextLine(a)}
        ${a.upnext ? `<span class="upnext-live">Up next on screen: ${esc(a.upnext.label)}</span>` : ""}
      </div>`;
  }
  $("#autoToggle").onchange = (e) => act(() => api("/api/autopilot", { method: "POST", body: { enabled: e.target.checked } }), e.target.checked ? "Autopilot on" : "Autopilot off");
  const pn = $("#playNext"); if (pn) pn.onclick = () => act(() => api("/api/autopilot/next", { method: "POST" }));
}
function nextLine(a) {
  if (!a.next) return a.now && a.now.info ? `<span>No next episode in your library</span>` : "";
  const n = a.next;
  let st;
  const j = n.target && activeJob("download:" + n.target);
  if (n.local) st = `<span class="state local">${ICON.check} Ready</span>`;
  else if (j) st = `<span class="state busy">Downloading ${j.progress != null ? Math.round(j.progress * 100) + "%" : ""}</span>`;
  else if (n.remote) st = `<span class="state remote">Downloads with ${S.settings ? S.settings.prefetch_minutes : 15} min left</span>`;
  else st = "";
  return `<span>Next: <strong>${esc(n.label)}</strong> ${st}</span>`;
}

// ---- library ------------------------------------------------------------------------
async function loadLibrary() {
  const d = await api("/api/library");
  S.shows = d.shows; S.sources = d.sources; S.refreshing = d.refreshing;
  if (S.show && !S.shows.find((s) => s.key === S.show)) S.show = null;
  if (!S.show && S.shows.length) {
    const playing = S.auto.now && S.auto.now.info && S.auto.now.info.key;
    S.show = (playing && S.shows.find((s) => s.key === playing) ? playing : S.shows[0].key);
  }
  renderFoot();
  if (S.page === "library") renderLibrary();
}
function renderFoot() {
  const n = S.sources.length;
  const err = S.sources.find((s) => s.error);
  $("#driveStatus").innerHTML = `<div><span class="dot ${S.refreshing ? "busy" : err ? "err" : n ? "ok" : ""}"></span>${S.refreshing ? "Reading Drive…" : n ? `${n} Drive folder${n > 1 ? "s" : ""}` : "No Drive folders"}</div>`;
}
function renderLibrary() {
  const el = $("#page-library");
  if (!S.shows.length) {
    el.innerHTML = `<div class="empty"><h2>${S.refreshing ? "Reading your Drive…" : "Your library is empty"}</h2>
      <p>${S.refreshing ? "This can take a minute the first time." : "Add a Google Drive folder with your shows in Settings. Episodes already in your download folder show up here too."}</p>
      ${S.refreshing ? "" : `<button class="btn primary" onclick="go('settings')">Add a Drive folder</button>`}</div>`;
    return;
  }
  const show = S.shows.find((s) => s.key === S.show) || S.shows[0];
  if (!show.seasons.find((x) => x.season === S.season)) {
    const playing = S.auto.now && S.auto.now.info && S.auto.now.info.key === show.key ? S.auto.now.info.season : null;
    // open where you are: the playing season, else the latest season you have episodes from
    const started = show.seasons.filter((x) => x.downloaded > 0).pop();
    S.season = playing ?? (started || show.seasons[0]).season;
  }
  const season = show.seasons.find((x) => x.season === S.season);
  const playingPath = S.auto.now && S.auto.now.path;
  const shows = S.shows.map((s) => `
    <button class="show ${s.key === show.key ? "active" : ""}" data-show="${esc(s.key)}">
      <span class="poster" style="background:hsl(${hue(s.name)} 45% 62%)">${esc(initials(s.name))}</span>
      <span class="name">${esc(s.name)}</span>
      <span class="count num">${s.seasons.length} season${s.seasons.length > 1 ? "s" : ""} · ${s.downloaded}/${s.episodes} on this Mac</span>
    </button>`).join("");
  const tabs = show.seasons.map((x) => `<button class="chip-tab ${x.season === S.season ? "active" : ""}" data-season="${x.season}">Season ${x.season}<small>${x.downloaded}/${x.episodes.length}</small></button>`).join("");
  const missing = season.episodes.filter((e) => !e.local && e.remote).length;
  const rows = season.episodes.map((e) => epRow(show, e, playingPath)).join("");
  el.innerHTML = `
    <div class="head"><div><h1>Library</h1><p class="sub">${S.shows.length} show${S.shows.length > 1 ? "s" : ""} from your Drive and this Mac</p></div>
      <button class="btn ghost" id="refreshLib">${ICON.refresh} ${S.refreshing ? "Refreshing…" : "Refresh"}</button></div>
    <div class="lib">
      <div class="shows">${shows}</div>
      <div>
        <div class="card-head"><h1 style="font-size:22px">${esc(show.name)}</h1>
          <button class="btn" id="dlSeason" ${missing ? "" : "disabled"}>${ICON.down} ${missing ? `Download ${missing} episode${missing > 1 ? "s" : ""}` : "Season downloaded"}</button></div>
        <div class="seasons">${tabs}</div>
        <div class="eps">${rows}</div>
      </div>
    </div>`;
  el.querySelectorAll("[data-show]").forEach((b) => (b.onclick = () => { S.show = b.dataset.show; S.season = null; renderLibrary(); }));
  el.querySelectorAll("[data-season]").forEach((b) => (b.onclick = () => { S.season = +b.dataset.season; renderLibrary(); }));
  $("#refreshLib").onclick = () => act(async () => { await api("/api/library/refresh", { method: "POST" }); S.refreshing = true; renderFoot(); renderLibrary(); }, "Reading Drive in the background");
  $("#dlSeason").onclick = () => act(async () => { const r = await api("/api/download", { method: "POST", body: { key: show.key, season: S.season } }); return r; }, `Queued Season ${S.season}`);
  el.querySelectorAll("[data-act]").forEach((b) => (b.onclick = () => epAction(show, b.dataset.act, +b.dataset.ep, b.dataset.path)));
}
function epRow(show, e, playingPath) {
  const dl = e.target ? jobFor("download:" + e.target) : null;
  const sj = e.local ? activeJob("subs:" + e.local.path) : null;
  let state;
  if (e.local && sj) state = `<span class="state busy">${ICON.cc} ${esc(shortMsg(sj))}</span>`;
  else if (e.local) state = `<span class="state local">${ICON.check} On this Mac</span>`;
  else if (dl && (dl.status === "running" || dl.status === "queued")) state = `<span class="state busy">${dl.status === "queued" ? "Queued" : `<span class="mini"><i style="width:${(dl.progress || 0) * 100}%"></i></span> ${Math.round((dl.progress || 0) * 100)}%`}</span>`;
  else if (dl && dl.status === "failed") state = `<span class="state err" title="${esc(dl.message)}">Download failed</span>`;
  else state = `<span class="state remote">On Drive</span>`;
  const p = e.local ? esc(e.local.path) : "";
  const acts = e.local
    ? `<button class="btn small primary" data-act="play" data-ep="${e.episode}" data-path="${p}">${ICON.play} Play</button>
       <button class="btn icon ghost" title="Subtitles" data-act="subs" data-ep="${e.episode}" data-path="${p}">${ICON.cc}</button>
       <button class="btn icon ghost" title="Show in folder" data-act="reveal" data-ep="${e.episode}" data-path="${p}">${ICON.folder}</button>
       <button class="btn icon ghost danger" title="Delete from this Mac" data-act="delete" data-ep="${e.episode}" data-path="${p}" ${e.remote ? "" : "disabled"}>${ICON.trash}</button>`
    : dl && (dl.status === "running" || dl.status === "queued")
      ? `<button class="btn small ghost" data-act="cancel" data-ep="${e.episode}" data-path="${dl.id}">${ICON.x} Cancel</button>`
      : `<button class="btn small" data-act="download" data-ep="${e.episode}">${ICON.down} Download</button>`;
  return `<div class="ep ${e.local && e.local.path === playingPath ? "playing" : ""}"><span class="code">${esc(e.code)}</span>
    <span class="t">${e.title ? esc(e.title) : `<em>Episode ${e.episode}</em>`}</span>${state}<span class="acts">${acts}</span></div>`;
}
const shortMsg = (j) => (j.status === "queued" ? "Subtitles queued" : j.progress != null && j.progress > 0 && j.progress < 1 ? `${j.message.split("·")[0].trim()} ${Math.round(j.progress * 100)}%` : j.message).slice(0, 34);
async function epAction(show, what, ep, path) {
  if (what === "play") return act(() => api("/api/play", { method: "POST", body: { path } }));
  if (what === "download") return act(() => api("/api/download", { method: "POST", body: { key: show.key, season: S.season, episode: ep } }), "Download queued");
  if (what === "cancel") return act(() => api(`/api/jobs/${path}/cancel`, { method: "POST" }), "Cancelled");
  if (what === "reveal") return act(() => api("/api/reveal", { method: "POST", body: { path } }));
  if (what === "subs") { S.video = path; S.results = null; return go("subtitles"); }
  if (what === "delete") {
    const row = document.querySelector(`[data-act=delete][data-ep="${ep}"]`);
    if (row.dataset.armed) { await act(() => api("/api/file", { method: "DELETE", body: { path } }), "Moved to the Trash"); return loadLibrary(); }
    row.dataset.armed = "1"; row.innerHTML = "Delete?"; row.classList.add("small");
    setTimeout(() => { if (row.isConnected) { delete row.dataset.armed; row.innerHTML = ICON.trash; } }, 3000);
  }
}

// ---- subtitles ----------------------------------------------------------------------------
async function loadVideos() {
  S.videos = await act(() => api("/api/videos")) || [];
  if (!S.video && S.videos.length) S.video = (S.auto.now && S.auto.now.path && S.videos.find((v) => v.path === S.auto.now.path) || S.videos[0]).path;
  if (S.video) loadVideoInfo();
  renderSubtitles();
}
async function loadVideoInfo() {
  const path = S.video;
  try { const info = await api("/api/subtitles?path=" + encodeURIComponent(path)); if (path === S.video) { S.vinfo = info; renderSubtitles(); } }
  catch (e) { S.vinfo = null; }
}
function renderSubtitles() {
  const el = $("#page-subtitles");
  if (!S.videos.length) {
    el.innerHTML = `<div class="empty"><h2>No episodes on this Mac yet</h2><p>Download an episode from the Library and its subtitles are handled here.</p><button class="btn primary" onclick="go('library')">Go to Library</button></div>`;
    return;
  }
  const f = S.vfilter.toLowerCase();
  const list = S.videos.filter((v) => !f || `${v.series} ${v.code} ${v.title}`.toLowerCase().includes(f)).map((v) => `
    <button class="vitem ${v.path === S.video ? "active" : ""}" data-v="${esc(v.path)}"><span><span class="c">${esc(v.code)}</span>${esc(v.title || v.series)}</span><span class="s">${esc(v.series)}</span></button>`).join("");
  const v = S.videos.find((x) => x.path === S.video);
  const info = S.vinfo;
  const job = v && jobFor("subs:" + v.path);
  const busy = job && (job.status === "running" || job.status === "queued");
  let detail = "";
  if (v) {
    const tracks = info ? [
      ...info.embedded.map((t) => `<span class="state local">${ICON.check} Inside the file${t.ours ? " (Upnext)" : t.title ? ` · ${esc(t.title)}` : ""}</span>`),
      info.sidecar ? `<span class="state local">${ICON.check} ${esc(info.sidecar.split("/").pop())}</span>` : "",
    ].join("") : "";
    const none = info && !info.embedded.length && !info.sidecar;
    detail = `
      <div class="card">
        <div class="card-head"><div><h2>${esc(v.series)} ${esc(v.code)}${v.title ? " · " + esc(v.title) : ""}</h2><p class="hint" style="word-break:break-all">${esc(v.path)}</p></div>
          <button class="btn primary" data-sa="auto" ${busy ? "disabled" : ""}>${ICON.cc} Fix automatically</button></div>
        <div class="tracks">${info ? (none ? `<span class="state remote">No English subtitles yet</span>` : tracks) : `<span class="state remote">Checking…</span>`}</div>
        ${job ? `<div class="job ${job.status}" style="padding:10px 12px"><span class="ic">${jobIcon(job)}</span><span class="jt">${esc(job.title)}</span><span>${busy ? `<button class="btn small ghost" data-cancel="${job.id}">Cancel</button>` : ""}</span><div class="jm">${progressBar(job)}<span>${esc(job.message)}</span></div></div>` : ""}
        <p class="hint">Fix automatically uses a subtitle already here if there is one, otherwise finds one online, syncs it to the speech, and falls back to generating one with Whisper. The result is saved next to the video and added inside it as the default English track.</p>
      </div>
      <div class="tools" style="margin-top:16px">
        <div class="tool"><h2>Sync to the audio</h2><p>For subtitles that start early or late, or drift. Matches them to when people actually speak.</p>
          <div class="inline">${info && info.embedded.length && !info.sidecar ? `<button class="btn" data-sa="sync" data-stream="${info.embedded[0].index}" ${busy ? "disabled" : ""}>Sync the track inside</button>` : `<button class="btn" data-sa="sync" ${busy || !(info && info.sidecar) ? "disabled" : ""}>Sync</button>`}</div></div>
        <div class="tool"><h2>Shift by hand</h2><p>Lines show up too early? Use a positive number to delay them.</p>
          <div class="shiftbox"><button class="btn small" data-nudge="-0.5">−0.5</button><input type="number" id="shiftSec" step="0.1" value="0" class="num"><button class="btn small" data-nudge="0.5">+0.5</button><button class="btn small" data-sa="shift" ${busy || none ? "disabled" : ""}>Apply</button></div></div>
        <div class="tool"><h2>Generate with Whisper</h2><p>Writes English subtitles from the audio on this Mac. Takes a few minutes, no internet needed.</p>
          <div class="inline"><button class="btn" data-sa="generate" ${busy ? "disabled" : ""}>Generate</button></div></div>
        <div class="tool"><h2>Put inside the file</h2><p>Embeds the .srt as the default English track, so it plays anywhere.</p>
          <div class="inline"><button class="btn" data-sa="embed" ${busy || !(info && info.sidecar && info.can_embed) ? "disabled" : ""}>Embed</button></div></div>
      </div>
      <div class="card" style="margin-top:16px">
        <div class="card-head"><div><h2>Pick from OpenSubtitles</h2><p class="hint">For when the automatic pick is the wrong episode or a bad translation.</p></div>
          <button class="btn" data-sa="search" ${S.searching ? "disabled" : ""}>${S.searching ? "Searching…" : "Search"}</button></div>
        ${S.results ? resultsTable(S.results, busy) : ""}
      </div>`;
  }
  el.innerHTML = `
    <div class="head"><div><h1>Subtitles</h1><p class="sub">Find, sync, fix or generate English subtitles</p></div></div>
    <div class="subs">
      <div><input type="text" id="vfilter" placeholder="Filter episodes" value="${esc(S.vfilter)}" style="width:100%;margin-bottom:10px"><div class="vlist">${list}</div></div>
      <div>${detail}</div>
    </div>`;
  const vf = $("#vfilter");
  vf.oninput = () => { S.vfilter = vf.value; renderSubtitles(); const n = $("#vfilter"); n.focus(); n.setSelectionRange(n.value.length, n.value.length); };
  el.querySelectorAll("[data-v]").forEach((b) => (b.onclick = () => { S.video = b.dataset.v; S.vinfo = null; S.results = null; renderSubtitles(); loadVideoInfo(); }));
  el.querySelectorAll("[data-nudge]").forEach((b) => (b.onclick = () => { const i = $("#shiftSec"); i.value = (Math.round((+i.value + +b.dataset.nudge) * 10) / 10).toFixed(1); }));
  el.querySelectorAll("[data-cancel]").forEach((b) => (b.onclick = () => act(() => api(`/api/jobs/${b.dataset.cancel}/cancel`, { method: "POST" }))));
  el.querySelectorAll("[data-sa]").forEach((b) => (b.onclick = () => subAction(b.dataset.sa, b)));
  el.querySelectorAll("[data-use]").forEach((b) => (b.onclick = () => subAction("fetch", b)));
}
function resultsTable(results, busy) {
  if (!results.results.length) return `<p class="hint">Nothing found for this episode.</p>`;
  const rows = results.results.map((r) => `<tr><td class="rel">${esc(r.release)}<div>${r.hash_match ? `<span class="tag good">Exact file match</span>` : ""}${r.trusted ? `<span class="tag">Trusted</span>` : ""}${r.hearing_impaired ? `<span class="tag">Hearing impaired</span>` : ""}</div></td>
    <td class="num">${r.downloads.toLocaleString()}</td><td><button class="btn small" data-use="${r.file_id}" data-hash="${r.hash_match ? 1 : ""}" ${busy || !results.has_key ? "disabled" : ""}>Use</button></td></tr>`).join("");
  return `${results.has_key ? "" : `<p class="hint">Add your free OpenSubtitles API key in <a href="#" onclick="go('settings');return false">Settings</a> to download these.</p>`}
    <div class="scroll-x"><table class="results"><thead><tr><th>Release</th><th>Downloads</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`;
}
async function subAction(what, btn) {
  const path = S.video;
  if (what === "search") {
    S.searching = true; renderSubtitles();
    try { S.results = await api("/api/subtitles/search?path=" + encodeURIComponent(path)); } catch (e) { toast(e.message, true); }
    S.searching = false; renderSubtitles();
    return;
  }
  const body = { path };
  if (what === "sync" && btn.dataset.stream) body.stream_index = +btn.dataset.stream;
  if (what === "shift") { body.seconds = +$("#shiftSec").value; if (!body.seconds) return toast("Enter how many seconds to shift", true); }
  if (what === "fetch") { body.file_id = +btn.dataset.use; body.hash_match = !!btn.dataset.hash; }
  await act(() => api(`/api/subtitles/${what}`, { method: "POST", body }), "Started. Progress shows here and in Activity");
}

// ---- activity ---------------------------------------------------------------------------------
const jobIcon = (j) => (j.status === "done" ? ICON.check : j.status === "failed" ? ICON.x : j.status === "cancelled" ? ICON.x : j.lane === "download" ? ICON.down : ICON.cc);
const progressBar = (j) => (j.status !== "running" ? "" : j.progress == null ? `<span class="bar indet"><i></i></span>` : `<span class="bar"><i style="width:${j.progress * 100}%"></i></span>`);
function renderActivity() {
  const el = $("#page-activity");
  const finished = S.jobs.some((j) => !["running", "queued"].includes(j.status));
  el.innerHTML = `<div class="head"><div><h1>Activity</h1><p class="sub">Downloads and subtitle work, running in the background</p></div>
      ${finished ? `<button class="btn ghost" id="clearJobs">Clear finished</button>` : ""}</div>
    ${S.jobs.length ? `<div class="jobs">${S.jobs.map((j) => `
      <div class="job ${j.status}"><span class="ic">${jobIcon(j)}</span><span class="jt">${esc(j.title)}</span>
        <span>${j.status === "running" || j.status === "queued" ? `<button class="btn small ghost" data-cancel="${j.id}">Cancel</button>` : ""}</span>
        <div class="jm">${progressBar(j)}<span title="${esc(j.detail || j.message)}">${j.status === "queued" ? "Waiting for its turn" : esc(j.message)}</span></div></div>`).join("")}</div>`
    : `<div class="empty"><h2>Nothing going on</h2><p>Downloads and subtitle jobs show up here while they run.</p></div>`}`;
  el.querySelectorAll("[data-cancel]").forEach((b) => (b.onclick = () => act(() => api(`/api/jobs/${b.dataset.cancel}/cancel`, { method: "POST" }))));
  const c = $("#clearJobs"); if (c) c.onclick = () => act(() => api("/api/jobs/clear", { method: "POST" }));
}

// ---- settings -----------------------------------------------------------------------------------
async function loadSettings() {
  const d = await act(() => api("/api/settings"));
  if (!d) return;
  S.settings = d.settings; S.drive = d.drive; S.tools = d.tools; S.sources = d.sources;
  renderSettings();
}
function renderSettings() {
  const el = $("#page-settings");
  const s = S.settings;
  if (!s) { el.innerHTML = ""; return; }
  const d = S.drive || {};
  const sources = s.sources.map((src) => {
    const info = S.sources.find((x) => x.folder_id === src.folder_id) || {};
    return `<div class="src"><div style="min-width:0"><div>${esc(src.name)}</div><div class="meta">${info.error ? `<span style="color:var(--err)">${esc(info.error)}</span>` : `${info.files ?? "…"} files · ${esc(src.folder_id)}`}</div></div>
      <button class="btn small ghost danger" data-rmsrc="${esc(src.folder_id)}">Remove</button></div>`;
  }).join("");
  const sw = (k, label, hint) => `<div class="row"><div><label class="lbl" for="s-${k}">${label}</label>${hint ? `<p class="hint">${hint}</p>` : ""}</div><label class="switch"><input type="checkbox" id="s-${k}" data-k="${k}" ${s[k] ? "checked" : ""}></label></div>`;
  const numr = (k, label, hint, unit) => `<div class="row"><div><label class="lbl" for="s-${k}">${label}</label>${hint ? `<p class="hint">${hint}</p>` : ""}</div><div class="inline"><input type="number" class="num" id="s-${k}" data-k="${k}" value="${s[k]}" min="0"><span class="hint">${unit}</span></div></div>`;
  const text = (k, label, hint, type = "text", ph = "") => `<div class="row"><div><label class="lbl" for="s-${k}">${label}</label>${hint ? `<p class="hint">${hint}</p>` : ""}</div><input type="${type}" id="s-${k}" data-k="${k}" value="${esc(s[k])}" placeholder="${esc(ph)}"></div>`;
  el.innerHTML = `<div class="settings">
    <div class="head"><div><h1>Settings</h1><p class="sub">Changes save as you make them</p></div></div>
    <div class="card"><div class="card-head"><h2>Google Drive</h2>
        <span class="hint"><span class="dot ${d.connected ? "ok" : "err"}"></span>${!d.installed ? "rclone isn't installed" : d.connected ? "Connected (read only)" : "Not connected"}</span></div>
      ${d.installed && !d.connected ? `<div class="inline"><button class="btn primary" id="connectDrive">Connect Google Drive</button><span class="hint">Opens your browser to sign in. Upnext only asks for read access.</span></div>` : ""}
      ${!d.installed ? `<p class="hint">Install rclone first: <code>brew install rclone</code> on a Mac, or from rclone.org on Windows and Linux.</p>` : ""}
      <div style="display:grid;gap:8px">${sources || `<p class="hint">No folders yet. Paste the link of a Drive folder that has your shows in it. Shared folders work too.</p>`}</div>
      <div class="inline"><input type="text" id="srcLink" placeholder="https://drive.google.com/drive/folders/…"><input type="text" id="srcName" placeholder="Name (optional)" style="flex:0 1 180px"><button class="btn" id="addSrc">Add folder</button></div>
    </div>
    <div class="card"><h2>Downloads</h2><div>
      ${text("download_dir", "Download folder", "Episodes go in Show / Season NN folders inside this. Episodes already in it show up in the Library.")}
      ${numr("prefetch_minutes", "Get the next episode early", "Start downloading the next episode when this much of the current one is left.", "min left")}
    </div></div>
    <div class="card"><h2>Playback</h2><div>
      ${sw("autoplay", "Play the next episode automatically", "Shows an Up Next countdown, then plays it in VLC.")}
      ${sw("detect_credits", "Show Up Next when the credits start", "Finds the black credits screen at the end of each episode. Otherwise Up Next shows in the last seconds.")}
      ${numr("countdown_seconds", "Countdown length", "", "seconds")}
      ${text("vlc_path", "VLC location", S.tools && S.tools.vlc ? `Found at ${esc(S.tools.vlc)}` : "VLC wasn't found. Install it from videolan.org or enter its path.", "text", "Found automatically")}
    </div></div>
    <div class="card"><h2>Subtitles</h2><div>
      ${sw("auto_subtitles", "Get English subtitles for every download", "Runs right after a download finishes.")}
      ${sw("generate_if_not_found", "Generate with Whisper when none are found", "Takes a few minutes per episode on this Mac.")}
      ${sw("embed_subtitles", "Put subtitles inside the video file", "MKV and MP4. The .srt next to the video is kept either way.")}
      ${text("opensubtitles_api_key", "OpenSubtitles API key", `Free, and needed to search and download. Make an account at <a href="https://www.opensubtitles.com/en/consumers" target="_blank" rel="noopener">opensubtitles.com/consumers</a> and create an API consumer. Without a key, Upnext generates subtitles with Whisper instead.`, "password", "Not set")}
      <div class="row"><div><label class="lbl" for="s-whisper_model">Whisper model</label><p class="hint">On an Apple Silicon Mac a 50 minute episode takes about 2 min with base, 5 with small and 10 with turbo. Other computers use the CPU and are several times slower.</p></div>
        <select id="s-whisper_model" data-k="whisper_model">${[["base", "base (fastest)"], ["small", "small (recommended)"], ["turbo", "turbo (most accurate)"]].map(([m, l]) => `<option value="${m}" ${s.whisper_model === m ? "selected" : ""}>${l}</option>`).join("")}</select></div>
    </div></div>
  </div>`;
  el.querySelectorAll("[data-k]").forEach((inp) => (inp.onchange = () => {
    const k = inp.dataset.k;
    const v = inp.type === "checkbox" ? inp.checked : inp.type === "number" ? +inp.value : inp.value;
    act(async () => { S.settings = { ...S.settings, ...(await api("/api/settings", { method: "PUT", body: { [k]: v } })) }; }, "Saved");
  }));
  el.querySelectorAll("[data-rmsrc]").forEach((b) => (b.onclick = () => act(async () => { await api(`/api/sources/${b.dataset.rmsrc}`, { method: "DELETE" }); await loadSettings(); }, "Folder removed")));
  $("#addSrc").onclick = () => act(async () => {
    const b = $("#addSrc"); b.disabled = true; b.textContent = "Checking…";
    try { await api("/api/sources", { method: "POST", body: { link: $("#srcLink").value, name: $("#srcName").value } }); await loadSettings(); setTimeout(loadLibrary, 500); }
    finally { if (b.isConnected) { b.disabled = false; b.textContent = "Add folder"; } }
  }, "Folder added. Reading it in the background");
  const cd = $("#connectDrive");
  if (cd) cd.onclick = () => act(async () => { cd.disabled = true; cd.textContent = "Waiting for the browser sign-in…"; await api("/api/drive/connect", { method: "POST" }); await loadSettings(); }, "Google Drive connected");
}

// ---- polling --------------------------------------------------------------------------------------
let lastDone = new Set(), libTick = 0, wasRefreshing = false;
async function poll() {
  try {
    const st = await api("/api/state");
    S.auto = st.autopilot; S.jobs = st.jobs;
    const done = new Set(st.jobs.filter((j) => j.status === "done").map((j) => j.id));
    const newlyDone = [...done].some((id) => !lastDone.has(id));
    lastDone = done;
    if (newlyDone || (wasRefreshing && !st.refreshing) || ++libTick % 15 === 0) { await loadLibrary(); if (newlyDone && S.page === "subtitles") { loadVideoInfo(); } }
    wasRefreshing = st.refreshing; S.refreshing = st.refreshing; renderFoot();
    renderNow();
    if (S.page === "library") renderLibraryLight();
    if (S.page === "activity") renderActivity();
    if (S.page === "subtitles") renderSubtitlesLight();
    const n = S.jobs.filter((j) => j.status === "running" || j.status === "queued").length;
    $("#activeCount").hidden = !n; $("#activeCount").textContent = n;
  } catch (e) { /* server restarting; try again */ }
  setTimeout(poll, 1000);
}
// Re-render only when something visible changed, so buttons don't flicker under the mouse
let libSig = "", subSig = "";
function renderLibraryLight() {
  const sig = JSON.stringify([S.jobs.map((j) => [j.key, j.status, Math.round((j.progress || 0) * 100), j.message]), S.auto.now && S.auto.now.path]);
  if (sig !== libSig) { libSig = sig; renderLibrary(); }
}
function renderSubtitlesLight() {
  if (document.activeElement && ["vfilter", "shiftSec"].includes(document.activeElement.id)) return;
  const j = S.video && jobFor("subs:" + S.video);
  const sig = JSON.stringify(j ? [j.status, Math.round((j.progress || 0) * 100), j.message] : null);
  if (sig !== subSig) { subSig = sig; renderSubtitles(); }
}

(async function boot() {
  let page = "library";
  try { page = localStorage.getItem("upnext.page") || "library"; } catch {}
  await act(async () => { const d = await api("/api/settings"); S.settings = d.settings; S.drive = d.drive; S.tools = d.tools; });
  await act(loadLibrary);
  go(page);
  poll();
})();
