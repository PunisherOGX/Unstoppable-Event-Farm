#!/usr/bin/env python3
"""Every event-specific setting, in one place.

When the event changes, this is the only file that should need editing. Every
value can be overridden with the environment variable named next to it.

Screen regions are (x, y, w, h) in display points on a 1920x1080 chiaki-ng
stream with no letterboxing. `calibrate.py verify` checks them against a live
playcall screen and writes the stamp file `grind.py` requires before it runs.
"""
import os


def _env(name, default):
    return os.environ.get(name, default)


# ---------------------------------------------------------------------------
# THE EVENT: UNSTOPPABLE (CPU)
# ---------------------------------------------------------------------------
# Ten straight wins completes a run; one loss ends it. Re-entry is free, so a
# finished or lost run rolls straight into a fresh one. Every game starts
# 10-0 down, and the house rules steal points in both directions:
#     15+ yd run / 25+ yd pass   steal 2      rushing/passing TD   4
#     forced fumble / sack        steal 1      incomplete / fumble  steal 1
#     safety                      4
# An incomplete pass gives the CPU a point, which is why the offence is a run.
#
# The events list has an UNSTOPPABLE (H2H) card right above ours, and entering
# it would be a real game against a human. So a card must match the title,
# contain every REQUIRE word, and contain no REJECT word.
EVENT_LABEL = _env("MUT_EVENT_LABEL", "Unstoppable (CPU)")
EVENT_MATCH = _env("MUT_EVENT_MATCH", r"UNSTOPPABLE")
EVENT_REQUIRE = ("CPU",)
EVENT_REJECT = (r"\bSQ\b", r"\bSQUADS?\b", r"\bH2H\b", r"TRAINING\s*CAMP")
# How many characters after the title count as "the title". Short, so the next
# card's (CPU)/(H2H) marker is not picked up.
EVENT_TITLE_WINDOW = 60

QUARTER_MINS = int(_env("MUT_EVENT_QUARTER_MINS", "3"))
# A Q1 clock at or above this means the loop saw the game from kickoff.
FULL_GAME_CLOCK = int(_env("MUT_EVENT_FULL_CLOCK", str(QUARTER_MINS * 60 - 15)))

# Off: a loss (or a completed 10/10) rolls straight into a fresh run, which is
# what you want when running unattended. On (=1): stop before entering another
# game after any loss and leave a HALT file that farm.sh refuses to start over.
HALT_ON_ANY_LOSS = _env("MUT_EVENT_HALT_ANY_LOSS", "0") != "0"

# ---------------------------------------------------------------------------
# MENUS
# ---------------------------------------------------------------------------
# Rows are found by their words and the focused one by brightness, never by
# position. Reject words are checked first ("RESTRICTED" is inside
# "UNRESTRICTED").
LINEUP_WANT = _env("MUT_EVENT_LINEUP", "RESTRICTED").upper()
LINEUP_ROWS = {
    "RESTRICTED": {"want": ("RESTRICTED",), "not": ("UNRESTRICTED",)},
    "FREE": {"want": ("FREE", "UNRESTRICTED"), "not": ()},
}
POSTGAME_ROWS = {
    "FINISH": {"want": ("FINISH GAME",), "not": ()},
    "OTHER": {"want": ("VIEW HIGHLIGHTS", "PLAYER STATS", "TEAM STATS",
                       "SCORE SUMMARY"), "not": ()},
}
POSTGAME_WANT = "FINISH"

# ---------------------------------------------------------------------------
# THE PLAYS
# ---------------------------------------------------------------------------
# Button names are the pad daemon's: cross, moon (circle), pyramid (triangle),
# box (square). There is no "triangle" key.
#
# OFFENCE: FB DIVE WEAK, on triangle in the offensive FAVORITES. The play is
# selected, then snapped, then the left stick is held UP with R2 (sprint) from
# `after` seconds after the snap for up to `hold` seconds. The daemon lets go
# the moment the playcall screen comes back, so no stick input ever lands on a
# menu.
#
# Keep a play you are happy to run on cross (X) as well: cross is also the
# snap button, so a stray snap on the playcall screen selects whatever is there.
# Do not put the play on circle: circle is the loop's "back out" key.
OFF_TAB = _env("MUT_EVENT_OFF_TAB", "FAVORITES")
OFFENSE = {
    "name": "FB DIVE WEAK",
    "button": _env("MUT_EVENT_FBD_BUTTON", "pyramid"),
    "run_seq": {"after": float(_env("MUT_EVENT_FBD_RUN_AFTER", "1.0")),
                "hold": float(_env("MUT_EVENT_FBD_RUN_HOLD", "3.0"))},
}
# Hybrid dive: once CONFIRMED ahead by this many points, switch to a short hold
# so the back stops early instead of breaking long scores (a quicker score means
# more kickoffs and plays). Back to the full run when the lead drops below it.
# 0 = always the full run.
FBD_SLOW_LEAD = int(_env("MUT_EVENT_FBD_SLOW_LEAD", "10"))
FBD_SLOW_RUN = {"after": float(_env("MUT_EVENT_FBD_SLOW_AFTER", "0.2")),
                "hold": float(_env("MUT_EVENT_FBD_SLOW_HOLD", "1.5"))}

