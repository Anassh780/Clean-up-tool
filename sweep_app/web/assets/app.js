/* Sweep web UI — vanilla ES2020, no build step, no external requests. */
'use strict';

const TOKEN = document.querySelector('meta[name="sweep-token"]').content;
const VERSION = document.querySelector('meta[name="sweep-version"]').content;

/* ------------------------------------------------------------------ icons */
const P = 'fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"';
const ICONS = {
  grid: `<svg viewBox="0 0 24 24" ${P}><rect x="3" y="3" width="7" height="7" rx="1.6"/><rect x="14" y="3" width="7" height="7" rx="1.6"/><rect x="3" y="14" width="7" height="7" rx="1.6"/><rect x="14" y="14" width="7" height="7" rx="1.6"/></svg>`,
  broom: `<svg viewBox="0 0 24 24" ${P}><path d="M14 4l6 6"/><path d="M12.5 5.5l6 6"/><path d="M13 10l-7.5 7.5a2.1 2.1 0 0 0 3 3L16 13"/><path d="M7 17l3 3"/></svg>`,
  cpu: `<svg viewBox="0 0 24 24" ${P}><rect x="7" y="7" width="10" height="10" rx="2"/><rect x="4" y="4" width="16" height="16" rx="3"/><path d="M9 1v3M15 1v3M9 20v3M15 20v3M1 9h3M1 15h3M20 9h3M20 15h3"/></svg>`,
  'folder-minus': `<svg viewBox="0 0 24 24" ${P}><path d="M3 7.5A1.5 1.5 0 0 1 4.5 6h4l2 2.5h7A1.5 1.5 0 0 1 19 10v8a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 3 18V7.5Z"/><path d="M9 14h6"/></svg>`,
  search: `<svg viewBox="0 0 24 24" ${P}><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.2-3.2"/></svg>`,
  shield: `<svg viewBox="0 0 24 24" ${P}><path d="M12 3l7 3v6c0 4.2-2.9 7.4-7 9-4.1-1.6-7-4.8-7-9V6l7-3Z"/><path d="M9 12l2 2 4-4"/></svg>`,
  settings: `<svg viewBox="0 0 24 24" ${P}><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1 1.55V21a2 2 0 1 1-4 0v-.09a1.7 1.7 0 0 0-1.11-1.55 1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.7 1.7 0 0 0 .34-1.87 1.7 1.7 0 0 0-1.55-1H3a2 2 0 1 1 0-4h.09a1.7 1.7 0 0 0 1.55-1.11 1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.7 1.7 0 0 0 1.87.34H9a1.7 1.7 0 0 0 1-1.55V3a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1 1.55 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.7 1.7 0 0 0-.34 1.87V9a1.7 1.7 0 0 0 1.55 1H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.51 1Z"/></svg>`,
  refresh: `<svg viewBox="0 0 24 24" ${P}><path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/></svg>`,
  help: `<svg viewBox="0 0 24 24" ${P}><circle cx="12" cy="12" r="9"/><path d="M9.2 9.2a2.9 2.9 0 1 1 4.2 2.6c-.9.5-1.4 1-1.4 2.2"/><path d="M12 17h.01"/></svg>`,
  play: `<svg viewBox="0 0 24 24" ${P}><path d="M7 4.5l12 7.5-12 7.5v-15Z"/></svg>`,
  trash: `<svg viewBox="0 0 24 24" ${P}><path d="M4 7h16"/><path d="M10 4h4"/><path d="M6 7l1 13h10l1-13"/><path d="M10 11v6M14 11v6"/></svg>`,
  restore: `<svg viewBox="0 0 24 24" ${P}><path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v6h6"/></svg>`,
  x: `<svg viewBox="0 0 24 24" ${P}><path d="M6 6l12 12M18 6L6 18"/></svg>`,
  check: `<svg viewBox="0 0 24 24" ${P}><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>`,
  alert: `<svg viewBox="0 0 24 24" ${P}><path d="M12 3.5 22 20H2L12 3.5Z"/><path d="M12 9.5v4.5"/><path d="M12 17.2h.01"/></svg>`,
  info: `<svg viewBox="0 0 24 24" ${P}><circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><path d="M12 8h.01"/></svg>`,
  'chevron-right': `<svg viewBox="0 0 24 24" ${P}><path d="M9 6l6 6-6 6"/></svg>`,
  external: `<svg viewBox="0 0 24 24" ${P}><path d="M14 4h6v6"/><path d="M20 4l-8 8"/><path d="M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4"/></svg>`,
  zap: `<svg viewBox="0 0 24 24" ${P}><path d="M13 2 4 14h7l-1 8 9-12h-7l1-8Z"/></svg>`,
  drive: `<svg viewBox="0 0 24 24" ${P}><rect x="3" y="5" width="18" height="14" rx="2.5"/><path d="M3 13h18"/><path d="M7 16.5h.01M11 16.5h.01"/></svg>`,
  lock: `<svg viewBox="0 0 24 24" ${P}><rect x="4.5" y="10" width="15" height="10" rx="2.2"/><path d="M8 10V7.5a4 4 0 0 1 8 0V10"/></svg>`,
  database: `<svg viewBox="0 0 24 24" ${P}><ellipse cx="12" cy="6" rx="7.5" ry="3"/><path d="M4.5 6v6c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3V6"/><path d="M4.5 12v6c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3v-6"/></svg>`,
  folder: `<svg viewBox="0 0 24 24" ${P}><path d="M3 7.5A1.5 1.5 0 0 1 4.5 6h4l2 2.5h7A1.5 1.5 0 0 1 19 10v8a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 3 18V7.5Z"/></svg>`,
  clock: `<svg viewBox="0 0 24 24" ${P}><circle cx="12" cy="12" r="9"/><path d="M12 7v5.5l3.5 2"/></svg>`,
  server: `<svg viewBox="0 0 24 24" ${P}><rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 7.5h.01M7 16.5h.01"/></svg>`,
  package: `<svg viewBox="0 0 24 24" ${P}><path d="M12 3 21 7.5v9L12 21 3 16.5v-9L12 3Z"/><path d="M3 7.5l9 4.5 9-4.5"/><path d="M12 12v9"/></svg>`,
  sparkles: `<svg viewBox="0 0 24 24" ${P}><path d="M12 3l1.7 4.8L18.5 9.5l-4.8 1.7L12 16l-1.7-4.8L5.5 9.5l4.8-1.7L12 3Z"/><path d="M19 14l.8 2.2L22 17l-2.2.8L19 20l-.8-2.2L16 17l2.2-.8L19 14Z"/></svg>`,
  eye: `<svg viewBox="0 0 24 24" ${P}><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z"/><circle cx="12" cy="12" r="3"/></svg>`,
  power: `<svg viewBox="0 0 24 24" ${P}><path d="M12 3v9"/><path d="M6.3 6.3a8 8 0 1 0 11.4 0"/></svg>`,
  more: `<svg viewBox="0 0 24 24" ${P}><path d="M5 12h.01M12 12h.01M19 12h.01" stroke-width="2.6"/></svg>`,
  arrow: `<svg viewBox="0 0 24 24" ${P}><path d="M5 12h14"/><path d="M13 6l6 6-6 6"/></svg>`,
};

function icon(name) {
  return ICONS[name] || '';
}

/* ------------------------------------------------------------------ format */
const esc = (value) =>
  String(value ?? '').replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));

