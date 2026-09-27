# Setup

> **If you are an AI agent setting this up for your user, read this whole file
> first.** It lists everything that is machine-specific, how to *find* each value
> rather than guess it, and the one check that must pass before the farm will
> run. Nothing here assumes the machine it was written on.

---

## What this is

A closed-loop farm for the Madden NFL 27 Ultimate Team event **UNSTOPPABLE (CPU)**.
It reads the PS5's screen over a Remote Play stream, classifies the situation,
presses buttons, verifies the result, and repeats. Nothing is time-based.

    read the screen -> classify -> act -> verify -> repeat

Run it with the watcher (`tools/health.sh`) so you hear about anything that
needs a human. It has no anti-detection layer, by deliberate choice.

---

## Requirements

| | |
|---|---|
| macOS | it drives the Mac's own display via CoreGraphics |
| Python 3.9+ | `setup.sh` builds a venv with pyobjc |
| [chiaki-ng](https://github.com/streetpea/chiaki-ng) | the Remote Play client |
| A PS5 | **wired** if you can — a dropped stream looks exactly like dead input |

chiaki-ng must be configured with **"Keyboard as controller"** using its default
map. The daemon sends macOS keycodes that correspond to those defaults; if you
have rebound keys in chiaki, update `KEYS` in `mini-pad/padd.py` to match.

---

## Install

```bash
./setup.sh
```

It creates `venv/`, generates the daemon's auth token, deploys and loads the
daemon as a LaunchAgent, and prints what still needs your input.

---

## ⛔ Security — read before running

This daemon **can synthesise keystrokes and capture your screen.** Treat it as
what it is.

- It listens on **127.0.0.1 only**. It is never exposed to your network.
- Every route requires a bearer token, compared with `hmac.compare_digest`.
- **It refuses to start without a token file.** That is deliberate: an external
  review of the previous version of this project found it serving *every route
  unauthenticated* when the token file was missing — and the old docs pointed at
  a different path than the code read, which guaranteed exactly that state.
  It now fails closed.
- The token lives at `~/mut-pad/token`, `chmod 600`. **Never commit it.**
  `.gitignore` covers the venv and logs; the token is outside the repo entirely.

If you change `TOKEN_FILE` in `padd.py`, change it in `setup.sh` too. **The docs
and the code must agree** — that mismatch is the actual bug that caused the
original vulnerability.

---

## Machine-specific values

None of these can be guessed. Each has a way to *find* it.

| Setting | Default | How to find yours |
|---|---|---|
| `MUT_PS5_HOST` | `192.168.1.50` | your console's IP — PS5 *Settings → Network → Connection Status*. `ping` it before anything else |
| `MUT_CHIAKI_HOST_TILE` | `300,175` | where your console's tile sits in chiaki's host list, in **display points**. Screenshot the host list and measure the tile's centre. Only used to auto-reconnect a dropped stream |
| `MUT_CHIAKI_APP` | `/Applications/chiaki-ng.app` | wherever you installed it |
| `MUT_PAD_LABEL` | `local.mutpad` | any LaunchAgent label you like |

Set them in your shell, or export them before `farm.sh`:

```bash
export MUT_PAD_REMOTE=local         # talk to the daemon over localhost
export MUT_PS5_HOST=10.0.0.42
export MUT_CHIAKI_HOST_TILE=529,231
```

### ⛔ The display assumption

**Every screen region assumes the stream fills a 1920x1080-point display with no
letterbox.** On any other display or window size, the crops point at the wrong
pixels. This is not a subtle failure — it reads bare grass.

`calibrate.py verify` exists to catch exactly this, and `grind.py` **refuses to
start** without its stamp.

---

## First run

```bash
# 1. Bring the stream up and connect to your console.
ping -c 3 "$MUT_PS5_HOST"

# 2. On the events list — confirm it picks the right card.
cd tools && ./calibrate.py event

# 3. On the entry-options screen — confirm focus reads decisively.
./calibrate.py entry

# 4. During a live game — this writes the stamp grind.py needs.
./calibrate.py verify

# 5. Go.
./farm.sh          # then start ./health.sh in the background
./status.sh        # report, any time
```

`calibrate.py` is read-only except for `tempo` and `snapfloor`, which are marked.
Use it constantly. **Looking at the screen is the cheapest debugging there is,
and nearly every long debugging session on this project came from reasoning about
behaviour instead of capturing a frame.**

---

## Adapting it to a different event

Everything event-specific is in **`tools/config.py`** — that is the file's whole
purpose. To retarget:

1. `EVENT_MATCH` / `EVENT_REQUIRE` / `EVENT_REJECT` — how the events list is
   matched. ⛔ This promo lists **four sibling cards** (H2H, SQ H2H, CPU, SQ CPU)
   and pressing X on the wrong one enters a different mode, so the match is a
   title regex *plus* a require list *plus* a reject list. Run
   `calibrate.py event` and read the real text off the screen.
2. `OFFENSE` (play name, button, run timing) / `DEF_PLAY_BUTTON` and their
   tabs — the plays. The play name is checked against the visible favourites
   row before the button is pressed.
3. `LINEUP_ROWS` / `LINEUP_WANT` — the entry-options screen.
4. `HIKE_AT` / `CHEW_SKIP_BELOW` — whether to chew the play clock. **Measure
   it, don't assume it:** it depends on whether your offensive play ends in
   bounds. Keep `MIN_SNAP_WAIT` at 6.0 unless you have watched a shorter one
   work: the snap is refused until every player is set.

### What you do NOT need to touch

`tools/hud.py` finds the clock and score **by content**, not at fixed
coordinates. Madden uses different scoreboard layouts per broadcast presentation
(default, primetime, ...), and this event cycles through them like an NFL season
— we measured two different layouts in the first two games. A fixed crop reads
grass in half of them. Leave it alone.

---

## Files

| Path | What |
|---|---|
| `tools/config.py` | **every event-specific knob.** The only file a new event should need |
| `tools/screen.py` | everything that READS. No button is pressed from here |
| `tools/hud.py` | the live HUD, layout-independent |
| `tools/actions.py` | everything that PRESSES |
| `tools/grind.py` | the loop and the menu walk |
| `tools/calibrate.py` | look at the screen |
| `tools/ocr.py` | Vision OCR helpers |
| `tools/pad.py` | client for the daemon |
| `mini-pad/padd.py` | the daemon: input + in-process capture |
| `tools/farm.sh` · `status.sh` · `health.sh` | start · report · watch |

---

## Two things that will bite you

**1. `screencapture` costs ~1.9 s per call** — fixed overhead, not pixel work.
The daemon captures in-process via CoreGraphics in ~0.03 s. That single change
took games from 32 minutes to 17. **Never shell out to `screencapture`.**

**2. Restarting the pad daemon requires restarting chiaki afterwards**, or
presses are silently dropped. Relatedly: the first press after a chiaki restart
is often swallowed by window activation — which is why every menu selection in
this codebase verifies the screen changed instead of trusting a press.