# DEFENCE: MID BLITZ, a plain press of square in the defensive FAVORITES.
DEF_TAB = _env("MUT_EVENT_DEF_TAB", "FAVORITES")
DEF_PLAY_BUTTON = _env("MUT_EVENT_DEF_BUTTON", "box")
DEF_PLAY_NAME = _env("MUT_EVENT_DEF_NAME", "MID BLITZ")

# Never punt: on a 4th-down PUNT screen, go back to FAVORITES and run the play.
# (Kickoffs use the same screen and are left alone.)
GO_FOR_IT_ON_FOURTH = _env("MUT_EVENT_GO_FOR_IT", "1") == "1"
# If the special-teams screen offers a FIELD GOAL, it is only kicked from
# inside the opponent's FG_MAX_YARDLINE (read off the HUD, with the arrow or
# GOAL TO GO proving it is their half). Otherwise the loop goes for it.
# The kick is snap, wait FG_PRESS_AFTER, then one accuracy press: skipping the
# power press lets the meter peak and come back down on its own.
FG_MAX_YARDLINE = int(_env("MUT_EVENT_FG_MAX_YARDLINE", "10"))
FG_PRESS_AFTER = float(_env("MUT_EVENT_FG_PRESS_AFTER", "3.5"))

# Press lengths. 200 ms: shorter presses were sometimes dropped over Remote Play.
OFF_SELECT_HOLD = float(_env("MUT_EVENT_SELECT_HOLD", "0.20"))
OFF_SNAP_HOLD = float(_env("MUT_EVENT_SNAP_HOLD", "0.20"))
# The run keys.
OFF_RUN_STICK = _env("MUT_EVENT_RUN_STICK", "lstick_up")
OFF_RUN_SPRINT = _env("MUT_EVENT_RUN_SPRINT", "r2")

# Before pressing the play button, check the visible favourites row shows the
# play (12 favourites = 4 rows, and stray stick input scrolls them). If another
# row shows, scroll and re-check; if the names are unreadable, press anyway.
PLAY_ROW = (70, 835, 1790, 70)          # the three play-name cards
PLAY_ROW_CHECK = _env("MUT_EVENT_PLAY_ROW_CHECK", "1") == "1"
PLAY_ROW_SCROLL_TRIES = int(_env("MUT_EVENT_PLAY_ROW_TRIES", "4"))

# What the daemon watches to end the run hold: the play-card band goes dark
# (>= PLAY_BAND_DARK) AND the L1 badge on the tab strip lights up. Both are only
# true on the playcall page.
PLAY_BAND = (80, 570, 1760, 250)
PLAY_BAND_DARK = float(_env("MUT_EVENT_PLAY_BAND_DARK", "0.70"))
PLAY_L1_BADGE = (72, 522, 44, 30)
PLAY_L1_BRIGHT = float(_env("MUT_EVENT_PLAY_L1_BRIGHT", "0.25"))

# ---------------------------------------------------------------------------
# THE CLOCK
# ---------------------------------------------------------------------------
# Two separate things:
#   1. The CHEW CLOCK tempo (R3 -> TEMPO), set on the first offensive play of
#      Q1 and again in Q3, because halftime resets it. On all game.
#   2. Waiting at the line for the play clock to fall to HIKE_AT before the
#      snap, but only while the game clock is actually running.
CHEW_SET_TEMPO = _env("MUT_EVENT_SET_TEMPO", "1") == "1"

