#!/usr/bin/env python3
"""Macro recorder - capture what Montrell does on a DualSense, replay it via the
pad daemon.

WHY THIS SHAPE (Sep 17, 2026). The daemon's vocabulary is chiaki's keyboard-as-
controller map: every button and every stick DIRECTION is a key. A DualSense
connected to the MAC (USB-C cable is simplest - it keeps its PS5 pairing) is
forwarded to the console by chiaki, and its HID reports can be read here at the
same time. So the recording is already in the daemon's vocabulary: a list of
(time, key, down/up). Replay is one `/sequence` call; the daemon does the timing.

⛔ THE PAD MUST BE ON THE MAC TO RECORD. A controller paired straight to the PS5
is invisible to this machine - there is nothing to record. `macrorec.py list`
says whether one is attached.
⛔ RECORD WITH THE PAD ON THE MAC, REPLAY WITH IT OFF. A DualSense on the Mac
steals controller 1 from chiaki and the keyboard path (the bot) goes dead.
⛔ Sticks are quantised to four directions with a dead zone. A recording that
depended on a half-tilt will not replay - that is a limit of the key map, not
of this tool. Triggers are digital at half travel for the same reason.

Usage:
    macrorec.py list                      is a DualSense attached to the Mac?
    macrorec.py record <name> [secs]      record until `touch /tmp/mut-event/
                                          macrorec.stop`, Ctrl-C, or secs.
                                          Writes Grind/macros/<name>.json
    macrorec.py show <name>               print the macro as a timeline
    macrorec.py play <name> [--speed=X]   replay through the daemon
    macrorec.py trim <name> <from> <to>   keep only [from, to] seconds, rebase to 0
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pad  # noqa: E402

MACRO_DIR = os.path.join(HERE, "..", "..", "Grind", "macros")

VID, PID = 0x054C, 0x0CE6            # Sony DualSense

# HID input report layout, relative to the first data byte (LX). Same for the
# USB report (id 0x01, data at [1:]) and the full Bluetooth report (id 0x31,
# data at [2:]). Verified against the public DualSense report map; `record`
# prints every transition, so a wrong bit shows up on the first press.
HAT = {0: ("up",), 1: ("up", "right"), 2: ("right",), 3: ("down", "right"),
       4: ("down",), 5: ("down", "left"), 6: ("left",), 7: ("up", "left")}
BTN0 = {0x10: "box", 0x20: "cross", 0x40: "moon", 0x80: "pyramid"}
BTN1 = {0x01: "l1", 0x02: "r1", 0x04: "l2", 0x08: "r2",
        0x20: "options", 0x40: "l3", 0x80: "r3"}
BTN2 = {0x01: "ps"}
DEADZONE = 0.45                       # of full travel, per axis
TRIGGER_ON = 0.5


def _open():
    import hid
    devs = hid.enumerate(VID, PID)
    if not devs:
        return None, None
    d = hid.device()
    d.open_path(devs[0]["path"])
    d.set_nonblocking(False)
    # A DualSense over Bluetooth starts in a minimal report (id 0x01, 10 bytes,
    # different layout). Reading the calibration feature report switches it to
    # the full 0x31 report, which shares the USB layout at an offset.
    try:
        d.get_feature_report(0x05, 41)
    except Exception:
        pass
    return d, devs[0]


def _decode(rep):
    """Return the set of daemon key names currently DOWN, or None if the report
    is not one we understand."""
    if not rep:
        return None
    if rep[0] == 0x01 and len(rep) >= 11:
        b = rep[1:]
    elif rep[0] == 0x31 and len(rep) >= 12:
        b = rep[2:]
    else:
        return None
    down = set()
    lx, ly, rx, ry, l2, r2 = b[0], b[1], b[2], b[3], b[4], b[5]
    h = b[7] & 0x0F
    down.update(HAT.get(h, ()))
    for m, k in BTN0.items():
        if b[7] & m:
            down.add(k)
    for m, k in BTN1.items():
        if b[8] & m:
            down.add(k)
    for m, k in BTN2.items():
        if b[9] & m:
            down.add(k)
    # Digital L2/R2 bits exist too, but the analog value is the honest one.
    if l2 / 255 >= TRIGGER_ON:
        down.add("l2")
    if r2 / 255 >= TRIGGER_ON:
        down.add("r2")

    def axis(v, neg, pos):
        f = (v - 128) / 128
        if f <= -DEADZONE:
            down.add(neg)
        elif f >= DEADZONE:
            down.add(pos)
    axis(lx, "lstick_left", "lstick_right")
    axis(ly, "lstick_up", "lstick_down")
    axis(rx, "rstick_left", "rstick_right")
    axis(ry, "rstick_up", "rstick_down")
    return down


def _path(name):
    os.makedirs(MACRO_DIR, exist_ok=True)
    return os.path.join(MACRO_DIR, f"{name}.json")


def _load(name):
    with open(_path(name)) as f:
        return json.load(f)


def _save(name, macro):
    with open(_path(name), "w") as f:
        json.dump(macro, f, indent=1)
    return _path(name)


def cmd_list():
    import hid
    devs = hid.enumerate(VID, PID)
    if not devs:
        print("  no DualSense on the Mac. Plug one in (USB-C) or pair it, then "
              "retry.\n  ⛔ A pad paired to the PS5 is invisible here.")
        return False
    for d in devs:
        print(f"  {d['product_string']}  path={d['path'].decode(errors='replace')}")
    return True


def cmd_record(name, secs=None):
    d, info = _open()
    if d is None:
        cmd_list()
        return False
    secs = float(secs) if secs else None
    print(f"  recording '{name}' from {info['product_string']} - Ctrl-C to stop"
          + (f", or after {secs:.0f}s" if secs else ""))
    print("  the clock starts at the FIRST input, so take your time\n")
    events = []
    prev = set()
    t0 = None
    unknown = 0
    # ⛔ Stop via a FILE, not a signal. (Sep 17) A take was lost because the
    # recorder had been launched from a non-interactive shell, which leaves
    # SIGINT ignored - the process sat there with every event in memory and no
    # way to get them out. `touch /tmp/mut-event/macrorec.stop` always works.
    stop_file = "/tmp/mut-event/macrorec.stop"
    try:
        os.remove(stop_file)
    except FileNotFoundError:
        pass
    try:
        while True:
            if os.path.exists(stop_file):
                break
            rep = d.read(128, timeout_ms=250)
            now = time.monotonic()
            cur = _decode(rep)
            if cur is None:
                if rep:
                    unknown += 1
                continue
            if cur == prev:
                if t0 and secs and now - t0 >= secs:
                    break
                continue
            if t0 is None:
                t0 = now
            t = now - t0
            for k in sorted(cur - prev):
                events.append({"t": round(t, 4), "key": k, "down": True})
                print(f"  {t:7.3f}  DOWN {k}", flush=True)
            for k in sorted(prev - cur):
                events.append({"t": round(t, 4), "key": k, "down": False})
                print(f"  {t:7.3f}   up  {k}", flush=True)
            prev = cur
            if secs and t >= secs:
                break
    except KeyboardInterrupt:
        pass
    finally:
        d.close()
    if t0 is None:
        print("\n  nothing was pressed - not saving")
        return False
    # Close anything still held at the moment recording stopped.
    t_end = round(time.monotonic() - t0, 4)
    for k in sorted(prev):
        events.append({"t": t_end, "key": k, "down": False})
    macro = {"name": name, "recorded": time.strftime("%Y-%m-%d %H:%M:%S"),
             "source": info["product_string"], "duration": t_end,
             "events": events}
    p = _save(name, macro)
    print(f"\n  saved {len(events)} events, {t_end:.2f}s -> {p}")
    if unknown:
        print(f"  ({unknown} reports had an unrecognised id - report that if "
              "presses were missed)")
    return True


def cmd_show(name):
    m = _load(name)
    print(f"  {m['name']}  recorded {m['recorded']}  {m['duration']:.2f}s  "
          f"{len(m['events'])} events")
    opened = {}
    for e in m["events"]:
        if e["down"]:
            opened[e["key"]] = e["t"]
        else:
            t0 = opened.pop(e["key"], None)
            held = f"held {e['t'] - t0:.3f}s" if t0 is not None else "(up only)"
            print(f"  {t0 if t0 is not None else e['t']:7.3f}  {e['key']:<13s} {held}")
    for k, t0 in opened.items():
        print(f"  {t0:7.3f}  {k:<13s} never released")


def cmd_play(name, speed="1.0"):
    m = _load(name)
    speed = float(speed)
    events = [{"t": e["t"] / speed, "key": e["key"], "down": e["down"]}
              for e in m["events"]]
    # Refuse to replay while a pad is on the Mac - the keyboard path is dead
    # and the presses would go nowhere, which then looks like a timing fault.
    try:
        import hid
        if hid.enumerate(VID, PID):
            print("  ⛔ a DualSense is on the Mac - unplug it before replaying "
                  "(it steals controller 1 from chiaki)")
            return False
    except ImportError:
        pass
    print(f"  playing '{name}' ({len(events)} events, "
          f"{m['duration'] / speed:.2f}s at {speed}x)")
    r = pad.sequence(events, max_seconds=max(30.0, m["duration"] / speed + 1))
    print(f"  {r}")
    return True


def cmd_trim(name, t_from, t_to):
    m = _load(name)
    a, b = float(t_from), float(t_to)
    kept = [dict(e, t=round(e["t"] - a, 4)) for e in m["events"] if a <= e["t"] <= b]
    # Anything down at `a` but pressed before it must be opened at 0; anything
    # still down at `b` must be closed at the end. Otherwise a trim can strand
    # a key, and the daemon would auto-release it at the wrong moment.
    state = {}
    for e in m["events"]:
        if e["t"] < a:
            state[e["key"]] = e["down"]
    for k, down in state.items():
        if down and not any(x["key"] == k and not x["down"] and x["t"] == 0 for x in kept):
            kept.insert(0, {"t": 0.0, "key": k, "down": True})
    open_now = {}
    for e in kept:
        open_now[e["key"]] = e["down"]
    for k, down in open_now.items():
        if down:
            kept.append({"t": round(b - a, 4), "key": k, "down": False})
    kept.sort(key=lambda e: e["t"])
    m["events"] = kept
    m["duration"] = round(b - a, 4)
    m["trimmed_from"] = [a, b]
    p = _save(name, m)
    print(f"  kept {len(kept)} events over {b - a:.2f}s -> {p}")


CMDS = {"list": cmd_list, "record": cmd_record, "show": cmd_show,
        "play": cmd_play, "trim": cmd_trim}

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    opts = {a.lstrip("-").split("=")[0]: (a.split("=", 1) + ["1"])[1]
            for a in sys.argv[1:] if a.startswith("--")}
    if not args or args[0] not in CMDS:
        print(__doc__)
        sys.exit(2)
    if args[0] == "play" and "speed" in opts:
        args.append(opts["speed"])
    ok = CMDS[args[0]](*args[1:])
    sys.exit(0 if ok in (True, None) else 1)
