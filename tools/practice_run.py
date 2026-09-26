#!/usr/bin/env python3
"""Practice-mode test of THE REAL OFFENSIVE PATH: snap+throw as one timed
/sequence, then the gated stick+R2 hold (`run_phase` -> /hold_watch).

Practice mode with the play pre-selected and "random defense": every play
resets to the line with PREPLAY on the action bar. This waits for that, fires
the same code the farm runs after a play call, and prints what the daemon
reports about the hold (how long, and what released it).

    practice_run.py --reps=6 --between=8

Stop early: touch /tmp/mut-event/practice.stop
"""
import os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import pad, screen, actions, config as C  # noqa: E402

STOP = "/tmp/mut-event/practice.stop"

def wait_bar(want, timeout):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if os.path.exists(STOP): return None
        if ("PREPLAY" in screen.action_bar()) == want: return True
        time.sleep(0.4)
    return False

def main(reps, between, settle):
    try: os.remove(STOP)
    except FileNotFoundError: pass
    print(f"  throw @{C.OFF_THROW_AFTER}s  run after {C.OFF_RUN_AFTER}s  hold {C.OFF_RUN_HOLD}s  "
          f"keys {C.OFF_RUN_STICK}+{C.OFF_RUN_SPRINT}  repress {C.OFF_RUN_REPRESS or 'off'}")
    for i in range(reps):
        if not wait_bar(True, 60): break
        time.sleep(settle)
        pad._remote_post("/focus", {}); time.sleep(0.35)
        t_snap = time.time()
        pad._remote_post("/sequence", {"events": [
            {"t": 0.0, "key": "cross", "down": True},
            {"t": C.OFF_SNAP_HOLD, "key": "cross", "down": False},
            {"t": C.OFF_THROW_AFTER, "key": C.OFF_THROW_BUTTON, "down": True},
            {"t": C.OFF_THROW_AFTER + C.OFF_THROW_HOLD, "key": C.OFF_THROW_BUTTON, "down": False},
        ], "focus": False, "max_seconds": 5.0})
        t_throw = t_snap + C.OFF_THROW_AFTER
        note = actions.run_phase(log=lambda m: print("   " + m.strip(), flush=True), after_throw_at=t_throw)
        print(f"  [{i+1}/{reps}] throw @{C.OFF_THROW_AFTER}s{note}", flush=True)
        if wait_bar(False, 15) is None: break
        if wait_bar(True, 45) is None: break
        time.sleep(between)
    print("  done")

if __name__ == "__main__":
    reps, between, settle = 6, 8.0, 2.5
    for a in sys.argv[1:]:
        if a.startswith("--reps="): reps = int(a.split("=")[1])
        if a.startswith("--between="): between = float(a.split("=")[1])
        if a.startswith("--settle="): settle = float(a.split("=")[1])
    main(reps, between, settle)
