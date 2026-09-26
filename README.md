# UNSTOPPABLE (CPU) — the farm

A Madden NFL 27 Ultimate Team farm for the **UNSTOPPABLE (CPU)** event on PS5:
it reads the screen over a chiaki-ng Remote Play stream and presses buttons
through an emulated controller (`mini-pad/padd.py`). Built 2026-09-24 from the
earlier GT: Clock's Ticking farm
([UM-CPU-EVENT-FARM](https://github.com/PunisherOGX/UM-CPU-EVENT-FARM)) and
retargeted.

**New here? Run `./setup.sh`, then read `SETUP.md`.** Every event-specific knob
lives in `tools/config.py`.

---

## The event — and why it is not like the last one

| | |
|---|---|
| Event card | **UNSTOPPABLE (CPU)** — ⛔ an **`UNSTOPPABLE (H2H)` twin sits directly above it** in the list |
| Structure | **10 straight wins to complete · ONE loss ends the run.** No tiers |
| Every game | **starts 10-0 DOWN.** That is the gimmick |
| Quarters | 4 x 3:00 (Q1 clock read 180s) |
| Badge | ARCADE |
| Entry options | **FREE** vs **Lineup Restricted** → always **RESTRICTED** (one d-pad DOWN from arrival) |
| Offense | FAVORITES → **triangle** = **FB DIVE WEAK**, hybrid: full run (hold 1.0s→4.0s), short run (0.2s→1.7s) once CONFIRMED ahead by 10+. No 2nd-half pass |
| Defense | FAVORITES → **box** = **MID BLITZ**, plain press (no macro) |
| Snap | 6.0s floor after the play call. **3.0s failed live** (players still walking to the line) |
| Chew | ON all game: skip below :22, hike at :14 |
| Results (Sep 25) | 6 runs completed, 23 straight wins from 14:21 to 21:08; ~18 min / ~44 plays per game |
| Expires | 10/1 1:30 PM ET |
| History | `~/.mut_unstoppable_history.jsonl` |

### House rules: points are STOLEN, in both directions

| | |
|---|---|
| 15+ yd run / 25+ yd pass | steal 2 pts |
| Rushing/passing TD | 4 pts |
| Forced fumble / sack | steal 1 pt |
| **Incomplete pass / fumble** | **steal 1 pt — our incompletion concedes a point** |
| Safety | 4 pts |

This is why the offence is a **run**: a run cannot throw an incompletion. Seen
working: game 1 went 10-0 → 8-2 on one chunk play, game 2 finished 0-21.

### Three things the last event's code got wrong here

1. **Both loss halts were gated on `tier >= 3`** — impossible in a one-tier
   event, so they were dead code and the farm would have rolled into a fresh
   run after a loss. Now `HALT_ON_ANY_LOSS`.
2. **The score reader rejects decreases** ("scores never decrease"). Scores
   genuinely fall here. It latched a bogus 57 and reported "lead +49" while the
   board read 0-21. `SCORE_CONTRADICT` is now 2, not 4.
3. **Games were never recorded.** Clock's Ticking ended on `FINISH GAME`, which
   is the only screen that set the boundary flag; this event ends on
   **`RETURN TO HUB`**, so every game fell through unbooked — zero history rows
   after two wins.

Also: the clock-chew was burning play clock **while trailing**, which shortens
the very game we need to come back in. Now gated on actually leading.

---

## The files

| File | What |
|---|---|
| `tools/config.py` | **every event-specific knob, in one place.** When this event expires, this is the only file that has to change |
| `tools/screen.py` | everything that READS. No button is ever pressed from here |
| `tools/actions.py` | everything that PRESSES |
| `tools/grind.py` | the loop and the menu walk |
| `tools/calibrate.py` | **look at the screen.** The tool that makes that the cheap option |
| `tools/farm.sh` · `status.sh` · `health.sh` | start · report · watch |
| `tools/pad.py` · `step.py` · `../mini-pad/padd.py` | proven over 311 games — do not rewrite |

---

## Bring it up

**First time on a machine: run `./setup.sh`, then read `SETUP.md`.**

```bash
export MUT_PAD_REMOTE=local                                # daemon over localhost
ping -c 3 "${MUT_PS5_HOST:-192.168.1.50}"                  # ⛔ ALWAYS FIRST
launchctl kickstart -k gui/$(id -u)/local.mutpad           # pad daemon
open -a /Applications/chiaki-ng.app                        # then connect to the console
```

⚠️ The IP, the LaunchAgent label and the chiaki host-tile coordinate are
**machine-specific**. `SETUP.md` lists each one and how to find yours.

⛔ **Restarting the pad daemon requires restarting chiaki afterwards**, or presses
are silently dropped.
⛔ **The daemon refuses to start without `~/mut-pad/token`.** That is deliberate —
it can synthesise keystrokes and capture the screen.

## Run it

```bash
cd tools
./calibrate.py verify      # ⛔ once, on a live playcall screen. grind.py
                           #    REFUSES to start without this stamp
./farm.sh                  # start
./health.sh                # ⛔ arm IN THE SAME MESSAGE, run_in_background: true
./status.sh                # report, any time
```

⛔ **`health.sh` must be armed through the Bash tool with `run_in_background:
true`, in the same message as `farm.sh`.** A `nohup ... &` cannot notify Claude.
This has failed twice, and both times Montrell found a paused game himself.

### Answering a Q4 pause

```bash
touch /tmp/mut-event/RESUME       # let it play out
touch /tmp/mut-event/INTERVENED   # I have the pad — touch nothing
touch /tmp/mut-event/EXTEND       # give me another 30 min
```

---

## Before the first unattended run

1. **`calibrate.py event`** on the events list — confirm the matcher takes our
   card and skips its siblings. ⛔ **Four cards of this promo are on that page:**
   two H2H, two CPU, and two of the four marked **SQ** (Squads). The title alone
   does not identify ours, so `config.py` carries a reject list as well as a
   match. Getting this wrong enters a different mode entirely.
2. **`calibrate.py verify`** on a live playcall screen.
3. **`calibrate.py entry`** on the ENTRY OPTIONS screen — confirm the focused row
   really does read brighter before trusting it unattended. *This is the screen
   that cost ~11 tier rewards last event.*

---

## What is deliberately NOT here

Absent on purpose, not forgotten. Each is documented in the archive:

- **QB kneel** — three variants, never faster. Kneeling makes it 3rd-and-long →
  punt → the opponent gets the ball → extra possessions add back every play saved.
- **The tier-1 slide** — pressed circle at a ball carrier the pad did not control;
  circle on a non-QB is a spin, not a give-up.
- **The left-stick run** — measured +11% slower over five games.
- **Flip play (R2)** — Air Raid ran a sweep to the wide side. A fullback dive goes
  up the middle; there is no wide side.
- **The coach-suggestions defence switch** — passive defence lost games.
- **Any tier-gated behaviour** — one play each side means nothing branches on the
  tier, so a badge misread cannot cost a run. The badge is logged, not obeyed.

## The one thing to measure first

**Is chewing the play clock actually winning here?** It is the single deliberate
change from a straight port. On Air Raid it measured *worse* (13.8 → 22.5 min)
because the jet sweep ended out of bounds and stopped the clock, so chewing
engaged on only 170 of 369 snaps. A fullback dive ends in bounds. **That is a
prediction, not a measurement.** Get a clean baseline, then A/B it:

```bash
MUT_EVENT_HIKE_AT=99 ./farm.sh    # chew OFF — snap immediately
MUT_EVENT_HIKE_AT=8  ./farm.sh    # chew ON  — the default
```

`hike_at` is recorded on every row of the history, so the two are separable
afterwards. **Change ONE thing at a time** — two changes at once once cost a full
day, because one silently disabled the other.

Second: **`MIN_SNAP_WAIT`.** ✅ Tested Sep 25: **3.0 s FAILED live** — snaps
were refused because the players are still walking to the line and the snap only
takes once everyone is set. 6.0 s stays. 4.5 s is untested, and should only be
tried with someone watching every snap.
