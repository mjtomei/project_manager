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
# `--validate` runs only after a successful job, with `$ARTIFACT` exported to
# it, and is bounded by the same `--timeout`: a validator that hangs is a
# failed validation, not an unbounded wait.
#
# On timeout only the job's own process group is signalled, so unrelated jobs
# (including a deliberately persistent observer started by the caller) are left
# alone; whatever is left in that group afterwards is SIGKILLed, because
# `timeout` exits as soon as its direct child dies and a descendant that
# ignores TERM would otherwise outlive the run.
#
# If the helper itself is signalled (Ctrl-C, or a supervisor killing the
# waiting shell) it terminates the running step's process group (the job, or
# the `--validate` command once the job has finished) — escalating to SIGKILL
# after a short grace period (`WAIT_FOR_JOB_KILL_GRACE`, default 5s) — and
# reports the interruption: a killed wait is never passed off as a job failure,
# never hangs on a job that ignores SIGTERM, and never leaves a renderer
# running behind it to race a later run over the artifact. Further signals
# during that cleanup are ignored, so a second Ctrl-C cannot kill the helper
# before it has stopped the job and said what happened.
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
    --validate) [ $# -ge 2 ] || die "--validate needs a value"
                # An empty validator would silently skip the check and still
                # report success — fail loudly instead.
                [ -n "$2" ] || die "--validate needs a non-empty command"
                validate_cmd=$2; shift 2 ;;
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

# How long an interrupted job gets to honour SIGTERM before it is killed
# outright. A job (or a shell it runs under) that ignores TERM keeps the trap
# blocked in `wait`, so the interrupt path needs its own explicit bound rather
# than relying on `timeout`'s `--kill-after` (an implementation detail that
# costs ~10s here and is not available everywhere). The bound is enforced by
# the escalator subshell below, which still fires if this helper is killed
# outright.
KILL_GRACE=${WAIT_FOR_JOB_KILL_GRACE:-5}
case "$KILL_GRACE" in ''|*[!0-9]*) KILL_GRACE=5 ;; esac

# Signal the job's process group. `timeout` made itself a process-group
# leader, so `-$job_pid` is the job's own group; the fallback covers a timeout
# that could not become leader (e.g. run in the terminal's foreground group).
signal_job() {
  kill -"$1" -- "-$job_pid" 2>/dev/null || \
      kill -"$1" "$job_pid" 2>/dev/null || true
}

# A group that still has members after its leader (`timeout`) was reaped means
# a descendant outlived the signal — either it ignores TERM or it was orphaned
# when its parent died. On the paths where *we* killed the run, KILL what is
# left in our own group so no renderer survives to race a later run over the
# same artifact. The group id cannot be recycled while a member exists, and a
# group that is already empty makes this a harmless ESRCH.
kill_job_group() {
  kill -KILL -- "-$job_pid" 2>/dev/null || true
}

job_group_alive() {
  kill -0 -- "-$job_pid" 2>/dev/null
}

# If the helper is signalled, stop the job too. Without this the `wait` would
# return 143 and be reported as a *job* failure while the renderer kept running
# — a misleading diagnostic and an orphan that can race a retry over the same
# artifact.
on_signal() {
  # *Ignore* further signals rather than restoring the default disposition:
  # the cleanup below can take up to KILL_GRACE, and a second Ctrl-C (or a
  # supervisor re-sending TERM) must not kill the helper before it has
  # stopped the job and reported the interruption.
  trap '' TERM INT HUP
  if [ -n "$job_pid" ]; then
    signal_job TERM
    # Escalator: SIGKILLs the job's group if the grace period runs out. It
    # inherits the ignored dispositions above, so it also survives a
    # group-wide Ctrl-C — and if this helper is killed outright, it still
    # stops the orphaned renderer.
    ( sleep "$KILL_GRACE"; signal_job KILL ) &
    escalator=$!
    wait "$job_pid" 2>/dev/null || true
    # Reaping the `timeout` wrapper does *not* mean the group is empty: a
    # descendant that ignores TERM (or was orphaned when its parent died)
    # outlives it, and `timeout` exits as soon as its direct child is gone.
    # Cancelling the escalator here would leave that renderer running.
    if job_group_alive; then
      wait "$escalator" 2>/dev/null || true
    else
      # SIGKILL, not TERM: the escalator ignores TERM (it inherited the
      # ignored dispositions), and waiting out its sleep would delay the
      # interrupt by the whole grace period for no reason.
      kill -KILL "$escalator" 2>/dev/null || true
      wait "$escalator" 2>/dev/null || true
    fi
  fi
  printf 'wait-for-job: interrupted before the run finished — this is a failure, not a result\n' >&2
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

# `2>/dev/null` drops bash's "Killed timeout ..." job notice when `timeout`
# SIGKILLs its own group after --kill-after; the diagnostics below say what
# actually happened.
wait "$job_pid" 2>/dev/null
status=$?
elapsed=$(( $(date +%s) - start_epoch ))

if { [ "$status" -eq 124 ] || [ "$status" -eq 137 ]; } && \
   [ "$elapsed" -ge "$timeout_secs" ]; then
  printf 'wait-for-job: job exceeded %ss and was killed — this is a failure, not a result\n' \
      "$timeout_secs" >&2
  # `timeout` signals the group but exits as soon as its direct child dies,
  # so a descendant that ignores TERM can outlive it. Finish our own group
  # here rather than leaving a renderer behind to race a later run.
  kill_job_group
  exit 3
fi
if [ "$status" -eq 125 ]; then
  # `timeout` returns 125 when it cannot run the job, but it also passes a
  # job's own 125 straight through (e.g. `docker run` on a daemon error), and
  # the two are indistinguishable here. Name both rather than blaming
  # `timeout` for a job that really did run and fail.
  printf 'wait-for-job: job exited 125 after %ss — either timeout could not start it or the job itself returned 125\n' \
      "$elapsed" >&2
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

# Validation gets the same bound as the job: a validator that hangs (a stuck
# ffprobe on a corrupt or network-mounted file, say) would otherwise stall the
# helper forever — the very failure class this script exists to prevent.
if [ -n "$validate_cmd" ]; then
  ARTIFACT=$artifact
  export ARTIFACT
  validate_start=$(date +%s)
  # Run the validator as the *tracked* job so an interrupt during validation
  # stops it too (a foreground child would make bash defer the trap until the
  # validator finished — unbounded if the validator is the thing that hung).
  timeout --signal=TERM --kill-after=10 "$timeout_secs" \
      bash -o pipefail -c "$validate_cmd" &
  job_pid=$!
  wait "$job_pid" 2>/dev/null
  vstatus=$?
  validate_elapsed=$(( $(date +%s) - validate_start ))
  if { [ "$vstatus" -eq 124 ] || [ "$vstatus" -eq 137 ]; } && \
     [ "$validate_elapsed" -ge "$timeout_secs" ]; then
    printf 'wait-for-job: artifact validation exceeded %ss and was killed — treating as failed validation: %s\n' \
        "$timeout_secs" "$artifact" >&2
    kill_job_group
    exit 4
  fi
  if [ "$vstatus" -ne 0 ]; then
    printf 'wait-for-job: artifact failed validation: %s\n' "$artifact" >&2
    exit 4
  fi
fi

printf 'wait-for-job: ok — job exited 0 in %ss, artifact fresh: %s\n' \
    "$elapsed" "$artifact"
exit 0
