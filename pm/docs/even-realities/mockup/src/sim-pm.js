// SIMULATED PM backend for the mockup.
//
// It models the user-facing rules the design depends on, not PM's real
// implementation:
//   - approval binds to the version (content hash) the user was shown;
//   - a changed document never inherits approval;
//   - opening an existing session never launches one; starting is explicit,
//     and repeated start requests coalesce;
//   - merge stays behind PM's sign-off gate;
//   - messages are sent at most once, also across reconnects.
// Simulated events (agent replies, revisions, disconnects) are applied by the
// director (scripts/journeys.mjs or the preview's demo buttons).
import { DOCUMENTS, SESSIONS, PRS, HISTORY, PROJECT } from './fixtures.js';

const clone = v => JSON.parse(JSON.stringify(v));

export class SimPM {
  constructor() {
    this.project = PROJECT;
    this.docs = clone(DOCUMENTS);
    this.sessions = clone(SESSIONS);
    this.prs = clone(PRS);
    this.history = clone(HISTORY);
    this.clock = [10, 25];
    this.conn = { state: 'ok', since: null, staleFor: 0, failures: 0 };
    this.pendingStarts = new Map(); // sessionId -> request id
    this.outbox = []; // messages accepted by PM (sent exactly once)
    this.seq = 0;
  }

  now() { const [h, m] = this.clock; return `${h}:${String(m).padStart(2, '0')}`; }
  tick(minutes = 1) { let [h, m] = this.clock; m += minutes; h += Math.floor(m / 60); this.clock = [h, m % 60]; }

  // ---- queries --------------------------------------------------------
  doc(id) { return this.docs[id]; }
  latest(id) { return this.docs[id].versions.at(-1); }
  version(id, n) { return this.docs[id].versions.find(v => v.n === n); }
  session(id) { return this.sessions.find(s => s.id === id); }
  pr(id) { return this.prs.find(p => p.id === id); }
  sessionsFor(prId) { return this.sessions.filter(s => s.pr === prId); }
  projectSessions() { return this.sessions.filter(s => !s.pr); }
  // A PR that never ran has no history entry yet.
  historyFor(prId) { return (this.history[prId] ??= { timers: [], attempts: [] }); }
  prLabel(prId) { const p = this.pr(prId); return p ? `#${p.num}` : ''; }
  // A current MERGE verdict is what lets the user ask PM to merge a held PR.
  signedForMerge(p) { return p.signoff?.verdict === 'MERGE' && !p.signoff.stale; }

  needsYou() {
    const items = [];
    for (const d of Object.values(this.docs)) {
      if (!d.pending) continue;
      const latest = this.latest(d.id);
      items.push({ kind: 'doc', id: d.id, glyph: '?', text: `${d.label} v${latest.n}`, state: d.kind === 'plan' ? 'plan review' : 'spec review' });
    }
    for (const s of this.sessions) {
      if (s.state !== 'needs') continue;
      const who = s.scenario != null ? `s${s.scenario} ${s.short}` : s.short;
      items.push({ kind: 'session', id: s.id, glyph: '?', text: `${this.prLabel(s.pr)} ${who}`.trim(), state: 'needs input' });
    }
    for (const p of this.prs) if (p.holds.length) items.push({ kind: 'pr', id: p.id, glyph: '◇', text: `#${p.num} merge`, state: 'manual merge' });
    return items;
  }

  // ---- commands -------------------------------------------------------
  connected() { return this.conn.state === 'ok'; }

  // Send a message into an existing session, with the reading context.
  // Returns {ok, id} or {ok:false, reason}. Never retried automatically.
  send(sessionId, text, context) {
    if (!this.connected()) return { ok: false, reason: 'offline' };
    const s = this.session(sessionId);
    if (!s || s.state === 'none' || s.state === 'ended') return { ok: false, reason: 'not-running' };
    const id = `m${++this.seq}`;
    // A busy or still-starting session takes the message after its current turn.
    const queued = s.state === 'working' || s.state === 'starting';
    (s.transcript ??= []).push({ who: 'user', t: text, context, id, queued });
    this.outbox.push({ id, sessionId, text, context });
    return { ok: true, id, queued };
  }

  // Approve exactly the version the user reviewed.
  approve(docId, version, hash) {
    if (!this.connected()) return { ok: false, reason: 'offline' };
    const d = this.doc(docId), latest = this.latest(docId);
    if (!d.pending) return { ok: false, reason: 'not-pending' };
    if (latest.n !== version || latest.hash !== hash) return { ok: false, reason: 'changed', latest };
    d.approved = { version, hash, at: this.now(), by: 'you · glasses' };
    d.pending = null;
    if (d.pr) {
      const pr = this.pr(d.pr);
      pr.activity = 'Implementation running'; pr.needs = null; pr.approvedAt = this.now();
      const s = this.session(d.session);
      if (s) { s.state = 'working'; s.stateText = 'implementing'; (s.transcript ??= []).push({ who: 'pm', t: `Spec v${version} (${hash}) approved from glasses · implementation resumed` }); }
      const h = this.historyFor(d.pr);
      h.timers = [];
      h.attempts.push([this.now(), `spec approved v${version}`, '—', 'approved'], [this.now(), 'impl', '0m', 'running']);
    }
    return { ok: true };
  }

