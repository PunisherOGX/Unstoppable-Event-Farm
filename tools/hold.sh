#!/bin/bash
# PAUSE THE GAME, THEN STOP THE FARM. Use this before ANY change.
#
# Stopping the farm on its own leaves the GAME RUNNING with nobody to hike the
# ball: the play clock runs out and you take a delay of game.
#
#   ./hold.sh     pause the game, then stop the farm
#   ./farm.sh     restart - it clears the pause menu itself on the way back in
cd "$(dirname "$0")" || exit 1
export MUT_PAD_REMOTE=local

resolve_py() {
  local here; here="$PWD"
  for c in "$MUT_PY" "$here/../venv/bin/python" "$here/qenv/bin/python" \
           "$(command -v python3)"; do
    [ -n "$c" ] && [ -x "$c" ] && { echo "$c"; return; }
  done
}
PY="$(resolve_py)"

# 1. PAUSE THE GAME FIRST, while the farm is still up and the pad is free.
"$PY" - <<'PY'
import sys, time
sys.path.insert(0, ".")
import pad, screen
try:
    txt = (screen.screen_text() or "").upper()
    if "RESUME" in txt:
        print("  game already paused")
    else:
        pad.press("options", hold=0.10)
        time.sleep(2.5)
        ok = "RESUME" in (screen.screen_text() or "").upper()
        print("  game paused" if ok else "  ⚠️ could not confirm the pause")
except Exception as e:
    print(f"  ⚠️ pause failed: {e}")
PY

# 2. Now stop the farm and the watcher.
./farm.sh stop
pkill -f health.sh 2>/dev/null
"$PY" -c "import sys; sys.path.insert(0,'.'); import pad; pad.release()" >/dev/null 2>&1
echo "  farm stopped, watcher down, pad released"
