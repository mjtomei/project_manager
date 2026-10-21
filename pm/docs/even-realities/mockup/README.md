# PM glasses mockup

A small Even Hub web app that demonstrates the [interaction proposal](../proposal.md) on G2 glasses. It uses the real SDK (`@evenrealities/even_hub_sdk@0.0.16`) and firmware font metrics (`@evenrealities/pretext@0.1.4`).

**All PM data is simulated** (`src/fixtures.js`, `src/sim-pm.js`). The mockup never contacts PM, tmux or an agent.

## Run

```bash
cd pm/docs/even-realities/mockup
npm ci --ignore-scripts
npm run check      # run all journeys in Node; validate every frame against container limits
npm run serve      # http://127.0.0.1:5180/  browser preview: mirror + companion
```

Browser preview keys:

| Key | Gesture |
|---|---|
| ↑ / ↓ | swipe |
| Enter | tap |
| Esc | double tap |
| hold A | speak (release to review) |
| 1–4 | OS menu items |

The demo buttons inject the same SIMULATED events the journeys use.

## Official simulator and screenshots

```bash
npm run capture    # -> ../screenshots/*.png, raw/, phone/, manifest.json
npm run gallery    # -> ../index.html
```

- `capture` starts `server.mjs` and the official simulator (`@evenrealities/evenhub-simulator@0.9.5`) with its automation API. It then replays `scripts/journeys.mjs`:
  - touchpad actions go through `/api/input`
  - simulated PM events and speech results go through the server's `/director` queue
- It saves the glasses framebuffer after each step tagged as a shot.
- On Linux without a display it runs the simulator under `xvfb-run -a` and `dbus-run-session`. On Ubuntu 22.04 arm64 the simulator needed these packages: `libwebkit2gtk-4.1-0 libgtk-3-0 libsoup-3.0-0 dbus dbus-x11 xvfb`.
- Labelled copies (2× scale, caption strip) need `ffmpeg` with drawtext.

To run on glasses during development, serve the directory and open it with `evenhub qr --url http://<lan-ip>:5180/` (Even Hub developer mode). This was not exercised in this PR.

## Layout

| File | Role |
|---|---|
| `src/text.js` | Geometry (576×288, 27 px rows, 9 body rows + footer), glyph availability, wrapping with pretext widths |
| `src/frame.js` | Frame → fixed set of 8 SDK text containers; checks bytes, rows, widths, glyphs, menu and capture rules |
| `src/app.js` | Views, navigation stack and intents; DOM-free |
| `src/sim-pm.js`, `src/fixtures.js` | SIMULATED PM: documents with versions, sessions, PRs, history, gates |
| `src/display.js` | SDK backend (create, then in-place upgrades, rebuild only for panels) and the browser canvas mirror |
| `src/companion.js` | Phone view: full text, transcript, typed reply, confirmations |
| `scripts/journeys.mjs` | The scripted demo shared by `check` and `capture` |
