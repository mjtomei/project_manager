// Runs the demo journeys in Node against the same controller the glasses use,
// validates every frame against the documented container limits, checks each
// screenshot's expected scene/text, and prints a text rendering per shot.
//   node scripts/check.mjs [--quiet] [journey-id...]
import { SimPM } from '../src/sim-pm.js';
import { App } from '../src/app.js';
import { buildFrame, pageDefinition } from '../src/frame.js';
import { JOURNEYS } from './journeys.mjs';

const INPUT = { down: 'next', up: 'prev', click: 'select', double_click: 'back', long_press: 'hold', long_press_release: 'release' };
const args = process.argv.slice(2);
const quiet = args.includes('--quiet');
const only = args.filter(a => !a.startsWith('--'));
let failures = 0, shots = 0, frames = 0;

export function frameText(frame) {
  return frame.rows.map(r => (r ? [...r.l.map(s => s.t), r.r?.t || ''].join(' ') : '')).join('\n') + '\n' + (frame.footer?.left || '') + ' ' + (frame.footer?.right || '');
}
function show(frame) {
  const out = [];
  for (let i = 0; i < 9; i++) {
    const r = frame.rows[i];
    const left = r ? r.l.map(s => (s.dim ? `‹${s.t}›` : s.t)).join(' ') : '';
    const right = r?.r ? (r.r.dim ? `‹${r.r.t}›` : r.r.t) : '';
    out.push(`  │${(left + (right ? '  ⟶ ' + right : '')).padEnd(78)}│${frame.panel && i >= frame.panel.top && i < frame.panel.top + frame.panel.rows ? ' ▒' : ''}`);
  }
  out.push(`  ├${'─'.repeat(78)}┤`);
  out.push(`  │${(`${frame.footer?.left || ''}   ‹${frame.footer?.right || ''}›`).padEnd(78)}│`);
  return out.join('\n');
}

