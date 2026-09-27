# Unstoppable Event Farm

Plays the Madden NFL 27 Ultimate Team event **UNSTOPPABLE (CPU)** on a PS5 by
itself. It watches the console over a [chiaki-ng](https://github.com/streetpea/chiaki-ng)
Remote Play stream on a Mac, reads the screen with Apple's Vision OCR, and
presses buttons through a small local daemon that drives chiaki's
keyboard-as-controller input.

    read the screen -> work out the situation -> act -> repeat

Nothing is time-based: every pass re-reads the screen, so long plays,
penalties, turnovers and cutscenes are handled the same way.

**First time on a machine: run `./setup.sh`, then read [`SETUP.md`](SETUP.md).**

---

## The event

| | |
|---|---|
| Run | 10 straight wins completes it, one loss ends it. Re-entry is free |
| Every game | starts **10-0 down**; 4 quarters of 3:00 |
| House rules | points are *stolen*: a 15+ yd run steals 2, a sack or forced fumble steals 1, and an **incomplete pass gives the CPU 1** |
| Entry option | always **Lineup Restricted** |
| Watch out | an `UNSTOPPABLE (H2H)` card sits right above ours. Entering it means a real game against a human, so the card is matched by title + `CPU` and rejected on `H2H` / `SQ` |

## What it does

| | |
|---|---|
| Offence | **FB DIVE WEAK** (triangle, in FAVORITES). Snap, then left stick up + R2 (sprint) from 1.0s for up to 3.0s. Once it is confirmed **ahead by 10+**, it switches to a short hold (0.2s / 1.5s) so the back stops early instead of breaking long scores. A run can't throw an incompletion |
| Defence | **MID BLITZ** (square, in FAVORITES), plain press |
| Snap timing | waits **6.0s** after the play call (the snap is refused until every player is set), then chews the play clock down to :14 while the game clock is running |
| Tempo | sets **CHEW CLOCK** (R3 → Tempo) in Q1 and again in Q3 |
| 4th down | never punts. Kicks a field goal only from inside the opponent's 10 |
| Between games | reads each menu by its text: postgame → progress → events list → entry options → next game. A loss or a completed run rolls straight into a fresh run |
| History | every game appended to `~/.mut_unstoppable_history.jsonl` |

Results on the author's setup: 23-0 in one session (6 full runs), then 37-0
overnight. Games average ~18 min and ~43 plays.

---

## Files

| File | What |
|---|---|
| `tools/config.py` | **every event-specific setting** (plays, timings, screen regions). Each one can be overridden by the environment variable next to it |
| `tools/grind.py` | the loop and the between-game menus |
| `tools/actions.py` | everything that presses a button |
| `tools/screen.py` · `tools/hud.py` | everything that reads the screen. `hud.py` finds the clock and score by content, so it works on every broadcast layout |
| `tools/calibrate.py` | look at the screen: checks every crop region and writes the stamp `grind.py` needs |
| `tools/pad.py` · `mini-pad/padd.py` | the daemon client, and the daemon (keystrokes + in-process screen capture, localhost only, token auth) |
| `tools/farm.sh` · `status.sh` · `health.sh` · `hold.sh` | start/stop · report · watcher · pause-then-stop |

## Run it

```bash
cd tools
./calibrate.py verify      # once, on a live playcall screen (grind.py refuses to start without it)
./farm.sh                  # start. Logs to /tmp/mut-event/grind-YYYYMMDD.log
./health.sh &              # the watcher: exits (with the reason) when something needs you
./status.sh                # last 10 games, record, pace, alerts
./farm.sh stop             # stop at the next play boundary
./hold.sh                  # pause the game, then stop (before changing anything)
```

**Taking over the controller:** just kill the loop (`pkill -f "grind.py loop"`)
and play. Don't press anything from the Mac while you have the pad. To hand
back, go to the events list or any playcall screen and run `./farm.sh`.

## Good to know

- **Look at the screen before changing code.** `calibrate.py shot` / `text`
  show exactly what the farm sees. Almost every long debugging session came
  from reasoning about what the code probably did instead of capturing a frame.
- **Don't put the offensive play on circle.** Circle is the loop's "back out"
  key. Keep a play you are happy to run on X too, because X is also the snap
  button.
- **The score reader is the least reliable read.** It only decides the hybrid
  dive's short run. Wins and losses come from the event's own progress screen
  (`x/1 LOSSES`, `x/10 WINS`), which is what to trust.
- **A dropped stream** (chiaki back on its host list) is restarted
  automatically. An EA sign-out is not: the screen shows `R2 SIGN IN TO EA`, and
  after that the farm needs to be walked back to the events list.
