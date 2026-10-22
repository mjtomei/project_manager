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
console.log(`\n${shots} screenshots, ${frames} frames checked, ${failures} failure(s)`);
process.exit(failures ? 1 : 0);
