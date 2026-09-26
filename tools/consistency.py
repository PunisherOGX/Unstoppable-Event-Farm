"""Is the formula repeatable? Reads the PERSISTENT history, never a log.

⭐ THE QUESTION THIS ANSWERS (Montrell, Sep 14): "how often are we going without
scoring?" A formula that wins 4 games in 5 and gets shut out in the fifth is a
different thing from one that scores 20 every time, and the averages hide it.

⛔ Rows written before Sep 14 have UNVALIDATED scores - one recorded 735 points
from a field-position token in the score slot - and mostly no tier. They are
counted separately rather than silently averaged in.
"""
import json
import os
import sys

HIST = os.path.expanduser("~/.mut_event_history.jsonl")
CLEAN_FROM = "2026-09-14"          # when score validation + tier went in


def load():
    rows = []
    try:
        with open(HIST) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        pass
    except OSError:
        pass
    return rows


def block(label, rows):
    rows = [r for r in rows if r.get("ours") is not None]
    if not rows:
        print(f"  {label:<16} no rows with a usable score")
        return
    pts = [r.get("ours") or 0 for r in rows]
    shutouts = [r for r in rows if (r.get("ours") or 0) == 0]
    wins = [r for r in rows if str(r.get("result", "")).upper().startswith("W")]
    mins = [r.get("minutes") for r in rows if r.get("minutes")]
    print(f"  {label:<16} n={len(rows):<3} "
          f"scored {len(rows)-len(shutouts)}/{len(rows)}  "
          f"avg {sum(pts)/len(pts):5.1f}  "
          f"min {min(pts):<3} max {max(pts):<3}"
          + (f"  W {len(wins)}" if wins else "")
          + (f"  {sum(mins)/len(mins):.1f} min/game" if mins else ""))
    if shutouts:
        print(f"  {'':16} ⚠️ SHUT OUT in {len(shutouts)}: "
              + ", ".join(s.get("ts", "?")[5:16] for s in shutouts[:5]))


def main():
    rows = load()
    if not rows:
        print("no history yet")
        return
    clean = [r for r in rows if (r.get("date") or "") >= CLEAN_FROM]
    old = [r for r in rows if (r.get("date") or "") < CLEAN_FROM]
    print(f"=== CONSISTENCY ===  {len(rows)} games "
          f"({len(clean)} with validated scores)\n")
    if clean:
        print("SINCE SCORE VALIDATION:")
        block("all", clean)
        for t in (1, 2, 3, 4):
            ts = [r for r in clean if r.get("tier") == t]
            if ts:
                block(f"tier {t}", ts)
    if old:
        print(f"\nBEFORE VALIDATION ({len(old)} games) - scores UNTRUSTED, "
              f"shown only so they are not silently lost:")
        block("legacy", old)


if __name__ == "__main__":
    sys.exit(main())