# Wait at least this long after calling a play before snapping. The game will
# not take a snap until the players are set; 3.0s was tested and snaps were
# refused. 6.0 is the known-good value.
MIN_SNAP_WAIT = float(_env("MUT_EVENT_SNAP_WAIT", "6.0"))
# Arriving with this much play clock or less: wait the floor and snap.
CHEW_SKIP_BELOW = int(_env("MUT_EVENT_CHEW_SKIP_BELOW", "22"))
# Otherwise snap when the play clock reaches this. 99 = never wait.
HIKE_AT = int(_env("MUT_EVENT_HIKE_AT", "14"))
# Furthest out (seconds) a snap is scheduled from a single play-clock reading.
SNAP_SCHEDULE_MAX = float(_env("MUT_EVENT_SNAP_SCHED_MAX", "12"))
# Hard ceiling on the whole pre-snap wait.
SNAP_DEADLINE = 42.0

# Seen at the line with a play selected and this much play clock or less, but
# not on the playcall screen: the play was selected without a snap. Snap it.
PRESNAP_RESCUE_AT = int(_env("MUT_EVENT_PRESNAP_RESCUE", "22"))

# ---------------------------------------------------------------------------
# SCREEN REGIONS
# ---------------------------------------------------------------------------
TABSTRIP = (75, 515, 1160, 45)     # playcall tab strip, both sides
CLOCKS = (1180, 1005, 780, 80)     # "2nd | 1:07 | :26 | 4TH & 6"
SCORE_L = (520, 1006, 250, 76)     # opponent code + score
SCORE_R = (770, 1006, 270, 76)     # our score + code
ACTIONBAR = (380, 915, 1180, 48)   # "ADD/REMOVE FAVORITE ... BACK"
TEMPO_LABEL = (90, 585, 300, 48)   # the words "TEMPO ADJUSTMENT"
TEMPO_VALUE = (351, 580, 300, 60)  # the < NORMAL > box next to it
# Score crops must include the team code: Vision returns nothing for a lone digit.

# Tab layouts. The active tab is a light box behind dark text, so "which tab"
# is a brightness question. Centres are x offsets from TABSTRIP's left edge.
OFF_TABS = ["COACH", "FORMATION", "CONCEPT", "PLAY TYPE", "PLAYER",
            "PERSONNEL", "FAVORITES", "RECENT"]
OFF_X = [149, 316, 436, 549, 654, 794, 949, 1056]
DEF_TABS = ["COACH", "PERSONNEL", "CONCEPT", "PLAY TYPE", "FAVORITES", "RECENT"]
DEF_X = [149, 313, 436, 548, 666, 772]
ST_TABS = ["NORMAL", "HEAVY", "PUNT"]
ST_X = [96, 189, 268]

# Which side we are on is decided by how far right the strip's text reaches.
EXTENT_OFFENSE = 980
EXTENT_DEFENSE = 600

# Minimum peak/median brightness ratio to act on a tab read. Good reads land
# 2.9-3.5; misreads came from 1.8-2.0.
CONFIDENT = 2.4

# Words that only appear in a playcall tab strip.
TAB_WORDS = ("COACH", "SUGGESTIONS", "FORMATION", "CONCEPT", "PLAY TYPE",
             "PLAYER", "PERSONNEL", "GROUP", "FAVORITES", "RECENT",
             "NORMAL", "HEAVY", "PUNT")

# ---------------------------------------------------------------------------
# PACING
# ---------------------------------------------------------------------------
LOOP_SLEEP = float(_env("MUT_EVENT_LOOP_SLEEP", "1.0"))
# Poll interval during a live play (a cheap pixel scan) and right after a play.
LOOP_SLEEP_LIVE = float(_env("MUT_EVENT_LOOP_SLEEP_LIVE", "0.3"))
# Full-screen OCR while off the playcall screen, at most this often (seconds).
SLOW_PATH_EVERY = float(_env("MUT_EVENT_SLOW_PATH_EVERY", "4.0"))
# Check for a latched "hold to select" overlay on every Nth play call.
OVERLAY_CHECK_EVERY = int(_env("MUT_EVENT_OVERLAY_CHECK_EVERY", "5"))