function fmtBytes(bytes) {
  const n = Number(bytes) || 0;
  if (n <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1; }
  const digits = v >= 100 || i === 0 ? 0 : v >= 10 ? 1 : 2;
  return `${v.toFixed(digits)} ${units[i]}`;
}
const fmtNum = (n) => Number(n || 0).toLocaleString('en-US');
function fmtAgo(ts) {
  if (!ts) return 'never';
  const diff = Date.now() / 1000 - Number(ts);
  if (diff < 45) return 'just now';
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return `${Math.round(diff / 86400)}d ago`;
}
const fmtClock = (ts) => new Date(Number(ts) * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

/* ------------------------------------------------------------------ state */
const S = {
  meta: null,
  junk: null,
  procs: null,
  leftovers: null,
  search: null,
  quarantine: null,
  activity: [],
  error: null,
  fatal: null,
  report: null,
  // {state, result} from GET /api/update. Kept separate from `meta` because it
  // is the one piece of the UI that can legitimately be unavailable.
  update: null,
};
const U = {
  route: 'dashboard',
  sel: { junk: new Set(), procs: new Set(), leftovers: new Set(), hits: new Set(), quarantine: new Set() },
  procFilter: 'all',
  procQuery: '',
  junkQuery: '',
  hitFilter: 'all',
  job: null,
  jobTimer: null,
  lastAction: null,
  busy: new Set(),
  // The dashboard banner is a nudge, not a modal: dismissing it lasts until
  // the page is reloaded and never suppresses the Settings card.
  updateDismissed: false,
  updateBusy: false,
  // {version, staged} for an archive verified during this session, so
  // "Install" does not download the same zip twice.
  updateStaged: null,
};

class ApiFailure extends Error {
  constructor(error) {
    super(error.message || 'Request failed');
    Object.assign(this, error);
    this.error = error;
  }
}

/* ------------------------------------------------------------------ api */
async function api(path, { method = 'GET', body } = {}) {
  let res;
  try {
    res = await fetch(path, {
      method,
      headers: { 'Content-Type': 'application/json', 'X-Sweep-Token': TOKEN },
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: 'same-origin',
    });
  } catch (cause) {
    throw new ApiFailure({
      code: 'server_unreachable',
      message: 'The Sweep server is not responding',
      reason: `The request to ${path} failed before an answer arrived (${cause.message}). The server may have stopped, or this tab is from an older session.`,
      hint: 'Check the console window running Sweep, then reload this page.',
    });
  }
  let payload = null;
  try { payload = await res.json(); } catch { /* handled below */ }
  if (!payload) {
    throw new ApiFailure({
      code: 'bad_response',
      message: 'The server sent an unreadable response',
      reason: `HTTP ${res.status} with a body that is not JSON.`,
      hint: 'Reload the page. If it repeats, check the server console for a traceback.',
    });
  }
  if (!res.ok || payload.ok === false) {
    throw new ApiFailure(payload.error || {
      code: `http_${res.status}`,
      message: `Request failed with HTTP ${res.status}`,
      reason: 'The server did not explain this failure.',
      hint: 'Check the server console.',
    });
  }
  return payload.data;
}

/* ------------------------------------------------------------------ toasts */
function toast({ kind = 'info', title, message = '', reason = '', hint = '', timeout }) {
  const host = document.getElementById('toasts');
  const el = document.createElement('div');
  el.className = `toast ${kind}`;
  el.setAttribute('role', kind === 'error' ? 'alert' : 'status');
  el.setAttribute('aria-atomic', 'true');
  el.innerHTML = `
    <span class="toast-icon">${icon(kind === 'error' ? 'alert' : kind === 'warn' ? 'alert' : kind === 'success' ? 'check' : 'info')}</span>
    <div class="toast-body">
      <div class="toast-title">${esc(title)}</div>
      ${message ? `<div class="toast-msg">${esc(message)}</div>` : ''}
      ${reason ? `<div class="toast-reason">${esc(reason)}</div>` : ''}
      ${hint ? `<div class="toast-hint">${esc(hint)}</div>` : ''}
    </div>
    <button class="toast-close" aria-label="Dismiss">×</button>`;
  const close = () => { el.style.opacity = '0'; el.style.transform = 'translateY(6px)'; setTimeout(() => el.remove(), 160); };
  el.querySelector('.toast-close').addEventListener('click', close);
  host.appendChild(el);
  const life = timeout ?? (kind === 'error' ? 14000 : kind === 'warn' ? 10000 : 6500);
  let remaining = life;
  let started = Date.now();
  let timer = setTimeout(close, life);
  const pause = () => { clearTimeout(timer); remaining -= Date.now() - started; };
  const resume = () => { started = Date.now(); clearTimeout(timer); timer = setTimeout(close, Math.max(1200, remaining)); };
  el.addEventListener('mouseenter', pause);
  el.addEventListener('mouseleave', resume);
  el.addEventListener('focusin', pause);
  el.addEventListener('focusout', resume);
  while (host.children.length > 4) host.firstElementChild.remove();
}

/* ------------------------------------------------------------------ modal */
function modal({ title, subtitle = '', iconName = 'info', danger = false, body = '', footer = '', width }) {
  const root = document.getElementById('modal-root');
  const previous = document.activeElement;
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  const titleId = `modal-title-${Math.random().toString(36).slice(2, 8)}`;
  overlay.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="${titleId}" tabindex="-1" ${width ? `style="width:${width}px"` : ''}>
      <div class="modal-head">
        <div class="modal-icon ${danger ? 'danger' : ''}">${icon(iconName)}</div>
        <div>
          <h2 class="modal-title" id="${titleId}">${esc(title)}</h2>
          ${subtitle ? `<div class="modal-sub">${esc(subtitle)}</div>` : ''}
        </div>
      </div>
      <div class="modal-body">${body}</div>
      <div class="modal-foot">${footer}</div>
    </div>`;
  root.appendChild(overlay);
  document.body.classList.add('modal-open');
  const inertTargets = [document.querySelector('.app'), document.querySelector('.mobilenav')].filter(Boolean);
  inertTargets.forEach((el) => { el.inert = true; });

  let resolveFn = null;
  const promise = new Promise((resolve) => { resolveFn = resolve; });
  const focusables = () => [...overlay.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')]
    .filter((el) => !el.disabled && el.getClientRects().length > 0);
  const onKey = (event) => {
    if (event.key === 'Escape') { event.preventDefault(); close(null); return; }
    if (event.key !== 'Tab') return;
    const items = focusables();
    const panel = overlay.querySelector('.modal');
    if (!items.length) { event.preventDefault(); panel?.focus(); return; }
    const first = items[0];
    const last = items[items.length - 1];
    if (event.shiftKey && (document.activeElement === first || document.activeElement === panel)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };
  const close = (value) => {
    overlay.remove();
    document.removeEventListener('keydown', onKey);
    if (!root.querySelector('.modal-overlay')) {
      document.body.classList.remove('modal-open');
      inertTargets.forEach((el) => { el.inert = false; });
    }
    if (previous instanceof HTMLElement && document.contains(previous)) previous.focus();
    resolveFn?.(value);
  };
  overlay.addEventListener('click', (event) => { if (event.target === overlay) close(null); });
  document.addEventListener('keydown', onKey);
  overlay.querySelectorAll('[data-modal-close]').forEach((btn) =>
    btn.addEventListener('click', () => close(btn.dataset.modalClose === 'confirm' ? true : null)));
  overlay._close = close;
  setTimeout(() => {
    if (overlay.contains(document.activeElement)) return;
    const items = focusables();
    (items.find((el) => el.id === 'confirm-word') || items[items.length - 1] || overlay.querySelector('.modal'))?.focus();
  }, 60);
  return { overlay, promise, close };
}

async function confirmAction({ title, subtitle = '', message = '', bullets = [], note = '', word = null, danger = true, confirmLabel = 'Confirm' }) {
  const body = `
    ${message ? `<p>${esc(message)}</p>` : ''}
    ${bullets.length ? `<ul>${bullets.map((b) => `<li>${esc(b)}</li>`).join('')}</ul>` : ''}
    ${note ? `<div class="modal-note">${note}</div>` : ''}
    ${word ? `
      <div class="field">
        <label class="field-label" for="confirm-word">Type <strong>${esc(word)}</strong> to confirm</label>
        <input class="input" id="confirm-word" autocomplete="off" spellcheck="false" placeholder="${esc(word)}" aria-describedby="confirm-word-hint">
        <div class="field-hint" id="confirm-word-hint">This action cannot be undone.</div>
      </div>` : ''}`;
  const handle = modal({
    title, subtitle, danger, iconName: danger ? 'alert' : 'shield', body,
    footer: `<button class="btn btn-ghost" data-modal-close="cancel">Cancel</button>
             <button class="btn ${danger ? 'btn-danger' : 'btn-primary'}" id="confirm-go" ${word ? 'disabled' : ''}>${esc(confirmLabel)}</button>`,
  });
  const go = handle.overlay.querySelector('#confirm-go');
  const input = handle.overlay.querySelector('#confirm-word');
  if (input) {
    input.addEventListener('input', () => { go.disabled = input.value.trim().toLowerCase() !== word.toLowerCase(); });
    setTimeout(() => input.focus(), 30);
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !go.disabled) handle.close(true); });
  }
  go.addEventListener('click', () => handle.close(true));
  const result = await handle.promise;
  return result === true;
}

/* ------------------------------------------------------------------ error UI */
function handleError(error) {
  const err = error?.error || error;
  S.error = {
    code: err.code || 'error',
    message: err.message || 'Something failed',
    reason: err.reason || '',
    hint: err.hint || '',
  };
  toast({ kind: 'error', title: S.error.message, reason: S.error.reason, hint: S.error.hint });
  render();
}

function bannerHtml() {
  if (!S.error) return '';
  return `
    <div class="banner" role="status" aria-live="polite">
      <span class="banner-icon">${icon('alert')}</span>
      <div class="banner-main">
        <div class="banner-title">${esc(S.error.message)}</div>
        ${S.error.reason ? `<div class="banner-reason">${esc(S.error.reason)}</div>` : ''}
        ${S.error.hint ? `<div class="banner-hint">${esc(S.error.hint)}</div>` : ''}
      </div>
      <div class="banner-actions">
        ${U.lastAction ? `<button class="btn btn-sm" data-action="retry">Retry</button>` : ''}
        <button class="btn btn-ghost btn-sm btn-icon" data-action="dismiss-error" aria-label="Dismiss">${icon('x')}</button>
      </div>
    </div>`;
}

/* ------------------------------------------------------------------ data */
async function refreshAll(onMeta) {
  const jobs = [
    api('/api/meta').then((v) => { S.meta = v; onMeta?.(); }).catch((e) => { S.fatal = S.fatal || e.error; }),
    api('/api/junk').then((v) => { S.junk = v; }).catch(() => {}),
    api('/api/procs').then((v) => { S.procs = v; }).catch(() => {}),
    api('/api/leftovers').then((v) => { S.leftovers = v; }).catch(() => {}),
    api('/api/search').then((v) => { S.search = v; }).catch(() => {}),
    api('/api/quarantine').then((v) => { S.quarantine = v; }).catch(() => {}),
    api('/api/activity?limit=12').then((v) => { S.activity = v; }).catch(() => {}),
    // Cheap and offline. A build without the endpoint leaves S.update null,
    // which the Settings card explains instead of treating as an error.
    api('/api/update').then((v) => { S.update = v; }).catch(() => {}),
  ];
  await Promise.allSettled(jobs);
  pruneSelections();
}

function pruneSelections() {
  if (S.junk) {
    const keys = new Set(S.junk.results.map((r) => r.key));
    U.sel.junk = new Set([...U.sel.junk].filter((k) => keys.has(k)));
  }
  if (S.procs) {
    const pids = new Set(S.procs.items.map((p) => String(p.pid)));
    U.sel.procs = new Set([...U.sel.procs].filter((p) => pids.has(p)));
  }
  if (S.leftovers) {
    const paths = new Set(S.leftovers.items.map((o) => o.path));
    U.sel.leftovers = new Set([...U.sel.leftovers].filter((p) => paths.has(p)));
  }
  if (S.search) {
    const ids = new Set(S.search.hits.map((h) => h.id));
    U.sel.hits = new Set([...U.sel.hits].filter((i) => ids.has(i)));
  }
  if (S.quarantine) {
    const ids = new Set(S.quarantine.batches.map((b) => b.id));
    U.sel.quarantine = new Set([...U.sel.quarantine].filter((i) => ids.has(i)));
  }
}

async function refreshData(keys) {
  const jobs = [];
  if (keys.includes('meta')) jobs.push(api('/api/meta').then((v) => { S.meta = v; }));
  if (keys.includes('junk')) jobs.push(api('/api/junk').then((v) => { S.junk = v; }));
  if (keys.includes('procs')) jobs.push(api('/api/procs').then((v) => { S.procs = v; }));
  if (keys.includes('leftovers')) jobs.push(api('/api/leftovers').then((v) => { S.leftovers = v; }));
  if (keys.includes('search')) jobs.push(api('/api/search').then((v) => { S.search = v; }));
  if (keys.includes('quarantine')) jobs.push(api('/api/quarantine').then((v) => { S.quarantine = v; }));
  if (keys.includes('activity')) jobs.push(api('/api/activity?limit=12').then((v) => { S.activity = v; }));
  if (keys.includes('update')) jobs.push(api('/api/update').then((v) => { S.update = v; }));
  await Promise.allSettled(jobs);
  pruneSelections();
}

/* ------------------------------------------------------------------ jobs */
async function launch(promise, options) {
  const job = await promise;
  U.job = job;
  renderJobBar();
  pollJob(job.id, options);
  return job;
}

async function pollJob(id, options) {
  clearTimeout(U.jobTimer);
  try {
    const job = await api(`/api/jobs/${id}`);
    U.job = job;
    renderJobBar();
    if (job.status === 'running' || job.status === 'queued') {
      U.jobTimer = setTimeout(() => pollJob(id, options), 450);
      return;
    }
    U.job = null;
    renderJobBar();
    if (job.status === 'error') {
      handleError(job.error);
      return;
    }
    if (job.status === 'cancelled') {
      toast({ kind: 'warn', title: 'Stopped', message: job.message || 'The job was cancelled.' });
    } else if (options?.onDone) {
      options.onDone(job.result, job);
    }
    await refreshData(options?.refresh || ['meta', 'activity']);
    render();
  } catch (error) {
    U.job = null;
    renderJobBar();
    handleError(error);
  }
}

function renderJobBar() {
  const bar = document.getElementById('jobbar');
  if (!U.job) {
    bar.hidden = true;
    sizeTallTables();
    return;
  }
  const job = U.job;
  bar.hidden = false;
  document.getElementById('job-title').textContent = job.title;
  document.getElementById('job-msg').textContent = job.message || job.phase || '';
  const fill = document.getElementById('job-fill');
  fill.style.width = `${job.percent || 0}%`;
  fill.setAttribute('aria-valuenow', String(Math.round(job.percent || 0)));
  document.getElementById('job-pct').textContent = `${Math.round(job.percent || 0)}%`;
  const cancel = bar.querySelector('[data-action="cancel-job"]');
  cancel.disabled = !(job.status === 'running' || job.status === 'queued');
  sizeTallTables();
}

async function cancelJob() {
  if (!U.job) return;
  try {
    await api(`/api/jobs/${U.job.id}/cancel`, { method: 'POST' });
  } catch (error) {
    handleError(error);
  }
}

async function post(path, body, options) {
  try {
    return await launch(api(path, { method: 'POST', body }), options);
  } catch (error) {
    if (error.code === 'confirmation_required') {
      const word = error.details?.word || 'confirm';
      const ok = await confirmAction({
        title: 'Confirm this action',
        message: error.message,
        bullets: [error.reason],
        note: error.hint ? esc(error.hint) : '',
        word,
        danger: true,
        confirmLabel: 'Confirm',
      });
      if (!ok) return null;
      try {
        return await launch(api(path, { method: 'POST', body: { ...body, confirm: word } }), options);
      } catch (retryError) {
        handleError(retryError);
        return null;
      }
    }
    handleError(error);
    return null;
  }
}

/* ------------------------------------------------------------------ pages */
function pageHead(title, sub, actions = '') {
  return `<div class="page-head"><div><h1>${esc(title)}</h1>${sub ? `<p class="page-sub">${sub}</p>` : ''}</div><div class="page-actions">${actions}</div></div>`;
}

function statStrip(items) {
  return `<div class="ledger">${items.map((it) => `<div class="item"><span class="v">${it.value}</span><span class="k">${esc(it.label)}</span></div>`).join('')}</div>`;
}

function actionBar(kind, { label, action, danger = false, extra = '' }) {
  return `<div class="actionbar" data-actionbar="${kind}" hidden>
    <span class="actionbar-count"><b data-sel-count="${kind}">0</b> selected</span>
    <span class="toolbar-spacer"></span>
    ${extra}
    <button class="btn btn-sm ${danger ? 'btn-danger-solid' : 'btn-primary'}" data-action="${action}" data-requires="${kind}" disabled>${label}</button>
  </div>`;
}

function emptyState(iconName, title, text, action = '') {
  return `<div class="empty"><div class="empty-icon">${icon(iconName)}</div><div class="empty-title">${esc(title)}</div><div class="empty-text">${esc(text)}</div>${action}</div>`;
}

function badge(text, kind = 'neutral') {
  return `<span class="badge badge-${kind}">${esc(text)}</span>`;
}

function riskBadge(risk) {
  return badge(risk, risk === 'safe' ? 'safe' : risk === 'caution' ? 'caution' : 'risky');
}

function statusBadge(row) {
  if (row.status === 'needs-admin') return badge('needs admin', 'admin');
  if (row.status === 'error') return `<span title="${esc(row.detail)}">${badge('error', 'bad')}</span>`;
  if (row.status === 'empty' || (!row.size && !row.items)) return badge('empty', 'neutral');
  return badge(`${fmtNum(row.files)} files`, 'neutral');
}

/* ---------- dashboard ---------- */
const ACTIVITY_ACTIONS = {
  scan: 'Junk scan',
  leftovers: 'Leftover scan',
  search: 'Program search',
  delete: 'Permanent delete',
  quarantine: 'Quarantined',
  restore: 'Restored',
  'purge-quarantine': 'Batch purged',
  'recycle-bin': 'Recycle Bin',
  mode: 'Safety mode',
  skip: 'Skipped',
  'registry-delete': 'Registry key removed',
  'service-delete': 'Service removed',
  'delete-failed': 'Delete failed',
  'quarantine-failed': 'Quarantine failed',
  'restore-failed': 'Restore failed',
};

function activityAction(a) {
  return ACTIVITY_ACTIONS[a.action] || String(a.action || '').replace(/-/g, ' ');
}

function activityDetail(a) {
  let text = String(a.detail || '');
  text = text.replace(/^web\s+/i, '');
  text = text.replace(/^junk scan:\s*(\d+)\s*bytes$/i, (m, n) => `${fmtBytes(Number(n))} measured`);
  text = text.replace(/^scan:\s*/i, '');
  text = text.replace(/^search\s+[“"](.+?)[”"]:\s*(\d+)\s*hits$/i, (m, q, n) => `“${q}” · ${fmtNum(Number(n))} hits`);
  text = text.replace(/^mode set to (\w+)$/i, (m, mode) => (mode === 'permanent' ? 'Permanent delete enabled' : 'Quarantine enabled'));
  text = text.replace(/(\d+)\s*bytes/gi, (m, n) => fmtBytes(Number(n)));
  return text;
}

function viewDashboard() {
  const m = S.meta;
  const junk = S.junk;
  const q = S.quarantine;
  const totals = junk?.totals || { bytes: 0, files: 0, categories: 0, total_categories: 0 };
  const neverScanned = !junk?.scanned_at;
  const free = m.drives.reduce((a, d) => a + d.free, 0);
  const used = m.drives.reduce((a, d) => a + d.total, 0);
  const idle = m.procs.summary.idle || 0;

  const byRisk = { safe: 0, caution: 0, risky: 0 };
  (junk?.results || []).forEach((r) => { if (r.size) byRisk[r.risk] = (byRisk[r.risk] || 0) + r.size; });
  const riskTotal = byRisk.safe + byRisk.caution + byRisk.risky;
  const RISK = [
    ['safe', 'Safe', 'var(--accent)'],
    ['caution', 'Review first', 'var(--warn)'],
    ['risky', 'Risky', 'var(--bad)'],
  ];
  const segments = RISK.filter(([k]) => byRisk[k] > 0)
    .map(([k, , color]) => `<span class="composition-seg" style="width:${((byRisk[k] / riskTotal) * 100).toFixed(2)}%;background:${color}"></span>`).join('');
  const legend = RISK.filter(([k]) => byRisk[k] > 0)
    .map(([k, label, color]) => `<span class="legend-item"><i class="legend-dot" style="background:${color}"></i>${label} <b>${fmtBytes(byRisk[k])}</b></span>`).join('');

  const [num, unit] = fmtBytes(totals.bytes).split(' ');
  const value = neverScanned
    ? `<span class="hero-value is-empty">—</span>`
    : `<span class="hero-value" data-hero-bytes="${totals.bytes}"><span class="hero-num">${num}</span><span class="unit">${unit || ''}</span></span>`;

  const sub = neverScanned
    ? 'A scan is read-only. Sweep walks the known cache locations, measures them, and reports what can go — nothing is changed.'
    : `<strong>${fmtNum(totals.files)} files</strong> across ${totals.categories} of ${totals.total_categories} categories · measured ${fmtAgo(junk.scanned_at)}`;

  const heroMain = neverScanned ? `
      <div class="hero-main">
        <div class="hero-label"><span class="pulse"></span>First run</div>
        <h2 class="hero-title">Measure first. Remove only what you choose.</h2>
        <p class="hero-sub">${sub}</p>
        <ol class="steps">
          <li><span class="step-n">01</span><span class="step-body"><b>Scan</b><span>18 categories · about 30 seconds</span></span></li>
          <li><span class="step-n">02</span><span class="step-body"><b>Review</b><span>Every category labelled safe, review or risky</span></span></li>
          <li><span class="step-n">03</span><span class="step-body"><b>Clean</b><span>Quarantine by default — restore any time</span></span></li>
        </ol>
        <div class="hero-actions">
          <button class="btn btn-primary" data-action="junk-scan">${icon('play')}Scan junk files</button>
          <button class="btn" data-action="open-help">${icon('help')}How Sweep decides</button>
          <span class="hero-hint"><kbd>2</kbd> junk · <kbd>?</kbd> help</span>
        </div>
      </div>` : `
      <div class="hero-main">
        <div class="hero-label"><span class="pulse"></span>Reclaimable now</div>
        ${value}
        <p class="hero-sub">${sub}</p>
        <div class="hero-actions">
          <button class="btn btn-primary" data-action="junk-scan">${icon('refresh')}Rescan junk</button>
          <button class="btn" data-action="nav" data-route="junk">Review categories</button>
          <span class="hero-hint"><kbd>2</kbd> junk · <kbd>?</kbd> help</span>
        </div>
        ${riskTotal > 0 ? `<div class="composition">
          <div class="composition-top"><span class="composition-label">Composition by risk</span><span class="composition-label">${fmtBytes(riskTotal)}</span></div>
          <div class="composition-bar" role="img" aria-label="Junk by risk">${segments}</div>
          <div class="composition-legend">${legend}</div>
        </div>` : ''}
      </div>`;

  const hero = `
    <section class="hero" aria-label="Reclaimable space">
      ${heroMain}
      <aside class="panel" aria-label="Drive capacity">
        <div class="panel-head"><span class="panel-title">${icon('drive')}Capacity</span><span class="mono dim" style="font-size:10px">${m.drives.length} volume${m.drives.length === 1 ? '' : 's'}</span></div>
        <div class="panel-body">
          ${m.drives.length ? m.drives.map((d) => {
            const cls = d.percent >= 90 ? 'bad' : d.percent >= 75 ? 'warn' : '';
            return `<div class="drive">
              <div class="drive-head"><span class="drive-name">${icon('drive')}${esc(d.letter)}</span><span class="drive-meta">${fmtBytes(d.free)} free · ${d.percent}%</span></div>
              <div class="drive-bar" role="img" aria-label="${esc(d.letter)} ${d.percent}% used"><div class="drive-fill ${cls}" style="width:${Math.min(100, d.percent)}%"></div></div>
            </div>`;
          }).join('') : `<p class="muted" style="font-size:12px">No fixed drives detected.</p>`}
        </div>
        <div class="panel-foot">
          <span class="capacity-total"><span class="k">Free of ${fmtBytes(used)}</span><span class="v">${fmtBytes(free)}</span></span>
          <button class="btn btn-ghost btn-sm" data-action="refresh-all" aria-label="Refresh capacity">${icon('refresh')}</button>
        </div>
      </aside>
    </section>`;

  const activity = (S.activity || []).length
    ? `<div class="timeline">${S.activity.map((a) => `
        <div class="tl-item">
          <span class="tl-dot ${a.ok ? '' : 'err'}"></span>
          <div class="tl-body"><div class="tl-action">${esc(activityAction(a))}</div><div class="tl-detail" title="${esc(a.detail)}">${esc(activityDetail(a))}</div></div>
          <span class="tl-time">${esc((a.time || '').slice(11, 16))}</span>
        </div>`).join('')}</div>`
    : emptyState('clock', 'No activity yet', 'Scans, cleanups and restores appear here as they happen.');

  const system = `
    <dl class="kv">
      <dt>Idle processes</dt><dd>${fmtNum(idle)} <span class="dim">of ${fmtNum(m.procs.total)}</span></dd>
      <dt>In quarantine</dt><dd>${fmtBytes(q?.total_bytes || 0)} <span class="dim">· ${fmtNum(q?.batches?.length || 0)} batches</span></dd>
      <dt>Safety mode</dt><dd class="${m.mode === 'permanent' ? 'val-warn' : 'val-good'}">${m.mode === 'permanent' ? 'Permanent delete' : 'Quarantine'}</dd>
      <dt>Elevation</dt><dd class="${m.admin ? 'val-good' : 'val-warn'}">${m.admin ? 'Administrator' : 'Standard user'}</dd>
      <dt>Version</dt><dd>${esc(m.app.version)}</dd>
    </dl>`;

  return `${updateBannerHtml()}${pageHead('Dashboard', 'What can go, what should stay, and how much you get back.')}
    ${hero}
    <div class="dash-grid">
      <section aria-label="Recent activity">
        <div class="section-head"><span class="section-title">${icon('clock')}Recent activity</span><a class="section-link" data-action="nav" data-route="quarantine">Quarantine ${icon('chevron-right')}</a></div>
        ${activity}
      </section>
      <section aria-label="System status">
        <div class="section-head"><span class="section-title">${icon('shield')}System</span><a class="section-link" data-action="nav" data-route="settings">Settings ${icon('chevron-right')}</a></div>
        <div style="padding-top:4px">${system}</div>
      </section>
    </div>`;
}

/* ---------- junk ---------- */
function failureReport() {
  const report = S.report;
  if (!report || !report.failed) return '';
  const seen = new Set();
  const details = [];
  for (const entry of report.errors || []) {
    for (const detail of entry.details || []) {
      if (!detail.path || seen.has(detail.path)) continue;
      seen.add(detail.path);
      details.push(detail);
    }
  }
  if (!details.length) {
    for (const entry of report.errors || []) {
      if (!entry.path || seen.has(entry.path)) continue;
      seen.add(entry.path);
      details.push({ path: entry.path, short: entry.short || entry.reason });
    }
  }
  const count = details.length || report.failed;
  const noun = count === 1 ? 'file' : 'files';
  const rows = details.slice(0, 40).map((detail) => `
    <li><code class="report-path">${esc(detail.path)}</code><span class="report-why">${esc(detail.short || detail.reason)}</span></li>`).join('');
  return `<section class="report" role="status" aria-live="polite">
    <div class="report-head">
      <span class="report-icon">${icon('alert')}</span>
      <div class="report-copy">
        <div class="report-title">${fmtNum(count)} ${noun} could not be moved</div>
        <div class="report-sub">${details.length ? 'They are open in another process. Close it and retry, or leave these categories alone — nothing else was touched.' : 'Windows refused the move. The reason for each item is below.'}</div>
        ${report.errors?.[0]?.hint ? `<div class="report-hint">${esc(report.errors[0].hint)}</div>` : ''}
      </div>
      <button class="btn btn-ghost btn-icon btn-sm" data-action="dismiss-report" aria-label="Dismiss this report">${icon('x')}</button>
    </div>
    ${rows ? `<ul class="report-list">${rows}</ul>` : ''}
    ${details.length > 40 ? `<div class="report-more">…and ${fmtNum(details.length - 40)} more</div>` : ''}
  </section>`;
}

function viewJunk() {
  const data = S.junk || { results: [], totals: { bytes: 0, files: 0, categories: 0, total_categories: 0 }, scanned_at: 0 };
  const q = U.junkQuery.toLowerCase();
  const rows = data.results.filter((r) => !q || `${r.title} ${r.blurb}`.toLowerCase().includes(q));
  const selected = U.sel.junk.size;
  const never = !data.scanned_at;
  const adminBytes = data.results.filter((r) => r.status === 'needs-admin').reduce((a, r) => a + r.size, 0);

  const table = rows.length ? `
    <div class="table-wrap tall">
      <table class="data">
        <thead><tr>
          <th class="col-check"><input type="checkbox" data-check-all="junk" aria-label="Select all categories"></th>
          <th style="width:46%">Category</th><th class="num">Size</th><th class="num">Files</th><th>Status</th>
        </tr></thead>
        <tbody>${rows.map((r) => `
          <tr data-row="junk" data-key="${esc(r.key)}" class="${U.sel.junk.has(r.key) ? 'is-selected' : ''}">
            <td class="col-check"><input type="checkbox" data-check="junk" data-id="${esc(r.key)}" ${U.sel.junk.has(r.key) ? 'checked' : ''} aria-label="Select ${esc(r.title)}"></td>
            <td class="cell-title">
              <div class="row-title">${esc(r.title)}${riskBadge(r.risk)}${r.note ? `<span title="${esc(r.note)}" class="dim" style="cursor:help">${icon('info')}</span>` : ''}</div>
              <div class="row-sub" title="${esc(r.blurb)}">${esc(r.blurb)}</div>
            </td>
            <td class="cell-meta num" data-label="Size">${fmtBytes(r.size)}</td>
            <td class="cell-meta num" data-label="Files">${fmtNum(r.files)}</td>
            <td class="cell-status">${r.status === 'needs-admin' ? badge('needs admin', 'admin') : r.status === 'error' ? `<span title="${esc(r.detail)}">${badge('error', 'bad')}</span>` : !r.size ? badge('empty', 'neutral') : badge('ready', 'good')}</td>
          </tr>`).join('')}
        </tbody>
      </table>
    </div>` : emptyState('search', 'No categories match that filter', 'Clear the search box to see all categories again.');

  const headActions = never
    ? `<button class="btn btn-primary" data-action="junk-scan">${icon('play')}Scan junk files</button>`
    : `<button class="btn" data-action="junk-safe">${icon('check')}Select safe</button>
       <button class="btn" data-action="junk-clear" ${selected ? '' : 'disabled'}>Clear</button>
       <button class="btn btn-danger" data-action="junk-clean" ${selected ? '' : 'disabled'}>${icon('trash')}Clean selected<span class="nav-count" data-count="junk">${selected}</span></button>`;

  return `${pageHead('Junk files', 'Temp, caches, logs and Windows leftovers — measured before anything is touched.', headActions)}
    ${never ? '' : statStrip([
      { value: fmtBytes(data.totals.bytes), label: 'reclaimable' },
      ...(adminBytes ? [{ value: fmtBytes(adminBytes), label: 'needs admin' }] : []),
      { value: fmtNum(data.totals.files), label: 'files' },
      { value: `${data.totals.categories}/${data.totals.total_categories}`, label: 'categories' },
      { value: data.scanned_at ? fmtAgo(data.scanned_at) : 'never', label: 'last scan' },
    ])}
    ${data.stale ? `<div class="banner banner-info" role="status">
      <span class="banner-icon">${icon('info')}</span>
      <div class="banner-main">
        <div class="banner-title">These sizes are out of date</div>
        <div class="banner-reason">You restored files after this scan, so the numbers below no longer match the disk.</div>
      </div>
      <div class="banner-actions"><button class="btn btn-sm" data-action="junk-scan">Rescan</button></div>
    </div>` : ''}
    ${failureReport()}
    <div class="toolbar">
      <div class="search-input">${icon('search')}<input class="input" id="junk-filter" placeholder="Filter categories…" value="${esc(U.junkQuery)}" aria-label="Filter categories"><kbd>/</kbd></div>
      <div class="toolbar-spacer"></div>
      <span class="toolbar-note">${S.meta?.mode === 'permanent' ? 'Permanent delete is on — files are not kept.' : 'Quarantine is on — every removal can be restored.'}</span>
      ${never ? '' : `<button class="btn btn-ghost btn-sm" data-action="junk-scan">${icon('refresh')}Rescan</button>`}
    </div>
    ${never ? emptyState('broom', 'Nothing measured yet', 'A scan walks the known cache locations, measures them and reports what can go. It does not change anything.', `<button class="btn btn-primary" data-action="junk-scan">${icon('play')}Scan junk files</button>`) : table}
    <p class="note">${icon('info')}Files in use are skipped and reported with the reason. Categories marked “needs admin” require Sweep to run as administrator.</p>
    ${actionBar('junk', { label: `${icon('trash')}Clean`, action: 'junk-clean', danger: true, extra: `<button class="btn btn-sm btn-ghost" data-action="junk-clear">Clear</button>` })}`;
}

/* ---------- processes ---------- */
const PROC_ORDER = { idle: 0, linked: 1, tray: 2, active: 3, service: 4, system: 5, locked: 6 };
const PROC_LABEL = { idle: 'Idle', active: 'Active', tray: 'Tray', service: 'Service', system: 'Windows', windows: 'Windows', linked: 'In use', locked: 'Locked' };
const PROC_BADGE = { idle: 'idle', active: 'good', tray: 'caution', service: 'info', system: 'neutral', windows: 'neutral', linked: 'info', locked: 'neutral' };

function viewProcesses() {
  const data = S.procs || { items: [], summary: {}, collected_at: 0 };
  const summary = data.summary || {};
  const counts = {
    all: data.items.length,
    idle: summary.idle || 0,
    active: summary.active || 0,
    tray: summary.tray || 0,
    linked: summary.linked || 0,
    locked: summary.locked || 0,
    service: summary.service || 0,
    system: summary.system || summary.windows || 0,
  };
  const filtered = data.items
    .filter((p) => (U.procFilter === 'all' ? true : p.group === U.procFilter))
    .filter((p) => !U.procQuery || `${p.name} ${p.exe} ${p.pid}`.toLowerCase().includes(U.procQuery.toLowerCase()))
    .sort((a, b) => (PROC_ORDER[a.group] ?? 9) - (PROC_ORDER[b.group] ?? 9) || b.rss - a.rss);

  const selected = U.sel.procs.size;
  const chip = (key, label, count) => `<button class="chip ${U.procFilter === key ? 'active' : ''}" data-action="proc-filter" data-filter="${key}" data-focus-key="chip:${key}" aria-pressed="${U.procFilter === key}">${label}<span class="n">${fmtNum(count)}</span></button>`;

  const rows = filtered.map((p) => `
    <tr data-row="procs" data-pid="${p.pid}" class="${U.sel.procs.has(String(p.pid)) ? 'is-selected' : ''}">
      <td class="col-check"><input type="checkbox" data-check="procs" data-id="${p.pid}" ${U.sel.procs.has(String(p.pid)) ? 'checked' : ''} ${p.killable ? '' : 'disabled'} aria-label="Select ${esc(p.name)}"></td>
      <td class="cell-title">
        <div class="row-title">${esc(p.name)}<span class="badge badge-${PROC_BADGE[p.group] || 'neutral'}">${esc(PROC_LABEL[p.group] || p.state)}</span></div>
        <div class="row-sub" title="${esc(p.exe)}">${esc(p.exe || '—')}</div>
      </td>
      <td class="cell-meta num" data-label="PID"><span class="mono-sm">${p.pid}</span></td>
      <td class="cell-meta num" data-label="RAM">${fmtBytes(p.rss)}</td>
      <td class="cell-meta num" data-label="CPU">${p.cpu.toFixed(1)}%</td>
      <td class="cell-meta num" data-label="Win">${p.visible_windows || p.hidden_windows ? `${p.visible_windows}/${p.hidden_windows}` : '—'}</td>
    </tr>`).join('');

  const table = filtered.length ? `
    <div class="table-wrap tall">
      <table class="data">
        <thead><tr><th class="col-check"><input type="checkbox" data-check-all="procs" aria-label="Select all processes"></th>
        <th style="width:46%">Process</th><th class="num">PID</th><th class="num">RAM</th><th class="num">CPU</th><th class="num" title="Visible / hidden windows">Win</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>` : emptyState('cpu', 'No processes in this filter', U.procFilter === 'idle' ? 'Idle means a third-party app with no window, no tray presence and no protected parent — that is what Sweep can safely stop.' : 'Try another filter.');

  return `${pageHead('Processes', 'Windows images, visible windows and tray apps are never auto-killed.',
    `<button class="btn" data-action="procs-idle" ${counts.idle ? '' : 'disabled'}>${icon('check')}Select idle</button>
     <button class="btn hide-sm" data-action="procs-clear" ${selected ? '' : 'disabled'}>Clear</button>
     <button class="btn btn-danger" data-action="procs-kill" ${selected ? '' : 'disabled'}>${icon('power')}Stop selected<span class="nav-count" data-count="procs">${selected}</span></button>`)}
    ${statStrip([
      { value: fmtNum(summary.idle || 0), label: 'idle' },
      { value: fmtNum(summary.active || 0), label: 'active' },
      { value: fmtNum(summary.tray || 0), label: 'tray' },
      { value: fmtNum(summary.locked || 0), label: 'locked' },
      { value: fmtNum(data.items.length), label: 'total' },
      { value: data.collected_at ? fmtAgo(data.collected_at) : 'never', label: 'last read' },
    ])}
    <div class="toolbar">
      <div class="chips">
        ${chip('all', 'All', counts.all)}${chip('idle', 'Idle', counts.idle)}${chip('active', 'Active', counts.active)}${chip('tray', 'Tray', counts.tray)}${chip('linked', 'In use', counts.linked)}${chip('locked', 'Locked', counts.locked)}${chip('service', 'Service', counts.service)}${chip('system', 'Windows', counts.system)}
      </div>
    </div>
    <div class="toolbar">
      <div class="search-input">${icon('search')}<input class="input" id="proc-filter" placeholder="Filter by name or PID…" value="${esc(U.procQuery)}" aria-label="Filter processes"><kbd>/</kbd></div>
      <div class="toolbar-spacer"></div>
      <span class="toolbar-note">${fmtNum(summary.idle || 0)} idle · nothing is stopped without your selection</span>
    </div>
    ${data.items.length ? table : emptyState('cpu', 'Reading processes…', 'This takes a few seconds. Press Refresh if nothing appears.', `<button class="btn btn-primary" data-action="procs-refresh">${icon('refresh')}Refresh</button>`)}
    ${actionBar('procs', { label: `${icon('power')}Stop`, action: 'procs-kill', danger: true, extra: `<button class="btn btn-sm btn-ghost" data-action="procs-clear">Clear</button>` })}`;
}

/* ---------- leftovers ---------- */
function viewLeftovers() {
  const data = S.leftovers || { items: [], scanned_at: 0, total_bytes: 0 };
  const items = data.items;
  const selected = U.sel.leftovers.size;
  const totalSelected = items.filter((o) => U.sel.leftovers.has(o.path)).reduce((a, o) => a + o.size, 0);

  const table = items.length ? `
    <div class="table-wrap tall">
      <table class="data">
        <thead><tr><th class="col-check"><input type="checkbox" data-check-all="leftovers" aria-label="Select all folders"></th>
        <th style="width:34%">Folder</th><th>Location</th><th class="num">Size</th><th class="num">Files</th><th>Last used</th><th>Why</th></tr></thead>
        <tbody>${items.map((o) => `
          <tr data-row="leftovers" data-path="${esc(o.path)}" class="${U.sel.leftovers.has(o.path) ? 'is-selected' : ''}">
            <td class="col-check"><input type="checkbox" data-check="leftovers" data-id="${esc(o.path)}" ${U.sel.leftovers.has(o.path) ? 'checked' : ''} aria-label="Select ${esc(o.name)}"></td>
            <td class="cell-title">
              <div class="row-title">${esc(o.name)}${o.confidence === 'orphan' ? badge('orphan', 'bad') : badge('suspect', 'caution')}</div>
              <div class="row-sub" title="${esc(o.path)}">${esc(o.path)}</div>
            </td>
            <td class="cell-meta tight muted" data-label="Location">${esc(o.root)}</td>
            <td class="cell-meta num" data-label="Size">${fmtBytes(o.size)}</td>
            <td class="cell-meta num" data-label="Files">${fmtNum(o.files)}</td>
            <td class="cell-meta tight muted" data-label="Last used">${esc(o.last_used)}</td>
            <td class="cell-wide"><span class="row-sub" style="max-width:300px" title="${esc(o.reason)}">${esc(o.reason)}</span></td>
          </tr>`).join('')}
        </tbody>
      </table>
    </div>` : emptyState('folder-minus', 'No stale leftovers', 'Every folder in AppData, ProgramData and Program Files belongs to an installed program — or was used in the last three weeks, so Sweep leaves it alone.');

  return `${pageHead('Uninstall leftovers', 'Folders no installed program claims and nothing has touched for three weeks.',
    `<button class="btn ${data.scanned_at ? '' : 'btn-primary'}" data-action="leftovers-scan">${icon(data.scanned_at ? 'refresh' : 'play')}${data.scanned_at ? 'Rescan' : 'Scan now'}</button>
     <button class="btn" data-action="leftovers-orphans" ${items.length ? '' : 'disabled'}>Select orphans</button>
     <button class="btn hide-sm" data-action="leftovers-clear" ${selected ? '' : 'disabled'}>Clear</button>
     <button class="btn btn-danger" data-action="leftovers-remove" ${selected ? '' : 'disabled'}>${icon('trash')}Remove<span class="nav-count" data-count="leftovers">${selected}</span></button>`)}
    ${statStrip([
      { value: fmtNum(items.length), label: 'candidates' },
      { value: fmtBytes(data.total_bytes), label: 'total size' },
      { value: fmtBytes(totalSelected), label: 'selected' },
      { value: data.scanned_at ? fmtAgo(data.scanned_at) : 'never', label: 'last scan' },
    ])}
    ${failureReport()}
    ${table}
    <p class="note">${icon('info')}A folder qualifies only when the registry, Program Files, Start Menu shortcuts and publisher metadata all fail to explain it — and its last write is older than three weeks. Removal goes to quarantine.</p>
    ${actionBar('leftovers', { label: `${icon('trash')}Remove`, action: 'leftovers-remove', danger: true, extra: `<button class="btn btn-sm btn-ghost" data-action="leftovers-clear">Clear</button>` })}`;
}

/* ---------- remover ---------- */
function viewRemover() {
  const data = S.search || { query: '', hits: [], meta: {}, searched_at: 0 };
  const hits = data.hits.filter((h) => U.hitFilter === 'all' || h.kind === U.hitFilter);
  const selected = U.sel.hits.size;
  const selectedSize = data.hits.filter((h) => U.sel.hits.has(h.id)).reduce((a, h) => a + h.size, 0);
  const kinds = ['all', 'folder', 'file', 'registry', 'service'];
  const counts = kinds.reduce((acc, k) => ({ ...acc, [k]: k === 'all' ? data.hits.length : data.hits.filter((h) => h.kind === k).length }), {});
  const meta = data.meta || {};
  const warnings = (meta.warnings || []).map((w) => `<div class="banner banner-warn" role="status">
      <span class="banner-icon">${icon('alert')}</span>
      <div class="banner-main"><div class="banner-title">${esc(w.source)} results are incomplete</div>
      <div class="banner-reason">${esc(w.reason)}</div><div class="banner-hint">${esc(w.hint)}</div></div></div>`).join('');

  const table = hits.length ? `
    <div class="table-wrap tall">
      <table class="data">
        <thead><tr><th class="col-check"><input type="checkbox" data-check-all="hits" aria-label="Select all matches"></th>
        <th style="width:40%">Match</th><th>Kind</th><th class="num">Size</th><th>Age</th></tr></thead>
        <tbody>${hits.map((h) => `
          <tr data-row="hits" data-id="${h.id}" class="${U.sel.hits.has(h.id) ? 'is-selected' : ''}">
            <td class="col-check"><input type="checkbox" data-check="hits" data-id="${h.id}" ${U.sel.hits.has(h.id) ? 'checked' : ''} aria-label="Select ${esc(h.name)}"></td>
            <td class="cell-title">
              <div class="row-title">${esc(h.name)}</div>
              ${h.extra ? `<div class="row-sub">${esc(h.extra)}</div>` : ''}
              <span class="path" title="${esc(h.path)}">${esc(h.path)}</span>
            </td>
            <td class="cell-status">${badge(h.kind_label, h.kind === 'registry' ? 'admin' : h.kind === 'service' ? 'info' : h.kind === 'folder' ? 'caution' : 'neutral')}</td>
            <td class="cell-meta num" data-label="Size">${h.size ? fmtBytes(h.size) : '—'}</td>
            <td class="cell-meta tight muted" data-label="Age">${esc(h.age)}</td>
          </tr>`).join('')}
        </tbody>
      </table>
    </div>` : emptyState('search', 'No matches', `Nothing on this PC matches “${data.query || ''}”. Try a shorter name, or switch on registry and services.`);

  const searched = Boolean(data.searched_at);
  return `${pageHead('Program remover', 'Type a name. Sweep searches every fixed drive — hidden and system paths included.',
    `${searched ? `<button class="btn btn-danger" data-action="hits-remove" ${selected ? '' : 'disabled'}>${icon('trash')}Remove selected<span class="nav-count" data-count="hits">${selected}</span></button>` : ''}`)}
    <div class="search-panel">
      <div class="search-panel-row">
        <div class="search-input search-big">${icon('search')}
          <input class="input mono" id="search-query" placeholder="e.g. Lightworks, Steam" value="${esc(data.query || '')}" autocomplete="off" spellcheck="false" aria-label="Program name">
          <kbd>Enter</kbd>
        </div>
        <button class="btn btn-primary" data-action="search-run">${icon('search')}Search</button>
      </div>
      <div class="search-panel-foot">
        <label class="switch-row"><span class="switch"><input type="checkbox" id="opt-registry" ${meta.registry ? 'checked' : ''}><span class="switch-track"></span></span><span class="switch-label">Registry keys <strong>${meta.registry ? 'on' : 'off'}</strong></span></label>
        <label class="switch-row"><span class="switch"><input type="checkbox" id="opt-services" ${meta.services ? 'checked' : ''}><span class="switch-track"></span></span><span class="switch-label">Windows services <strong>${meta.services ? 'on' : 'off'}</strong></span></label>
        <span class="toolbar-note">Registry keys are backed up before they are touched.</span>
      </div>
    </div>
    ${warnings}
    ${searched ? statStrip([
      { value: fmtNum(data.hits.length), label: 'matches' },
      { value: fmtNum(meta.scanned || 0), label: 'folders scanned' },
      { value: `${meta.elapsed || 0}s`, label: 'elapsed' },
      { value: fmtBytes(selectedSize), label: 'selected' },
      { value: data.searched_at ? fmtAgo(data.searched_at) : 'never', label: 'searched' },
    ]) : ''}
    ${searched ? `<div class="toolbar"><div class="chips">${kinds.map((k) => `<button class="chip ${U.hitFilter === k ? 'active' : ''}" data-action="hit-filter" data-filter="${k}" data-focus-key="hit:${k}" aria-pressed="${U.hitFilter === k}">${k === 'all' ? 'All' : k[0].toUpperCase() + k.slice(1)}<span class="n">${fmtNum(counts[k])}</span></button>`).join('')}</div>
      ${meta.truncated ? `<span class="badge badge-caution">stopped at 400 matches</span>` : ''}</div>` : ''}
    ${searched ? table : emptyState('search', 'Search for a program', 'Sweep looks for folders, files, registry keys and services on every fixed drive. Nothing is deleted until you pick it.', `<button class="btn" data-action="search-focus">Focus search</button>`)}
    ${searched ? actionBar('hits', { label: `${icon('trash')}Remove`, action: 'hits-remove', danger: true }) : ''}`;
}

/* ---------- quarantine ---------- */
function viewQuarantine() {
  const data = S.quarantine || { batches: [], total_bytes: 0, total_items: 0 };
  const selected = U.sel.quarantine.size;
  const selectedSize = data.batches.filter((b) => U.sel.quarantine.has(b.id)).reduce((a, b) => a + b.size, 0);
  const table = data.batches.length ? `
    <div class="table-wrap tall">
      <table class="data">
        <thead><tr><th class="col-check"><input type="checkbox" data-check-all="quarantine" aria-label="Select all batches"></th>
        <th style="width:30%">Batch</th><th>Created</th><th class="num">Items</th><th class="num">Size</th><th>Note</th></tr></thead>
        <tbody>${data.batches.map((b) => `
          <tr data-row="quarantine" data-id="${esc(b.id)}" class="${U.sel.quarantine.has(b.id) ? 'is-selected' : ''}">
            <td class="col-check"><input type="checkbox" data-check="quarantine" data-id="${esc(b.id)}" ${U.sel.quarantine.has(b.id) ? 'checked' : ''} aria-label="Select batch ${esc(b.id)}"></td>
            <td class="cell-title"><div class="row-title mono">${esc(b.id)}</div></td>
            <td class="cell-meta tight muted" data-label="Created">${esc(b.created_label)}</td>
            <td class="cell-meta num" data-label="Items">${fmtNum(b.items)}</td>
            <td class="cell-meta num" data-label="Size">${fmtBytes(b.size)}</td>
            <td class="cell-wide"><span class="row-sub" title="${esc(b.note)}">${esc(b.note || '—')}</span></td>
          </tr>`).join('')}
        </tbody>
      </table>
    </div>` : emptyState('shield', 'Quarantine is empty', 'Anything Sweep removes lands here first, on the same drive it came from. Restore it, or purge it when you are sure.');

  return `${pageHead('Quarantine', 'Removed files wait here, on the drive they came from. Restore or purge them.',
    `<button class="btn hide-sm" data-action="q-open">${icon('folder')}Open folder</button>
     <button class="btn" data-action="q-restore" ${selected ? '' : 'disabled'}>${icon('restore')}Restore<span class="nav-count" data-count="quarantine">${selected}</span></button>
     <button class="btn btn-danger" data-action="q-purge" ${selected ? '' : 'disabled'}>${icon('trash')}Purge selected</button>
     <button class="btn btn-danger" data-action="q-empty" ${data.batches.length ? '' : 'disabled'}>Empty all</button>`)}
    ${statStrip([
      { value: fmtBytes(data.total_bytes), label: 'held' },
      { value: fmtNum(data.total_items), label: 'items' },
      { value: fmtNum(data.batches.length), label: 'batches' },
      { value: fmtBytes(selectedSize), label: 'selected' },
    ])}
    ${table}
    <p class="note">${icon('info')}Restoring puts every file back at its original path. Purging deletes the batch for good; Sweep asks you to type a word first.</p>
    ${actionBar('quarantine', { label: `${icon('restore')}Restore`, action: 'q-restore', extra: `<button class="btn btn-sm btn-danger" data-action="q-purge" data-requires="quarantine" disabled>Purge</button>` })}`;
}

/* ---------- updates ---------- */
// The update API has two shapes: `state` (a cheap, offline settings snapshot)
// and `result` (the last CheckResult, possibly cached from a previous session).
// Neither is guaranteed: a build without the endpoint renders a disabled card
// rather than pretending updates work.
const UPDATE_STATUS_BADGE = {
  available: ['available', 'good'],
  up_to_date: ['up to date', 'good'],
  disabled: ['off', 'neutral'],
  unconfigured: ['no source', 'caution'],
  error: ['check failed', 'bad'],
  skipped: ['skipped', 'neutral'],
};

function updateStateData() {
  return S.update?.state || null;
}

function updateResult() {
  if (!S.update) return null;
  return S.update.result || S.update.state?.last_result || null;
}

function updateVersion(result, state) {
  return result?.release?.version || result?.latest || state?.current || VERSION;
}

// The version to nudge about. A skipped version is still installable from
// Settings, but it stops driving the banner and the sidebar badge.
function pendingUpdate() {
  const result = updateResult();
  if (!result || result.status !== 'available') return null;
  const state = updateStateData();
  const latest = result.latest || result.release?.version || '';
  if (state?.skipped && latest && state.skipped === latest) return null;
  return result;
}

function updateInstallLabel(state) {
  if (!state) return 'unknown';
  if (state.install === 'frozen') return 'standalone build';
  if (state.install === 'source') return 'source checkout';
  return 'unknown';
}

function updateStatusHtml() {
  const state = updateStateData();
  if (!S.update) {
    return `<div class="update-status" aria-live="polite">
      <div class="update-status-head"><span class="update-status-title">Updates are unavailable in this build</span></div>
      <p class="update-status-text">This copy of Sweep does not expose the update API, so it cannot check for a newer version. Rebuild it from the current source to turn updates on.</p>
    </div>`;
  }
  if (U.updateBusy) {
    return `<div class="update-status is-checking" aria-live="polite">
      <div class="update-status-head"><span class="spinner" aria-hidden="true"></span><span class="update-status-title">Checking for updates…</span></div>
      <p class="update-status-text">Reading ${esc(state?.manifest_url || 'the release manifest')}. This is the only request Sweep makes without being asked to install something.</p>
    </div>`;
  }
  const result = updateResult();
  if (!result && state && !state.configured) {
    return `<div class="update-status" aria-live="polite">
      <div class="update-status-head"><span class="update-status-title">No update source yet</span>${badge('no source', 'caution')}</div>
      <p class="update-status-text">This build has no source to read, so Sweep cannot look for a release until one is set.</p>
    </div>`;
  }
  if (!result) {
    return `<div class="update-status" aria-live="polite">
      <div class="update-status-head"><span class="update-status-title">Not checked yet</span></div>
      <p class="update-status-text">Sweep has not looked for a newer version on this PC. A check is one request for a small JSON file — nothing about you or this machine is sent.</p>
      <div class="update-actions"><button type="button" class="btn btn-sm" data-action="update-check" ${state ? '' : 'disabled'}>${icon('refresh')}Check now</button></div>
    </div>`;
  }

  const version = updateVersion(result, state);
  const current = result.current || state?.current || VERSION;
  const [label, kind] = UPDATE_STATUS_BADGE[result.status] || [result.status, 'neutral'];
  const head = (title) => `<div class="update-status-head"><span class="update-status-title">${title}</span>${badge(label, kind)}</div>`;

  if (result.status === 'available') {
    const release = result.release || {};
    const notes = release.notes
      ? `<details class="update-notes"><summary>What is new in Sweep ${esc(version)}</summary><div class="update-notes-body">${esc(release.notes)}</div></details>`
      : '';
    const details = [
      release.size ? fmtBytes(release.size) : '',
      release.released ? `released ${String(release.released).slice(0, 10)}` : '',
      release.channel ? `${release.channel} channel` : '',
    ].filter(Boolean).join(' · ');
    const canApply = !state || state.can_apply !== false;
    return `<div class="update-status available" aria-live="polite">
      ${head(`Sweep ${esc(version)} is available`)}
      <p class="update-status-text">You have <strong>${esc(current)}</strong>${details ? ` · ${esc(details)}` : ''}.</p>
      ${result.hint ? `<p class="update-status-hint">${esc(result.hint)}</p>` : ''}
      ${notes}
      ${canApply ? '' : `<p class="update-status-hint">This copy cannot replace itself: ${esc(state?.install === 'frozen' ? 'a standalone build needs a folder you can write to.' : 'the Sweep folder is read-only for this user.')} Install the release by hand instead.</p>`}
      <div class="update-actions">
        <button type="button" class="btn btn-primary btn-sm" data-action="update-install" ${canApply ? '' : 'disabled'}>${icon('package')}Download &amp; install</button>
        <button type="button" class="btn btn-sm" data-action="update-download" ${canApply ? '' : 'disabled'}>Download only</button>
        <button type="button" class="btn btn-ghost btn-sm" data-action="update-dismiss">Later</button>
        <button type="button" class="btn btn-ghost btn-sm" data-action="update-skip">Skip this version</button>
      </div>
    </div>`;
  }

  if (result.status === 'up_to_date') {
    return `<div class="update-status" aria-live="polite">
      ${head('Sweep is up to date')}
      <p class="update-status-text">${esc(result.message || `You have ${current}, the newest ${state?.channel || 'stable'} release.`)}</p>
      ${result.hint ? `<p class="update-status-hint">${esc(result.hint)}</p>` : ''}
      <div class="update-actions"><button type="button" class="btn btn-sm" data-action="update-check">${icon('refresh')}Check again</button></div>
    </div>`;
  }

  if (result.status === 'disabled') {
    return `<div class="update-status" aria-live="polite">
      ${head('Automatic update checks are off')}
      <p class="update-status-text">${esc(result.message || 'Sweep will not contact an update server while this is off.')}</p>
      ${result.hint ? `<p class="update-status-hint">${esc(result.hint)}</p>` : ''}
      <div class="update-actions"><button type="button" class="btn btn-sm" data-action="update-enable" data-enabled="true">Turn checks on</button></div>
    </div>`;
  }

  if (result.status === 'unconfigured') {
    return `<div class="update-status" aria-live="polite">
      ${head('No update source yet')}
      <p class="update-status-text">${esc(result.message || 'This build does not know where its releases live, so it cannot tell whether a newer version exists.')}</p>
      ${result.hint ? `<p class="update-status-hint">${esc(result.hint)}</p>` : ''}
    </div>`;
  }

  if (result.status === 'error') {
    return `<div class="update-status error" aria-live="polite">
      ${head('Could not check for updates')}
      <p class="update-status-text">${esc(result.message || 'The update check failed.')}</p>
      ${result.reason ? `<p class="update-status-reason">${esc(result.reason)}</p>` : ''}
      ${result.hint ? `<p class="update-status-hint">${esc(result.hint)}</p>` : ''}
      <div class="update-actions"><button type="button" class="btn btn-sm" data-action="update-check">${icon('refresh')}Retry</button></div>
    </div>`;
  }

  if (result.status === 'skipped') {
    const canApply = !state || state.can_apply !== false;
    return `<div class="update-status" aria-live="polite">
      ${head(`Sweep ${esc(version)} was skipped`)}
      <p class="update-status-text">${esc(result.message || 'Sweep will not offer this version again.')} It is still installable here whenever you are ready.</p>
      <div class="update-actions">
        ${canApply ? `<button type="button" class="btn btn-primary btn-sm" data-action="update-install">${icon('package')}Install update</button>` : ''}
        <button type="button" class="btn btn-sm" data-action="update-check">${icon('refresh')}Check for newer</button>
      </div>
    </div>`;
  }

  return `<div class="update-status" aria-live="polite">
    ${head(esc(result.message || 'Update status unknown'))}
    <p class="update-status-text">${esc(result.reason || result.hint || 'Sweep did not explain this result.')}</p>
    <div class="update-actions"><button type="button" class="btn btn-sm" data-action="update-check">${icon('refresh')}Check now</button></div>
  </div>`;
}

function updateSectionHtml() {
  const state = updateStateData();
  const enabled = state ? Boolean(state.enabled) : false;
  const channel = state?.channel === 'beta' ? 'beta' : 'stable';
  const configured = Boolean(state?.configured);
  const available = pendingUpdate();
  const current = state?.current || updateResult()?.current || VERSION;
  const last = state?.last_check || updateResult()?.checked_at || 0;
  const canApply = !state || state.can_apply !== false;
  return `
    <section class="setting-section setting-section-wide" aria-labelledby="updates-title">
      <div>
        <h3 id="updates-title">${icon('package')}Updates</h3>
        <p>Check for a newer Sweep, verify it and replace this copy in place. Nothing is downloaded or installed until you ask.</p>
        <div class="update-card">
          ${updateStatusHtml()}
          <dl class="update-meta">
            <div><dt>Current version</dt><dd>${esc(current)}</dd></div>
            <div><dt>Install type</dt><dd>${esc(updateInstallLabel(state))}</dd></div>
            <div><dt>Last checked</dt><dd>${esc(last ? fmtAgo(last) : 'never')}</dd></div>
          </dl>
          <div class="update-controls">
            <div class="update-control-row">
              <span class="update-control-label" id="update-channel-label">Release channel</span>
              <div class="seg" role="group" aria-labelledby="update-channel-label">
                <button type="button" class="seg-option ${channel === 'stable' ? 'active' : ''}" data-action="update-channel" data-channel="stable" aria-pressed="${channel === 'stable'}" ${state ? '' : 'disabled'}>Stable</button>
                <button type="button" class="seg-option ${channel === 'beta' ? 'active' : ''}" data-action="update-channel" data-channel="beta" aria-pressed="${channel === 'beta'}" ${state ? '' : 'disabled'}>Beta</button>
              </div>
            </div>
            <div class="update-control-row">
              <span class="update-control-label" id="update-auto-label">Check for updates automatically</span>
              <button type="button" class="update-switch" role="switch" aria-checked="${enabled}" aria-labelledby="update-auto-label" data-action="update-enable" ${state ? '' : 'disabled'}>
                <span class="update-switch-track" aria-hidden="true"></span><span>${enabled ? 'On' : 'Off'}</span>
              </button>
            </div>
            <div class="update-source">
              <label for="update-source">Update source</label>
              <div class="update-source-row">
                <input class="input mono" id="update-source" type="url" inputmode="url" autocomplete="off" spellcheck="false" placeholder="latest.json address" value="${esc(state?.manifest_url || '')}" aria-describedby="update-source-hint" ${state ? '' : 'disabled'}>
                <button type="button" class="btn btn-sm" data-action="update-save-source" ${state ? '' : 'disabled'}>Save</button>
              </div>
              <div class="update-hint" id="update-source-hint">${configured ? 'Where Sweep reads latest.json. Clear it and save to stop all checks.' : 'No source is configured in this build. Paste a latest.json URL, or read docs/RELEASING.md.'}</div>
            </div>
            ${!configured && state ? `<div class="update-callout" role="status">This build has no update source yet, so it cannot look for releases. Paste the address of a <code>latest.json</code> manifest above and press Save — <code>docs/RELEASING.md</code> explains how a release publishes one. Until then, Sweep makes no outbound request at all.</div>` : ''}
            <div class="update-actions">
              <button type="button" class="btn btn-sm" data-action="update-check" ${state ? '' : 'disabled'}>${icon('refresh')}Check now</button>
              ${available ? `<button type="button" class="btn btn-primary btn-sm" data-action="update-install" ${canApply ? '' : 'disabled'}>${icon('package')}Install update</button>` : ''}
              <button type="button" class="btn btn-ghost btn-sm" data-action="update-cleanup" ${state ? '' : 'disabled'}>${icon('trash')}Clean up downloads</button>
            </div>
          </div>
        </div>
      </div>
    </section>`;
}

function updateBannerHtml() {
  if (U.updateDismissed) return '';
  const result = pendingUpdate();
  if (!result) return '';
  const state = updateStateData();
  const latest = updateVersion(result, state);
  const current = result.current || state?.current || VERSION;
  return `<div class="update-banner" role="status">
    <span class="update-banner-icon" aria-hidden="true">${icon('package')}</span>
    <span class="update-banner-text"><strong>Sweep ${esc(latest)} is available</strong> — you have ${esc(current)}.</span>
    <button type="button" class="btn btn-sm" data-action="nav" data-route="settings">See update</button>
    <button type="button" class="btn btn-ghost btn-icon btn-sm" data-action="update-dismiss" aria-label="Dismiss update notice">${icon('x')}</button>
  </div>`;
}

/* ---------- settings ---------- */
function viewSettings() {
  const m = S.meta;
  const permanent = m.mode === 'permanent';
  const upd = updateStateData();
  return `${pageHead('Settings', 'Safety, updates, elevation and where Sweep keeps its data.')}
    <div class="settings">
      <section class="setting-section">
        <div>
          <h3>${icon('shield')}Safety mode</h3>
          <p>Quarantine moves files to a holding area on the same drive and keeps a manifest, so every removal can be restored. Permanent delete frees the space immediately and cannot be undone. This applies to both interfaces.</p>
        </div>
        <div class="setting-control">
          <div class="seg" role="group" aria-label="Removal mode">
            <button class="seg-option ${permanent ? '' : 'active'}" data-action="mode" data-mode="quarantine" aria-pressed="${!permanent}">${icon('shield')}Quarantine</button>
            <button class="seg-option ${permanent ? 'active danger' : ''}" data-action="mode" data-mode="permanent" aria-pressed="${permanent}">${icon('trash')}Permanent</button>
          </div>
          <div class="modal-note"><strong>${permanent ? 'Permanent delete is on.' : 'Quarantine is on.'}</strong> ${permanent ? 'Cleanups will not keep a copy; Sweep asks you to type “delete” before each one.' : 'Every cleanup can be undone from the Quarantine page.'}</div>
        </div>
      </section>

      ${updateSectionHtml()}

      <section class="setting-section">
        <div>
          <h3>${icon('lock')}Elevation</h3>
          <p>${m.admin ? 'Sweep has full access. Every category, including Windows.old and the Windows Update cache, can be cleaned.' : 'Some Windows locations are read-only for standard users. Windows temp, Prefetch, the Update cache, Windows.old and Windows logs need Administrator; those categories show “needs admin” and are skipped with a reason.'}</p>
        </div>
        <div class="setting-control">
          ${m.admin ? badge('administrator', 'good') : badge('standard user', 'caution')}
          ${m.admin ? '' : `<button class="btn" data-action="admin-help">${icon('lock')}How to elevate</button>`}
        </div>
      </section>

      <section class="setting-section setting-section-wide">
        <div>
          <h3>${icon('folder')}Data locations</h3>
          <p>Everything Sweep writes stays on this PC. Nothing is uploaded and there is no telemetry. The only optional outbound request is the update check above — plus the release download when you choose to install — and both can be turned off.</p>
          <dl class="setting-kv">
            <div><dt>Quarantine</dt><dd>${esc(m.paths.quarantine)}</dd></div>
            <div><dt>Logs</dt><dd>${esc(m.paths.logs)}</dd></div>
            <div><dt>Config</dt><dd>${esc(m.paths.config)}</dd></div>
            <div><dt>Temp folder</dt><dd>${esc(m.paths.temp)}</dd></div>
          </dl>
          <div class="toolbar" style="margin-top:14px;margin-bottom:0">
            <button class="btn btn-sm" data-action="open-path" data-path="${esc(m.paths.home)}">${icon('external')}Open data folder</button>
            <button class="btn btn-sm" data-action="open-path" data-path="${esc(m.paths.logs)}">${icon('external')}Open logs</button>
          </div>
        </div>
      </section>

      <section class="setting-section setting-section-wide">
        <div>
          <h3>${icon('info')}About</h3>
          <p>Sweep ${esc(m.app.version)} — local, portable, no telemetry. The only outbound request is an update check against the source below, and a release download only when you choose to install; both can be turned off.</p>
          <dl class="setting-kv">
            <div><dt>Version</dt><dd>${esc(m.app.version)}</dd></div>
            <div><dt>Install type</dt><dd>${esc(updateInstallLabel(upd))}</dd></div>
            <div><dt>Update source</dt><dd>${esc(upd?.manifest_url || 'not configured')}</dd></div>
            <div><dt>Update checks</dt><dd>${upd ? (upd.enabled ? 'on' : 'off') : 'unavailable'}</dd></div>
            <div><dt>Server started</dt><dd>${fmtClock(m.app.started)}</dd></div>
            <div><dt>Interface</dt><dd>Web · localhost only</dd></div>
            <div><dt>Network</dt><dd>${upd && upd.enabled && upd.configured ? 'optional update check' : 'none'}</dd></div>
          </dl>
        </div>
      </section>
    </div>`;
}

/* ------------------------------------------------------------------ render */
const PAGES = {
  dashboard: { title: 'Dashboard', view: viewDashboard },
  junk: { title: 'Junk files', view: viewJunk },
  processes: { title: 'Processes', view: viewProcesses },
  leftovers: { title: 'Leftovers', view: viewLeftovers },
  remover: { title: 'Program remover', view: viewRemover },
  quarantine: { title: 'Quarantine', view: viewQuarantine },
  settings: { title: 'Settings', view: viewSettings },
};

function currentRoute() {
  const hash = location.hash.replace(/^#\/?/, '');
  return PAGES[hash] ? hash : 'dashboard';
}

function render() {
  const route = currentRoute();
  const routeChanged = U.route !== route;
  U.route = route;
  document.querySelectorAll('[data-nav]').forEach((el) => {
    const active = el.dataset.nav === route;
    el.classList.toggle('active', active);
    if (active) el.setAttribute('aria-current', 'page'); else el.removeAttribute('aria-current');
  });
  const moreBtn = document.querySelector('.mobilenav [data-action="more"]');
  if (moreBtn) moreBtn.classList.toggle('active', ['leftovers', 'remover', 'settings'].includes(route));
  const page = PAGES[route];
  document.getElementById('crumb').textContent = page.title;
  document.title = `${page.title} — Sweep`;
  const view = document.getElementById('view');
  const active = document.activeElement;
  // `#view` itself is a focus target after navigation, not a control worth
  // restoring: treating it as one would block the Updates autofocus below.
  const focusKey = active && active !== view && view.contains(active)
    ? (active.dataset.focusKey
      || (active.dataset.action ? `action:${active.dataset.action}` : null)
      || (active.id ? `id:${active.id}` : null))
    : null;
  if (routeChanged) {
    view.classList.remove('view-in');
    void view.offsetWidth;
    view.classList.add('view-in');
  }
  if (!S.meta) {
    view.innerHTML = `<div class="skeleton"><div class="sk-row"></div><div class="sk-row"></div><div class="sk-row"></div><div class="sk-row"></div></div>`;
    return;
  }
  if (S.fatal) {
    view.innerHTML = `<div class="banner" style="margin:0">
      <span class="banner-icon">${icon('alert')}</span>
      <div class="banner-main"><div class="banner-title">Sweep could not load</div>
      <div class="banner-reason">${esc(S.fatal.reason || S.fatal.message || '')}</div>
      <div class="banner-hint">${esc(S.fatal.hint || 'Check that the server is still running, then reload.')}</div></div>
    </div>`;
    return;
  }
  view.innerHTML = `${bannerHtml()}${page.view()}`;
  enhanceTables(page.title);
  renderSidebar();
  syncAllCounts();
  animateHero();
  if (focusKey) {
    const selector = focusKey.startsWith('action:')
      ? `[data-action="${CSS.escape(focusKey.slice(7))}"]`
      : focusKey.startsWith('id:')
        ? `#${CSS.escape(focusKey.slice(3))}`
        : `[data-focus-key="${CSS.escape(focusKey)}"]`;
    view.querySelector(selector)?.focus({ preventScroll: true });
  } else if (routeChanged) {
    view.focus({ preventScroll: true });
    const status = document.getElementById('route-status');
    if (status) status.textContent = `${page.title} — Sweep`;
  }
  // A build with no update source has one obvious next action: paste the
  // manifest URL. Only do this when the render was not restoring a focus.
  if (!focusKey && route === 'settings') focusUpdateSourceIfNeeded();
  sizeTallTables();
  requestAnimationFrame(sizeTallTables);
}

function focusUpdateSourceIfNeeded() {
  const state = updateStateData();
  if (!state || state.configured) return;
  document.getElementById('update-source')?.focus({ preventScroll: true });
}

function sizeTallTables() {
  if (window.matchMedia('(max-width: 760px)').matches) {
    document.querySelectorAll('.table-wrap.tall').forEach((wrap) => { wrap.style.maxHeight = ''; });
    return;
  }
  const nav = document.querySelector('.mobilenav');
  const navHeight = nav && getComputedStyle(nav).display !== 'none' ? nav.offsetHeight : 0;
  document.querySelectorAll('.table-wrap.tall').forEach((wrap) => {
    let top = 0;
    for (let el = wrap; el; el = el.offsetParent) top += el.offsetTop;
    top -= window.scrollY;
    let max = Math.max(260, window.innerHeight - top - navHeight - 24);
    const table = wrap.querySelector('table');
    const head = table && table.querySelector('thead');
    if (head && table) {
      const headH = head.getBoundingClientRect().height;
      let used = headH;
      for (const row of table.querySelectorAll('tbody tr')) {
        const h = row.getBoundingClientRect().height;
        if (!h) continue;
        if (used + h + 2 > max) break;
        used += h;
      }
      if (used > headH) max = used + 2;
    }
    wrap.style.maxHeight = `${Math.round(max)}px`;
  });
}

function enhanceTables(pageTitle) {
  document.querySelectorAll('#view table.data').forEach((table) => {
    if (!table.querySelector('caption')) {
      const caption = document.createElement('caption');
      caption.className = 'sr-only';
      caption.textContent = `${pageTitle} — ${table.querySelectorAll('tbody tr').length} rows`;
      table.prepend(caption);
    }
    table.querySelectorAll('thead th').forEach((th) => { if (!th.hasAttribute('scope')) th.setAttribute('scope', 'col'); });
    table.querySelectorAll('tbody tr').forEach((tr) => {
      const first = tr.querySelector('td.cell-title, th.cell-title');
      if (first) first.setAttribute('role', 'rowheader');
      const firstMeta = tr.querySelector('td.cell-meta');
      if (firstMeta && !tr.querySelector('.row-break')) {
        firstMeta.insertAdjacentHTML('beforebegin', '<td class="row-break" aria-hidden="true"></td>');
      }
    });
  });
}

function animateHero() {
  const el = document.querySelector('[data-hero-bytes]');
  if (!el || !el.dataset.heroBytes) return;
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const target = Number(el.dataset.heroBytes);
  const numEl = el.querySelector('.hero-num');
  const unitEl = el.querySelector('.unit');
  if (!target || !numEl) return;
  const start = performance.now();
  const duration = 620;
  const tick = (now) => {
    const p = Math.min(1, (now - start) / duration);
    const eased = 1 - Math.pow(1 - p, 3);
    const [num, unit] = fmtBytes(target * eased).split(' ');
    numEl.textContent = num;
    if (unitEl) unitEl.textContent = unit || '';
    if (p < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

function renderSidebar() {
  const m = S.meta;
  if (!m) return;
  const adminDot = document.getElementById('admin-dot');
  const adminLabel = document.getElementById('admin-label');
  adminDot.className = `dot ${m.admin ? 'good' : 'warn'}`;
  adminLabel.textContent = m.admin ? 'Administrator' : 'Standard user';
  document.getElementById('mode-label').textContent = m.mode === 'permanent' ? 'Permanent delete mode' : 'Quarantine mode';
  const versionEl = document.getElementById('version-label');
  versionEl.textContent = `Sweep ${m.app.version}`;
  const pending = pendingUpdate();
  if (pending) {
    const badgeEl = document.createElement('span');
    badgeEl.className = 'update-badge';
    badgeEl.title = `Sweep ${updateVersion(pending, updateStateData())} is available`;
    badgeEl.textContent = 'update';
    versionEl.append(' ', badgeEl);
  }

  const counts = {
    junk: S.junk?.totals?.categories || 0,
    processes: m.procs.summary.idle || 0,
    leftovers: S.leftovers?.items?.length || 0,
    quarantine: S.quarantine?.batches?.length || 0,
  };
  document.querySelectorAll('[data-nav-count]').forEach((el) => {
    const value = counts[el.dataset.navCount] || 0;
    el.hidden = !value;
    el.textContent = value;
  });
}

function syncAllCounts() {
  ['junk', 'procs', 'leftovers', 'hits', 'quarantine'].forEach((kind) => {
    const size = U.sel[kind].size;
    document.querySelectorAll(`[data-count="${kind}"]`).forEach((el) => {
      el.textContent = size;
      el.hidden = size === 0;
    });
    document.querySelectorAll(`[data-sel-count="${kind}"]`).forEach((el) => { el.textContent = size; });
    document.querySelectorAll(`[data-actionbar="${kind}"]`).forEach((bar) => { bar.hidden = size === 0; });
    document.querySelectorAll(`[data-requires="${kind}"]`).forEach((btn) => { btn.disabled = size === 0; });
  });
}

/* ------------------------------------------------------------------ events */
function navigate(route) {
  location.hash = `#/${route}`;
  render();
}

document.addEventListener('click', async (event) => {
  const target = event.target.closest('[data-action]');
  if (!target) return;
  const action = target.dataset.action;
  try {
    await handleAction(action, target);
  } catch (error) {
    handleError(error);
  }
});

async function handleAction(action, el) {
  switch (action) {
    case 'nav':
      navigate(el.dataset.route);
      break;
    case 'refresh-all':
      if (U.route === 'processes') {
        await post('/api/procs/refresh', {}, {
          refresh: ['procs', 'meta'],
          onDone: (result) => toast({ kind: 'success', title: 'Process list refreshed', message: `${fmtNum(result.items.length)} processes, ${result.summary.idle} idle.` }),
        });
      } else {
        await refreshAll();
        S.error = null;
        render();
      }
      break;
    case 'dismiss-error':
      S.error = null;
      render();
      break;
    case 'retry':
      if (U.lastAction) { const fn = U.lastAction; U.lastAction = null; await fn(); }
      break;
    case 'open-help':
      showHelp();
      break;
    case 'cancel-job':
      await cancelJob();
      break;
    case 'junk-scan':
      U.lastAction = () => handleAction('junk-scan', el);
      S.report = null;
      await post('/api/junk/scan', {}, {
        refresh: ['junk', 'meta', 'activity'],
        onDone: (result) => toast({ kind: 'success', title: 'Scan complete', message: `${fmtBytes(result.totals.bytes)} across ${result.totals.categories} categories.` }),
      });
      break;
    case 'junk-safe':
      S.junk.results.filter((r) => r.risk === 'safe' && (r.size || r.items) && r.status !== 'needs-admin').forEach((r) => U.sel.junk.add(r.key));
      render();
      break;
    case 'junk-clear':
      U.sel.junk.clear();
      render();
      break;
    case 'junk-clean':
      await cleanJunk();
      break;
    case 'dismiss-report':
      S.report = null;
      render();
      break;
    case 'proc-filter':
      U.procFilter = el.dataset.filter;
      render();
      break;
    case 'procs-refresh':
      U.lastAction = () => handleAction('procs-refresh', el);
      await post('/api/procs/refresh', {}, {
        refresh: ['procs', 'meta'],
        onDone: (result) => toast({ kind: 'success', title: 'Process list refreshed', message: `${fmtNum(result.items.length)} processes, ${result.summary.idle} idle.` }),
      });
      break;
    case 'procs-idle':
      S.procs.items.filter((p) => p.killable).forEach((p) => U.sel.procs.add(String(p.pid)));
      render();
      break;
    case 'procs-clear':
      U.sel.procs.clear();
      render();
      break;
    case 'procs-kill':
      await killProcesses();
      break;
    case 'leftovers-scan':
      U.lastAction = () => handleAction('leftovers-scan', el);
      S.report = null;
      await post('/api/leftovers/scan', {}, {
        refresh: ['leftovers', 'meta', 'activity'],
        onDone: (result) => toast({
          kind: result.items.length ? 'success' : 'info',
          title: result.items.length ? 'Leftovers found' : 'No stale leftovers',
          message: result.items.length ? `${result.items.length} candidate folders, ${fmtBytes(result.total_bytes)}.` : 'Everything here belongs to an installed program or was used recently.',
        }),
      });
      break;
    case 'leftovers-orphans':
      S.leftovers.items.filter((o) => o.confidence === 'orphan').forEach((o) => U.sel.leftovers.add(o.path));
      render();
      break;
    case 'leftovers-clear':
      U.sel.leftovers.clear();
      render();
      break;
    case 'leftovers-remove':
      await removeLeftovers();
      break;
    case 'search-run':
      await runSearch();
      break;
    case 'search-focus':
      document.getElementById('search-query')?.focus();
      break;
    case 'hit-filter':
      U.hitFilter = el.dataset.filter;
      render();
      break;
    case 'hits-remove':
      await removeHits();
      break;
    case 'refresh-quarantine':
      await refreshData(['quarantine', 'meta']);
      render();
      break;
    case 'q-open':
      await api('/api/open', { method: 'POST', body: { path: S.meta.paths.quarantine } });
      break;
    case 'q-restore':
      await restoreBatches();
      break;
    case 'q-purge':
      await purgeBatches();
      break;
    case 'q-empty':
      await purgeAll();
      break;
    case 'mode':
      await setMode(el.dataset.mode);
      break;
    case 'update-check':
      await checkForUpdates();
      break;
    case 'update-save-source':
      await saveUpdateSource();
      break;
    case 'update-channel':
      await saveUpdateSettings(
        { channel: el.dataset.channel },
        { title: `Channel set to ${el.dataset.channel}`, message: 'The next check reads this channel.' },
      );
      break;
    case 'update-enable':
      await setUpdateEnabled(el.dataset.enabled === undefined ? undefined : el.dataset.enabled === 'true');
      break;
    case 'update-download':
      await downloadUpdate();
      break;
    case 'update-install':
      await installUpdate();
      break;
    case 'update-skip':
      await skipUpdateVersion();
      break;
    case 'update-cleanup':
      await cleanupUpdates();
      break;
    case 'update-dismiss':
      U.updateDismissed = true;
      render();
      toast({ kind: 'info', title: 'Not now', message: 'Sweep will not download anything on its own. Install any time from Settings → Updates.' });
      break;
    case 'open-path':
      await api('/api/open', { method: 'POST', body: { path: el.dataset.path } });
      break;
    case 'more':
      showMore();
      break;
    case 'admin-help':
      modal({
        title: 'Run Sweep as administrator',
        iconName: 'lock',
        body: `<p>Close this tab, then close the console window that is running Sweep.</p>
               <p>In the Sweep folder, right-click <strong>Sweep Web.bat</strong> and choose <strong>Run as administrator</strong>. Accept the UAC prompt, then open the address it prints.</p>
               <div class="modal-note">Administrator rights are granted by Windows to a new process only. The running server cannot request them on your behalf.</div>`,
        footer: '<button class="btn btn-primary" data-modal-close="cancel">Got it</button>',
      });
      break;
    default:
      break;
  }
}

/* ---------- selection ---------- */
document.addEventListener('change', (event) => {
  const el = event.target;
  if (el.matches('[data-check]')) {
    const kind = el.dataset.check;
    const id = el.dataset.id;
    if (el.checked) U.sel[kind].add(id); else U.sel[kind].delete(id);
    const row = el.closest('[data-row]');
    if (row) row.classList.toggle('is-selected', el.checked);
    syncAllCounts();
    updateSelectAll(kind);
    updateActionState(kind);
  }
  if (el.matches('[data-check-all]')) {
    const kind = el.dataset.checkAll;
    const rows = [...document.querySelectorAll(`[data-row="${kind}"]`)];
    rows.forEach((row) => {
      const box = row.querySelector('[data-check]');
      if (!box || box.disabled) return;
      box.checked = el.checked;
      if (el.checked) U.sel[kind].add(box.dataset.id); else U.sel[kind].delete(box.dataset.id);
      row.classList.toggle('is-selected', el.checked);
    });
    syncAllCounts();
    updateActionState(kind);
  }
});

function updateSelectAll(kind) {
  const all = document.querySelector(`[data-check-all="${kind}"]`);
  if (!all) return;
  const boxes = [...document.querySelectorAll(`[data-row="${kind}"] [data-check]`)].filter((b) => !b.disabled);
  const checked = boxes.filter((b) => b.checked).length;
  all.checked = boxes.length > 0 && checked === boxes.length;
  all.indeterminate = checked > 0 && checked < boxes.length;
}

function updateActionState(kind) {
  const map = { junk: ['junk-clean'], procs: ['procs-kill'], leftovers: ['leftovers-remove'], hits: ['hits-remove'], quarantine: ['q-restore', 'q-purge'] };
  (map[kind] || []).forEach((action) => {
    document.querySelectorAll(`[data-action="${action}"]`).forEach((btn) => {
      if (btn.querySelector('[data-count]')) btn.disabled = U.sel[kind].size === 0;
    });
  });
}

/* ---------- filters (no re-render: keeps focus) ---------- */
document.addEventListener('input', (event) => {
  const el = event.target;
  if (el.id === 'proc-filter') {
    U.procQuery = el.value;
    applyProcFilter();
  }
  if (el.id === 'junk-filter') {
    U.junkQuery = el.value;
    applyJunkFilter();
  }
});

function applyProcFilter() {
  const needle = U.procQuery.trim().toLowerCase();
  document.querySelectorAll('[data-row="procs"]').forEach((row) => {
    const text = row.textContent.toLowerCase();
    row.hidden = Boolean(needle) && !text.includes(needle);
  });
}

function applyJunkFilter() {
  const needle = U.junkQuery.trim().toLowerCase();
  document.querySelectorAll('[data-row="junk"]').forEach((row) => {
    const text = row.textContent.toLowerCase();
    row.hidden = Boolean(needle) && !text.includes(needle);
  });
}

/* ---------- actions ---------- */
async function cleanJunk() {
  const keys = [...U.sel.junk];
  if (!keys.length) return;
  const rows = S.junk.results.filter((r) => keys.includes(r.key));
  const bytes = rows.reduce((a, r) => a + r.size, 0);
  const permanent = S.meta.mode === 'permanent';
  const adminRows = rows.filter((r) => r.status === 'needs-admin');
  const ok = await confirmAction({
    title: permanent ? 'Permanently delete this junk?' : 'Move this junk to quarantine?',
    subtitle: `${rows.length} categories · ${fmtBytes(bytes)}`,
    message: permanent
      ? 'The selected files will be deleted immediately. There is no copy and no undo.'
      : 'The selected files move to quarantine on the same drive. You can restore them from the Quarantine page.',
    bullets: [
      ...rows.slice(0, 6).map((r) => `${r.title} — ${fmtBytes(r.size)}`),
      ...(rows.length > 6 ? [`and ${rows.length - 6} more categories`] : []),
      ...(adminRows.length ? [`${adminRows.length} categories need Administrator and will be skipped with a reason`] : []),
    ],
    note: permanent ? 'Typing the word is required because this cannot be undone.' : '',
    word: permanent ? 'delete' : null,
    danger: true,
    confirmLabel: permanent ? 'Delete permanently' : 'Quarantine',
  });
  if (!ok) return;
  U.lastAction = cleanJunk;
  S.report = null;
  await post('/api/junk/clean', { keys, permanent, confirm: permanent ? 'delete' : undefined }, {
    refresh: ['junk', 'meta', 'quarantine', 'activity'],
    onDone: (result) => {
      const failed = result.failed || 0;
      const locked = result.failures?.length || 0;
      S.report = failed ? result : null;
      const first = result.errors?.[0];
      toast({
        kind: failed ? 'warn' : 'success',
        title: failed ? 'Some files could not be moved' : result.mode === 'permanent' ? 'Deleted' : 'Moved to quarantine',
        message: `${fmtBytes(result.bytes)} freed${failed ? ` · ${fmtNum(locked || failed)} file${locked === 1 ? '' : 's'} left behind` : ''}${result.skipped_admin.length ? ` · ${result.skipped_admin.length} need admin` : ''}.`,
        reason: failed ? first?.reason || '' : '',
        hint: failed ? first?.hint || '' : '',
      });
    },
  });
}

async function killProcesses() {
  const pids = [...U.sel.procs].map(Number);
  if (!pids.length) return;
  const rows = S.procs.items.filter((p) => pids.includes(p.pid));
  const ok = await confirmAction({
    title: `Stop ${pids.length} process${pids.length === 1 ? '' : 'es'}?`,
    subtitle: rows.slice(0, 4).map((p) => p.name).join(', ') + (rows.length > 4 ? ` +${rows.length - 4} more` : ''),
    message: 'Windows terminates the process immediately. Unsaved work in it is lost.',
    bullets: rows.slice(0, 6).map((p) => `${p.name} (PID ${p.pid}) — ${fmtBytes(p.rss)}`),
    word: pids.length >= 5 ? 'kill' : null,
    danger: true,
    confirmLabel: 'Stop processes',
  });
  if (!ok) return;
  U.lastAction = killProcesses;
  await post('/api/procs/kill', { pids, confirm: pids.length >= 5 ? 'kill' : undefined }, {
    refresh: ['procs', 'meta', 'activity'],
    onDone: (result) => {
      U.sel.procs.clear();
      toast({
        kind: result.failed.length ? 'warn' : 'success',
        title: 'Processes stopped',
        message: `${result.killed} of ${result.requested} terminated.`,
        reason: result.failed[0]?.reason || '',
        hint: result.failed[0]?.hint || '',
      });
    },
  });
}

async function removeLeftovers() {
  const paths = [...U.sel.leftovers];
  if (!paths.length) return;
  const rows = S.leftovers.items.filter((o) => paths.includes(o.path));
  const bytes = rows.reduce((a, o) => a + o.size, 0);
  const permanent = S.meta.mode === 'permanent';
  const ok = await confirmAction({
    title: permanent ? 'Permanently remove these folders?' : 'Move these folders to quarantine?',
    subtitle: `${rows.length} folders · ${fmtBytes(bytes)}`,
    message: permanent
      ? 'The folders are deleted immediately and cannot be restored.'
      : 'The folders move to quarantine and can be restored from the Quarantine page.',
    bullets: rows.slice(0, 5).map((o) => `${o.name} — ${fmtBytes(o.size)}`),
    word: permanent || bytes > 500 * 1024 * 1024 ? 'remove' : null,
    danger: true,
    confirmLabel: permanent ? 'Delete permanently' : 'Quarantine',
  });
  if (!ok) return;
  U.lastAction = removeLeftovers;
  S.report = null;
  await post('/api/leftovers/remove', { paths, permanent, confirm: permanent || bytes > 500 * 1024 * 1024 ? 'remove' : undefined }, {
    refresh: ['leftovers', 'meta', 'quarantine', 'activity'],
    onDone: (result) => {
      U.sel.leftovers.clear();
      S.report = result.failed ? result : null;
      const first = result.errors?.[0];
      toast({
        kind: result.failed ? 'warn' : 'success',
        title: result.failed ? 'Some folders could not be moved' : 'Folders removed',
        message: `${fmtBytes(result.bytes)} across ${rows.length} folders${result.failed ? ` · ${result.failures?.length || result.failed} files left behind` : ''}.`,
        reason: result.failed ? first?.reason || '' : '',
        hint: result.failed ? first?.hint || '' : '',
      });
    },
  });
}

async function runSearch() {
  const input = document.getElementById('search-query');
  const query = (input?.value || S.search?.query || '').trim();
  if (query.length < 2) {
    handleError(new ApiFailure({
      code: 'invalid_request',
      message: 'Type at least two characters',
      reason: `“${query}” is too short to match anything useful.`,
      hint: 'Try the app name as it appears in Settings → Apps, e.g. “OBS Studio”.',
    }));
    return;
  }
  const registry = document.getElementById('opt-registry')?.checked ?? false;
  const services = document.getElementById('opt-services')?.checked ?? false;
  U.lastAction = runSearch;
  await post('/api/search', { query, registry, services }, {
    refresh: ['search', 'meta', 'activity'],
    onDone: (result) => {
      U.sel.hits.clear();
      U.hitFilter = 'all';
      toast({
        kind: result.hits.length ? 'success' : 'info',
        title: result.hits.length ? `${result.hits.length} matches` : 'No matches',
        message: result.hits.length
          ? `Scanned ${fmtNum(result.meta.scanned)} folders in ${result.meta.elapsed}s.`
          : `Nothing on this PC matches “${result.query}”.`,
        hint: result.meta.truncated ? 'Stopped at 400 matches — refine the name for a complete list.' : '',
      });
    },
  });
}

async function removeHits() {
  const ids = [...U.sel.hits];
  if (!ids.length) return;
  const rows = S.search.hits.filter((h) => ids.includes(h.id));
  const bytes = rows.reduce((a, h) => a + h.size, 0);
  const permanent = S.meta.mode === 'permanent';
  const sensitive = rows.some((h) => h.kind === 'registry' || h.kind === 'service');
  const ok = await confirmAction({
    title: permanent ? 'Permanently remove these matches?' : 'Remove these matches?',
    subtitle: `${rows.length} items · ${fmtBytes(bytes)}`,
    message: sensitive
      ? 'Registry keys and services are changed in place; they cannot be quarantined. File and folder matches go to quarantine.'
      : 'File and folder matches move to quarantine and can be restored.',
    bullets: rows.slice(0, 6).map((h) => `${h.kind_label}: ${h.name}`),
    note: sensitive ? 'Registry keys are exported to the batch folder before they are deleted.' : '',
    word: permanent || bytes > 1024 ** 3 || sensitive ? 'remove' : null,
    danger: true,
    confirmLabel: 'Remove',
  });
  if (!ok) return;
  U.lastAction = removeHits;
  await post('/api/search/remove', { ids, permanent, confirm: permanent || bytes > 1024 ** 3 || sensitive ? 'remove' : undefined }, {
    refresh: ['search', 'meta', 'quarantine', 'activity'],
    onDone: (result) => {
      U.sel.hits.clear();
      toast({
        kind: result.failed ? 'warn' : 'success',
        title: 'Removal finished',
        message: `${fmtBytes(result.bytes)} freed · ${result.moved + result.deleted} items · ${result.failed} failed.`,
        reason: result.errors?.[0]?.reason || '',
        hint: result.errors?.[0]?.hint || '',
      });
    },
  });
}

async function restoreBatches() {
  const ids = [...U.sel.quarantine];
  if (!ids.length) return;
  const ok = await confirmAction({
    title: 'Restore these batches?',
    subtitle: `${ids.length} batches`,
    message: 'Every file goes back to the exact path it was removed from.',
    bullets: ids.slice(0, 6),
    danger: false,
    confirmLabel: 'Restore',
  });
  if (!ok) return;
  U.lastAction = restoreBatches;
  await post('/api/quarantine/restore', { ids }, {
    refresh: ['quarantine', 'junk', 'meta', 'activity'],
    onDone: (result) => {
      U.sel.quarantine.clear();
      const restored = result.results.reduce((a, r) => a + r.restored, 0);
      toast({ kind: 'success', title: 'Restored', message: `${fmtNum(restored)} items put back.`, reason: result.errors?.[0]?.reason || '' });
    },
  });
}

async function purgeBatches() {
  const ids = [...U.sel.quarantine];
  if (!ids.length) return;
  const ok = await confirmAction({
    title: 'Purge these batches?',
    subtitle: `${ids.length} batches`,
    message: 'The quarantined files are deleted for good. There is no undo.',
    bullets: ids.slice(0, 6),
    word: 'purge',
    danger: true,
    confirmLabel: 'Purge',
  });
  if (!ok) return;
  U.lastAction = purgeBatches;
  await post('/api/quarantine/purge', { ids, confirm: 'purge' }, {
    refresh: ['quarantine', 'meta', 'activity'],
    onDone: (result) => {
      U.sel.quarantine.clear();
      toast({ kind: result.failed.length ? 'warn' : 'success', title: 'Purged', message: `${result.purged} batches deleted.`, reason: result.failed?.[0]?.reason || '' });
    },
  });
}

async function purgeAll() {
  const ok = await confirmAction({
    title: 'Empty the whole quarantine?',
    subtitle: `${S.quarantine.batches.length} batches · ${fmtBytes(S.quarantine.total_bytes)}`,
    message: 'Every batch on every drive is deleted. This cannot be undone.',
    bullets: ['Files still inside the batches are removed permanently', 'Restoring is no longer possible'],
    word: 'empty',
    danger: true,
    confirmLabel: 'Empty quarantine',
  });
  if (!ok) return;
  U.lastAction = purgeAll;
  await post('/api/quarantine/purge-all', { confirm: 'empty' }, {
    refresh: ['quarantine', 'meta', 'activity'],
    onDone: (result) => toast({ kind: 'success', title: 'Quarantine emptied', message: `${result.purged} batches deleted.` }),
  });
}

async function setMode(mode) {
  if (S.meta.mode === mode) return;
  if (mode === 'permanent') {
    const ok = await confirmAction({
      title: 'Turn on permanent delete?',
      subtitle: 'This changes every cleanup',
      message: 'Removals will no longer keep a copy. Each permanent cleanup asks you to type a word first.',
      bullets: ['Quarantine stops being used', 'Removed files cannot be restored', 'You can switch back at any time'],
      danger: true,
      confirmLabel: 'Turn on permanent delete',
    });
    if (!ok) return;
  }
  try {
    await api('/api/mode', { method: 'POST', body: { mode } });
    await refreshData(['meta']);
    toast({ kind: 'success', title: 'Mode changed', message: mode === 'permanent' ? 'Permanent delete is now on.' : 'Quarantine is now on — removals can be restored.' });
    render();
  } catch (error) {
    handleError(error);
  }
}

/* ---------- update actions ---------- */
async function saveUpdateSettings(patch, success) {
  try {
    const state = await api('/api/update/settings', { method: 'POST', body: patch });
    S.update = { state, result: updateResult() };
    await refreshData(['update']);
    render();
    if (success) toast({ kind: 'success', title: success.title, message: success.message || '' });
  } catch (error) {
    handleError(error);
  }
}

function toastUpdateCheck(result) {
  if (!result) return;
  if (result.status === 'available') {
    toast({
      kind: 'success',
      title: `Sweep ${updateVersion(result, updateStateData())} is available`,
      message: result.message || 'A newer release is ready to install.',
      hint: result.hint || '',
    });
  } else if (result.status === 'up_to_date') {
    toast({ kind: 'success', title: 'Sweep is up to date', message: result.message || 'You have the newest release for this channel.' });
  } else if (result.status === 'error') {
    toast({ kind: 'warn', title: result.message || 'Could not check for updates', reason: result.reason || '', hint: result.hint || '' });
  } else {
    toast({ kind: 'info', title: result.message || 'Update check finished', message: result.hint || '' });
  }
}

async function checkForUpdates() {
  if (U.updateBusy) return;
  U.updateBusy = true;
  render();
  try {
    const result = await api('/api/update/check', { method: 'POST', body: { force: true } });
    S.update = { state: updateStateData(), result };
    await refreshData(['update']);
    U.updateBusy = false;
    render();
    toastUpdateCheck(updateResult() || result);
  } catch (error) {
    U.updateBusy = false;
    render();
    handleError(error);
  }
}

async function saveUpdateSource() {
  const input = document.getElementById('update-source');
  const url = (input?.value || '').trim();
  try {
    const state = await api('/api/update/settings', { method: 'POST', body: { manifest_url: url } });
    S.update = { state, result: updateResult() };
    await refreshData(['update']);
    render();
    toast({
      kind: 'success',
      title: url ? 'Update source saved' : 'Update source cleared',
      message: url ? 'Sweep will read latest.json from that address on the next check.' : 'Sweep will not contact an update server until a source is set.',
    });
    if (!url) document.getElementById('update-source')?.focus();
  } catch (error) {
    handleError(error);
  }
}

async function setUpdateEnabled(force) {
  const state = updateStateData();
  if (!state) return;
  const enabled = typeof force === 'boolean' ? force : !state.enabled;
  await saveUpdateSettings(
    { enabled },
    {
      title: enabled ? 'Automatic checks on' : 'Automatic checks off',
      message: enabled ? 'Sweep will look for a newer release at launch.' : 'Sweep will not contact the update server until you turn this back on.',
    },
  );
}

// Shared by "Download only" and the install flow so both show progress in the
// existing job bar and both record the verified staging path.
function startUpdateDownload(version, onDone) {
  return post('/api/update/download', {}, {
    refresh: ['update'],
    onDone: (data) => {
      U.updateStaged = { version: data?.version || version, staged: data?.staged || '' };
      onDone?.(U.updateStaged, data);
    },
  });
}

async function downloadUpdate() {
  const version = updateVersion(updateResult(), updateStateData());
  await startUpdateDownload(version, (staged) => {
    toast({
      kind: 'success',
      title: 'Downloaded and verified',
      message: `Sweep ${staged.version} passed its SHA-256 check and is ready to install from Settings.`,
    });
  });
}

async function installUpdate() {
  const result = updateResult();
  const state = updateStateData();
  if (!result || !['available', 'skipped'].includes(result.status)) {
    toast({ kind: 'info', title: 'No update ready', message: 'Check for updates first.' });
    return;
  }
  const version = updateVersion(result, state);
  const canApply = !state || state.can_apply !== false;
  if (!canApply) {
    handleError(new ApiFailure({
      code: 'not_writable',
      message: 'This copy of Sweep cannot replace itself',
      reason: 'The Sweep folder is read-only for this user, or this build was not made to update in place.',
      hint: 'Move Sweep to a folder you can write to (for example your user folder) and try again, or install the release by hand.',
    }));
    return;
  }
  const ok = await confirmAction({
    title: `Update Sweep to ${version}?`,
    subtitle: result.release?.size ? `${fmtBytes(result.release.size)} · verified before it runs` : 'Verified before it runs',
    message: `Sweep ${version} will download, verify its SHA-256, replace its own files and restart. Quarantine, logs and settings are kept.`,
    bullets: [
      'The archive is checked against the SHA-256 in the release manifest before anything is replaced',
      'The current files are backed up first, so the previous version can be restored',
      'Sweep closes and reopens on its own; this page stops working until it is back',
    ],
    note: 'Nothing in Quarantine, your logs or your settings is touched.',
    word: 'update',
    danger: false,
    confirmLabel: 'Download & install',
  });
  if (!ok) return;
  if (U.updateStaged && U.updateStaged.version === version) {
    await applyUpdate(version);
    return;
  }
  await startUpdateDownload(version, async (staged) => {
    toast({ kind: 'success', title: 'Download verified', message: `Sweep ${staged.version} is ready. Installing now…` });
    await applyUpdate(version);
  });
}

async function applyUpdate(version) {
  try {
    await api('/api/update/apply', { method: 'POST', body: { confirm: 'update' } });
    U.updateStaged = null;
    showRestarting(version);
  } catch (error) {
    // The helper is started detached and the server exits shortly after it
    // answers. A dropped connection here is the expected ending, not a fault.
    const code = error?.code || error?.error?.code;
    if (code === 'server_unreachable' || code === 'bad_response') {
      U.updateStaged = null;
      showRestarting(version);
      return;
    }
    handleError(error);
  }
}

function showRestarting(version) {
  const handle = modal({
    title: 'Updating — Sweep is restarting',
    subtitle: version ? `Sweep ${version}` : '',
    iconName: 'refresh',
    body: `<p>Sweep is replacing its own files now. The local server stops for a moment, so this page can no longer reach it.</p>
      <ul>
        <li>Wait about ten seconds.</li>
        <li>Reopen the address printed in the Sweep console window — usually <code>http://127.0.0.1:8765</code>.</li>
        <li>Quarantine, logs and settings are unchanged.</li>
      </ul>
      <div class="modal-note" id="update-restart-note">If Sweep does not come back, start it again the way you normally do; the previous version is kept as a backup.</div>`,
    footer: `<button class="btn btn-ghost" data-modal-close="cancel">Close</button>
             <button class="btn btn-primary" id="update-reload">Reload page</button>`,
  });
  const reload = handle.overlay.querySelector('#update-reload');
  const note = handle.overlay.querySelector('#update-restart-note');
  reload?.addEventListener('click', async () => {
    reload.disabled = true;
    try {
      await api('/api/health');
      location.reload();
    } catch {
      if (note) note.textContent = 'The server is still restarting. Wait a few seconds and press Reload page again.';
      reload.disabled = false;
    }
  });
}

async function skipUpdateVersion() {
  const result = updateResult();
  const version = updateVersion(result, updateStateData());
  if (!result || !version) return;
  try {
    const state = await api('/api/update/skip', { method: 'POST', body: { version } });
    S.update = { state, result: updateResult() };
    U.updateDismissed = true;
    await refreshData(['update']);
    render();
    toast({
      kind: 'info',
      title: `Sweep ${version} skipped`,
      message: 'Sweep will not offer this version again. Check now any time to see newer releases.',
    });
  } catch (error) {
    handleError(error);
  }
}

async function cleanupUpdates() {
  try {
    const data = await api('/api/update/cleanup', { method: 'POST', body: {} });
    const result = updateResult();
    if (data?.state) S.update = { state: data.state, result };
    await refreshData(['update']);
    render();
    toast({
      kind: data?.freed ? 'success' : 'info',
      title: data?.freed ? 'Download cache cleaned' : 'Nothing to clean',
      message: data?.freed ? `${fmtBytes(data.freed)} freed from previous downloads.` : 'There are no leftover downloads to remove.',
    });
  } catch (error) {
    handleError(error);
  }
}

function showHelp() {
  modal({
    title: 'How Sweep works',
    subtitle: `Sweep ${VERSION} · local, offline`,
    iconName: 'help',
    width: 640,
    body: `
      <p><strong>Junk files</strong> measures 18 known cache locations before touching them. Risky categories are never pre-selected, and categories that need Administrator say so instead of failing silently.</p>
      <p><strong>Processes</strong> keeps Windows images, services, anything with a visible window or tray presence, and their children. What is left — a third-party app with no window and no tray — is what it can stop.</p>
      <p><strong>Leftovers</strong> only offers folders that no installed program, shortcut or publisher explains, and that nothing has touched for three weeks.</p>
      <p><strong>Program remover</strong> searches every fixed drive for a name, plus optionally registry keys and services. It only ever deletes paths it found itself.</p>
      <div class="modal-note">
        <strong>Safety rules:</strong> quarantine by default, one destructive job at a time, typed confirmation for permanent deletes and large removals, and hard refusals for Windows system locations, your personal folders and credential stores.
      </div>`,
    footer: '<button class="btn btn-primary" data-modal-close="cancel">Close</button>',
  });
}

function showMore() {
  const items = [
    ['leftovers', 'folder-minus', 'Leftovers', 'Folders no installed program claims'],
    ['remover', 'search', 'Program remover', 'Search every drive by name'],
    ['settings', 'settings', 'Settings', 'Safety mode, elevation and data'],
  ];
  const handle = modal({
    title: 'More sections',
    subtitle: 'Everything else in Sweep',
    iconName: 'more',
    body: `<div class="more-list">${items.map(([route, ic, label, sub]) => `
      <button type="button" class="more-item" data-more-route="${route}">
        <span class="more-icon">${icon(ic)}</span>
        <span class="more-text"><b>${label}</b><span>${sub}</span></span>
        ${icon('chevron-right')}
      </button>`).join('')}
      <button type="button" class="more-item" data-more-help>
        <span class="more-icon">${icon('help')}</span>
        <span class="more-text"><b>Help</b><span>How Sweep decides what is safe</span></span>
        ${icon('chevron-right')}
      </button>
    </div>`,
    footer: '<button class="btn btn-ghost" data-modal-close="cancel">Close</button>',
  });
  handle.overlay.querySelectorAll('[data-more-route]').forEach((el) =>
    el.addEventListener('click', () => { handle.close(null); navigate(el.dataset.moreRoute); }));
  handle.overlay.querySelector('[data-more-help]')?.addEventListener('click', () => { handle.close(null); showHelp(); });
}

/* ------------------------------------------------------------------ boot */
function fillStaticIcons() {
  document.querySelectorAll('[data-icon]').forEach((el) => { el.innerHTML = icon(el.dataset.icon); });
}

function routeFromHash() {
  if (!location.hash) location.hash = '#/dashboard';
}

function isTyping() {
  const el = document.activeElement;
  return Boolean(el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable));
}

function installShortcuts() {
  document.addEventListener('keydown', (event) => {
    if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.key === 'Enter' && document.activeElement?.id === 'search-query') {
      event.preventDefault();
      handleAction('search-run', document.activeElement);
      return;
    }
    if (isTyping()) return;
    if (event.key === '/') {
      const input = document.getElementById('junk-filter') || document.getElementById('proc-filter') || document.getElementById('search-query');
      if (input) { event.preventDefault(); input.focus(); input.select?.(); }
      return;
    }
    if (event.key === '?') { event.preventDefault(); showHelp(); return; }
    const routes = { 1: 'dashboard', 2: 'junk', 3: 'processes', 4: 'leftovers', 5: 'remover', 6: 'quarantine', 7: 'settings' };
    if (routes[event.key]) { event.preventDefault(); navigate(routes[event.key]); }
  });
}

async function boot() {
  fillStaticIcons();
  routeFromHash();
  installShortcuts();
  document.querySelector('.skip-link')?.addEventListener('click', (event) => {
    event.preventDefault();
    const view = document.getElementById('view');
    view.focus();
    view.scrollIntoView({ block: 'start' });
  });
  window.addEventListener('hashchange', () => {
    if (!location.hash.startsWith('#/')) return;
    S.error = null;
    render();
    window.scrollTo({ top: 0 });
  });
  let resizeTimer = 0;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(sizeTallTables, 120);
  });
  let painted = false;
  const initial = refreshAll(() => { if (!painted) { painted = true; render(); } });
  await initial;
  render();
  if (!S.procs?.collected_at && !S.procs?.items?.length && !S.meta?.active_job) {
    post('/api/procs/refresh', {}, { refresh: ['procs', 'meta'] }).catch(() => {});
  }
  if (S.meta?.active_job) {
    U.job = S.meta.active_job;
    renderJobBar();
    pollJob(U.job.id, { refresh: ['meta', 'junk', 'procs', 'leftovers', 'quarantine', 'activity'] });
  }
  setInterval(async () => {
    if (document.hidden || U.job) return;
    try {
      const meta = await api('/api/meta');
      S.meta = meta;
      renderSidebar();
    } catch { /* the error path already reports a dead server */ }
  }, 30000);
}

boot();
