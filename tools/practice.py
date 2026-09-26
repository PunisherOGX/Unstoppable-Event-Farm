"""Run the pass sequence over and over in PRACTICE MODE, so the timings can be
tuned against a live console instead of argued about.

⭐ WHY THIS IS NOT grind.py: practice resets the play for us, so there is no
play to call, no tab to reach, no HUD to read and no menu to handle. Stripping
all of that out means a rep is JUST the sequence under test - nothing else can
be blamed for a bad rep, and nothing else costs time between them.

Every timing is an env var so a change is a restart, not an edit:
    MUT_P_PRE        seconds from reset to the snap      (default MIN_SNAP_WAIT)
    MUT_P_THROW      snap -> throw                       (default OFF_THROW_AFTER)
    MUT_P_HOLD       throw button tap length             (default OFF_THROW_HOLD)
    MUT_P_RUNAFTER   throw -> run                        (default OFF_RUN_AFTER)
    MUT_P_RUN        run hold length                     (default OFF_RUN_HOLD)
    MUT_P_GAP        end of run -> next snap             (default 7.0)
    MUT_P_STICK      1/0 - hold the stick across the throw (default from config)

Stop it with:  touch /tmp/mut-event/practice.stop
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C  # noqa: E402
import hud  # noqa: E402
import pad  # noqa: E402

STOP = "/tmp/mut-event/practice.stop"


def f(name, default):
    return float(os.environ.get(name, default))


PRE = f("MUT_P_PRE", C.MIN_SNAP_WAIT)
THROW = f("MUT_P_THROW", C.OFF_THROW_AFTER)
HOLD = f("MUT_P_HOLD", C.OFF_THROW_HOLD)
RUNAFTER = f("MUT_P_RUNAFTER", C.OFF_RUN_AFTER)
RUN = f("MUT_P_RUN", C.OFF_RUN_HOLD)
GAP = f("MUT_P_GAP", 7.0)
STICK = os.environ.get("MUT_P_STICK", "1" if C.OFF_THROW_STICK else "0") == "1"

# ⭐ WHICH RECEIVER ICON to press. Different plays put the man we want on a
# different button, so this must be settable without editing anything.
BTN = os.environ.get("MUT_P_BTN", C.OFF_THROW_BUTTON)

# ⭐ MODE: "pass" = snap, wait, throw, then run. "run" = snap, then just drive
# the ball carrier (no throw at all) - for testing run plays.
MODE = os.environ.get("MUT_P_MODE", "pass").lower()

# ⛔⛔ THE PIPELINE IS CONSISTENTLY LATE, AND ON A SHORT WINDOW THAT IS FATAL.
# Measured across every target today: the realised delay runs ~0.08s longer than
# asked - daemon dispatch plus the Remote Play round trip. At 1.85s that is a 5%
# error nobody notices. At 0.25s it is 36%, and on an RPO - where the throw
# window closes at the handoff - it is the difference between a pass and a run.
# Subtract it so the number requested is the number the console performs.
BIAS = f("MUT_P_BIAS", 0.08)


def release():
    # ⛔ Never leave the stick or a trigger held between reps. A jammed stick
    # wedges practice mode exactly as it wedges a game.
    try:
        pad._remote_post("/release", {})
    except Exception:
        pass


def wait_for_presnap(timeout=25.0):
    """Block until the pre-snap HUD is up. True if it appeared.

    ⛔⛔ NEVER PRESS ON A TIMER ALONE. (Sep 15.) This loop fired a rep every ~18s
    regardless of what was on screen. A rep that landed between plays - on a
    practice reset or setup screen - sent `cross` and `R2` into THAT menu, and
    R2 there SWITCHES SIDES. Montrell found himself on defense and had to go
    back and re-pick the play.
    #
    ⭐ THE PLAY CLOCK IS THE TELL: it exists only at a live pre-snap. If it is
    not there, we are not on the field, and nothing should be pressed.
    """
    # ⛔ PRACTICE MODE HAS NO PLAY CLOCK. Measured: at a live pre-snap in
    # practice the clock reads None, so a play-clock-only test waits forever and
    # never presses. The PRE-SNAP PROMPTS are the reliable tell on this screen -
    # "PREPLAY" and "SUBS" appear only when the ball is ready to be hiked.
    end = time.time() + timeout
    while time.time() < end:
        try:
            h = hud.read_clocks_fast()
            if h.get("play") is not None:
                return True
        except Exception:
            pass
        try:
            import screen
            txt = (screen.screen_text() or "").upper()
            if "PREPLAY" in txt or "SUBS" in txt:
                return True
        except Exception:
            pass
        time.sleep(0.8)
    return False


def rep(n):
    """One snap -> throw -> run. Returns the REALISED throw delay."""
    # ⛔ FOCUS ONCE, then post with focus=False. pad.press() re-focuses on every
    # call and costs ~0.5s, which would land the throw half a second late inside
    # a 2-3s window. Same discipline as actions.snap().
    pad._remote_post("/focus", {})
    time.sleep(0.35)

    t_snap = time.time()
    pad._remote_post("/press", {"buttons": ["cross"], "hold": 0.06,
                                "gap": 0.0, "focus": False})

    # Everything below is scheduled off t_snap, never off cumulative sleeps, so
    # jitter in one step cannot push every later step out.
    if MODE == "run":
        # No throw at all - just take control of the carrier after the handoff.
        # ⛔ t_throw is still set: everything below schedules off it, and leaving
        # it undefined here is exactly the class of bug that crashed the farm
        # twice (`actual`, `tier`, `lead`). Same name, same meaning: the instant
        # the macro's second phase begins.
        time.sleep(max(0.0, (t_snap + THROW - BIAS) - time.time()))
        t_throw = time.time()
        actual = t_throw - t_snap
    else:
        time.sleep(max(0.0, (t_snap + THROW) - time.time()))
        t_throw = time.time()
        actual = t_throw - t_snap
        if STICK:
            pad._remote_post("/combo", {"hold": C.OFF_THROW_STICK,
                                        "taps": [BTN],
                                        "pre": 0.0, "tap_hold": HOLD,
                                        "gap": 0.0, "post": 0.0, "focus": False})
        else:
            pad._remote_post("/press", {"buttons": [BTN],
                                        "hold": HOLD, "gap": 0.0,
                                        "focus": False})
        release()

    if RUN and C.OFF_RUN_STICK and C.OFF_RUN_SPRINT:
        time.sleep(max(0.0, (t_throw + RUNAFTER) - time.time()))
        try:
            pad._remote_post("/combo", {"hold": C.OFF_RUN_STICK,
                                        "taps": [C.OFF_RUN_SPRINT],
                                        "pre": 0.0, "tap_hold": RUN,
                                        "gap": 0.0, "post": 0.0, "focus": False})
        finally:
            release()
    return actual


def main():
    if os.path.exists(STOP):
        os.remove(STOP)
    print(f"=== PRACTICE LOOP [{MODE.upper()}] ===  btn={BTN}  pre={PRE}s  "
          f"snap->{'throw' if MODE=='pass' else 'run'}={THROW}s  "
          f"tap={HOLD}s  run+{RUNAFTER}s for {RUN}s  gap={GAP}s  "
          f"stick={'ON' if STICK else 'OFF'}", flush=True)
    print(f"    stop with: touch {STOP}", flush=True)
    release()

    n = 0
    hits = []
    try:
        while not os.path.exists(STOP):
            n += 1
            if not wait_for_presnap():
                print("      waiting for the pre-snap (no play clock on screen) "
                      "- not pressing", flush=True)
                continue
            time.sleep(PRE)
            actual = rep(n)
            hits.append(actual)
            drift = actual - THROW
            recent = hits[-20:]
            spread = max(recent) - min(recent)
            print(f"[{n:3d}] throw @{actual:.3f}s  (target {THROW}, "
                  f"drift {drift:+.3f})  last{len(recent)}: "
                  f"mean {sum(recent)/len(recent):.3f}  spread {spread:.3f}",
                  flush=True)
            time.sleep(GAP)
    except KeyboardInterrupt:
        pass
    finally:
        release()
        if hits:
            print(f"\n{n} reps  mean {sum(hits)/len(hits):.3f}s  "
                  f"min {min(hits):.3f}  max {max(hits):.3f}  "
                  f"spread {max(hits)-min(hits):.3f}", flush=True)
        print("practice loop stopped - pad released", flush=True)


if __name__ == "__main__":
    main()
