# Pageborne source snapshot: provenance and review notes

Pageborne is the user's G2 reader app: package id `local.even.reader`, display name Pageborne, version 0.8.113. It lives at `~/even/reader` on the host; the PR description calls it `~/even/reading`.

The repository was not mounted in this PR's container. At the user's request it was reviewed from a read-only copy. **The snapshot is not committed to PM.** Only this provenance record and the citations in these documents are.

| Field | Value |
|---|---|
| Copied from | `/home/matt/even/reader` |
| Upstream HEAD | `4d769f60a77ab38ae327d715db777a702e8fb2bd` |
| Location during review | `/tmp/pm-design-context/pageborne-source` (container-local, not persisted) |
| Files | 294 source and documentation files, listed with SHA-256 and byte counts in `SNAPSHOT-MANIFEST.json` |
| Manifest SHA-256 | `240e9baed4cef2db3528ccac2b52b5009e2047f64e8b04752c690181f93c3cdd` |
| Integrity check | All 294 file hashes matched the manifest on 2026-10-21 |
| Excluded by the user | Runtime configuration, `.env` files, state, the private library, git metadata, dependencies, built bundles and model weights. Hashes describe the copied bytes, including any uncommitted local edits |

## Files cited (manifest SHA-256 prefixes)

| File | sha256 | Used for |
|---|---|---|
| `README.md` | `ce8c92b44d14` | Version history 0.8.81–0.8.113: snapshots per question, shared desktop sessions, status symbols, reconnect rule, reading controls and the display pipeline |
| `ASK-ABOUT-THIS.md` | `7007b73fcea3` | Hold-to-speak review, conversation layout, session linking, reading while waiting, voice/STT stack, network origins |
| `UI-DESIGN.md` | `21e4cf51ebe6` | One semantic binding table for glasses, phone preview and keyboard |
| `SCROLLING-RESEARCH.md` | `84bbfd15aff6` | No viewport API, the 999-byte simulator limit, pagination rationale |
| `PHONE-PERSISTENCE.md` | `a0c376e67948` | SDK storage instead of browser storage across WebView restarts |
| `SIMULATOR-TESTING.md` | `6c59bb85f29d` | Headless official-simulator workflow (Xvfb, dbus) and what simulator evidence means |
| `src/glasses.js` | `1e62a2064f1f` | Container geometry, dim level 1, two-layer footer, bordered popups that displace text |
| `src/controls.js` | `5a6c36f439bc` | SDK event → action mapping, including omitted click values |
| `src/ask-status.js` | `b4aae63a3083` | Status glyphs that exist in the firmware font |
| `src/document.js`, `src/native-text.js` | `db998d2774b7`, `08cd0f9ccbf2` | 576×288, margin 12, body 258 px, 27 px rows, 900-byte cap |
| `integrations/even-terminal/README.md` | `df4eb0148e4f` | Paper workspaces, file transfer and session titles on a custom Even Terminal |
| `app.json` | `8c80da2e1ecd` | Permissions (camera, album, g2-microphone), min app 2.2.9, SDK 0.0.14 |

## Pageborne behaviors the proposal follows

These are user-facing conventions, kept so the two apps feel the same. They are not decisions about code sharing, which belong to [pr-9374887](open-questions.md#pageborne-sharing-pr-9374887).

| Behavior | Pageborne evidence | Where the proposal uses it |
|---|---|---|
| Native-text pages with a non-capturing text body and a blank capture container; discrete page turns | README "Reading controls"; `SCROLLING-RESEARCH.md` | Document reader (A02, A03) |
| Footer: bright status, dim (level 1) commands | README 0.8.103/0.8.104; `glasses.js footerTextObjects` | Every view |
| Hold to speak, release to review, then Send / Cancel; double tap cancels; the panel shrinks the view above it | `ASK-ABOUT-THIS.md` (intro) | A04, A05, B07 |
| Return to the exact reading position after a conversation or cancellation | `ASK-ABOUT-THIS.md`; README | A10, B15 |
| Each question carries an immutable snapshot of the version being read | README 0.8.113 | Messages carry doc, version, hash, section and page (A08, B08) |
| Follow-ups while an agent is busy go to the same session | README 0.8.112 | B07, B08 |
| No automatic view switching on replies; unread and status glyphs instead | README 0.8.100, 0.8.101 | Footers and state column |
| Glyphs ○ ◐ ● ↑ ↔ ! ? exist in the firmware font | `src/ask-status.js` | State glyph set ([constraints](constraints.md)) |
| Reconnecting is shown only after 3 consecutive failed checks, and recovered requests are never resubmitted | README 0.8.101; `ASK-ABOUT-THIS.md` "Reading while waiting" | C08–C10 |
| Ambiguous network failures never auto-retry or create a duplicate session | `ASK-ABOUT-THIS.md` "Reading while waiting" | C09; rules in [proposal](proposal.md) |
| Root double tap opens the system exit dialog | README "Glasses menu"; DOCS `ship/app-submission` | C11 |

## Relevant Pageborne capabilities PM does not have

- Per-document conversations bound to desktop Claude/Codex sessions through Even Terminal:
  - The native Claude connector attaches to an existing Remote Control session and cannot create one.
  - The Codex connector uses a shared daemon.
- A Librarian session spanning the library, and library sync to `~/.pageborne/library`.
- On-device STT with vocabulary hints taken from the current reading position.
- A debug/release build split with per-build network origin whitelists. Release builds have no AI origins by default.
