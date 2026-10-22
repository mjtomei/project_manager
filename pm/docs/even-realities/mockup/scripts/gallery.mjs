// Build ../index.html (the review gallery) from ../screenshots/manifest.json.
//   node scripts/gallery.mjs
// The page is static and self-contained apart from the screenshots, so it
// can be opened from the repo or served from PM's captures directory.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const manifest = JSON.parse(fs.readFileSync(path.join(root, 'screenshots', 'manifest.json'), 'utf8'));
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const shotsTotal = manifest.journeys.reduce((n, j) => n + j.shots.length, 0);

const steps = s => s.steps.length
  ? `<details><summary>${s.steps.length} step${s.steps.length === 1 ? '' : 's'} before this shot</summary><p class="steps">${s.steps.map(x => `<code class="${x.startsWith('SIMULATED') ? 'sim' : ''}">${esc(x)}</code>`).join(' ')}</p></details>`
  : '';
const card = s => `
  <figure id="${esc(s.id)}">
    <a href="screenshots/${esc(s.file)}"><img src="screenshots/${esc(s.file)}" alt="${esc(s.title)}: glasses display" loading="lazy" width="1152" height="612"></a>
    <figcaption>
      <b>${esc(s.id.split('-')[0])}</b> ${esc(s.title)}
      <span class="tag">SIMULATED PM</span>
      <p>${esc(s.caption)}</p>
      <p class="meta">scene <code>${esc(s.scene)}</code> · <a href="screenshots/${esc(s.raw)}">raw 576×288</a>${s.phone ? ` · <a href="screenshots/${esc(s.phone)}">phone companion</a>` : ''}</p>
      ${steps(s)}
      ${s.phone ? `<a class="phone" href="screenshots/${esc(s.phone)}"><img src="screenshots/${esc(s.phone)}" alt="${esc(s.title)}: phone companion view" loading="lazy" width="300" height="400"></a>` : ''}
    </figcaption>
  </figure>`;

const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PM glasses review</title>
<style>
  :root { color-scheme: light dark; --bg: #f7f8f6; --fg: #1b1f1a; --muted: #5b6458; --line: #d6dbd3; --card: #fff; --accent: #1f7a33; --sim: #8a5a00; }
  @media (prefers-color-scheme: dark) { :root { --bg: #111310; --fg: #e4e9e1; --muted: #9aa596; --line: #2a3128; --card: #181b17; --accent: #6fd27f; --sim: #e0b04a; } }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--fg); font: 15px/1.5 system-ui, -apple-system, sans-serif; }
  main { max-width: 1240px; margin: 0 auto; padding: 24px 16px 64px; }
  h1 { font-size: 26px; margin: 0 0 4px; } h2 { font-size: 20px; margin: 40px 0 8px; border-top: 1px solid var(--line); padding-top: 24px; }
  a { color: var(--accent); }
  .lede { color: var(--muted); max-width: 70ch; }
  .docs { display: flex; flex-wrap: wrap; gap: 8px 16px; padding: 0; list-style: none; }
  .note { border-left: 3px solid var(--sim); padding: 8px 12px; background: var(--card); max-width: 90ch; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 520px), 1fr)); gap: 20px; }
  figure { margin: 0; background: var(--card); border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
  figure > a > img { display: block; width: 100%; height: auto; background: #000; image-rendering: pixelated; }
  figcaption { padding: 10px 14px 14px; } figcaption p { margin: 6px 0; }
  .tag { font-size: 11px; border: 1px solid var(--sim); color: var(--sim); border-radius: 4px; padding: 0 5px; margin-left: 6px; white-space: nowrap; }
  .meta { color: var(--muted); font-size: 13px; overflow-wrap: anywhere; }
  .steps code { font-size: 12px; margin-right: 4px; } .steps code.sim { color: var(--sim); }
  .phone img { margin-top: 8px; width: 50%; max-width: 300px; height: auto; border: 1px solid var(--line); border-radius: 6px; }
  details summary { cursor: pointer; color: var(--muted); font-size: 13px; }
  code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
</style>
</head>
<body>
<main>
  <h1>Plan/spec review and PM sessions on Even Realities G2</h1>
  <p class="lede">Design checkpoint for pr-9e7847d: ${shotsTotal} glasses screenshots from a runnable mockup driven through Even's official simulator. Manual merge of this PR approves the behavior; the refactoring PRs decide how to build it.</p>
  <ul class="docs">
    <li><a href="proposal.md">Interaction proposal</a></li>
    <li><a href="constraints.md">Constraints (cited)</a></li>
    <li><a href="session-inventory.md">Session inventory and parity</a></li>
    <li><a href="open-questions.md">Open questions</a></li>
    <li><a href="pageborne-snapshot.md">Pageborne snapshot provenance</a></li>
    <li><a href="mockup/README.md">Run the mockup</a></li>
  </ul>
  <p class="note"><b>What is simulated.</b> ${esc(manifest.simulated)} Each image is the simulator's 576×288 glasses framebuffer, shown at 2× on black with a caption strip; follow "raw" for the original PNG. Captured ${esc(manifest.generated.slice(0, 16).replace('T', ' '))} UTC with ${esc(manifest.simulator)}, ${esc(manifest.sdk)} and ${esc(manifest.pretext)} on ${esc(manifest.host)}. The simulator does not model firmware timing, Bluetooth or phone lifecycles${manifest.problems?.length ? `. <b>${manifest.problems.length} problem(s) were logged during capture.</b>` : '; no constraint or SDK errors were logged during capture.'}</p>
  ${manifest.journeys.map(j => `<h2 id="journey-${esc(j.id)}">${esc(j.id)}. ${esc(j.title)}</h2>\n  <div class="grid">${j.shots.map(card).join('')}\n  </div>`).join('\n')}
  ${manifest.osMenu ? `<h2 id="os-menu">OS contextual menu</h2>\n  <div class="grid">${card({ ...manifest.osMenu, scene: 'OS menu (simulator)', steps: [] })}</div>` : ''}
</main>
</body>
</html>
`;
fs.writeFileSync(path.join(root, 'index.html'), html);
console.log(`wrote ${path.join(root, 'index.html')} (${shotsTotal} shots)`);
