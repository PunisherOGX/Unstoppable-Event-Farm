#!/bin/bash
# THE WATCHER. Blocks until something actually needs Montrell, then exits with a
# reason on stdout.
#
# ⛔ ARM THIS VIA THE BASH TOOL WITH run_in_background: true, in the SAME message
# as farm.sh. That is the only way its exit can notify Claude - a `nohup ... &`
# cannot. This has failed twice and both times Montrell found a paused game
# himself.
D=/tmp/mut-event
sticky_count() { [ -f "$D/ALERT.STICKY" ] && wc -l < "$D/ALERT.STICKY" || echo 0; }
STICKY_BEFORE=$(sticky_count)

# ⛔⛔ ONLY TRIP ON EVENTS NEWER THAN THIS WATCHER.
# (Sep 13) Three separate arms were consumed within seconds by a LEFTOVER
# INTERVENE file from a process that had already been killed. Each one printed a
# stale pause, exited, and left the LIVE game completely unwatched - the exact
# failure this script exists to prevent. A file on disk is not an event; a file
# written AFTER we started watching is.
ARMED=$(date +%s)
newer_than_arm() {   # $1 = path. True only if it exists and postdates ARMED.
  [ -f "$1" ] || return 1
  [ "$(stat -f %m "$1")" -ge "$ARMED" ]
}
STALE_SECS=${MUT_EVENT_STALE:-420}

while true; do
  sleep 30

  if ! pgrep -f "grind.py loop" >/dev/null; then
    echo "FARM STOPPED — the grind.py process is gone."
    tail -15 "$D"/grind-*.log 2>/dev/null | tail -15
    exit 0
  fi

  if newer_than_arm "$D/INTERVENE"; then
    echo "PAUSED — losing at the start of Q4, waiting on a decision:"
    cat "$D/INTERVENE"
    echo "Answer by creating ONE of: $D/RESUME (play it out), $D/INTERVENED (I have the pad), $D/EXTEND (+30 min)"
    exit 0
  fi

  if newer_than_arm "$D/HALT"; then
    echo "⛔ FARM HALTED — a loss on tier 3 or 4. It stopped BEFORE entering another game."
    cat "$D/HALT"
    echo "The run is one loss from over. Take the next game yourself, then: rm $D/HALT"
    exit 0
  fi

  if newer_than_arm "$D/FROZEN"; then
    echo "GAME FROZEN — the loop aborted. Madden has to be quit by hand."
    cat "$D/FROZEN"
    exit 0
  fi

  NOW=$(sticky_count)
  if [ "$NOW" -gt "$STICKY_BEFORE" ]; then
    echo "NEW STICKY ALERT:"
    tail -n $(( NOW - STICKY_BEFORE )) "$D/ALERT.STICKY"
    exit 0
  fi

  # A log that stops growing means the loop is wedged even though the process
  # is alive — the failure mode that burned 4h15m unnoticed on the old build.
  # ⛔⛔ A PAUSE IS NOT A STALL. While an INTERVENE pause is open the loop is
  # deliberately writing nothing - for up to 30 MINUTES - which trips the
  # staleness check and kills this watcher on a false alarm. That leaves the
  # live game unwatched, which is the one thing this script exists to prevent.
  # (The in-loop watchdogs learned this same lesson on Sep 13.)
  if [ -f "$D/INTERVENE" ]; then
    continue
  fi

  L=$(ls -t "$D"/grind-*.log 2>/dev/null | head -1)
  if [ -n "$L" ]; then
    AGE=$(( $(date +%s) - $(stat -f %m "$L") ))
    if [ "$AGE" -gt "$STALE_SECS" ]; then
      echo "LOG STALE — nothing written for ${AGE}s (threshold ${STALE_SECS}s). The loop is alive but not progressing."
      tail -15 "$L"
      exit 0
    fi
  fi
done