  // Explicit start for a session that is not running. Coalesces repeats.
  start(sessionId) {
    if (!this.connected()) return { ok: false, reason: 'offline' };
    const s = this.session(sessionId);
    if (['working', 'idle', 'waiting', 'needs', 'done'].includes(s.state)) return { ok: true, already: 'running' };
    if (this.pendingStarts.has(sessionId)) return { ok: true, already: 'starting', id: this.pendingStarts.get(sessionId) };
    const id = `r${++this.seq}`;
    this.pendingStarts.set(sessionId, id);
    s.state = 'starting'; s.stateText = 'starting…';
    return { ok: true, id };
  }
  started(sessionId) {
    const s = this.session(sessionId);
    this.pendingStarts.delete(sessionId);
    s.state = 'working'; s.stateText = 'working';
    s.transcript = [{ who: 'pm', t: `Started from glasses at ${this.now()}` }, { who: 'agent', t: s.short === 'sign-off' ? `Reading the QA verdicts and evidence for ${this.prLabel(s.pr)}…` : `Loading context for ${s.role}…` }];
    if (s.pr && s.short === 'sign-off') { const p = this.pr(s.pr); p.status = 'sign_off'; p.activity = 'Sign-off running'; }
  }

  merge(prId, head) {
    if (!this.connected()) return { ok: false, reason: 'offline' };
    const p = this.pr(prId);
    if (!this.signedForMerge(p)) return { ok: false, reason: 'no-signoff' };
    if (p.currentHead && p.currentHead !== head) {
      // PM's gate refuses and reruns sign-off on the new HEAD; the old verdict
      // no longer authorizes a merge, but the manual merge hold stays.
      p.signoff = { ...p.signoff, stale: true };
      p.activity = `Sign-off rerunning on ${p.currentHead} · manual merge`;
      const s = this.sessions.find(x => x.pr === prId && x.short === 'sign-off');
      if (s) { s.state = 'working'; s.stateText = `rerun @${p.currentHead}`; (s.transcript ??= []).push({ who: 'pm', t: `Merge refused: HEAD ${p.currentHead} ≠ signed ${head} · sign-off rerunning` }); }
      this.historyFor(prId).attempts.push([this.now(), 'merge (glasses)', '—', 'refused'], [this.now(), 'sign-off', '0m', 'running']);
      return { ok: false, reason: 'stale', head: p.currentHead };
    }
    p.status = 'merged'; p.holds = []; p.activity = `Merged ${this.now()}`; p.needs = null;
    return { ok: true };
  }

  // ---- director: simulated events ----------------------------------------
  apply(event) {
    const e = typeof event === 'string' ? { type: event } : event;
    switch (e.type) {
      case 'agent-reply': {
        const s = this.session(e.session);
        const last = (s.transcript ??= []).at(-1);
        if (e.stream && last?.who === 'agent' && last.streaming) { last.t += e.text; if (e.done) delete last.streaming; }
        else s.transcript.push({ who: e.who || 'agent', t: e.text, ...(e.done === false ? { streaming: true } : {}) });
        if (e.state) { s.state = e.state; s.stateText = e.stateText || e.state; }
        break;
      }
      case 'publish-revision': { // the session rewrote the document
        const d = this.doc(e.doc);
        const next = d.revisions.shift();
        if (!next) break; // no scripted revision left (e.g. demo button pressed again)
        d.versions.push(next);
        if (d.pending) d.pending = { version: next.n, since: this.now() };
        break;
      }
      case 'progress': { // unattended PM phases after approval
        const p = this.pr(e.pr);
        Object.assign(p, e.patch || {});
        if (e.session) Object.assign(this.session(e.session), e.sessionPatch);
        if (e.history) this.historyFor(e.pr).attempts.push(e.history);
        break;
      }
      case 'session': Object.assign(this.session(e.id), e.patch); break;
      case 'started': this.started(e.session); break;
      case 'head-moved': this.pr(e.pr).currentHead = e.head; break;
      case 'disconnect': this.conn = { state: 'reconnecting', since: this.now(), staleFor: e.stale || 42, failures: 3 }; break;
      case 'offline': this.conn = { ...this.conn, state: 'offline', staleFor: e.stale || 300 }; break;
      case 'reconnect': this.conn = { state: 'ok', since: null, staleFor: 0, failures: 0, recovered: true }; break;
      case 'tick': this.tick(e.minutes || 1); break;
      default: throw new Error(`unknown director event ${e.type}`);
    }
  }
}
