// Companion (phone WebView) view. On Even Hub the same web page is the phone
// screen, so the companion shows what the glasses cannot: full text, exact
// diffs, typed input and confirmation details. It never becomes a second
// source of truth: every button calls the same intents/PM commands.
import { fmtAge } from './app.js';

const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

export function renderCompanion(root, app, pm, act) {
  const v = app.view;
  const parts = [];
  const conn = pm.conn.state === 'ok' ? '' : `<p class="warn">↔ ${pm.conn.state === 'offline' ? 'PM offline' : 'Reconnecting to PM'} · data ${fmtAge(pm.conn.staleFor)} old · actions are refused, not queued</p>`;
  // The glasses footer notice (sent, queued, refused) also shows here, so a
  // send typed on the phone gets its answer on the phone.
  const notice = app.toast ? `<p class="${app.toast.startsWith('!') ? 'warn' : 'muted'}" role="status">${esc(app.toast)}</p>` : '';
  parts.push(`<header><b>PM on glasses</b> <span class="sim">SIMULATED PM data</span><br><small>${esc(pm.project.name)} · ${esc(pm.now())} · glasses view: <code>${esc(app.sceneId())}</code></small></header>${conn}${notice}`);
  if (v.type === 'doc') {
    const d = pm.doc(v.docId), shown = pm.version(v.docId, v.version), latest = pm.latest(v.docId);
    parts.push(`<h2>${esc(d.label)} <small>v${shown.n} · ${shown.hash} · ${esc(d.path)}</small></h2>`);
    if (latest.n !== shown.n) parts.push(`<p class="warn">● v${latest.n} (${latest.hash}) is newer than the version you are reading. Approval needs v${latest.n}.</p>`);
    if (d.pending) parts.push(`<p>${esc(d.gate || '')}. Pending review of v${d.pending.version} since ${esc(d.pending.since)}.</p>`);
    parts.push(`<pre class="doc">${esc(shown.text)}</pre>`);
  } else if (v.type === 'session') {
    const s = pm.session(v.id);
    parts.push(`<h2>${esc(app.sessionTitle(s))} <small>${esc(s.window)} · pane ${esc(s.pane)} · ${esc(s.stateText)}</small></h2>`);
    parts.push('<ol class="chat">' + (s.transcript || []).map(m => `<li class="${m.who}">${esc(m.t)}${m.context ? `<br><small>context: ${esc(m.context.label)}</small>` : ''}</li>`).join('') + '</ol>');
    if (s.state !== 'ended') parts.push(`<form class="compose"><input placeholder="Type to ${esc(app.sessionName(s))}…" aria-label="Message"><button type="submit">Send</button></form>`);
  } else {
    const [title] = app.title(v);
    parts.push(`<h2>${esc(title)}</h2>`);
    if (v.kind === 'confirm') parts.push(`<ul>${v.confirm.lines.map(l => `<li>${esc(l)}</li>`).join('')}</ul><p><button data-confirm>${esc(v.confirm.yes)}</button> <button data-i="back">${esc(v.confirm.no)}</button></p>`);
    else parts.push('<ul class="rows">' + app.items(v).map(it => `<li class="${it.act ? 'act' : ''}">${esc(Array.isArray(it.l) ? it.l.map(s => s.t).join(' ') : it.l)} <small>${esc(it.r?.t || '')}</small></li>`).join('') + '</ul>');
  }
  // Re-rendering (an agent reply, a director event, a glasses gesture) must
  // not wipe a message being typed: carry the draft and focus over while the
  // same session stays open.
  const prev = root.querySelector('form.compose input');
  const session = v.type === 'session' ? v.id : '';
  const draft = prev && root.dataset.session === session ? { value: prev.value, focused: document.activeElement === prev, at: prev.selectionStart } : null;
  root.innerHTML = parts.join('');
  root.dataset.session = session;
  const input = root.querySelector('form.compose input');
  if (input && draft) {
    input.value = draft.value;
    if (draft.focused) { input.focus(); input.setSelectionRange(draft.at, draft.at); }
  }
  root.querySelectorAll('[data-i]').forEach(b => b.addEventListener('click', () => act(b.dataset.i)));
  // Run the confirmation directly: "select" would pick whatever row the glasses cursor is on.
  root.querySelector('[data-confirm]')?.addEventListener('click', () => { v.confirm.run(); act('noop'); });
  const form = root.querySelector('form.compose');
  if (form) form.addEventListener('submit', e => {
    e.preventDefault();
    const text = form.querySelector('input').value.trim();
    if (!text) return;
    // Typed messages carry the same reading context as spoken ones.
    const r = pm.send(v.id, text, app.contextFor({ session: v.id, doc: app.contextDoc(v.id) }));
    const s = pm.session(v.id);
    if (r.ok) app.say(r.queued ? `Queued from phone in ${app.sessionName(s)} (${s.state === 'starting' ? 'starting' : 'busy'}) · same session` : `Sent from phone to ${app.sessionName(s)}`);
    else app.fail(r);
    // A sent message clears the draft; a refused one was not sent, so the
    // re-render keeps it for the user to send later.
    if (r.ok) form.querySelector('input').value = '';
    act('noop');
  });
}
