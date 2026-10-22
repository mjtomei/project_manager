// Mockup controller: views, navigation and intents. DOM-free so the same code
// runs in the Even Hub WebView (simulator), the browser preview and Node checks.
//
// Intents are the behavior; the gesture binding lives in input.js and is one
// candidate (see ../proposal.md "Candidate binding").
import { wrap, width, GLYPH, BODY_ROWS } from './text.js';
import { row } from './frame.js';

export const MENU = Object.freeze([
  { itemID: 1, itemName: 'Needs you', go: 'home' },
  { itemID: 2, itemName: 'Sessions', go: 'sessions' },
  { itemID: 3, itemName: 'PRs and status', go: 'prs' },
  { itemID: 4, itemName: 'Plans and project', go: 'project' },
]);

const STATE_GLYPH = { working: '◐', starting: '◐', idle: '○', waiting: '●', needs: '?', done: '■', ended: '□', queued: '□', none: '·', failed: '!' };
const glyphFor = s => STATE_GLYPH[s] || '·';
const ATTENTION = new Set(['needs', 'waiting', 'failed']);
const LIVE = new Set(['working', 'idle', 'waiting', 'needs', 'starting']);
const stateCell = s => ({ t: `${glyphFor(s.state)} ${s.stateText}`, dim: !ATTENTION.has(s.state) && s.state !== 'working' && s.state !== 'starting' });
const LIST_ROWS = BODY_ROWS - 1; // row 0 is the identity/header row
const INDENT = 28; // label x after the cursor column (▶ is 20 px)
const TEXT_WIDTH = 540; // wrap width; leaves room below the 552 px container
const VOICE_CHOICES = ['Send', 'Speak again', 'Cancel'];
const CONFIRM_LINES = 5; // explanation rows above a confirmation's two choices

