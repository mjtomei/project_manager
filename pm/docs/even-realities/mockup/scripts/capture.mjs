// Drive the official Even Hub simulator through the demo journeys and save
// glasses screenshots (576x288) plus a few companion (phone WebView) shots.
//
//   npm ci && node scripts/capture.mjs [--out ../screenshots] [A B ...]
//
// Linux without a display needs Xvfb and dbus-run-session (the simulator is a
// GTK/WebKitGTK app); this script wraps it with `xvfb-run -a` when DISPLAY is
// unset. Real touchpad actions go through the simulator's automation API
// (/api/input). SIMULATED PM events, agent replies and speech results go
// through the mockup server's /director queue. Labelled PNGs (black
// background, 2x, caption strip) are made with ffmpeg when it is available.
import { spawn, execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { JOURNEYS, PHONE_SHOTS } from './journeys.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..');
const args = process.argv.slice(2);
const outArg = args.indexOf('--out');
const out = path.resolve(outArg >= 0 ? args[outArg + 1] : path.join(root, '..', 'screenshots'));
const only = args.filter((a, i) => !a.startsWith('--') && args[i - 1] !== '--out');
const PORT = Number(process.env.MOCKUP_PORT || 5180);
const SIM = Number(process.env.SIMULATOR_PORT || 9898);
const sleep = ms => new Promise(r => setTimeout(r, ms));
const pkg = name => JSON.parse(fs.readFileSync(path.join(root, 'node_modules', name, 'package.json'), 'utf8')).version;

const children = [];
function start(cmd, argv, logFile) {
  const log = fs.openSync(logFile, 'w');
  const child = spawn(cmd, argv, { cwd: root, stdio: ['ignore', log, log], detached: true });
  children.push(child);
  return child;
}
function stopAll() {
  for (const c of children) { try { process.kill(-c.pid, 'SIGTERM'); } catch { /* gone */ } }
}
process.on('exit', stopAll);
process.on('SIGINT', () => { stopAll(); process.exit(130); });

function simulatorBinary() {
  const plat = `${process.platform}-${process.arch}`;
  const p = path.join(root, 'node_modules', '@evenrealities', `sim-${plat}`, 'bin', process.platform === 'win32' ? 'evenhub-simulator.exe' : 'evenhub-simulator');
  if (!fs.existsSync(p)) throw new Error(`simulator binary for ${plat} not found; run npm ci`);
  return p;
}

