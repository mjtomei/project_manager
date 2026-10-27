#!/usr/bin/env bash
# wait-for-job.sh — wait for one captured background job, safely.
#
# Starts a command as a single background job, waits on *that job's captured
# PID* (never bare `wait`, never process-name polling such as
# `until ! pgrep -f ...`), returns the job's real exit status, and requires a
# fresh, optionally validated artifact before reporting success.
#
# Usage:
#   wait-for-job.sh --timeout SECONDS --artifact PATH \
#                   [--validate 'SHELL COMMAND'] \
#                   -c 'SHELL COMMAND'
#   wait-for-job.sh --timeout SECONDS --artifact PATH \
#                   [--validate 'SHELL COMMAND'] -- CMD [ARG...]
#
# The `-c` form runs under `bash -o pipefail`, so a failing stage in a
# pipeline (e.g. `pytest ... | tail`) is not masked by the last command.
# Add `set -e` inside the command string when every step must succeed.
#
# `--validate` runs only after a successful job; `$ARTIFACT` is exported to it.
# On timeout only the job's own process group is signalled, so unrelated jobs
# (including a deliberately persistent observer started by the caller) are
# left alone. If the helper itself is signalled (Ctrl-C, or a supervisor killing
# the waiting shell) it terminates the job's process group and reports the
# interruption — a killed wait is never passed off as a job failure, and never
# leaves a renderer running behind it to race a later run over the artifact.
#
# Exit status:
#   0  job exited 0 and the artifact is fresh (and --validate passed)
#   1  job exited non-zero (status printed)
#   2  usage error
#   3  job exceeded --timeout and was killed
#   4  artifact missing, empty, stale (not produced by this run), or
#      --validate failed
#   130  the wait was interrupted by a signal; the job was terminated
#
# Why not poll process names? `until ! pgrep -f "<renderer>"` matches the
# waiting shell itself, whose command line contains the pattern, so it never
# ends even after the renderer exits. Why not bare `wait`? It blocks on every
# child, including a deliberately persistent observer/reaper, so a finite job
# looks stuck forever. This helper waits on exactly the job it started and
# reaps it with `wait "$pid"` — a finished-but-unreaped (zombie) child is
# reaped and its status used, never mistaken for live work.

set -u

usage() {
  awk 'NR == 1 { next }
       /^#/ { sub(/^# ?/, ""); print; next }
       { exit }' "$0"
}

die() {
  printf 'wait-for-job: %s\n' "$*" >&2
  exit 2
}

timeout_secs=""
artifact=""
validate_cmd=""
use_shell=0
shell_cmd=""

while [ $# -gt 0 ]; do
  case "$1" in
    --timeout)  [ $# -ge 2 ] || die "--timeout needs a value"; timeout_secs=$2; shift 2 ;;
    --artifact) [ $# -ge 2 ] || die "--artifact needs a value"; artifact=$2; shift 2 ;;
    --validate) [ $# -ge 2 ] || die "--validate needs a value"; validate_cmd=$2; shift 2 ;;
    -c)         [ $# -ge 2 ] || die "-c needs a command"; use_shell=1; shell_cmd=$2; shift 2 ;;
    --)         shift; break ;;
    -h|--help)  usage; exit 0 ;;
    *)          die "unexpected argument: $1" ;;
  esac
done

[ -n "$timeout_secs" ] || die "--timeout is required"
case "$timeout_secs" in
  ''|*[!0-9]*) die "--timeout must be a positive integer (seconds)" ;;
