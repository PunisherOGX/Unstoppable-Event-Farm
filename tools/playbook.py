#!/usr/bin/env python3
"""Named play configurations - save one, list them, run one, ship one.

⭐ WHY THIS EXISTS: tuning a play produces a handful of numbers that are
worthless a day later if nobody wrote down which PLAY they belonged to. The
numbers are cheap to measure and expensive to re-measure, and the whole point of
testing several candidates is being able to compare them side by side.

    ./playbook.py save "PA Power QB Keep" --mode run --delay 0.5 --hold 3.0 \
        --notes "tuned 2.0/1.0/1.5/0.5; 0.5 looked best"
    ./playbook.py list
    ./playbook.py practice "PA Power QB Keep"     # loop it in practice mode
    ./playbook.py env "PA Power QB Keep"          # env to run it in the FARM
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.expanduser("~/.mut_plays.json")


def load():
    try:
        with open(STORE) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_all(d):
    with open(STORE, "w") as fh:
        json.dump(d, fh, indent=2, sort_keys=True)


def cmd_save(a):
    d = load()
    d[a.name] = {
        "mode": a.mode,            # run | pass
        "button": a.button,        # receiver icon, pass only
        "select": a.select,        # FAVORITES button that picks the play
        "delay": a.delay,          # snap -> throw (pass) or -> sprint (run)
        "hold": a.hold,            # stick+sprint hold, seconds
        "tap": a.tap,              # throw button tap, pass only
        "notes": a.notes or "",
        "measured": a.measured or "",
    }
    save_all(d)
    print(f"saved {a.name!r}")
    cmd_show(argparse.Namespace(name=a.name))


def cmd_list(_a):
    d = load()
    if not d:
        print("no plays saved yet")
        return
    print(f"{'PLAY':<30} {'MODE':<5} {'SEL':<8} {'DELAY':>6} {'HOLD':>6}  NOTES")
    for name, p in sorted(d.items()):
        print(f"{name[:30]:<30} {p['mode']:<5} {str(p.get('select') or '-'):<8} "
              f"{p['delay']:>6} {p['hold']:>6}  {p.get('notes','')[:44]}")


def cmd_show(a):
    p = load().get(a.name)
    if not p:
        print(f"no play named {a.name!r}"); return 1
    print(f"\n  {a.name}")
    for k in ("mode", "select", "button", "delay", "hold", "tap", "notes", "measured"):
        if p.get(k) not in (None, ""):
            print(f"    {k:<9} {p[k]}")
    print()


def _env(p):
    e = {"MUT_P_MODE": p["mode"], "MUT_P_THROW": str(p["delay"]),
         "MUT_P_RUN": str(p["hold"])}
    if p["mode"] == "pass":
        e["MUT_P_BTN"] = p.get("button") or "r1"
        e["MUT_P_HOLD"] = str(p.get("tap") or 0.2)
    return e


def cmd_practice(a):
    p = load().get(a.name)
    if not p:
        print(f"no play named {a.name!r}"); return 1
    env = dict(os.environ, MUT_PAD_REMOTE="local", MUT_P_PRE="1.0",
               MUT_P_GAP="6.0", **_env(p))
    print(f"looping {a.name!r} in practice - stop with: "
          f"touch /tmp/mut-event/practice.stop")
    try:
        os.remove("/tmp/mut-event/practice.stop")
    except OSError:
        pass
    py = os.path.join(HERE, "qenv/bin/python")
    subprocess.run([py if os.path.exists(py) else sys.executable, "-u",
                    os.path.join(HERE, "practice.py")], env=env)


def cmd_env(a):
    """The FARM env for this play - the numbers mean the same thing there."""
    p = load().get(a.name)
    if not p:
        print(f"no play named {a.name!r}"); return 1
    parts = [f"MUT_EVENT_RUN_HOLD={p['hold']}"]
    if p["mode"] == "pass":
        parts += [f"MUT_EVENT_THROW_AFTER={p['delay']}",
                  f"MUT_EVENT_THROW_HOLD={p.get('tap') or 0.2}"]
    else:
        parts += [f"MUT_EVENT_DIVE_RUN_AFTER={p['delay']}"]
    if p.get("select"):
        parts.append(f"MUT_EVENT_COMP_BUTTON={p['select']}")
    print(" ".join(parts) + "  ./farm.sh")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("save"); s.set_defaults(fn=cmd_save)
    s.add_argument("name")
    s.add_argument("--mode", choices=["run", "pass"], default="run")
    s.add_argument("--select", default=None, help="FAVORITES button, e.g. box")
    s.add_argument("--button", default="r1", help="receiver icon (pass only)")
    s.add_argument("--delay", type=float, required=True)
    s.add_argument("--hold", type=float, default=3.0)
    s.add_argument("--tap", type=float, default=0.2)
    s.add_argument("--notes", default="")
    s.add_argument("--measured", default="")
    for name, fn in (("list", cmd_list), ("show", cmd_show),
                     ("practice", cmd_practice), ("env", cmd_env)):
        q = sub.add_parser(name); q.set_defaults(fn=fn)
        if name != "list":
            q.add_argument("name")
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main() or 0)
