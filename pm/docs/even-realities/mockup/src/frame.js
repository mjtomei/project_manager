// Frame -> Even Hub page containers, plus constraint checks.
//
// A frame is what a view wants on the glasses:
//   rows:   up to 9 body rows; each row {l: [{t, dim}], r: {t, dim}}
//   footer: {left, right}; left is bright status, right is dim commands
//   panel:  optional {top, rows} bordered box (voice review, confirmation)
//   menu:   app items for the OS contextual menu
//
// The container set is fixed so that ordinary updates use
// textContainerUpgrade (no flicker, keeps the page); only adding/removing the
// panel border needs rebuildPageContainer. Glasses text has no background:
// black is transparent, so nothing may be drawn "over" other text. Panels
// therefore own whole rows instead of overlaying them.
import {
  WIDTH, MARGIN, LINE, BODY_ROWS, BODY_HEIGHT, FOOTER_Y, CONTENT_WIDTH,
  RIGHT_X, RIGHT_WIDTH, TEXT_BYTES, bytes, width, padTo, fit, missingGlyphs,
} from './text.js';

const DIM = 1; // Pageborne: level 2 was barely distinguishable on glasses; 1 is visibly dimmer.
const BRIGHT = 4;
export const CONTAINERS = Object.freeze({
  input: { id: 1, name: 'input', x: MARGIN, y: 0, w: CONTENT_WIDTH, h: BODY_HEIGHT },
  left: { id: 2, name: 'left', x: MARGIN, y: 0, w: CONTENT_WIDTH, h: BODY_HEIGHT, color: BRIGHT },
  leftDim: { id: 3, name: 'left-dim', x: MARGIN, y: 0, w: CONTENT_WIDTH, h: BODY_HEIGHT, color: DIM },
  right: { id: 4, name: 'right', x: RIGHT_X, y: 0, w: RIGHT_WIDTH, h: BODY_HEIGHT, color: BRIGHT },
  rightDim: { id: 5, name: 'right-dim', x: RIGHT_X, y: 0, w: RIGHT_WIDTH, h: BODY_HEIGHT, color: DIM },
  foot: { id: 6, name: 'foot', x: MARGIN, y: FOOTER_Y, w: CONTENT_WIDTH, h: 28, color: BRIGHT },
  footDim: { id: 7, name: 'foot-dim', x: MARGIN, y: FOOTER_Y, w: CONTENT_WIDTH, h: 28, color: DIM },
});
const PANEL_ID = 8;

const seg = s => (typeof s === 'string' ? { t: s, dim: false } : s);
export const row = (l = [], r = null) => ({ l: (Array.isArray(l) ? l : [l]).map(seg), r: r && seg(r) });

function layoutColumn(rows, pick, maxWidth) {
  const bright = [], dim = [];
  for (const r of rows) {
    let b = '', d = '', x = 0;
    for (const s of pick(r)) {
      if (!s?.t) continue;
      // Space padding rounds to whole spaces; keep right-aligned text 4 px clear.
      const target = s.align === 'right' ? maxWidth - width(s.t) - 4 : Math.max(x, s.x ?? 0);
      if (s.dim) d += padTo(d, target) + s.t; else b += padTo(b, target) + s.t;
      x = target + width(s.t);
    }
    bright.push(b.trimEnd()); dim.push(d.trimEnd());
  }
  const join = lines => lines.join('\n').replace(/\n+$/, '') || ' ';
  return [join(bright), join(dim)];
}

