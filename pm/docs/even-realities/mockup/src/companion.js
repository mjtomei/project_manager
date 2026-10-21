// Companion (phone WebView) view. On Even Hub the same web page is the phone
// screen, so the companion shows what the glasses cannot: full text, exact
// diffs, typed input and confirmation details. It never becomes a second
// source of truth: every button calls the same intents/PM commands.
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

export function renderCompanion(root, app, pm, act) {
  const v = app.view;
  const parts = [];
  const conn = pm.conn.state === 'ok' ? '' : `<p class="warn">↔ ${pm.conn.state === 'offline' ? 'PM offline' : 'Reconnecting to PM'} · data ${pm.conn.staleFor}s old · actions disabled</p>`;
  parts.push(`<header><b>PM on glasses</b> <span class="sim">SIMULATED PM data</span><br><small>${esc(pm.project.name)} · ${esc(pm.now())} · glasses view: <code>${esc(app.sceneId())}</code></small></header>${conn}`);
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
    if (v.kind === 'confirm') parts.push(`<ul>${v.confirm.lines.map(l => `<li>${esc(l)}</li>`).join('')}</ul><p><button data-i="select">${esc(v.confirm.yes)}</button> <button data-i="back">${esc(v.confirm.no)}</button></p>`);
    else parts.push('<ul class="rows">' + app.items(v).map(it => `<li class="${it.act ? 'act' : ''}">${esc(Array.isArray(it.l) ? it.l.map(s => s.t).join(' ') : it.l)} <small>${esc(it.r?.t || '')}</small></li>`).join('') + '</ul>');
  }
  root.innerHTML = parts.join('');
  root.querySelectorAll('[data-i]').forEach(b => b.addEventListener('click', () => act(b.dataset.i)));
  const form = root.querySelector('form.compose');
  if (form) form.addEventListener('submit', e => {
    e.preventDefault();
    const text = form.querySelector('input').value.trim();
    if (!text) return;
    const r = pm.send(v.id, text, null);
    app.say(r.ok ? `Sent from phone to ${app.sessionName(pm.session(v.id))}` : `! Not sent: ${r.reason}`);
    act('noop');
  });
}