# ---------------------------------------------------------------------------
# SCORE READING
# ---------------------------------------------------------------------------
# The score is read after the snap, during the play: every SCORE_EVERY plays
# in the first half and every play from Q3. It only feeds the hybrid-dive lead
# check and the history; wins and losses come from the event's own screens.
SCORE_EVERY = int(_env("MUT_EVENT_SCORE_EVERY", "2"))
# From Q3, a stat ticker can cover the score right after the snap: retry.
SCORE_TICKER_RETRIES = int(_env("MUT_EVENT_SCORE_RETRIES", "1"))
SCORE_TICKER_GAP = float(_env("MUT_EVENT_SCORE_RETRY_GAP", "1.0"))
# Scores CAN go down in this event (points are stolen), so a lower reading is
# accepted once it repeats this many times in a row.
SCORE_CONTRADICT = int(_env("MUT_EVENT_SCORE_CONTRADICT", "2"))
# Points are stolen one at a time here, so 1 is a legal score.
ALLOW_SCORE_OF_ONE = _env("MUT_EVENT_ALLOW_ONE", "1") == "1"
# A jump bigger than this per unread play (and never more than SCORE_JUMP_ABS in
# one read) is a misread until it repeats 3x.
SCORE_JUMP_MAX = 8
SCORE_JUMP_ABS = int(_env("MUT_EVENT_SCORE_JUMP_ABS", "16"))
# Nothing above this is a score (stat and field-position numbers share the strip).
SCORE_MAX = int(_env("MUT_EVENT_SCORE_MAX", "99"))

# ---------------------------------------------------------------------------
# WATCHDOGS
# ---------------------------------------------------------------------------
# The same side/tab this many times in a row with the game clock not moving:
# warn, then stop (the known Madden freeze: pause works, play calling does not).
STALL_WARN = int(_env("MUT_EVENT_STALL_WARN", "16"))
STALL_ABORT = int(_env("MUT_EVENT_STALL_ABORT", "40"))
# No game finished in this long: alert.
GAME_STALL_SECS = int(_env("MUT_EVENT_GAME_STALL", "2700"))

# A frozen chiaki feed reads as a valid screen forever, so byte-identical
# captures are counted. Stop trusting the picture after STALE_FRAMES; restart
# the stream after FROZEN_RESTART, but only if a playcall screen was seen in the
# last FROZEN_ONLY_WITHIN seconds (menus are legitimately static) and the
# freeze survives a FROZEN_CONFIRM_SECS re-check (a restart costs 25-220s).
STALE_FRAMES = int(_env("MUT_EVENT_STALE_FRAMES", "3"))
FROZEN_RESTART = 6
FROZEN_ALERT = 14
FROZEN_ONLY_WITHIN = float(_env("MUT_EVENT_FROZEN_WITHIN", "120"))
FROZEN_CONFIRM_SECS = float(_env("MUT_EVENT_FROZEN_CONFIRM", "4.0"))

PS5_HOST = _env("MUT_PS5_HOST", "192.168.1.50")

# ---------------------------------------------------------------------------
# FILES
# ---------------------------------------------------------------------------
RUN_DIR = "/tmp/mut-event"
SHOT_DIR = RUN_DIR
STUCK_DIR = f"{RUN_DIR}/stuck"
# One history file per event, so averages never mix events.
HISTORY = os.path.expanduser(_env("MUT_EVENT_HISTORY",
                                  "~/.mut_unstoppable_history.jsonl"))
STATE_FILE = os.path.expanduser("~/.mut_event_state.json")
CALIB_FILE = os.path.expanduser("~/.mut_event_calibration.json")

ALERT_FILE = f"{RUN_DIR}/ALERT"
STICKY_ALERT = f"{RUN_DIR}/ALERT.STICKY"   # only a human clears this
HALT_FILE = f"{RUN_DIR}/HALT"              # farm.sh will not start over it
FROZEN_FILE = f"{RUN_DIR}/FROZEN"


def _validate_buttons():
    """Refuse to start on a button name the pad daemon does not know.

    An unknown name is rejected by the daemon with nothing pressed, which looks
    exactly like a timing problem. Fail loudly here instead.
    """
    try:
        import pad
        keys = set(getattr(pad, "KEYS", {}) or {})
    except Exception:
        return
    if not keys:
        return
    named = {"DEF_PLAY_BUTTON": DEF_PLAY_BUTTON,
             "OFFENSE button": OFFENSE["button"],
             "OFF_RUN_STICK": OFF_RUN_STICK,
             "OFF_RUN_SPRINT": OFF_RUN_SPRINT}
    bad = {k: v for k, v in named.items() if v and v not in keys}
    if bad:
        raise SystemExit(
            "\nCONFIG ERROR - these buttons do not exist in the pad key map:\n"
            + "\n".join(f"    {k} = {v!r}" for k, v in bad.items())
            + f"\n\n  valid keys: {', '.join(sorted(keys))}\n"
              "  (triangle is 'pyramid', circle is 'moon', square is 'box')\n")


_validate_buttons()