// Build container contents for a frame. Returns {contents, panel, page, problems}.
export function buildFrame(frame) {
  const rows = (frame.rows || []).slice();
  const problems = [];
  if (rows.length > BODY_ROWS) problems.push(`body has ${rows.length} rows > ${BODY_ROWS}`);
  while (rows.length < BODY_ROWS) rows.push(null);
  const body = rows.slice(0, BODY_ROWS).map(r => r || row());

  // Left column: truncate to the space left of the right column when a row
  // has a right-hand state.
  for (const r of body) {
    const limit = r.r ? RIGHT_X - MARGIN - 8 : CONTENT_WIDTH - 4;
    let used = 0;
    r.l = r.l.map(s => {
      used = Math.max(used, s.x ?? 0);
      const room = limit - used;
      const t = width(s.t) > room ? fit(s.t, Math.max(0, room)) : s.t;
      used += width(t);
      return { ...s, t };
    });
    if (r.r) r.r = { ...r.r, t: fit(r.r.t, RIGHT_WIDTH - 4), align: 'right' };
  }
  const [left, leftDim] = layoutColumn(body, r => r.l, CONTENT_WIDTH);
  const [right, rightDim] = layoutColumn(body, r => (r.r ? [r.r] : []), RIGHT_WIDTH - 2);

  const f = frame.footer || {};
  const footRight = f.right ? fit(f.right, CONTENT_WIDTH - 24 - Math.min(width(f.left || ''), 300)) : '';
  const footLeft = fit(f.left || '', CONTENT_WIDTH - 20 - width(footRight));
  const footDim = footRight ? padTo('', CONTENT_WIDTH - 6 - width(footRight)) + footRight : ' ';

  const contents = {
    input: ' ', left, leftDim, right, rightDim, foot: footLeft || ' ', footDim,
  };
  for (const [key, text] of Object.entries(contents)) {
    const c = CONTAINERS[key];
    if (bytes(text) > TEXT_BYTES) problems.push(`${key}: ${bytes(text)} bytes > ${TEXT_BYTES}`);
    if ([...text].length > 1000) problems.push(`${key}: more than 1000 characters`);
    const lines = text.split('\n');
    if (lines.length > Math.floor(c.h / LINE)) problems.push(`${key}: ${lines.length} lines exceed ${Math.floor(c.h / LINE)}`);
    lines.forEach((line, i) => { if (width(line) > c.w) problems.push(`${key} line ${i + 1}: ${width(line)}px > ${c.w}px`); });
    const missing = missingGlyphs(text);
    if (missing.length) problems.push(`${key}: glyphs missing from firmware font: ${missing.join(' ')}`);
  }
  const menu = frame.menu || [];
  if (menu.length > 10) problems.push(`menu has ${menu.length} items > 10`);
  for (const m of menu) {
    if (!m.itemID) problems.push(`menu item ${m.itemName} has id 0`);
    if (bytes(m.itemName) > 32) problems.push(`menu item ${m.itemName} > 32 bytes`);
  }
  if (new Set(menu.map(m => m.itemID)).size !== menu.length) problems.push('duplicate menu ids');

  const panel = frame.panel ? {
    id: PANEL_ID, name: 'panel', x: 4, y: Math.max(0, frame.panel.top * LINE - 4),
    w: WIDTH - 8, h: Math.min(FOOTER_Y - 2, frame.panel.rows * LINE + 8),
  } : null;
  if (panel && panel.y + panel.h > FOOTER_Y) problems.push('panel overlaps footer');
  return { contents, panel, menu, problems };
}

export function pageDefinition(built) {
  const textObject = Object.entries(CONTAINERS).map(([key, c]) => ({
    xPosition: c.x, yPosition: c.y, width: c.w, height: c.h,
    containerID: c.id, containerName: c.name, content: built.contents[key],
    isEventCapture: key === 'input' ? 1 : 0, paddingLength: 0, borderWidth: 0,
    ...(c.color != null ? { textColor: c.color } : {}),
  }));
  if (built.panel) {
    const p = built.panel;
    textObject.push({ xPosition: p.x, yPosition: p.y, width: p.w, height: p.h, containerID: p.id,
      containerName: p.name, content: ' ', isEventCapture: 0, paddingLength: 0,
      borderWidth: 1, borderColor: 10, borderRadius: 4 });
  }
  const page = { containerTotalNum: textObject.length, textObject };
  if (built.menu.length) page.menuObject = { menuItems: built.menu.map(({ itemName, itemID }) => ({ itemName, itemID })) };
  const capture = textObject.filter(t => t.isEventCapture).length;
  if (textObject.length > 8) built.problems.push(`${textObject.length} text containers > 8`);
  if (capture !== 1) built.problems.push(`${capture} event-capture containers (need exactly 1)`);
  for (const t of textObject) if (t.containerName.length > 16) built.problems.push(`container name ${t.containerName} > 16`);
  return page;
}
