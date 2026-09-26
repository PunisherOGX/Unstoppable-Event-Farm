#!/usr/bin/env python3
"""Run recorded macros back to back in PRACTICE mode, to see whether they hold up.

Practice mode resets to the line after every play with "PREPLAY" on the action
bar - that is the ready signal. Loop: wait for PREPLAY -> fire the next macro
-> wait for PREPLAY to VANISH (the play is live) and COME BACK (reset) -> next.

    practice_macro.py money_square money_circle --reps=6 --settle=2.5 --between=10

Alternates through the names given, `reps` plays in total. Stop early with
`touch /tmp/mut-event/practice.stop`. Nothing here reads the result of a play -
Montrell watches; this only supplies consistent input.
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pad  # noqa: E402
import screen  # noqa: E402
import macrorec as M  # noqa: E402

STOP = "/tmp/mut-event/practice.stop"


def wait_bar(want_present, timeout, label):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if os.path.exists(STOP):
            return None
        present = "PREPLAY" in screen.action_bar()
        if present == want_present:
            return True
        time.sleep(0.4)
    print(f"  timeout: {label}")
    return False


def main(names, reps, settle, between):
    macros = [(n, M._load(n)) for n in names]
    try:
        os.remove(STOP)
    except FileNotFoundError:
        pass
    for i in range(reps):
        name, m = macros[i % len(macros)]
        if not wait_bar(True, 60, "waiting for PREPLAY"):
            break
        time.sleep(settle)                    # players walking to the line - PREPLAY shows before they are set
        r = pad.sequence(m["events"])
        print(f"  [{i + 1}/{reps}] {name}: {r.get('events')} events, "
              f"late {r.get('max_late_ms')}ms", flush=True)
        # The play is live once the bar clears; the reset brings it back.
        if wait_bar(False, 15, "bar never cleared - did the hike land?") is None:
            break
        if wait_bar(True, 45, "no reset after the play") is None:
            break
        time.sleep(between)                   # Montrell: 10s between attempts so the next never starts on a play still ending
    print("  done")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    reps = 6
    settle = 2.5
    between = 10.0
    for a in sys.argv[1:]:
        if a.startswith("--reps="):
            reps = int(a.split("=", 1)[1])
        if a.startswith("--settle="):
            settle = float(a.split("=", 1)[1])
        if a.startswith("--between="):
            between = float(a.split("=", 1)[1])
    if not args:
        print(__doc__)
        sys.exit(2)
    main(args, reps, settle, between)
