// Page entry: wires the simulated PM, the controller, a display backend, the
// companion (phone) view and the director that injects simulated events.
import { waitForEvenAppBridge } from '@evenrealities/even_hub_sdk';
import { SimPM } from './sim-pm.js';
import { App } from './app.js';
import { SdkDisplay, CanvasDisplay, intentForEvent } from './display.js';
import { renderCompanion } from './companion.js';
import { keyIntent } from './input.js';

let pm = new SimPM();
let app = new App(pm);
const mirror = new CanvasDisplay(document.getElementById('mirror'));
let glasses = null;
let directorSeq = 0;
let directorFailed = false;

const log = (...a) => console.log(...a);

function draw() {
  const frame = app.render();
  mirror.show(frame).then(problems => { document.getElementById('problems').textContent = problems.join('\n'); });
  if (glasses) glasses.show(frame);
  renderCompanion(document.getElementById('companion'), app, pm, act);
  if (app.exitRequested && glasses) log('EXIT-REQUEST (root double tap would call shutDownPageContainer(1))');
}

function act(name, arg) {
  if (name === 'lifecycle') { log(`LIFECYCLE ${arg}`); return; }
  if (name !== 'noop') app.intent(name, arg);
  draw();
}

function applyDirector(e) {
  if (e.type === 'reset') { pm = new SimPM(); app = new App(pm); }
  else if (e.type === 'speech') app.nextUtterance = e.text;
  else if (e.type === 'words') { if (app.overlay?.stage === 'listening') app.overlay.words = e.text; }
  else if (e.type === 'intent') { act(e.name, e.arg); return; }
  else if (e.type === 'pm') app.pmEvent(e.event);
  else throw new Error(`unknown director event ${e.type}`);
  draw();
}

// Poll on an interval with an in-flight guard: a single lost timer callback
// (the SDK wraps WebView timers) cannot stop the director, and the request
// timeout keeps one hung fetch from holding the guard forever.
// The first poll only skips to the queue's end: events posted for an earlier
// page load (a previous capture or demo) must not replay into fresh state.
let polling = false;
async function pollDirector(skip = false) {
  if (polling) return;
  polling = true;
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), 2000);
  try {
    const r = await fetch(`/director?since=${directorSeq}`, { cache: 'no-store', signal: abort.signal });
    if (r.ok) {
      const { events, seq } = await r.json();
      directorSeq = seq;
      // The server queues any JSON object, so one unknown or broken event is
      // logged and skipped; it must not drop the rest of the batch.
      if (!skip) for (const e of events) {
        log(`DIRECTOR ${e.type}`);
        try { applyDirector(e); } catch (err) { log(`DIRECTOR ignored ${e.type}: ${err?.message || err}`); }
      }
    }
  } catch (e) { if (!directorFailed) log(`DIRECTOR unavailable: ${e?.message || e}`); directorFailed = true; }
  finally { clearTimeout(timer); polling = false; }
}

// The SDK hands out a bridge even in a plain browser (its postMessage then
// fails), so only the host's injected window.flutter_inappwebview (Even app,
// official simulator) means glasses are attached.
async function hasEvenHost(ms) {
  for (const end = Date.now() + ms; !window.flutter_inappwebview && Date.now() < end;) await new Promise(r => setTimeout(r, 100));
  return Boolean(window.flutter_inappwebview);
}

async function connectGlasses() {
  const bridge = await hasEvenHost(2500) && await Promise.race([waitForEvenAppBridge(), new Promise(r => setTimeout(() => r(null), 2500))]);
  if (!bridge) { document.body.dataset.mode = 'browser'; log('No Even host: browser preview only'); return; }
  document.body.dataset.mode = 'even';
  glasses = new SdkDisplay(bridge, log);
  bridge.onEvenHubEvent(event => {
    const i = intentForEvent(event);
    if (i) act(...i);
  });
  draw();
}

document.addEventListener('keydown', e => {
  if (e.target.closest?.('input, textarea')) return;
  const i = keyIntent(e, 'down');
  if (i) { e.preventDefault(); act(...i); }
});
document.addEventListener('keyup', e => {
  const i = keyIntent(e, 'up');
  if (i) { e.preventDefault(); act(...i); }
});
// A demo button gives focus back after its click, so the next Enter or Space
// taps the glasses instead of clicking the button again.
for (const b of document.querySelectorAll('[data-demo]')) {
  b.addEventListener('click', () => { b.blur(); applyDirector(JSON.parse(b.dataset.demo)); });
}

draw();
// Before the first glasses frame, so the capture script (which waits for that
// frame before posting) cannot have its first event skipped.
await pollDirector(true);
connectGlasses();
setInterval(pollDirector, 150);