esac
[ "$timeout_secs" -gt 0 ] || die "--timeout must be greater than 0"
[ -n "$artifact" ] || die "--artifact is required"
if [ "$use_shell" -eq 1 ]; then
  [ $# -eq 0 ] || die "-c takes a single command string (got extra args)"
  [ -n "$shell_cmd" ] || die "-c command is empty"
else
  [ $# -gt 0 ] || die "no command given (use -c 'CMD' or -- CMD [ARG...])"
fi
command -v timeout >/dev/null 2>&1 || die "the 'timeout' command is required"

job_pid=""

# If the helper is signalled, stop the job too. Without this the `wait` would
# return 143 and be reported as a *job* failure while the renderer kept running
# — a misleading diagnostic and an orphan that can race a retry over the same
# artifact. `timeout` made itself a process-group leader, so `-$job_pid` is the
# job's own group; the fallback covers a timeout that could not become leader.
on_signal() {
  trap - TERM INT HUP
  if [ -n "$job_pid" ]; then
    kill -TERM -- "-$job_pid" 2>/dev/null || \
        kill -TERM "$job_pid" 2>/dev/null || true
    wait "$job_pid" 2>/dev/null || true
  fi
  printf 'wait-for-job: interrupted before the job finished — this is a failure, not a result\n' >&2
  exit 130
}
trap on_signal TERM INT HUP

mkdir -p -- "$(dirname -- "$artifact")" 2>/dev/null || true

# Size + mtime identify a file's content state for freshness checks without
# hashing a large video.
sig() {
  stat -L -c '%s:%y' -- "$1" 2>/dev/null || cksum -- "$1" 2>/dev/null
}

before_sig=""
[ -e "$artifact" ] && before_sig=$(sig "$artifact")

start_epoch=$(date +%s)

# `timeout` runs the job in its own process group and signals only that group
# on expiry — never the caller's shell or its unrelated children. `$!` is the
# timeout process; the `wait` below reaps it (and the job it supervises).
if [ "$use_shell" -eq 1 ]; then
  timeout --signal=TERM --kill-after=10 "$timeout_secs" \
      bash -o pipefail -c "$shell_cmd" &
else
  timeout --signal=TERM --kill-after=10 "$timeout_secs" "$@" &
fi
job_pid=$!

wait "$job_pid"
status=$?
elapsed=$(( $(date +%s) - start_epoch ))

if { [ "$status" -eq 124 ] || [ "$status" -eq 137 ]; } && \
   [ "$elapsed" -ge "$timeout_secs" ]; then
  printf 'wait-for-job: job exceeded %ss and was killed — this is a failure, not a result\n' \
      "$timeout_secs" >&2
  exit 3
fi
if [ "$status" -eq 125 ]; then
  printf 'wait-for-job: timeout could not start the job (status 125)\n' >&2
  exit 1
fi
if [ "$status" -ne 0 ]; then
  printf 'wait-for-job: job failed with exit status %s after %ss\n' \
      "$status" "$elapsed" >&2
  exit 1
fi

# The job exited 0 — now prove it produced *this run's* artifact.
if [ ! -e "$artifact" ]; then
  printf 'wait-for-job: job exited 0 but the expected artifact is missing: %s\n' \
      "$artifact" >&2
  exit 4
fi
if [ ! -f "$artifact" ]; then
  printf 'wait-for-job: expected artifact is not a regular file: %s\n' \
      "$artifact" >&2
  exit 4
fi
if [ ! -s "$artifact" ]; then
  printf 'wait-for-job: expected artifact is empty: %s\n' "$artifact" >&2
  exit 4
fi
after_sig=$(sig "$artifact")
if [ -n "$before_sig" ] && [ "$after_sig" = "$before_sig" ]; then
  printf 'wait-for-job: expected artifact was not rewritten by this run (stale leftover): %s\n' \
      "$artifact" >&2
  exit 4
fi
mtime=$(stat -L -c %Y -- "$artifact" 2>/dev/null || echo "$start_epoch")
if [ "$mtime" -lt "$start_epoch" ]; then
  printf 'wait-for-job: expected artifact is older than this run (stale): %s\n' \
      "$artifact" >&2
  exit 4
fi

if [ -n "$validate_cmd" ]; then
  ARTIFACT=$artifact
  export ARTIFACT
  if ! bash -o pipefail -c "$validate_cmd"; then
    printf 'wait-for-job: artifact failed validation: %s\n' "$artifact" >&2
    exit 4
  fi
fi

printf 'wait-for-job: ok — job exited 0 in %ss, artifact fresh: %s\n' \
    "$elapsed" "$artifact"
exit 0
