# Even Realities G2: constraints for PM plan/spec review

These are the constraints that shape the [interaction proposal](proposal.md). Each row says what the constraint means for the design and how it was established.

**Labels**

- **DOCS**: Even Hub documentation, fetched 2026-10-21 (`https://hub.evenrealities.com/docs/<page>`).
- **SDK**: `@evenrealities/even_hub_sdk@0.0.16`, from its README and `dist/index.d.ts`.
- **FONT**: `@evenrealities/pretext@0.1.4`, the firmware font metrics.
- **SIM**: observed during this PR in the official simulator `@evenrealities/evenhub-simulator@0.9.5` (`sim-linux-arm64`), run headless under Xvfb.
- **PB**: Pageborne's own recorded findings, in the snapshot described in [pageborne-snapshot.md](pageborne-snapshot.md).
- **COMM**: community notes, chiefly `github.com/nickustinov/even-g2-notes` at 227c866.
- **ASSUME**: an assumption that has not been verified.

The simulator re-implements the renderer; it does not run firmware or model Bluetooth, display latency or phone lifecycles (DOCS `test/simulator`; PB `SIMULATOR-TESTING.md`). Hardware-only items are listed at the end.

## Device and platform

| Constraint | Design consequence | Source | Label |
|---|---|---|---|
| Even Hub apps target **G2** glasses with the optional **R1 ring**. The SDK enum also lists G1, but no doc says the G1 runs Hub apps. | Design for G2. Ring and temple gestures are equivalent. | DOCS `get-started/overview`; SDK `DeviceModel` | DOCS, SDK |
| SDK 0.0.16 requires **Even App 2.2.10+**. Long press and the contextual menu need 2.2.9+. Pageborne ships with SDK 0.0.14, min app 2.2.9. | The design can rely on long press and app menu items. | SDK README; Pageborne `app.json` | SDK, PB |
| The app is a web page in the Even phone app's WebView. Glasses only display containers and send input. | All logic and networking live on the phone. The same page is the companion surface. | DOCS `get-started/architecture` | DOCS |

## Display and readability

| Constraint | Design consequence | Source | Label |
|---|---|---|---|
| Canvas is **576×288** per eye, origin top-left, 4-bit greyscale green. Black is off and **transparent; there is no background fill**. | Nothing can be drawn "over" text. Panels and confirmations take whole rows and displace content (the listening/review panel shrinks the page above it). | DOCS `build/display`; SIM screenshots are 576×288 RGBA | DOCS, SIM |
| One built-in proportional font. No size, bold, alignment or font control. Characters missing from the font are dropped. | Emphasis comes from brightness, position, upper-case section headings and glyphs only. | DOCS `build/display`, `build/device-apis` ("no text alignment, no font control, no background colors") | DOCS |
| Line height is **27 px**. Pageborne uses 9 body rows (258 px) plus a 28 px footer row at y 260. English averages about 9.3 px per character, so a 540 px line holds about 55–60 characters and a full screen about 450–500 characters. | Pages are ≤9 rows. The footer always carries identity and position. One screen holds about one requirement or ambiguity item. | FONT (`line_height: 27`, advance widths); PB `src/document.js`; DOCS `build/design-guidelines` ("pre-paginate at ~400–500 characters") | FONT, PB, DOCS |
| `textColor` has levels 0–4. Level 2 was barely distinguishable on glasses; **level 1 is visibly dimmer**. | Two brightness tiers: bright for content and state that needs attention, dim (1) for hints, metadata and quiet states. | SDK README; PB `src/glasses.js` comment; SIM (dim renders distinctly) | SDK, PB, SIM |
| Available glyphs include ● ○ ◐ ? ! ↔ ▶ › » « ■ □ ◆ ◇ ▲ ▼ · • … — → and box drawing. **Not available:** ✓ ✔ ✗ ⚠ ⟳ ⏸ ▸ ▪ ✎ ⌂. | The state glyph set uses only present glyphs: ◐ working, ○ idle, ● waiting for you, ? needs input, ! error, ■ done, □ ended/queued, ◆ approved, ◇ hold, ↔ reconnecting, ▶ cursor. | FONT advance widths (0 means absent); SIM render; PB `src/ask-status.js` | FONT, SIM, PB |
| Leading spaces render, so space padding can position text inside a container (about 5 px per space). | Two-column rows (label and state) use separate left/right containers per brightness; the checker keeps padding inside its byte budget. | SIM; PB `footerTextObjects` | SIM, PB |