async function api(method, p, body) {
  const r = await fetch(`http://127.0.0.1:${SIM}${p}`, { method, headers: body ? { 'content-type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined });
  if (!r.ok) throw new Error(`${method} ${p} -> ${r.status}`);
  return r;
}
async function director(event) {
  const r = await fetch(`http://127.0.0.1:${PORT}/director`, { method: 'POST', body: JSON.stringify(event) });
  if (!r.ok) throw new Error(`director -> ${r.status}`);
}

let consoleId = 0, lastFrame = { seq: 0, scene: '' };
const problems = [];
const recent = [];
async function pollConsole() {
  const r = await api('GET', `/api/console?since_id=${consoleId}`);
  const { entries } = await r.json();
  for (const e of entries) {
    consoleId = Math.max(consoleId, e.id + 1);
    recent.push(e.message); if (recent.length > 12) recent.shift();
    const m = /^FRAME (\d+) (.*)$/.exec(e.message);
    if (m) lastFrame = { seq: Number(m[1]), scene: m[2] };
    if (/^(CONSTRAINT|SDKERROR)|\[uncaught\]|\[unhandledrejection\]/.test(e.message)) problems.push(e.message);
  }
}
async function waitFrame(after, timeout = 5000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeout) {
    await pollConsole();
    if (lastFrame.seq > after) return lastFrame;
    await sleep(60);
  }
  throw new Error(`no new frame after #${after} (last ${lastFrame.scene})\nrecent console:\n  ${recent.join('\n  ')}`);
}

const hasFfmpeg = (() => { try { execFileSync('ffmpeg', ['-version'], { stdio: 'ignore' }); return true; } catch { return false; } })();
function label(raw, dest, text) {
  if (!hasFfmpeg) return false;
  const font = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf';
  const safe = text.replace(/[:\\']/g, m => `\\${m}`);
  const draw = fs.existsSync(font) ? `,drawtext=fontfile=${font}:text='${safe}':x=12:y=582:fontsize=17:fontcolor=0xd8a040` : '';
  execFileSync('ffmpeg', ['-loglevel', 'error', '-y', '-f', 'lavfi', '-i', 'color=black:s=576x288', '-i', raw,
    '-filter_complex', `[0][1]overlay,scale=1152:576:flags=neighbor,pad=1152:612:0:0:0x1a1a1a${draw}`, '-frames:v', '1', dest]);
  return true;
}

async function main() {
  fs.mkdirSync(path.join(out, 'raw'), { recursive: true });
  fs.mkdirSync(path.join(out, 'phone'), { recursive: true });
  const tmp = path.join(root, '.capture-tmp');
  fs.mkdirSync(tmp, { recursive: true });
  start(process.execPath, ['server.mjs', String(PORT)], path.join(tmp, 'server.log'));
  const simArgs = [simulatorBinary(), `http://127.0.0.1:${PORT}/`, '--automation-port', String(SIM), '--no-glow'];
  // The first page creation occasionally never completes in simulator 0.9.5
  // on this host; relaunch the simulator rather than failing the capture.
  for (let attempt = 1; ; attempt++) {
    const sim = process.env.DISPLAY
      ? start('dbus-run-session', ['--', ...simArgs], path.join(tmp, 'simulator.log'))
      : start('xvfb-run', ['-a', '-s', '-screen 0 1280x1024x24', 'dbus-run-session', '--', ...simArgs], path.join(tmp, 'simulator.log'));
    try {
      for (let i = 0; ; i++) {
        try { await api('GET', '/api/ping'); break; } catch { if (i > 120) throw new Error('simulator did not start'); await sleep(250); }
      }
      await waitFrame(0, 15000);
      break;
    } catch (e) {
      if (attempt >= 3) throw e;
      console.log(`simulator start attempt ${attempt} failed (${e.message.split('\n')[0]}); retrying`);
      try { process.kill(-sim.pid, 'SIGTERM'); } catch { /* gone */ }
      await sleep(1500);
      consoleId = 0;
    }
  }
  const manifest = {
    generated: new Date().toISOString(),
    simulated: 'All PM state, agent replies, document revisions, connection changes and speech recognition are SIMULATED by the mockup. Inputs are real simulator touchpad actions.',
    simulator: `@evenrealities/evenhub-simulator ${pkg('@evenrealities/evenhub-simulator')}`,
    sdk: `@evenrealities/even_hub_sdk ${pkg('@evenrealities/even_hub_sdk')}`,
    pretext: `@evenrealities/pretext ${pkg('@evenrealities/pretext')}`,
    host: `${process.platform}-${process.arch}`,
    journeys: [],
  };
  let osMenuShot = false;
  for (const j of JOURNEYS) {
    if (only.length && !only.includes(j.id)) continue;
    const jm = { id: j.id, title: j.title, shots: [] };
    manifest.journeys.push(jm);
    const actions = [];
    for (const step of j.steps) {
      const before = lastFrame.seq;
      if (step.reset) { await director({ type: 'reset' }); await waitFrame(before); actions.push('reset'); continue; }
      if (step.input) { await api('POST', '/api/input', { action: step.input }); await waitFrame(before); actions.push(step.input); continue; }
      if (step.menu) {
        await api('POST', '/api/input', { action: 'context_menu' });
        await sleep(500);
        if (!osMenuShot) {
          osMenuShot = true;
          const buf = Buffer.from(await (await api('GET', '/api/screenshot/glasses')).arrayBuffer());
          fs.writeFileSync(path.join(out, 'raw', 'X01-os-menu.png'), buf);
          label(path.join(out, 'raw', 'X01-os-menu.png'), path.join(out, 'X01-os-menu.png'), 'SIMULATED · Even Hub simulator · X01 OS contextual menu (app items only)');
          manifest.osMenu = { id: 'X01-os-menu', title: 'OS contextual menu', caption: 'Tap-then-hold opens Even’s menu with the app’s four items. On glasses the OS also adds Display off, Brightness and Close, which the simulator does not draw.', file: 'X01-os-menu.png', raw: 'raw/X01-os-menu.png' };
        }
        for (let i = 1; i < step.menu; i++) { await api('POST', '/api/input', { action: 'down' }); await sleep(150); }
        await api('POST', '/api/input', { action: 'click' });
        await waitFrame(before);
        // The OS menu reports closing (sysEvent 5) after the item event; input
        // sent before that is swallowed by the closing menu in simulator 0.9.5.
        await sleep(700);
        actions.push(`menu ${step.menu}`);
        continue;
      }
      if (step.pm) { await director({ type: 'pm', event: step.pm }); await waitFrame(before); actions.push(`SIMULATED pm:${step.pm.type}`); continue; }
      if (step.speech) { await director({ type: 'speech', text: step.speech }); await waitFrame(before); actions.push('SIMULATED speech result queued'); continue; }
      if (step.words) { await director({ type: 'words', text: step.words }); await waitFrame(before); actions.push('SIMULATED live words'); continue; }
      if (step.shot) {
        await sleep(350); await pollConsole();
        if (step.expect && !lastFrame.scene.includes(step.expect)) throw new Error(`${step.shot}: scene ${lastFrame.scene} lacks ${step.expect}`);
        const raw = path.join(out, 'raw', `${step.shot}.png`);
        fs.writeFileSync(raw, Buffer.from(await (await api('GET', '/api/screenshot/glasses')).arrayBuffer()));
        const file = `${step.shot}.png`;
        const labelled = label(raw, path.join(out, file), `SIMULATED · Even Hub simulator · ${step.shot} · ${step.title}`);
        const shot = { id: step.shot, title: step.title, caption: step.caption, scene: lastFrame.scene, file: labelled ? file : `raw/${file}`, raw: `raw/${file}`, steps: actions.splice(0) };
        if (PHONE_SHOTS.has(step.shot)) {
          await sleep(300);
          fs.writeFileSync(path.join(out, 'phone', file), Buffer.from(await (await api('GET', '/api/screenshot/webview')).arrayBuffer()));
          shot.phone = `phone/${file}`;
        }
        jm.shots.push(shot);
        console.log(`shot ${step.shot}  [${lastFrame.scene}]`);
      }
    }
  }
  await pollConsole();
  manifest.problems = problems;
  fs.writeFileSync(path.join(out, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n');
  console.log(`${manifest.journeys.reduce((n, j) => n + j.shots.length, 0)} screenshots in ${out}; ${problems.length} problem(s)`);
  if (problems.length) { console.log(problems.join('\n')); process.exitCode = 1; }
}

main().catch(e => { console.error(e); process.exitCode = 1; }).finally(() => { stopAll(); setTimeout(() => process.exit(), 300); });
