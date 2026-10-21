// Display backends.
//
// SdkDisplay drives real glasses (or the official simulator) through
// @evenrealities/even_hub_sdk. All calls go through one serial lane, like
// Pageborne's BridgeLane: the first frame creates the page, later frames send
// textContainerUpgrade for changed containers only, and a change in the
// container set (panel border on/off) rebuilds the page.
//
// CanvasDisplay draws the same containers in an ordinary browser for quick
// iteration. Its font is not the firmware font; screenshots for review come
// from the official simulator instead.
import { buildFrame, pageDefinition, CONTAINERS } from './frame.js';
import { WIDTH, HEIGHT, LINE } from './text.js';

export function intentForEvent(event) {
  // Even Hub event values (OsEventTypeList): 0 click (often omitted),
  // 1 scroll top (swipe up), 2 scroll bottom (swipe down), 3 double click,
  // 4/5 foreground enter/exit, 6 abnormal exit, 7 system exit,
  // 9 long press, 10 long-press release. Candidate binding only.
  if (event.menuItemClickEvent) return ['menu', event.menuItemClickEvent.itemID];
  const parts = [event.sysEvent, event.textEvent, event.listEvent].filter(Boolean);
  if (!parts.length) return null;
  const types = parts.map(e => e.eventType ?? 0);
  if (types.includes(6) || types.includes(7)) return ['lifecycle', 'exit'];
  if (types.includes(9)) return ['hold'];
  if (types.includes(10)) return ['release'];
  if (types.includes(3)) return ['back'];
  if (types.includes(4)) return ['lifecycle', 'foreground-4'];
  if (types.includes(5)) return ['lifecycle', 'foreground-5'];
  if (types.includes(1)) return ['prev'];
  if (types.includes(2)) return ['next'];
  if (types.includes(8)) return null;
  return ['select'];
}

export class SdkDisplay {
  constructor(bridge, log = console.log) {
    this.bridge = bridge; this.log = log;
    this.lane = Promise.resolve();
    this.created = false; this.sent = null; this.panelKey = null; this.seq = 0;
  }
  show(frame) {
    const built = buildFrame(frame);
    const page = pageDefinition(built);
    if (built.problems.length) this.log(`CONSTRAINT ${frame.scene}: ${built.problems.join('; ')}`);
    const seq = ++this.seq;
    this.lane = this.lane.then(() => this.apply(built, page, seq, frame.scene)).catch(e => this.log(`SDKERROR ${e?.message || e}`));
    return this.lane;
  }
  async apply(built, page, seq, scene) {
    const panelKey = built.panel ? JSON.stringify(built.panel) : '';
    if (!this.created) {
      const r = await this.bridge.createStartUpPageContainer(page);
      if (r !== 0) throw new Error(`createStartUpPageContainer -> ${r}`);
      this.created = true;
    } else if (panelKey !== this.panelKey) {
      const ok = await this.bridge.rebuildPageContainer(page);
      if (!ok) throw new Error('rebuildPageContainer -> false');
    } else {
      for (const [key, content] of Object.entries(built.contents)) {
        if (this.sent[key] === content) continue;
        const c = CONTAINERS[key];
        const ok = await this.bridge.textContainerUpgrade({ containerID: c.id, containerName: c.name, content });
        if (!ok) throw new Error(`textContainerUpgrade ${c.name} -> false`);
      }
    }
    this.panelKey = panelKey; this.sent = { ...built.contents };
    this.log(`FRAME ${seq} ${scene}`);
  }
  requestExit() { return this.bridge.shutDownPageContainer(1); }
}

export class CanvasDisplay {
  constructor(canvas) { this.ctx = canvas.getContext('2d'); }
  show(frame) {
    const built = buildFrame(frame);
    const page = pageDefinition(built);
    const ctx = this.ctx;
    ctx.fillStyle = '#000'; ctx.fillRect(0, 0, WIDTH, HEIGHT);
    ctx.font = '18px "DejaVu Sans", sans-serif'; ctx.textBaseline = 'top';
    for (const t of page.textObject) {
      if (t.borderWidth) { ctx.strokeStyle = '#3c3'; ctx.lineWidth = 1; ctx.strokeRect(t.xPosition + .5, t.yPosition + .5, t.width, t.height); }
      ctx.fillStyle = t.textColor === 1 ? '#2a8a2a' : '#5f5';
      t.content.split('\n').forEach((line, i) => ctx.fillText(line, t.xPosition, t.yPosition + i * LINE + 3));
    }
    return Promise.resolve(built.problems);
  }
  requestExit() {}
}
