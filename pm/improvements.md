# Improvements

Improvements suggested by the autonomous monitor.

## PRs

### PR: Add periodic auto-start scan for state changes
- **description**: Auto-start currently only scans for ready PRs on startup and after merge events. Add a periodic scan (every 30-60 seconds) that checks for newly-ready PRs. This would handle cases where PRs are manually reset, status changes are made outside auto-start's flow, or state recovery after crashes.
- **tests**: Enable auto-start. Wait for periodic scan to detect a ready PR. Verify it starts the PR without requiring a merge event trigger.
- **files**: Auto-start loop logic — add a timer-based scan alongside event-based triggers.