// ---- document formatting ----------------------------------------------
function formatDoc(text) {
  const out = [];
  let section = '';
  for (const raw of text.split('\n')) {
    const line = raw.trimEnd();
    if (!line) continue;
    if (line.startsWith('# ')) { out.push({ segs: [{ t: line.slice(2) }], section: '', key: 'title' }); continue; }
    if (line.startsWith('## ')) {
      section = line.slice(3);
      out.push({ segs: [] , section, key: `${section}#gap` });
      out.push({ segs: [{ t: section.toUpperCase() }], section, key: section });
      continue;
    }
    if (line.startsWith('- ')) {
      const body = line.slice(2);
      const key = (body.match(/^([A-Z]\d+|s\d+)\.|^(#\d+) /) || []).slice(1).find(Boolean) || body.slice(0, 16);
      wrap(body, TEXT_WIDTH - 18).forEach((t, i) => out.push({ segs: i ? [{ t, x: 18 }] : [{ t: '•' }, { t, x: 18 }], section, key: i ? `${key}+${i}` : key }));
      continue;
    }
    const dim = out.length === 1; // subtitle line under the title
    wrap(line, TEXT_WIDTH).forEach((t, i) => out.push({ segs: [{ t, dim }], section, key: `${section}:${line.slice(0, 12)}+${i}` }));
  }
  return out;
}

// Page starts that keep a bullet or heading together when it fits on the
// next page, and never start a page with a blank separator row.
export function paginate(lines, per) {
  const starts = [];
  let s = 0;
  while (s < lines.length) {
    while (s < lines.length - 1 && !lines[s].segs.length) s++;
    starts.push(s);
    let e = Math.min(lines.length, s + per);
    if (e < lines.length) {
      let b = e;
      while (b > s && lines[b].key.includes('+')) b--; // start of the split bullet
      if (b > s + 2 && e - b < per) e = b;
      while (e - 1 > s && (!lines[e - 1].segs.length || /^[A-Z0-9 .]+$/.test(lines[e - 1].segs.map(x => x.t).join('')) && lines[e - 1].key === lines[e - 1].section)) e--; // no orphan heading
    }
    s = e;
  }
  return starts.length ? starts : [0];
}

export class App {
  constructor(pm) {
    this.pm = pm;
    this.stack = [{ type: 'list', kind: 'home', cursor: 0, top: 0 }];
    this.overlay = null;
    this.toast = null;
    this.nextUtterance = null;
    this.docCache = new Map();
    this.exitRequested = false;
  }

  get view() { return this.stack.at(-1); }
  // Apply a SIMULATED PM event and surface what the user should notice.
  pmEvent(e) {
    this.pm.apply(e);
    if (e.type === 'reconnect') this.say('Reconnected · same place · nothing resent');
  }
  push(v) { this.stack.push(v); }
  pop() { if (this.stack.length > 1) this.stack.pop(); else this.exitRequested = true; }
  say(text) { this.toast = text; }

  // ---- intents --------------------------------------------------------
  intent(name, arg) {
    const keepToast = name === 'hold' || name === 'release';
    if (!keepToast) this.toast = null;
    this.exitRequested = false;
    if (name === 'menu') return this.menu(arg);
    if (this.overlay) return this.overlayIntent(name);
    if (name === 'hold') return this.startListening();
    if (name === 'release') return;
    const v = this.view;
    if (v.type === 'doc') return this.docIntent(v, name);
    if (v.type === 'session') return this.sessionIntent(v, name);
    return this.listIntent(v, name);
  }

  menu(id) {
    const item = MENU.find(m => m.itemID === id);
    if (!item) return;
    this.overlay = null;
    if (item.go === 'home') { this.stack = [this.stack[0]]; return; }
    this.push({ type: 'list', kind: item.go, cursor: 0, top: 0 });
  }

  // ---- lists ----------------------------------------------------------
  listIntent(v, name) {
    const items = this.items(v);
    const selectable = items.map((it, i) => (it.act ? i : -1)).filter(i => i >= 0);
    if (name === 'back') return this.pop();
    if (!selectable.length) return;
    if (name === 'next' || name === 'prev') {
      const pos = Math.max(0, selectable.indexOf(v.cursor));
      const nextPos = name === 'next' ? Math.min(selectable.length - 1, pos + 1) : Math.max(0, pos - 1);
      v.cursor = selectable[nextPos];
      return;
    }
    if (name === 'select') {
      const it = items[selectable.includes(v.cursor) ? v.cursor : selectable[0]];
      return it.act();
    }
  }

  openSession(id, how = 'open') {
    const s = this.pm.session(id);
    if (s.state === 'none' || s.state === 'starting') return this.confirmStart(s);
    // A queued QA scenario has no window yet; PM launches it when a slot frees.
    if (s.state === 'queued') { this.say(`${this.sessionName(s)} queued · PM launches it when a slot frees`); return; }
    this.push({ type: 'session', id, scroll: 0, opened: s.state === 'ended' ? 'ended' : how });
    if (s.state !== 'ended') this.say(`Opened existing ${s.pane} · nothing launched`);
  }

  confirmStart(s) {
    if (s.state === 'starting') { this.say(`Already starting ${s.short} · opens when ready`); return; }
    this.pushConfirm({
      title: `Start ${this.pm.prLabel(s.pr)} ${s.role}?`.trim(),
      lines: [`${s.role} is not running.`, ...(s.effects || []), 'Repeated taps join this request.'],
      yes: `Start ${s.short}`, no: 'Cancel',
      run: () => {
        const r = this.pm.start(s.id);
        this.pop();
        if (!r.ok) return this.fail(r);
        this.say(r.already === 'starting' ? `Already starting ${s.short}` : `Starting ${s.short} (${r.id}) · not opened twice`);
      },
    });
  }

  // Confirmation screen: dim explanation lines, then the confirming choice
  // (selected) and the cancelling one.
  pushConfirm(confirm) {
    this.push({ type: 'list', kind: 'confirm', cursor: Math.max(CONFIRM_LINES, confirm.lines.length), top: 0, confirm });
  }

  fail(r) {
    const why = { offline: '! Not sent: PM unreachable · nothing queued', 'not-running': '! Session not running · start it first' }[r.reason] || `! ${r.reason}`;
    this.say(why);
  }

  items(v) {
    const pm = this.pm;
    const it = (l, r, act) => ({ l, r, act });
    switch (v.kind) {
      case 'home': {
        const needs = pm.needsYou();
        const out = needs.map(n => it(`${n.glyph} ${n.text}`, { t: n.state, dim: false }, () => this.openNeed(n)));
        const running = pm.sessions.filter(s => LIVE.has(s.state)).length;
        out.push(it('Sessions', { t: `${running} live`, dim: true }, () => this.push({ type: 'list', kind: 'sessions', cursor: 0, top: 0 })));
        out.push(it('PRs and status', { t: `${pm.prs.filter(p => p.status !== 'merged').length} open`, dim: true }, () => this.push({ type: 'list', kind: 'prs', cursor: 0, top: 0 })));
        return out;
      }
      case 'doc-actions': {
        const d = pm.doc(v.docId), latest = pm.latest(v.docId), shown = pm.version(v.docId, v.version);
        const s = pm.session(d.session);
        const out = [];
        out.push(it(`Discuss in ${this.sessionName(s)}`, stateCell(s), () => { this.pop(); this.openSession(s.id, 'discuss'); }));
        out.push(it('Request changes (speak)', null, () => { this.pop(); this.startListening('changes'); }));
        if (latest.n !== shown.n) out.push(it(`What changed v${shown.n} → v${latest.n}`, null, () => { this.pop(); this.whatChanged(v.docId, shown.n, latest.n); }));
        if (d.pending) {
          out.push(latest.n === shown.n
            ? it(`Approve v${shown.n}…`, { t: d.kind === 'plan' ? 'proposed' : `${shown.hash}`, dim: true }, () => this.confirmApprove(v.docId, shown))
            : it(`Approve: read v${latest.n} first`, { t: 'blocked', dim: true }, () => this.say(`v${shown.n} is not current · approval needs v${latest.n}`)));
        } else if (d.approved) out.push(it(`Approved v${d.approved.version}`, { t: d.approved.at, dim: true }, null));
        if (d.pr) out.push(it(`Sessions for ${pm.prLabel(d.pr)}`, null, () => this.push({ type: 'list', kind: 'sessions-pr', pr: d.pr, cursor: 0, top: 0 })));
        if (d.pr) out.push(it(`${pm.prLabel(d.pr)} status`, null, () => this.push({ type: 'list', kind: 'pr', pr: d.pr, cursor: 0, top: 0 })));
        out.push(it('Back to reading', null, () => this.pop()));
        return out;
      }
      case 'session-actions': {
        const s = pm.session(v.id);
        const origin = this.originDoc();
        const out = [];
        if (s.state !== 'ended') out.push(it('Speak to this session', null, () => { this.pop(); this.startListening(); }));
        else out.push(it(`Start new ${s.short} session…`, null, () => { this.pop(); this.confirmStart({ ...s, state: 'none' }); }));
        if (s.scenario != null && s.helper) out.push(it(`Other s${s.scenario} sessions`, null, () => this.jumpTo({ type: 'list', kind: 'scenario', pr: s.pr, run: s.run, k: s.scenario, cursor: 0, top: 0 })));
        if (s.pr) out.push(it(`All ${pm.prLabel(s.pr)} sessions`, null, () => this.jumpTo({ type: 'list', kind: 'sessions-pr', pr: s.pr, cursor: 0, top: 0 })));
        if (origin) out.push(it(`Return to ${this.docName(origin)}`, null, () => this.returnTo(origin)));
        out.push(it('Back to session', null, () => this.pop()));
        return out;
      }
      case 'sessions': {
        const out = [];
        for (const p of pm.prs.filter(p => pm.sessionsFor(p.id).length)) {
          const ss = pm.sessionsFor(p.id);
          const live = ss.filter(s => LIVE.has(s.state));
          const attn = ss.some(s => ATTENTION.has(s.state));
          out.push(it(`#${p.num} ${p.title}`, { t: `${attn ? '? ' : ''}${live.length}/${ss.length} live`, dim: !attn },
            () => this.push({ type: 'list', kind: 'sessions-pr', pr: p.id, cursor: 0, top: 0 })));
        }
        const proj = pm.projectSessions();
        out.push(it('Plans and project', { t: `${proj.filter(s => LIVE.has(s.state)).length}/${proj.length} live`, dim: true },
          () => this.push({ type: 'list', kind: 'project', cursor: 0, top: 0 })));
        return out;
      }
      case 'sessions-pr': {
        const ss = pm.sessionsFor(v.pr);
        const out = [];
        // Merge recovery is listed only when its window exists (session-inventory.md).
        const top = ss.filter(s => s.run == null && !(s.short === 'merge' && s.state === 'none'));
        const order = ['impl', 'review', 'sign-off', 'merge', 'claude'];
        top.sort((a, b) => order.indexOf(a.short) - order.indexOf(b.short));
        const runs = [...new Set(ss.filter(s => s.run != null).map(s => s.run))];
        for (const s of top.filter(s => ['impl', 'review'].includes(s.short))) out.push(it(s.role, stateCell(s), () => this.openSession(s.id)));
        for (const run of runs) {
          const rs = ss.filter(s => s.run === run);
          const scen = new Set(rs.filter(s => s.scenario > 0).map(s => s.scenario));
          const attn = rs.some(s => ATTENTION.has(s.state));
          out.push(it(`QA run ${run} · ${scen.size} scenarios`, { t: `${attn ? '? ' : ''}${rs.length} sessions ›`, dim: !attn },
            () => this.push({ type: 'list', kind: 'qa-run', pr: v.pr, run, cursor: 0, top: 0 })));
        }
        for (const s of top.filter(s => !['impl', 'review'].includes(s.short))) out.push(it(s.role, stateCell(s), () => this.openSession(s.id)));
        return out;
      }
      case 'qa-run': {
        const rs = pm.sessionsFor(v.pr).filter(s => s.run === v.run);
        const out = [];
        const one = short => rs.find(s => s.short === short);
        const planner = one('planner');
        if (planner) out.push(it('Planner', stateCell(planner), () => this.openSession(planner.id)));
        const s0 = rs.find(s => s.scenario === 0);
        if (s0) out.push(it('s0 Interactive', stateCell(s0), () => this.openSession(s0.id)));
        const ks = [...new Set(rs.filter(s => s.scenario > 0).map(s => s.scenario))].sort((a, b) => a - b);
        for (const k of ks) {
          const parts = rs.filter(s => s.scenario === k);
          const title = parts[0].scenarioTitle;
          const summary = scenarioSummary(parts);
          out.push(it([{ t: `s${k}` }, { t: title, x: INDENT + 26 }], summary,
            () => (parts[0].helper == null ? this.openSession(parts[0].id) : this.push({ type: 'list', kind: 'scenario', pr: v.pr, run: v.run, k, cursor: 0, top: 0 }))));
        }
        const fin = one('finalize');
        // Finalize is launched by PM once every scenario has a verdict; it is not user-startable.
        out.push(fin ? it('Finalize', stateCell(fin), () => this.openSession(fin.id)) : it('Finalize', { t: '· after all verdicts', dim: true }, null));
        return out;
      }
      case 'scenario': {
        const parts = pm.sessionsFor(v.pr).filter(s => s.run === v.run && s.scenario === v.k);
        const by = h => parts.find(s => s.helper === h);
        const out = [];
        for (const [h, label, absent] of [['refiner', 'Refiner', 'pane gone'], ['worker', 'Execution', 'not launched'], ['verifier', 'Verifier', 'on first PASS']]) {
          const s = by(h);
          out.push(s ? it(`${label}`, stateCell(s), () => this.openSession(s.id)) : it(label, { t: `· ${absent}`, dim: true }, null));
        }
        return out;
      }
      case 'project': {
        const out = [];
        let group = null;
        for (const s of pm.projectSessions()) {
          if (s.group !== group) {
            group = s.group;
            out.push(it([{ t: group.toUpperCase(), dim: true }], null, null));
            // Plan documents lead the PLANS group, ahead of their sessions.
            if (group === 'Plans') {
              for (const d of Object.values(pm.docs).filter(x => x.kind === 'plan')) {
                out.push(it(`${d.label} v${pm.latest(d.id).n}`, { t: d.pending ? '? review' : 'read', dim: false }, () => this.openDoc(d.id)));
              }
            }
          }
          out.push(it(s.role, stateCell(s), () => this.openSession(s.id)));
        }
        return out;
      }
      case 'prs': return pm.prs.filter(p => p.status !== 'merged').map(p => it(`#${p.num} ${p.title}`, { t: prState(p), dim: !p.needs }, () => this.push({ type: 'list', kind: 'pr', pr: p.id, cursor: 0, top: 0 })));
      case 'pr': {
        const p = pm.pr(v.pr);
        const out = [it([{ t: p.activity, dim: false }], null, null)];
        for (const h of p.holds) out.push(it([{ t: `◇ Hold: ${h}`, dim: false }], null, null));
        if (p.deps.length) out.push(it([{ t: `Waits for ${p.deps.map(d => pm.prLabel(d)).join(', ')}`, dim: true }], null, null));
        for (const d of Object.values(pm.docs).filter(d => d.pr === p.id)) {
          const latest = pm.latest(d.id);
          out.push(it(`Read ${d.phase === 'qa' ? 'QA' : d.phase} spec v${latest.n}`, { t: d.pending ? '? review' : d.approved ? '◆ approved' : '', dim: !d.pending }, () => this.openDoc(d.id)));
        }
        out.push(it('Sessions', { t: `${pm.sessionsFor(p.id).length} ›`, dim: true }, () => this.push({ type: 'list', kind: 'sessions-pr', pr: p.id, cursor: 0, top: 0 })));
        out.push(it('History and timers', null, () => this.push({ type: 'list', kind: 'history', pr: p.id, cursor: 0, top: 0 })));
        if (p.holds.length && p.signoff) out.push(it(`Merge #${p.num} now…`, { t: `signed ${p.signoff.head}`, dim: true }, () => this.confirmMerge(p)));
        const signoff = pm.sessionsFor(p.id).find(s => s.short === 'sign-off' && s.state === 'none');
        if (signoff) out.push(it('Start sign-off…', { t: 'not started', dim: true }, () => this.confirmStart(signoff)));
        return out;
      }
      case 'history': {
        const h = pm.historyFor(v.pr);
        const out = [it([{ t: 'TIMERS', dim: true }], null, null)];
        for (const t of h.timers) out.push(it([{ t: t.what }, { t: ` · ${t.owner}`, dim: true }], { t: `${t.left} → ${t.then}`, dim: false }, null));
        if (!h.timers.length) out.push(it([{ t: 'No PR-owned timers', dim: true }], null, null));
        out.push(it([{ t: 'ATTEMPTS', dim: true }], null, null));
        if (!h.attempts.length) out.push(it([{ t: 'No attempts yet', dim: true }], null, null));
        for (const [at, what, took, outcome] of h.attempts.slice(-5)) out.push(it([{ t: at, dim: true }, { t: what, x: 86 }], { t: `${took} ${outcome}`, dim: outcome !== 'running' }, null));
        return out;
      }
      case 'whatchanged': {
        const out = v.changes.map(c => it([{ t: c.key, dim: true }, { t: c.text, x: 52 }], null, () => { this.pop(); this.openDoc(v.docId, v.to, c.key); }));
        out.push(it(`Read v${v.to} from the first change`, null, () => { this.pop(); this.openDoc(v.docId, v.to, v.changes[0]?.key); }));
        return out;
      }
      case 'confirm': {
        const c = v.confirm;
        const out = c.lines.map(l => it([{ t: l, dim: true }], null, null));
        while (out.length < CONFIRM_LINES) out.push(it('', null, null));
        out.push(it(c.yes, null, c.run));
        out.push(it(c.no, null, () => this.pop()));
        return out;
      }
      case 'progress': {
        const p = pm.pr(v.pr);
        return (p.timeline || defaultTimeline(pm, p)).map(([g, label, state, dim]) => it([{ t: g }, { t: label, x: INDENT, dim: !!dim }], state ? { t: state, dim: !!dim } : null,
          label.startsWith('Implementation') ? () => this.openSession(`${v.pr}/impl`) : label.startsWith('Merge') ? () => this.push({ type: 'list', kind: 'pr', pr: v.pr, cursor: 0, top: 0 }) : null));
      }
      default: return [];
    }
  }

  // ---- documents ------------------------------------------------------
  lines(docId, n) {
    const k = `${docId}@${n}`;
    if (!this.docCache.has(k)) this.docCache.set(k, formatDoc(this.pm.version(docId, n).text));
    return this.docCache.get(k);
  }
  docName(v) { const d = this.pm.doc(v.docId); return `${d.label} v${v.version} p${this.page(v).page}`; }
  sessionName(s) {
    const pr = this.pm.prLabel(s.pr);
    if (!pr) return s.role;
    if (s.scenario != null) return `${pr} s${s.scenario} ${s.helper ? s.short : s.scenario === 0 ? 'interactive' : 'scenario'}`;
    return `${pr} ${s.short === 'planner' || s.short === 'finalize' ? 'QA ' + s.short : s.short}`;
  }

  openDoc(docId, version, anchorKey) {
    const latest = this.pm.latest(docId);
    const d = this.pm.doc(docId);
    const n = version ?? (d.pending ? d.pending.version : latest.n);
    // Re-reading another version of the open document replaces that view, so
    // Back still returns to where the document was opened from.
    const reuse = this.view.type === 'doc' && this.view.docId === docId;
    const v = reuse ? Object.assign(this.view, { version: n, top: 0 }) : { type: 'doc', docId, version: n, top: 0 };
    if (anchorKey) {
      const lines = this.lines(docId, n);
      const i = lines.findIndex(l => l.key === anchorKey);
      if (i >= 0) v.top = Math.max(0, i - 1);
    }
    if (!reuse) this.push(v);
  }
  openNeed(n) {
    if (n.kind === 'doc') return this.openDoc(n.id);
    if (n.kind === 'session') { const s = this.pm.session(n.id); return this.jumpTo({ type: 'list', kind: 'scenario', pr: s.pr, run: s.run, k: s.scenario, cursor: 0, top: 0 }); }
    if (n.kind === 'pr') return this.push({ type: 'list', kind: 'pr', pr: n.id, cursor: 0, top: 0 });
  }
  banners(v) {
    const out = [];
    const c = this.pm.conn;
    if (c.state !== 'ok') out.push(row([{ t: `${GLYPH.reconnect} ${c.state === 'offline' ? 'PM offline' : 'Reconnecting to PM'} · data ${fmtAge(c.staleFor)} old` }]));
    if (v?.type === 'doc') {
      const latest = this.pm.latest(v.docId), d = this.pm.doc(v.docId);
      if (latest.n !== v.version) out.push(row([{ t: `● Changed: v${latest.n} on desktop · you are reading v${v.version}` }]));
      else if (d.approved?.version === v.version) out.push(row([{ t: `◆ Approved v${v.version} · ${d.approved.at} · ${d.approved.by}`, dim: true }]));
    }
    return out;
  }
  page(v) {
    const per = BODY_ROWS - this.banners(v).length;
    const starts = paginate(this.lines(v.docId, v.version), per);
    let i = starts.findLastIndex(st => st <= v.top);
    if (i < 0) i = 0;
    v.top = starts[i];
    const end = Math.min(starts[i + 1] ?? Infinity, v.top + per, this.lines(v.docId, v.version).length);
    return { per, page: i + 1, pages: starts.length, starts, end };
  }
  docIntent(v, name) {
    const { page, starts } = this.page(v);
    if (name === 'next' && page < starts.length) v.top = starts[page];
    if (name === 'prev' && page > 1) v.top = starts[page - 2];
    if (name === 'select') this.push({ type: 'list', kind: 'doc-actions', docId: v.docId, version: v.version, cursor: 0, top: 0 });
    if (name === 'back') this.pop();
  }
  anchorAt(v) {
    const lines = this.lines(v.docId, v.version);
    const l = lines[Math.min(v.top, lines.length - 1)];
    return { section: l?.section || '', key: l?.key, page: this.page(v).page };
  }
  whatChanged(docId, from, to) {
    const a = this.lines(docId, from), b = this.lines(docId, to);
    const before = new Map(a.map(l => [l.key, l.segs.map(s => s.t).join(' ')]));
    const changes = [];
    for (const l of b) {
      if (!/^([A-Z]\d+|s\d+|#\d+)$/.test(l.key)) continue;
      const text = b.filter(x => x.key === l.key || x.key.startsWith(`${l.key}+`)).map(x => x.segs.at(-1).t).join(' ');
      const old = before.has(l.key) ? a.filter(x => x.key === l.key || x.key.startsWith(`${l.key}+`)).map(x => x.segs.at(-1).t).join(' ') : null;
      if (old === text) continue;
      changes.push({ key: l.key, text: `${old == null ? 'Added: ' : ''}${text.replace(/^([A-Z]\d+\.|#\d+)\s*/, '')}` });
    }
    this.push({ type: 'list', kind: 'whatchanged', docId, from, to, changes, cursor: 0, top: 0 });
  }
  confirmApprove(docId, shown) {
    const d = this.pm.doc(docId);
    const plan = d.kind === 'plan';
    this.pushConfirm({
      title: `Approve ${d.label} v${shown.n}?`,
      lines: plan
        ? [`Content ${shown.hash} · the version you read`, 'PROPOSED: PM has no plan approval today.', 'Then: load new PRs; start nothing else.']
        : [`Content ${shown.hash} · the version you read`, 'Then implementation resumes unattended:', 'review, QA and sign-off run automatically.', 'Merge stays manual (wait-for-merge).'],
      yes: `Approve v${shown.n}`, no: 'Cancel',
      run: () => {
        const r = this.pm.approve(docId, shown.n, shown.hash);
        this.pop();
        // The actions list was for the version just confirmed; drop it either
        // way so reading the new version replaces the document view and Back
        // does not land on stale actions.
        this.stack = this.stack.filter(x => x.type !== 'list' || x.kind !== 'doc-actions');
        if (r.ok) {
          if (d.pr) this.push({ type: 'list', kind: 'progress', pr: d.pr, cursor: 1, top: 0 });
          else this.say(`◆ Plan v${shown.n} approved (simulated)`);
          return;
        }
        if (r.reason === 'changed') {
          this.pushConfirm({
            title: '! Not approved', lines: [`${d.label} changed to v${r.latest.n} (${r.latest.hash})`, `while you confirmed v${shown.n}.`, 'Nothing was approved.'],
            yes: `What changed v${shown.n} → v${r.latest.n}`, no: 'Back',
            run: () => { this.pop(); this.whatChanged(docId, shown.n, r.latest.n); } });
          return;
        }
        this.fail(r);
      },
    });
  }
  confirmMerge(p) {
    this.pushConfirm({
      title: `Merge #${p.num} now?`,
      lines: [`Sign-off MERGE at ${p.signoff.head}`, `Integration checked on ${p.signoff.base}`, 'PM re-checks both before merging.', 'This releases the manual merge hold.'],
      yes: `Merge #${p.num}`, no: 'Keep waiting',
      run: () => {
        const r = this.pm.merge(p.id, p.signoff.head);
        this.pop();
        if (r.ok) return this.say(`■ #${p.num} merged`);
        if (r.reason === 'stale') {
          this.pushConfirm({
            title: '! Merge refused by PM', lines: [`Head is ${r.head}; sign-off was ${p.signoff.head}.`, 'Sign-off runs again automatically.', 'The manual merge hold stays.'],
            yes: 'History and timers', no: 'Back', run: () => { this.pop(); this.push({ type: 'list', kind: 'history', pr: p.id, cursor: 0, top: 0 }); } });
          return;
        }
        this.fail(r);
      },
    });
  }

  // ---- sessions -------------------------------------------------------
  originDoc() { return [...this.stack].reverse().find(x => x.type === 'doc'); }
  returnTo(target) { while (this.view !== target && this.stack.length > 1) this.stack.pop(); }
  jumpTo(v) {
    // Reuse an equivalent list already on the stack instead of growing it.
    // Scenario numbers are unique only within a QA run, so the run is part of the identity.
    const i = this.stack.findIndex(x => x.type === 'list' && x.kind === v.kind && x.pr === v.pr && x.run === v.run && x.k === v.k);
    if (i >= 0) { this.stack.length = i + 1; return; }
    this.push(v);
  }
  transcriptLines(s) {
    const out = [];
    for (const m of s.transcript || []) {
      const lead = { agent: '', user: '› ', tool: '· ', pm: '— ' }[m.who];
      const dim = m.who !== 'agent';
      const text = m.who === 'user' && m.context ? `${m.t}  [${m.context.label}]` : m.t;
      const lines = wrap(text + (m.streaming ? ' …' : '') + (m.queued ? '  (queued)' : ''), TEXT_WIDTH - (lead ? 16 : 0));
      lines.forEach((t, i) => out.push(lead ? [{ t: i ? '' : lead.trim(), dim }, { t, x: 16, dim }] : [{ t }]));
    }
    return out;
  }
  sessionIntent(v, name) {
    const s = this.pm.session(v.id);
    const lines = this.transcriptLines(s);
    const per = BODY_ROWS - 1 - this.banners(v).length - (s.scenarioTitle ? 1 : 0);
    if (name === 'prev') v.scroll = Math.min(Math.max(0, lines.length - per), v.scroll + per);
    if (name === 'next') v.scroll = Math.max(0, v.scroll - per);
    if (name === 'select') this.push({ type: 'list', kind: 'session-actions', id: v.id, cursor: 0, top: 0 });
    if (name === 'back') this.pop();
  }

  // ---- voice ----------------------------------------------------------
  target() {
    const v = this.view;
    if (v.type === 'doc') return { session: this.pm.doc(v.docId).session, doc: v };
    if (v.type === 'session') return { session: v.id, doc: this.originDoc() };
    return null;
  }
  startListening(purpose = 'discuss') {
    const t = this.target();
    if (!t) { this.say('Open a document or session to speak'); return; }
    this.overlay = { stage: 'listening', purpose, words: '', target: t, choice: 0 };
    this.toast = null; // the panel's own hints replace any earlier notice
  }
  overlayRows() { return !this.overlay ? 0 : this.overlay.stage === 'listening' ? 2 : 4; }
  overlayIntent(name) {
    const o = this.overlay;
    if (o.stage === 'listening') {
      if (name === 'release') { o.stage = 'review'; o.text = this.nextUtterance || '(no speech recognized)'; this.nextUtterance = null; }
      else if (name === 'back') this.overlay = null;
      return;
    }
    if (name === 'next') o.choice = Math.min(VOICE_CHOICES.length - 1, o.choice + 1);
    if (name === 'prev') o.choice = Math.max(0, o.choice - 1);
    if (name === 'back') { this.overlay = null; this.say('Cancelled · nothing sent'); return; }
    if (name === 'hold') { this.overlay = { ...o, stage: 'listening', words: '' }; return; }
    if (name !== 'select') return;
    if (VOICE_CHOICES[o.choice] === 'Cancel') { this.overlay = null; this.say('Cancelled · nothing sent'); return; }
    if (VOICE_CHOICES[o.choice] === 'Speak again') { this.overlay = { ...o, stage: 'listening', words: '', choice: 0 }; return; }
    const ctx = this.contextFor(o.target);
    const text = o.purpose === 'changes' ? `Please revise: ${o.text}` : o.text;
    const r = this.pm.send(o.target.session, text, ctx);
    this.overlay = null;
    if (!r.ok) return this.fail(r);
    const s = this.pm.session(o.target.session);
    this.say(r.queued ? `Queued in ${this.sessionName(s)} (busy) · same session` : `Sent to ${this.sessionName(s)} · ${GLYPH.idle} waiting for reply`);
  }
  contextFor(t) {
    if (!t.doc) return null;
    const d = this.pm.doc(t.doc.docId), shown = this.pm.version(t.doc.docId, t.doc.version);
    const a = this.anchorAt(t.doc);
    return { doc: d.id, version: shown.n, hash: shown.hash, section: a.section, page: a.page,
      label: `${d.label} v${shown.n} ${shown.hash} · ${a.section ? a.section.replace(/^\d+\.\s*/, '') + ' · ' : ''}p${a.page}` };
  }

  // ---- render ---------------------------------------------------------
  render() {
    const v = this.view;
    let frame;
    if (v.type === 'doc') frame = this.renderDoc(v);
    else if (v.type === 'session') frame = this.renderSession(v);
    else frame = this.renderList(v);
    if (this.overlay) frame = this.renderOverlay(frame);
    // A notice takes the whole footer for one frame; hints return on the next input.
    if (this.toast) frame.footer = { left: this.toast, right: '' };
    if (this.exitRequested) frame.footer = { left: 'Root: double tap opens the system exit dialog', right: '' };
    frame.menu = MENU;
    frame.scene = this.sceneId();
    return frame;
  }
  sceneId() {
    const v = this.view;
    return [v.type, v.kind, v.docId, v.id, v.pr, v.k, this.overlay?.stage].filter(x => x != null).join(':');
  }
  renderDoc(v) {
    const d = this.pm.doc(v.docId);
    const banners = this.banners(v);
    const { page, pages, end } = this.page(v);
    const lines = this.lines(v.docId, v.version).slice(v.top, end);
    const shown = this.pm.version(v.docId, v.version);
    const state = d.pending?.version === v.version ? ' · review' : '';
    return {
      rows: [...banners, ...lines.map(l => row(l.segs.map(s => ({ ...s, dim: !!s.dim }))))],
      footer: { left: `${d.label} v${shown.n}${state} · ${page}/${pages}`, right: 'Tap: actions · Hold: speak' },
    };
  }
  renderSession(v) {
    const s = this.pm.session(v.id);
    const banners = this.banners(v);
    const head = [row([{ t: this.sessionTitle(s) }], stateCell(s))];
    if (s.scenarioTitle) head.push(row([{ t: s.scenarioTitle, dim: true }], { t: s.pane, dim: true }));
    // The voice panel displaces the oldest visible lines, so the newest reply
    // stays readable while answering it.
    const per = BODY_ROWS - head.length - banners.length - this.overlayRows();
    const lines = this.transcriptLines(s);
    const end = lines.length - v.scroll;
    const shown = lines.slice(Math.max(0, end - per), end);
    const origin = this.originDoc();
    const left = v.scroll ? `Earlier · ${v.scroll} lines up` : origin ? `« ${this.docName(origin)}` : `« ${this.breadcrumb(1)}`;
    return {
      rows: [...banners, ...head, ...shown.map(segs => row(segs))],
      footer: { left, right: s.state === 'ended' ? 'Tap: actions · 2×: back' : 'Tap: actions · Hold: speak' },
    };
  }
  sessionTitle(s) {
    if (!s.pr) return s.role;
    if (s.run != null && s.scenario != null) return `#${this.pm.pr(s.pr).num} QA run ${s.run} · s${s.scenario} ${s.role}`;
    if (s.run != null) return `#${this.pm.pr(s.pr).num} QA run ${s.run} · ${s.role}`;
    return `#${this.pm.pr(s.pr).num} ${s.role}`;
  }
  breadcrumb(skip = 0) {
    const names = this.stack.slice(0, this.stack.length - skip).map(x => this.shortName(x)).filter(Boolean);
    return names.slice(-2).join(' › ');
  }
  shortName(x) {
    if (x.type === 'doc') return `${this.pm.doc(x.docId).label} v${x.version} p${this.page(x).page}`;
    if (x.type === 'session') return this.sessionName(this.pm.session(x.id));
    return ({ home: 'Needs you', sessions: 'Sessions', prs: 'PRs', project: 'Project', 'sessions-pr': `${this.pm.prLabel(x.pr)} sessions`,
      'qa-run': `QA run ${x.run}`, scenario: `s${x.k}`, pr: this.pm.prLabel(x.pr), history: 'History', progress: 'Progress' })[x.kind] || null;
  }
  title(v) {
    const pm = this.pm;
    switch (v.kind) {
      case 'home': return [`Needs you · ${pm.project.name}`, { t: pm.now(), dim: true }];
      case 'doc-actions': { const d = pm.doc(v.docId); return [`${d.label} v${v.version}`, { t: d.pending ? 'review pending' : d.approved ? 'approved' : '', dim: true }]; }
      case 'session-actions': { const s = pm.session(v.id); return [this.sessionTitle(s), stateCell(s)]; }
      case 'sessions': return ['Sessions · all PRs', { t: `${pm.sessions.length} known`, dim: true }];
      case 'sessions-pr': { const p = pm.pr(v.pr); return [`#${p.num} sessions`, { t: p.status, dim: true }]; }
      case 'qa-run': {
        const ks = pm.sessionsFor(v.pr).filter(s => s.run === v.run && s.scenario > 0).map(s => s.scenario);
        return [`#${pm.pr(v.pr).num} QA run ${v.run}`, { t: ks.length ? `scenarios ${Math.min(...ks)}-${Math.max(...ks)}` : 'no scenarios', dim: true }];
      }
      case 'scenario': { const s = pm.sessionsFor(v.pr).find(x => x.run === v.run && x.scenario === v.k); return [`#${pm.pr(v.pr).num} run ${v.run} · s${v.k} ${s.scenarioTitle}`, null]; }
      case 'project': return ['Plans and project sessions', { t: pm.project.name, dim: true }];
      case 'prs': return ['PRs and status', { t: 'plan-sync', dim: true }];
      case 'pr': { const p = pm.pr(v.pr); return [`#${p.num} ${p.title}`, { t: p.status, dim: true }]; }
      case 'history': return [`#${pm.pr(v.pr).num} history and timers`, { t: pm.now(), dim: true }];
      case 'whatchanged': return [`${pm.doc(v.docId).label} v${v.from} → v${v.to}`, { t: `${v.changes.length} change${v.changes.length === 1 ? '' : 's'}`, dim: true }];
      case 'confirm': return [v.confirm.title, null];
      case 'progress': { const p = pm.pr(v.pr); return [`#${p.num} after approval`, { t: 'unattended', dim: true }]; }
      default: return [v.kind, null];
    }
  }
  renderList(v) {
    const items = this.items(v);
    const banners = this.banners(v);
    const per = LIST_ROWS - banners.length;
    if (v.cursor >= items.length || !items[v.cursor]?.act) v.cursor = Math.max(0, items.findIndex(i => i.act));
    if (v.cursor < v.top) v.top = v.cursor;
    if (v.cursor >= v.top + per) v.top = v.cursor - per + 1;
    const [title, right] = this.title(v);
    const rows = [...banners, row([{ t: title }], right)];
    items.slice(v.top, v.top + per).forEach((it, j) => {
      const i = v.top + j;
      const segs = Array.isArray(it.l) ? it.l : [{ t: it.l }];
      const selected = it.act && i === v.cursor;
      // Segment x positions are relative to the label column (after the cursor).
      rows.push(row([...(selected ? [{ t: GLYPH.cursor }] : []), ...segs.map((s, n) => ({ ...s, x: n === 0 || s.x != null ? INDENT + (s.x ?? 0) : undefined, dim: s.dim ?? !it.act }))], it.r));
    });
    const more = items.length > per ? ` · ${v.top + 1}-${Math.min(items.length, v.top + per)}/${items.length}` : '';
    const hint = v.kind === 'confirm' ? 'Swipe: choose · Tap: confirm' : items.some(i => i.act) ? 'Tap: open · 2×: back' : '2×: back';
    return { rows, footer: { left: `${this.breadcrumb(0) || ''}${more}`, right: hint } };
  }
  renderOverlay(frame) {
    const o = this.overlay;
    const s = this.pm.session(o.target.session);
    const rows = frame.rows.slice();
    while (rows.length < BODY_ROWS) rows.push(row());
    const ctx = this.contextFor(o.target);
    const top = BODY_ROWS - this.overlayRows();
    if (o.stage === 'listening') {
      rows.splice(top, 2,
        row([{ t: `Listening · to ${this.sessionName(s)}`, dim: true }], { t: ctx ? `about p${ctx.page}` : '', dim: true }),
        row([{ t: o.words || 'Speak now; release to review' }]));
      return { rows, panel: { top, rows: 2 }, footer: { left: o.purpose === 'changes' ? 'Request changes' : 'Speak', right: 'Release: review · 2×: cancel' } };
    }
    const text = wrap((o.purpose === 'changes' ? 'Revise: ' : '') + o.text, 528).slice(0, 2);
    let x = 10;
    const choiceSegs = VOICE_CHOICES.flatMap((c, i) => { const segs = [{ t: i === o.choice ? GLYPH.cursor : '', x }, { t: c, x: x + 22, dim: i !== o.choice }]; x += 22 + width(c) + 28; return segs; });
    rows.splice(top, 4,
      row([{ t: `To ${this.sessionName(s)} · ${s.pane !== s.short ? s.pane : 'window ' + s.window}`, dim: true, x: 6 }], { t: s.state === 'working' ? '◐ busy: queues' : '', dim: true }),
      row([{ t: text[0] || '', x: 6 }]),
      row([{ t: text[1] || (ctx ? `[${ctx.label}]` : ''), x: 6, dim: !text[1] }]),
      row(choiceSegs));
    return { rows, panel: { top, rows: 4 }, footer: { left: 'Review before sending', right: 'Swipe: choose · Tap: confirm' } };
  }
}

function scenarioSummary(parts) {
  if (parts.length === 1 && parts[0].state === 'queued') return { t: '□ queued · max 4', dim: true };
  const by = h => parts.find(s => s.helper === h);
  const ver = by('verifier'), work = by('worker'), ref = by('refiner');
  if (ref?.state === 'needs') return { t: '? refiner: input', dim: false };
  if (ver?.state === 'working') return { t: '◐ verifying', dim: false };
  if (ver?.state === 'done') return { t: `■ ${ver.stateText}`, dim: true };
  if (work?.state === 'working') return { t: `◐ ${work.stateText}`, dim: false };
  if (work) return { t: `${glyphFor(work.state)} ${work.stateText}`, dim: true };
  return { t: '·', dim: true };
}
function prState(p) {
  if (p.needs === 'spec') return '? spec review';
  if (p.needs === 'qa-input') return '? QA input';
  if (p.needs === 'merge') return '◇ manual merge';
  return { in_progress: '◐ impl', in_review: '◐ review', qa: '◐ QA', sign_off: '◐ sign-off', pending: '· pending', merged: '■ merged' }[p.status] || p.status;
}
function defaultTimeline(pm, p) {
  const d = Object.values(pm.docs).find(x => x.pr === p.id && x.approved);
  return [
    ['◆', `Spec v${d?.approved.version} approved`, `${d?.approved.at} · you`, true],
    ['◐', 'Implementation', 'running', false],
    ['□', 'Review loop', 'next', true],
    ['□', 'QA', 'after review', true],
    ['□', 'Sign-off', 'after QA', true],
    ['◇', 'Merge', 'manual hold', false],
    ['', 'Nothing needs you until merge.', '', true],
  ];
}
export function fmtAge(s) { return s >= 60 ? `${Math.floor(s / 60)}m${String(s % 60).padStart(2, '0')}s` : `${s}s`; }

export { formatDoc };
