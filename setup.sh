#!/bin/bash
# One-shot setup for a fresh machine. Safe to re-run.
set -u
cd "$(dirname "$0")" || exit 1
ROOT="$PWD"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
ok()  { printf '  ✅ %s\n' "$*"; }
warn(){ printf '  ⚠️  %s\n' "$*"; }
bad() { printf '  ⛔ %s\n' "$*"; }

[ "$(uname)" = "Darwin" ] || { bad "macOS only - this drives a Mac's display."; exit 1; }

say "1. Python + pyobjc"
if [ ! -x "$ROOT/venv/bin/python" ]; then
  python3 -m venv "$ROOT/venv" || { bad "could not create venv"; exit 1; }
fi
"$ROOT/venv/bin/pip" install -q --upgrade pip
"$ROOT/venv/bin/pip" install -q pyobjc-framework-Quartz pyobjc-framework-Vision \
  || { bad "pyobjc install failed"; exit 1; }
"$ROOT/venv/bin/python" -c "import Quartz, Vision, Foundation" 2>/dev/null \
  && ok "venv ready at venv/" || { bad "pyobjc import failed"; exit 1; }

say "2. Daemon auth token"
# ⛔ THE DAEMON REFUSES TO START WITHOUT THIS, on purpose. It can synthesise
# keystrokes and capture the screen; an external review of the previous repo
# found it serving every route unauthenticated when this file was missing.
TOKEN_DIR="${MUT_PAD_TOKEN_DIR:-$HOME/mut-pad}"
mkdir -p "$TOKEN_DIR"
if [ -s "$TOKEN_DIR/token" ]; then
  ok "token already present at $TOKEN_DIR/token"
else
  head -c 32 /dev/urandom | xxd -p | tr -d '\n' > "$TOKEN_DIR/token"
  chmod 600 "$TOKEN_DIR/token"
  ok "generated $TOKEN_DIR/token (chmod 600)"
fi

say "3. Pad daemon"
cp "$ROOT/mini-pad/padd.py" "$TOKEN_DIR/padd.py"
ok "deployed padd.py -> $TOKEN_DIR/padd.py"
LABEL="${MUT_PAD_LABEL:-local.mutpad}"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$ROOT/venv/bin/python</string>
    <string>$TOKEN_DIR/padd.py</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <!-- Interactive so launchd does not throttle it into the background band;
       input timing matters here. -->
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>$TOKEN_DIR/pad.log</string>
  <key>StandardErrorPath</key><string>$TOKEN_DIR/pad.log</string>
  <key>WorkingDirectory</key><string>$TOKEN_DIR</string>
</dict>
</plist>
PLISTEOF
ok "wrote $PLIST"
launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null
launchctl kickstart -k "gui/$(id -u)/$LABEL" 2>/dev/null
sleep 2
if pgrep -f padd.py >/dev/null; then
  ok "daemon running on 127.0.0.1:8773 (localhost only)"
else
  warn "daemon not running yet - check $TOKEN_DIR/pad.log"
  warn "most often this is macOS permissions: see step 5"
fi

say "4. What YOU must set for this machine"
cat <<'TXT'
  These cannot be guessed. See SETUP.md for how to find each one.

    MUT_PS5_HOST           your console's IP           (default 192.168.1.50)
    MUT_CHIAKI_HOST_TILE   "x,y" of the console tile   (default 300,175)
                           in chiaki's host list, in display POINTS
    MUT_CHIAKI_APP         chiaki app path             (default /Applications/chiaki-ng.app)

  ⛔ Every screen region assumes the stream FILLS a 1920x1080-point display
     with NO letterbox. On any other display the crops are wrong and
     `calibrate.py verify` will fail - which is exactly what it is for.
TXT

say "5. macOS permissions (System Settings > Privacy & Security)"
cat <<'TXT'
  Grant BOTH to the app that runs the daemon (usually Terminal, or Python):
    · Screen Recording   - to capture frames
    · Accessibility      - to synthesise keystrokes
  Then restart the daemon:  launchctl kickstart -k gui/$(id -u)/local.mutpad
TXT

say "Next"
cat <<'TXT'
  1. Open chiaki and connect to your console.
  2. cd tools && ./calibrate.py verify     # must pass before the farm will run
  3. ./farm.sh                             # and arm ./health.sh alongside it
TXT
