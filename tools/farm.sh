#!/bin/bash
# Start the farm. APPENDS to a dated log so a restart can never destroy history.
#
# ⛔ AFTER RUNNING THIS, ARM THE WATCHER IN THE SAME MESSAGE:
#       ./health.sh        (via the Bash tool with run_in_background: true)
# A `nohup ... &` cannot notify Claude. This has failed twice, and both times
# Montrell found a paused game himself.
cd "$(dirname "$0")" || exit 1

# Resolve the interpreter. Order: an explicit MUT_PY, this repo's venv, then a
# legacy sibling venv (Montrell's mini), then whatever python3 is on PATH.
resolve_py() {
  # ⛔ We have already cd'd into the script's directory, so use PWD.
  # "$(dirname "$0")" here would resolve against the NEW cwd and point at a
  # directory that does not exist.
  local here; here="$PWD"
  for c in "$MUT_PY" "$here/../venv/bin/python" "$here/qenv/bin/python" \
           "$(command -v python3)"; do
    [ -n "$c" ] && [ -x "$c" ] && { echo "$c"; return; }
  done
  echo ""
}
PY="$(resolve_py)"
if [ -z "$PY" ]; then
  echo "No python found. Run ./setup.sh first." >&2
  exit 1
fi

export MUT_PAD_REMOTE=local

# ⛔⛔ `farm.sh stop` - THE ONLY SAFE WAY TO STOP. Never `pkill` the loop.
# (Sep 13) A bare pkill landed between the hike and the throw: the QB held the
# ball, took a sack, and Montrell had to take over. The loop checks for this
# file at a PLAY BOUNDARY, so stopping costs nothing.
mkdir -p /tmp/mut-event
if [ "$1" = "stop" ]; then
  pgrep -f "grind.py loop" >/dev/null || { echo "not running"; exit 0; }
  touch /tmp/mut-event/stop
  echo -n "stopping at the next play boundary"
  for _ in $(seq 1 40); do
    pgrep -f "grind.py loop" >/dev/null || { echo " -> stopped clean"; exit 0; }
    echo -n "."; sleep 1
  done
  # A play cannot outlast 40s. If we are here the loop is wedged, not playing.
  echo " -> no boundary in 40s, forcing"
  rm -f /tmp/mut-event/stop
  pkill -f "grind.py loop"
  exit 0
fi
rm -f /tmp/mut-event/stop

# ⛔ The reachability check comes AFTER the stop path on purpose. (Sep 17) The
# PS5 went down mid-game and `farm.sh stop` refused with "PS5 UNREACHABLE" -
# the one moment the farm most needs stopping is exactly when the console has
# died under it.
ping -c 1 -t 2 "${MUT_PS5_HOST:-192.168.1.50}" >/dev/null 2>&1 \
  || { echo "PS5 UNREACHABLE - not starting"; exit 1; }

# ⛔⛔⛔ A TIER 3/4 LOSS HALT IS NOT SOMETHING A RESTART MAY STEP OVER.
# The whole point is that Montrell decides what happens next, not a reflex
# `./farm.sh`. Clearing this is a deliberate act.
if [ -f /tmp/mut-event/HALT ]; then
  echo ""
  echo "⛔ FARM HALTED - a loss on tier 3/4:"
  sed 's/^/   /' /tmp/mut-event/HALT
  echo ""
  echo "   The run is one loss from over. Take the next game yourself, or"
  echo "   clear the halt deliberately:  rm /tmp/mut-event/HALT"
  echo ""
  exit 1
fi

pgrep -f "grind.py loop" >/dev/null && { echo "already running"; exit 0; }

LOG=/tmp/mut-event/grind-$(date +%Y%m%d).log
mkdir -p /tmp/mut-event
{ echo ""; echo "===== farm started $(date '+%Y-%m-%d %H:%M:%S') ====="; } >> "$LOG"
ln -sf "$LOG" /tmp/mut-event/grind.log
nohup "$PY" -u grind.py loop 99999 >> "$LOG" 2>&1 &
sleep 4
if pgrep -f "grind.py loop" >/dev/null; then
  echo "farm RUNNING -> $LOG"
else
  echo "FAILED TO START:"; tail -5 "$LOG"; exit 1
fi