## Containers and updates

| Constraint | Design consequence | Source | Label |
|---|---|---|---|
| A page has 1–12 containers: **at most 8 text/list and at most 4 image**. Exactly one container has `isEventCapture: 1`. | The mockup uses a fixed set: 1 blank capture container, 6 text containers (left/right × bright/dim, footer bright/dim) and an optional bordered panel, 8 in total. | DOCS `build/display`; SDK README | DOCS, SDK |
| Text per call: **1,000 characters** on create/rebuild and **2,000** on `textContainerUpgrade`. The simulator rejects **≥1,000 UTF-8 bytes** on both paths. | Every container stays ≤900 bytes (Pageborne's margin). `scripts/check.mjs` enforces this on all 186 journey frames. | DOCS `build/display`; PB `SCROLLING-RESEARCH.md` (999 accepted, 1,000 rejected) | DOCS, PB |
| `textContainerUpgrade` is flicker-free and needs an exact id+name match (a mismatch silently does nothing). `rebuildPageContainer` flickers, loses list selection and scroll, and drops the menu unless it is sent again. | Ordinary navigation updates text in place. Only showing or hiding a bordered panel rebuilds, and the menu is re-sent each time. | DOCS `build/page-lifecycle`; SIM (create/upgrade/rebuild all accepted) | DOCS, SIM |
| No programmatic scroll position, animation, or reliable append/accumulate. Native scrolling inside an overflowing capture container behaves badly across sections. | Documents are **pre-paginated** by the app, with a blank capture container and non-capturing text, as Pageborne does. Paging is discrete. | DOCS `build/device-apis`; PB `SCROLLING-RESEARCH.md` | DOCS, PB |
| Native lists allow ≤20 items of ≤64 characters (simulator ≤63 bytes); the firmware moves the highlight, and changing items needs a rebuild. | Session and PR lists are drawn as text with an app-drawn cursor so they can show a state column, scroll beyond 20 entries and update in place. A native list is an implementation option. | DOCS `build/display`; simulator changelog 0.7.3 | DOCS |
| Update cost is about 83 ms per in-place text update and about 165 ms per rebuild (firmware 2.2.7.14). | Update only changed containers. Coalesce rapid inputs. | COMM `even-g2-notes/docs/performance.md`; PB serial "BridgeLane" | COMM, PB |

## Input and navigation

| Constraint | Design consequence | Source | Label |
|---|---|---|---|
| Events: click (0, often omitted), swipe up/top (1), swipe down/bottom (2), double click (3), foreground enter/exit (4/5), abnormal and system exit (6/7), IMU (8), long press (9) and release (10). The source is the right temple, left temple or ring. | Behavior is defined on intents: **next, previous, choose, back, speak (hold → release), more actions**. There is no text input on glasses. | SDK `OsEventTypeList`, `EventSourceType`; SIM (down → `textEvent` 2; click → `sysEvent` without type; long press → 9) | SDK, SIM |
| **Root-page double tap must call `shutDownPageContainer(1)`** (the system exit dialog), or the app is rejected. | Back is double tap everywhere, and on the root it exits through the OS. No in-app exit UI. | DOCS `ship/app-submission` | DOCS |
| Tap-then-long-press opens the **OS contextual menu**: up to 10 app items of ≤32 bytes, inside system items (Display off, Brightness, Close). It is declared with the page and closes after one selection. | Global destinations (Needs you, Sessions, PRs, Plans and project) go in the app menu. Approval and starting actions are not menu items, so they always pass through an explicit confirmation. | DOCS `build/contextual-menu`; SDK menu validation | DOCS, SDK |
| In the simulator the menu covers the page and shows only app items. It emits sysEvent 4 on open and 5 on close, and a tap sent before the close event is swallowed. | Treat menu open/close as lifecycle noise, not navigation. On hardware, check whether input right after a menu selection is lost. | SIM (this PR's capture needs a 700 ms settle) | SIM |
| No haptics, no head-up event (raw IMU only), no push notifications. | Feedback is purely visual and in place: footer notices, state glyphs and banners. No interruptions or auto-switching (Pageborne removed auto-switch to Ask in 0.8.100). | DOCS `reference/faq`, `build/device-apis`; PB README 0.8.100 | DOCS, PB |

## Voice

| Constraint | Design consequence | Source | Label |
|---|---|---|---|
| The microphone is raw PCM (16 kHz, 16-bit mono, 100 ms frames) from the glasses or the phone. **The SDK has no speech-to-text.** | Speaking needs an STT path (on-device or remote). The design assumes recognized text arrives with partial words and that the user **reviews before sending**. | SDK README (audio); DOCS `build/device-apis`; SIM README | SDK, DOCS |
| Pageborne runs on-device STT: Moonshine Tiny on CPU drafts, Whisper Small on WebGPU corrects, and weights of about 586 MB download after WebGPU is confirmed. Hold to speak, release to review, then Send/Cancel. | The voice flow mirrors Pageborne. Whether PM reuses Pageborne's speech stack is an [open question](open-questions.md#pageborne-sharing-pr-9374887). | PB `ASK-ABOUT-THIS.md` (Voice and network permissions) | PB |

## Connection lifecycle and networking

| Constraint | Design consequence | Source | Label |
|---|---|---|---|
| Backgrounding: iOS keeps the WebView; Android may suspend or kill it, so treat a relaunch as a cold start. QR dev builds die when backgrounded. Review includes a 5-minute lock test. The FAQ says no network calls while backgrounded. | State that matters (the place in a document, the navigation stack, pending sends) persists in SDK storage. After resume, data is shown with its age until refreshed. Nothing that was sent is sent again. | DOCS `build/background-lifecycle`, `reference/faq` (they conflict on iOS) | DOCS |
| Browser storage is not reliable across Even app restarts; use `bridge.setLocalStorage`/`getLocalStorage`. | Persist with SDK storage. | PB `PHONE-PERSISTENCE.md`; DOCS `build/device-apis` | PB, DOCS |
| Network calls need **exact origins whitelisted in `app.json`** (no wildcards) plus server CORS. HTTPS in production; `http://` only for LAN development. | PM must expose a fixed HTTPS origin, for example over Tailscale. PM's dashboard binds `127.0.0.1` today. See the [open question](open-questions.md). | DOCS `build/networking`; PB README (Tailscale origins, release builds have no AI origins by default) | DOCS, PB |
| WebSockets are allowed but drop on background (Android). | Prefer resumable polling or an event stream with a cursor. Show ↔ only after repeated failures (Pageborne requires 3 consecutive failed checks). | DOCS `reference/faq`; PB README 0.8.101 | DOCS, PB |

## Glasses versus companion (phone)

| Constraint | Design consequence | Source | Label |
|---|---|---|---|
| The same WebView page is the phone UI. The app knows whether it was opened from the phone or the glasses menu, and exiting on the glasses must close the phone page too. | The companion shows full text, exact diffs, typed input and confirmation details, and calls the same commands. The glasses never depend on the phone being visible. | SDK `onLaunchSource`; DOCS `ship/app-submission` | SDK, DOCS |
| Phone and glasses UI at the same time | Assumed possible (it is one page); Pageborne does it with a phone mirror. | PB README "Phone interface" | PB, ASSUME |

## Needs hardware validation (not established here)

- Physical refresh latency and flicker for the paged reader and in-place list updates.
- Gesture reliability: double tap versus tap, long press after a menu selection, and whether input is lost while the OS menu closes.
- Readability of dim (level 1) text outdoors, and of the right-hand state column.
- Interaction with phone notifications while the app is in front.
- A Tailscale or other HTTPS origin reaching PM from a release (non-QR) build.
- Android suspension during a pending send, and the 5-minute lock test.