for (const j of JOURNEYS) {
  if (only.length && !only.includes(j.id)) continue;
  let app = new App(new SimPM());
  console.log(`\n=== Journey ${j.id}: ${j.title}`);
  for (const [n, step] of j.steps.entries()) {
    if (step.reset) app = new App(new SimPM());
    else if (step.input) app.intent(INPUT[step.input]);
    else if (step.menu) app.intent('menu', step.menu);
    else if (step.pm) app.pmEvent(step.pm);
    else if (step.speech) app.nextUtterance = step.speech;
    else if (step.words) { if (app.overlay?.stage === 'listening') app.overlay.words = step.words; }
    const frame = app.render();
    const built = buildFrame(frame); pageDefinition(built); frames++;
    if (built.problems.length) { failures++; console.log(`  ! step ${n} ${frame.scene}: ${built.problems.join('; ')}`); }
    if (!step.shot) continue;
    shots++;
    // Match against the fitted text, so a truncated row or footer fails.
    const text = frameText(built.shown);
    const errs = [];
    if (step.expect && !frame.scene.includes(step.expect)) errs.push(`scene ${frame.scene} lacks ${step.expect}`);
    if (step.contains && !text.includes(step.contains)) errs.push(`text lacks "${step.contains}"`);
    if (errs.length) failures++;
    console.log(`\n${errs.length ? 'FAIL' : 'ok  '} ${step.shot}  [${frame.scene}]${errs.length ? '\n  ' + errs.join('\n  ') : ''}`);
    if (!quiet || errs.length) console.log(show({ ...built.shown, panel: frame.panel }));
  }
}
// Rules outside the scripted shots. A message carries the originating
// document's reading context only into a session that document belongs to.
if (!only.length) {
  const spoken = (from, sessionId) => {
    const app = new App(new SimPM());
    app.openDoc(from);
    app.openSession(sessionId);
    app.nextUtterance = 'rule check';
    for (const i of ['hold', 'release', 'select']) app.intent(i);
    return app.pm.session(sessionId).transcript.at(-1).context?.doc ?? null;
  };
  for (const [from, to, want] of [
    ['spec:pr-214:impl', 'pr-214/impl', 'spec:pr-214:impl'],
    ['spec:pr-215:qa', 'pr-215/qa/run2/s2/verifier', 'spec:pr-215:qa'],
    ['plan:plan-sync', 'plan-sync/review', 'plan:plan-sync'],
    ['spec:pr-214:impl', 'pr-216/impl', null],
  ]) {
    const got = spoken(from, to);
    if (got !== want) { failures++; console.log(`FAIL rule: ${from} → ${to} context ${got}, expected ${want}`); }
  }
  const rule = (ok, what) => { if (!ok) { failures++; console.log(`FAIL rule: ${what}`); } };
  // A connection banner never pushes the newest attempt off the history view.
  {
    const app = new App(new SimPM());
    app.pm.apply({ type: 'head-moved', pr: 'pr-211', head: 'f00d123' });
    app.pm.merge('pr-211', 'a1b2c3d');
    app.pmEvent({ type: 'disconnect' });
    app.push({ type: 'list', kind: 'history', pr: 'pr-211', cursor: 0, top: 0 });
    const [at, what, took, outcome] = app.pm.historyFor('pr-211').attempts.at(-1);
    const rows = app.render().rows.map(r => r ? [...r.l.map(s => s.t), r.r?.t || ''].join(' ') : '');
    rule(rows.includes(`${at} ${what} ${took} ${outcome}`), `history under a banner hides newest attempt "${what}"`);
  }
  // Any session needing input (not only a QA helper) is listed and opens directly.
  {
    const app = new App(new SimPM());
    app.pmEvent({ type: 'session', id: 'pr-216/impl', patch: { state: 'needs', stateText: 'question' } });
    const need = app.pm.needsYou().find(n => n.id === 'pr-216/impl');
    rule(need?.text === '#216 impl', `needs-you label ${need?.text}`);
    if (need) app.openNeed(need);
    rule(app.view.type === 'session' && app.view.id === 'pr-216/impl', `needs-you opened ${app.sceneId()}`);
  }
  // What changed lists removed items too, without a jump target.
  {
    const app = new App(new SimPM());
    app.pm.apply({ type: 'publish-revision', doc: 'spec:pr-214:impl' });
    app.lines('spec:pr-214:impl', 3).splice(0, Infinity, ...app.lines('spec:pr-214:impl', 3).filter(l => !/^R1(\+|$)/.test(l.key)));
    app.whatChanged('spec:pr-214:impl', 2, 3);
    const removed = app.view.changes.find(c => c.key === 'R1');
    rule(removed?.removed && removed.text.startsWith('Removed: '), 'what changed omits a removed requirement');
    rule(app.items(app.view).every(i => !i.act || !i.l?.[0]?.t?.startsWith?.('R1')), 'removed change is selectable');
  }
  // Every live session takes a message, also one PM shows without a transcript
  // (meta, watchers); one still starting queues it instead of claiming delivery.
  for (const s of new SimPM().sessions.filter(x => ['working', 'idle', 'waiting', 'needs'].includes(x.state))) {
    try {
      const r = new SimPM().send(s.id, 'rule check', null);
      rule(r.ok && r.queued === (s.state === 'working'), `send to ${s.id} → ${JSON.stringify(r)}`);
    } catch (e) { rule(false, `send to ${s.id} threw ${e.message}`); }
  }
  {
    const pm = new SimPM();
    pm.start('pr-215/signoff');
    rule(pm.send('pr-215/signoff', 'rule check', null).queued, 'send to a starting session is not queued');
  }
  // What changed strips a scenario's own number (s2.) as it does R1. and #214.
  {
    const app = new App(new SimPM());
    const d = app.pm.doc('spec:pr-215:qa'), v1 = d.versions[0];
    d.versions.push({ ...v1, n: 2, hash: 'beef', text: v1.text.replace('- s2. Banner clears', '- s2. Banner now clears') });
    app.whatChanged(d.id, 1, 2);
    const c = app.view.changes.find(x => x.key === 's2');
    rule(c && c.text.startsWith('Banner now clears'), `what changed s2 text "${c?.text}"`);
  }
  // Leaving a voice review through the OS menu says the message was not sent.
  {
    const app = new App(new SimPM());
    app.openDoc('spec:pr-214:impl');
    app.nextUtterance = 'rule check';
    for (const i of ['hold', 'release']) app.intent(i);
    app.intent('menu', 2);
    rule(!app.overlay && app.toast === 'Cancelled · nothing sent', `menu during voice review: toast ${app.toast}`);
    rule(!app.pm.session('pr-214/impl').transcript.some(m => m.t === 'rule check'), 'menu during voice review sent the message');
  }
  // Merge now is offered only with a current MERGE verdict, the one PM accepts.
  {
    const app = new App(new SimPM());
    const p = app.pm.pr('pr-211');
    const offered = () => app.items({ type: 'list', kind: 'pr', pr: p.id }).some(i => i.act && /^Merge #/.test(i.l));
    rule(offered(), 'Merge now not offered with a MERGE sign-off');
    p.signoff = { ...p.signoff, verdict: 'REVIEW' };
    rule(!offered(), 'Merge now offered without a MERGE verdict');
    app.fail(app.pm.merge(p.id, p.signoff.head));
    rule(!app.toast.includes('no-signoff'), `merge refusal shows raw reason: ${app.toast}`);
  }
  // An action that leads elsewhere closes its actions list: Back returns to
  // the document or session, not to a stale actions list.
  for (const [open, label, under] of [
    [a => a.openDoc('spec:pr-214:impl'), /^Sessions for/, 'doc'],
    [a => a.openDoc('spec:pr-214:impl'), /status$/, 'doc'],
    [a => a.openSession('pr-216/review'), /^All #216/, 'session'],
    [a => a.openSession('pr-215/qa/run2/s2/verifier'), /^Other s2/, 'session'],
  ]) {
    const app = new App(new SimPM());
    open(app);
    app.intent('select');
    app.items(app.view).find(i => label.test(i.l)).act();
    app.intent('back');
    rule(app.view.type === under, `${label} then Back landed on ${app.sceneId()}`);
  }
  // Holding to speak to a session that is not running is refused before
  // listening, so nothing is dictated only to be dropped on send.
  for (const [open, id] of [[a => a.openSession('pr-215/impl'), 'pr-215/impl'], [a => { a.pm.session('pr-214/impl').state = 'none'; a.openDoc('spec:pr-214:impl'); }, 'pr-214/impl']]) {
    const app = new App(new SimPM());
    open(app);
    app.intent('hold');
    rule(!app.overlay && /not running/.test(app.toast || ''), `hold on ${id} (not running) opened ${app.overlay?.stage ?? 'nothing'}, toast ${app.toast}`);
  }
  // Choosing the OS menu item for the view already shown does not stack a copy.
  {
    const app = new App(new SimPM());
    for (let i = 0; i < 3; i++) app.intent('menu', 2);
    rule(app.stack.length === 2, `menu Sessions ×3 stacked ${app.stack.map(x => x.kind || x.type).join(' › ')}`);
  }
}
console.log(`\n${shots} screenshots, ${frames} frames checked, ${failures} failure(s)`);
process.exit(failures ? 1 : 0);
