// Candidate input binding for the browser preview. On the glasses the same
// intents come from SDK events (display.js intentForEvent); the binding
// follows Pageborne and Even's guidelines but is not part of the proposal's
// required behavior.
//   swipe down / up  -> next / prev        (↓ / ↑)
//   tap              -> select              (Enter, Space)
//   double tap       -> back                (Escape, Backspace)
//   hold / release   -> speak, then review  (hold A)
//   tap-then-hold    -> OS menu: app items  (1-4 choose an item directly)
let holding = false;
export function keyIntent(e, phase) {
  if (e.ctrlKey || e.metaKey || e.altKey) return null;
  if (e.code === 'KeyA') {
    if (phase === 'down' && !holding && !e.repeat) { holding = true; return ['hold']; }
    if (phase === 'up' && holding) { holding = false; return ['release']; }
    return null;
  }
  if (phase !== 'down') return null;
  switch (e.code) {
    case 'ArrowDown': case 'ArrowRight': case 'PageDown': return ['next'];
    case 'ArrowUp': case 'ArrowLeft': case 'PageUp': return ['prev'];
    case 'Enter': case 'Space': return ['select'];
    case 'Escape': case 'Backspace': return ['back'];
    case 'Digit1': case 'Digit2': case 'Digit3': case 'Digit4': return ['menu', Number(e.code.slice(-1))];
    default: return null;
  }
}
