// Glasses geometry and firmware-font text fitting.
//
// Widths come from @evenrealities/pretext, which carries the G2 firmware
// font's advance widths and the 27 px line height. Geometry follows the
// Pageborne reader (src/document.js, src/native-text.js): 9 body rows above a
// one-row footer.
import { getTextWidth, getAdvW } from '@evenrealities/pretext';

export const WIDTH = 576;
export const HEIGHT = 288;
export const MARGIN = 12;
export const LINE = 27;
export const BODY_ROWS = 9;
export const BODY_HEIGHT = BODY_ROWS * LINE + 15; // 258, as in Pageborne
export const FOOTER_Y = 260;
export const CONTENT_WIDTH = WIDTH - 2 * MARGIN; // 552
// Right-hand column used for states/badges in list rows. A separate column
// keeps space padding (and so UTF-8 bytes) small; see frame.js.
export const RIGHT_X = 300;
export const RIGHT_WIDTH = WIDTH - MARGIN - RIGHT_X; // 264
// Simulator 0.7.1+ caps a text container at 999 bytes; docs say 1000
// characters on create/rebuild. Keep a margin like Pageborne (900).
export const TEXT_BYTES = 900;

const encoder = new TextEncoder();
export const bytes = text => encoder.encode(text).length;
export const width = text => getTextWidth(text);
export const SPACE = getTextWidth(' ');

// Glyphs present in the firmware font (pretext advance width > 0). Checked in
// the official simulator as well. ✓ ⚠ ⟳ ⏸ are absent and must not be used.
export const GLYPH = Object.freeze({
  needs: '●', idle: '○', working: '◐', ask: '?', error: '!', reconnect: '↔',
  cursor: '▶', done: '■', pending: '□', approved: '◆', held: '◇', up: '▲', down: '▼', dot: '·',
});
export function missingGlyphs(text) {
  return [...new Set([...text].filter(c => c !== '\n' && c !== ' ' && !getAdvW(c.codePointAt(0))))];
}

// Truncate to a pixel budget with an ellipsis (… is in the font).
export function fit(text, maxPx) {
  if (getTextWidth(text) <= maxPx) return text;
  const chars = [...text];
  let lo = 0, hi = chars.length;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (getTextWidth(chars.slice(0, mid).join('') + '…') <= maxPx) lo = mid; else hi = mid - 1;
  }
  return chars.slice(0, lo).join('').trimEnd() + '…';
}

// Greedy word wrap that never relies on firmware wrapping: every returned
// line is measured to fit, so the firmware renders exactly these rows.
export function wrap(text, maxPx) {
  const out = [];
  for (const para of String(text).split('\n')) {
    const words = para.split(/ +/).filter(Boolean);
    if (!words.length) { out.push(''); continue; }
    let line = '';
    for (const word of words) {
      const candidate = line ? `${line} ${word}` : word;
      if (getTextWidth(candidate) <= maxPx) { line = candidate; continue; }
      if (line) out.push(line);
      // Hard-split a single overlong token.
      let rest = word;
      while (getTextWidth(rest) > maxPx) {
        const head = fit(rest, maxPx).replace(/…$/, '');
        out.push(head); rest = rest.slice(head.length);
      }
      line = rest;
    }
    if (line) out.push(line);
  }
  return out;
}

// Spaces that move the next glyph to x (relative to the container's left).
export function padTo(current, x) {
  const gap = x - getTextWidth(current);
  return gap > 0 ? ' '.repeat(Math.round(gap / SPACE)) : (current ? ' ' : '');
}
