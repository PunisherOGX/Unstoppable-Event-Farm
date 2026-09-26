#!/usr/bin/env python3
"""Every event-specific knob in ONE place.

⛔ THE RULE THIS FILE EXISTS TO ENFORCE: nothing about the event is allowed to
be hardcoded anywhere else. The Air Raid build scattered play calls, regions and
tier rules through a 2100-line loop, and retiring the event meant auditing all
of it. When this event expires, this file is the only thing that has to change.

⛔ EVERY REGION HERE IS A CANDIDATE, NOT A FACT. They are carried over from the
Air Raid build because the display and the Madden HUD are the same, but the
handoff rule stands: recalibrate before trusting. `calibrate.py verify` looks at
a real screen, confirms each one, and writes the stamp file that `grind.py`
refuses to run without.
"""
import os

# ---------------------------------------------------------------------------
# THE EVENT
# ---------------------------------------------------------------------------
#                        UNSTOPPABLE (CPU)
#              read off the screens on Sep 24 2026, 20:14-20:17
#
# ⭐ ONE RUN, TEN STRAIGHT WINS, ONE LOSS AND IT IS OVER. The progress screen
# (entry options -> SQUARE) reads exactly:
#
#       OBJECTIVE PROGRESS
#       ELIMINATION                    COMPLETION
#       0/1 LOSSES                     0/10 WINS
#
# ⛔⛔ THERE ARE NO TIERS. Do not carry over tier reasoning from Clock's
# Ticking: there is no tier in the title, no ARCADE/COMP escalation to read,
# and no "tier 3-4 allows two losses" escape. **Every loss is fatal**, from
# game 1 to game 10. That makes this event the exact opposite of the last one
# in the only way that matters: there is no such thing as an acceptable loss,
# so NOTHING may be risked for speed.
#
# ⛔⛔⛔ EVERY GAME STARTS 10-0 DOWN. (Montrell, Sep 24: "each game starts
# down 10-0 FYI".) Confirmed on the scoreboard in game 1: CHI 10 - 0 JOH with
# the Q1 clock still at a full 3:00 and no play run. That is the event's
# gimmick - you are handed a deficit and have to erase it - and it rewrites
# the whole protection layer:
#   ⛔ "LOSING" IS THE NORMAL STATE. A deficit alarm, a Q3-and-losing alarm
#      and a Q4 tied-or-losing alarm would ALL fire in almost every game, and
#      with the auto-resume off an unanswered one now stops the farm. They are
#      off (INTERVENE=0). The LOSS HALT on the progress screen is the net
#      instead: play the game out, and if it is lost, stop and wait.
#   ⛔ DO NOT CHEW THE PLAY CLOCK WHILE TRAILING. Chewing shortens the game,
#      and a shorter game is exactly what you do not want when you start 10
#      points down - it destroys the possessions needed to come back. Chew is
#      now gated on actually LEADING (CHEW_ONLY_WHEN_AHEAD_TIERS includes the
#      only tier), which is what that knob was built for.
#   ⚠️ A 10-0 start also means the score reader sees a NON-ZERO opponent
#      score from the first frame. That is normal here; do not "fix" it.
#
# ⭐ CORRECTION (Sep 24, 21:05): THE EVENT CARD DOES PRINT A RECORD. It was
# read as absent at 0-0 because there was nothing to print yet; after game 1
# the events list logged `selected (tier 1, record 1-0)`. So the record-delta
# W/L detection and the events-list loss halt DO work in this event - there
# are two independent halts on a loss, not one.
#
# ⭐ Re-entry is free (both entry options read FREE), so an eliminated run
# rolls into a fresh one - the cost of a loss is the WINS BANKED, not coins.
# Losing game 9 throws away eight wins of work.
#
# ⭐ THE REWARD LADDER (Lineup Restricted track, bottom rungs - the rest needs
# RS to scroll and the sticks are not mapped): 0 wins = 5 coins, 1 = 1,500,
# 2 = 2,500. Featured reward: an 85+ OVR Unstoppable player pack. Extra
# rewards if 3x 85+ OVR Unstoppable players are in the lineup.
# Event expires 10/1 1:30 PM ET.
#
# ⛔⛔ THE HOUSE RULES ARE A STEAL-POINTS MODEL - THIS IS THE STRATEGY DRIVER.
# Straight from the event panel:
#
#       15+ Yd Run / 25+ Yd Pass ....... Steal 2 Pts
#       Rushing/Passing TD ............. 4 Pts
#       Forced Fumble/Sack ............. Steal 1 Pt
#       Incomplete Pass/Fumble ......... Steal 1 Pt
#       Safety ......................... 4 Pts
#
# "Steal" moves a point from one side to the other, so the rules cut BOTH
# ways and two of them are about OUR ball:
#   ⛔ AN INCOMPLETE PASS HANDS THEM A POINT. Last event's TEXAS SMASH pass
#      threw 2 incompletes in 9 snaps - that is -2 here, every game, for free.
#      A run play cannot throw an incompletion.
#   ⭐ A 15+ YARD RUN STEALS 2. Inside zone averaged 7.5 yds on COMP last
#      event; the chunk runs are worth double points here.
#   ⭐ Sacks and forced fumbles by our DEFENCE steal a point each, on top of
#      whatever the stop is worth - aggressive defence is rewarded directly,
#      which was NOT true last event.
# ⚠️ None of this is settled as a play call yet - Montrell decides the offence
# and defence from the live playcall screen (Sep 24). What IS settled is the
# arithmetic above.
#
# ⛔⛔ THE EVENTS LIST HAS A TWIN OF THIS EVENT DIRECTLY ABOVE OURS.
# Seen on screen Sep 24: "UNSTOPPABLE (H2H)" sits in the row immediately above
# "UNSTOPPABLE (CPU)", same artwork, same timer, same FREE entry options. H2H
# is head-to-head against a human - entering it would be a real loss against a
# real opponent. Two TRAINING CAMP (CPU) rows sit above that.
#
# Ours is:  UNSTOPPABLE (CPU)
#
# So the match is THREE tests, not one:
#   EVENT_MATCH    the title, loosely - Vision mangles punctuation and renders
#                  "(CPU)" as "(CPU." about half the time, so never anchor on
#                  punctuation
#   EVENT_REQUIRE  every one of these must appear in the title window
#   EVENT_REJECT   NONE of these may appear in it
#
# ⛔ The reject list is the part that matters. A loose title match alone would
# happily select the H2H card sitting right next to ours.
# The human name, for logs and alerts. Nothing matches on it.
EVENT_LABEL = os.environ.get("MUT_EVENT_LABEL", "Unstoppable (CPU)")
EVENT_MATCH = os.environ.get("MUT_EVENT_MATCH", r"UNSTOPPABLE")
EVENT_REQUIRE = ("CPU",)
EVENT_REJECT = (r"\bSQ\b", r"\bSQUADS?\b", r"\bH2H\b", r"TRAINING\s*CAMP")
# How many characters after the title count as "the title window" for the
# require/reject tests. Short on purpose: the (CPU) / (H2H) marker sits in the
# title itself, and a wide window would drag in the NEXT card's marker.
EVENT_TITLE_WINDOW = 60

# ⭐ CONFIRMED FOR THIS EVENT (Sep 24): FOUR 3-MINUTE QUARTERS. `calibrate.py
# verify` read Q1 game=180s, and the quarter-change log has since shown Q2, Q3
# and Q4 each starting at 180s / 175s ("FULL"). No longer an assumption.
QUARTERS = 4
QUARTER_MINS = int(os.environ.get("MUT_EVENT_QUARTER_MINS", "3"))
# If the first clock we ever see in Q1 is at least this, the loop did not miss
# a meaningful part of the game. Derived from the quarter length above.
FULL_GAME_CLOCK = int(os.environ.get(
    "MUT_EVENT_FULL_CLOCK", str(QUARTER_MINS * 60 - 15)))

# ---------------------------------------------------------------------------
# ONE TIER, AND A LOSS ENDS THE RUN
# ---------------------------------------------------------------------------
# The tier machinery is kept (the loop is built around it) but collapsed to a
# single tier, so `tier` is always 1 and nothing can branch on it:
#     tier = min(TIERS, wins // WINS_PER_TIER + 1)  ->  always 1
TIERS = 1
WINS_PER_TIER = int(os.environ.get("MUT_EVENT_WINS_PER_TIER", "10"))
WINS_TO_COMPLETE = int(os.environ.get("MUT_EVENT_WINS_TO_COMPLETE", "10"))
LOSS_LIMIT_TIERS = {1}
LOSS_LIMIT = 1

# ⛔⛔ ANY LOSS HALTS THE FARM, ON ANY SCREEN THAT SHOWS A LOSS COUNT.
# Last event this gate was `_t34` - "is this tier 3 or 4" - because tiers 1-2
# could absorb a loss. Here there is no such tier, and the Sep 19 run died
# because a halt was conditional. With one life, the gate is unconditional.
# ⭐⭐ OFF FOR OVERNIGHT RUNNING (Sep 24, ~23:00. Montrell: "I want this farm
# to run all night after the run finishes. It should be starting a new one.")
#
# A loss ends a run, and Madden rolls straight into a FRESH run of 10 - so with
# the halt off, a loss costs the wins banked and nothing else, and the farm
# keeps earning through the night instead of sitting idle from whenever it
# first lost. Same for a COMPLETED 10/10: it re-enters and starts again.
#
# ⛔ THE TRADE: nobody is told about the loss until morning. The record is in
# ~/.mut_unstoppable_history.jsonl and the log, and the progress screen still
# logs every `x/1 LOSSES` / `x/10 WINS`, so the night is fully reconstructable.
# ⛔ Set MUT_EVENT_HALT_ANY_LOSS=1 to go back to supervised running, where the
# farm stops before entering another game and waits for a decision.
HALT_ON_ANY_LOSS = os.environ.get("MUT_EVENT_HALT_ANY_LOSS", "0") != "0"

# ⛔ Difficulty is UNREAD. The card says only "Take on CPU". Whether the live
# badge reads ARCADE or COMP has not been seen for this event, so tier 1 is
# mapped to ARCADE for LOGGING ONLY and nothing branches on it. Check the
# badge on the first drive and write down what it says.
ARCADE_TIERS = {1}
COMP_TIERS = set()      # ⚠️ unread for this event

# ---------------------------------------------------------------------------
# ENTRY OPTIONS - the ~11-reward mistake, and why this is a screen READ
# ---------------------------------------------------------------------------
# Last event the entry screen offered Coins / Packs, the code assumed which row
# had focus, the assumption was BACKWARDS, and roughly 11 tier rewards went down
# the wrong path before anyone looked at the screen.
#
# This event offers a LINEUP restriction instead. We always want RESTRICTED.
# ⛔ Never a blind directional press. `choose_lineup` finds both options by
# their TEXT wherever they are on screen, confirms which one actually has focus,
# and only then presses cross - so a layout change during the event's run
# cannot silently send us down the wrong path.
# The rows are named "Clock's Ticking - Lineup Restricted" and its Free
# counterpart (Montrell, Sep 12), so the word RESTRICTED is what identifies ours.
LINEUP_WANT = os.environ.get("MUT_EVENT_LINEUP", "RESTRICTED").upper()
# Words that identify each row. Matched case-insensitively as substrings.
# ⛔ "RESTRICTED" is a substring of "UNRESTRICTED", so the reject list is
# checked FIRST and a row matching it can never be taken as the wanted one.
LINEUP_ROWS = {
    "RESTRICTED": {"want": ("RESTRICTED",), "not": ("UNRESTRICTED",)},
    "FREE": {"want": ("FREE", "UNRESTRICTED"), "not": ()},
}

# ---------------------------------------------------------------------------
# THE END-OF-GAME MENU
# ---------------------------------------------------------------------------
# ⭐ A FULL GAME ENDS DIFFERENTLY FROM AIR RAID (Montrell, Sep 12). Because this
# is a complete four-quarter game, Madden shows its own post-game menu before
# any event screen:
#
#       FINISH GAME      <- focused on arrival, and what we want
#       VIEW HIGHLIGHTS
#       PLAYER STATS
#       TEAM STATS
#       SCORE SUMMARY
#
# ⛔ It is READ, not assumed. FINISH GAME being focused by default is exactly
# the kind of "obviously it's the first one" claim that cost ~11 rewards on the
# entry screen last event, so it goes through the same verified selector.
POSTGAME_ROWS = {
    "FINISH": {"want": ("FINISH GAME",), "not": ()},
    "OTHER": {"want": ("VIEW HIGHLIGHTS", "PLAYER STATS", "TEAM STATS",
                       "SCORE SUMMARY"), "not": ()},
}
POSTGAME_WANT = "FINISH"

# ---------------------------------------------------------------------------
# PLAY CALLING - one play each side, chosen by Montrell, Sep 12 2026
# ---------------------------------------------------------------------------
# OFFENSE: FAVORITES -> BOX = FULLBACK DIVE.
#   Up the middle, always IN BOUNDS, and run plays carry no penalty this event.
#   In-bounds is the whole point: the game clock keeps running after the whistle,
#   which is what makes chewing the play clock actually burn game clock.
# DEFENSE: FAVORITES -> BOX = MID BLITZ.
# ⭐ THE FAVORITES MAPPING (Montrell, Sep 13 2026):
#       BOX / square  = the new PASS play   <- what we run now
#       CROSS / X     = FULLBACK DIVE       <- the old play, kept as the fallback
#
# ⛔⛔ IF YOU EVER SWITCH BACK TO THE DIVE, note that CROSS IS ALSO THE SNAP
# BUTTON. Selecting the play and snapping would both be `cross`, so the sequence
# becomes cross (select) -> wait -> cross (snap) and the two are indistinguishable
# in a log. Set MUT_EVENT_OFF_PLAY_BUTTON=cross and MUT_EVENT_THROW=0 together —
# running the dive while still throwing would be worse than either alone.
OFF_PLAY_BUTTON = os.environ.get("MUT_EVENT_OFF_PLAY_BUTTON", "box")
OFF_PLAY_NAME = os.environ.get("MUT_EVENT_OFF_PLAY_NAME", "BULLET PASS (RB)")

# ---------------------------------------------------------------------------
# THE THROW  (Montrell, Sep 13 2026 — practised and confirmed)
# ---------------------------------------------------------------------------
# ⛔ WHY THE OFFENCE CHANGED. The fullback dive won every ARCADE game (~18 pts
# avg) and could not score AT ALL on COMP — two tier-3 games ended 0-0 through
# regulation while the mid blitz still shut the opponent out. A run-only offence
# is solvable for a tier-3 defence.
#
# This play is on the SAME button (box on FAVORITES); what changed is that we now
# throw after the snap instead of letting the run develop:
#
#       press X (snap)  ->  wait 2.0s  ->  hold R1 for 1.0s  ->  NOTHING else
#
# ⭐⭐ THE HOLD LENGTH MATTERS AND 1.0s IS MEASURED. At 2.0s the receiver CAUGHT
# it and then just stood there: holding a receiver's button past the catch takes
# CONTROL of that player, so the CPU stops running it for us. The whole value of
# this play is that the computer runs after the catch. Release early.
#
# ⛔ NOTHING may be pressed after the throw, for the same reason.
#
# ⭐ Expected side effect: scoring MORE should make games SHORTER (fewer plays),
# but each score also buys a PAT and a kickoff. Montrell's read is it may score
# too much on tier 1-2 and cost time there, in which case flip those tiers back
# to the dive with MUT_EVENT_THROW=0 and keep this for tier 3.
# ---------------------------------------------------------------------------
# ⭐⭐ THE OFFENCE IS CHOSEN BY THE LIVE BADGE (Montrell, Sep 13 2026)
# ---------------------------------------------------------------------------
# Measured over clean games:
#     FULLBACK DIVE   n=3   20.7 min   41 plays   21 pts   2.79 games/hour
#     BULLET PASS     n=2   28.0 min   48 plays   30 pts   2.08 games/hour
#                          (28.2 and 27.9 - remarkably consistent)
#
# The pass costs ~7.3 min/game, a 25% throughput loss, for TWO reasons:
#   1. more scores -> more PATs and kickoffs -> more plays
#   2. scoring STOPS THE CLOCK, so play-clock chewing gets far fewer chances to
#      fire (measured: 6 snaps chewed vs 13 that found the clock already stopped)
#
# But on COMP the dive scored **ZERO through regulation, twice**. So:
#     ARCADE (tiers 1-2)  -> FULLBACK DIVE, no throw   - fast, and it wins there
#     COMP   (tiers 3-4)  -> BULLET PASS, throw        - slower, but it SCORES
#
# ⛔ The badge is the only tier signal that does not drift (there is no tier
# number on the event card - see enter_event). ARCADE = tiers 1-2, COMP = 3-4.
# ⭐⭐ EXPERIMENT, Sep 13 2026 (Montrell): DIVE ON EVERY TIER, NO RESCUE.
# He has bought a much better fullback, so the question is whether the dive now
# scores on COMP - where it previously managed ZERO through regulation three
# times. Pure run game, every down, no pass anywhere.
#
# ⛔ TO REVERT: set MUT_EVENT_DIVE_ONLY=0. The pass profile below is intact and
# every timing it needs is still recorded - nothing has been deleted.
# ⛔ Experiment OVER (Sep 13). The better fullback did NOT make the dive score
# on COMP - it was still scoreless there. Back to: dive on 1-2, pass on 3-4.
DIVE_ONLY = os.environ.get("MUT_EVENT_DIVE_ONLY", "0") == "1"

# ⭐⭐ QB POWER - THE OFFENCE (Sep 15). Tuned on a live console in practice:
# snap, 0.5s, then stick-up + sprint for 3s. No throw, so no throw window to
# miss and no sack to take while the QB holds the ball - which is what parked
# TEXAS SMASH. Favorites: X.
_DIVE = {"button": os.environ.get("MUT_EVENT_ARCADE_BUTTON", "box"),
         "name": "QB POWER", "throw": False}
_PASS = {"button": os.environ.get("MUT_EVENT_COMP_BUTTON", "cross"),
         "name": "RPO READ SCREEN", "throw": True}

# ⭐ HYBRID DOWN-BASED OFFENCE ON COMP (Sep 14, Montrell).
# Dive on 1st and 2nd - it is faster, keeps the clock moving and needs no throw
# window - then pass on 3rd and 4th, where a two-yard gain is a punt anyway.
#
# ⛔ WHEN THE DOWN CANNOT BE READ, PASS. The two errors are not equal: passing
# on a 1st down is simply the offence we ran all night, while diving on a 3rd
# and long hands the ball back. Fail toward the play that can convert.
# ⭐ GOAL LINE: DIVE ONLY. (Sep 14, Montrell.)
# "That pass play doesn't work too well in a goal line situation." Read off
# "1ST & GOAL" rather than the field-position arrow - it is on the down row we
# already parse, so it needs no new geometry and no arrow-direction logic.
# ⭐ NEVER PUNT. (Sep 14, Montrell chose "go for it every time".)
# ⛔ Kickoffs are EXCLUDED - the same screen serves both and kicking off is
# correct and unavoidable. The discriminator is in grind.py's specialteams
# branch, and it falls back to punting if it cannot reach FAVORITES, because a
# delay of game on 4th down is worse than the punt.
GO_FOR_IT_ON_FOURTH = os.environ.get("MUT_EVENT_GO_FOR_IT", "1") == "1"

# ⭐ ONE-OFF DIAGNOSTIC: dump a FULL-FRAME OCR on an offensive playcall, so we
# can find out whether the YARD LINE is on screen and where. Needed before any
# field-goal-range rule can exist - Montrell wants to kick on 4th down inside
# some yard line, and we cannot read field position yet.
# ⛔ Off by default: it costs a full-screen OCR on the play it fires.
DUMP_FIELD_POS = os.environ.get("MUT_EVENT_DUMP_FIELDPOS", "0") == "1"

GOALLINE_DIVE = os.environ.get("MUT_EVENT_GOALLINE_DIVE", "0") == "1"

# ⛔⛔ FIELD GOAL ON 4TH & GOAL - SCAFFOLDED, DELIBERATELY OFF.
# Montrell wants this, and the KICK METER timing is already solved (3.5s, from
# the practice session he ran). What is NOT known is how the 4th-down special
# teams screen presents the FG option: the handler currently takes the MIDDLE
# play, which is correct for punts and kickoffs, and the capture armed for that
# screen has only ever caught KICKOFFS.
#
# ⛔ Do not enable this from reasoning. Capture the 4th-and-goal screen, read it,
# then wire the selection. Guessing a button sequence on an unread screen is how
# the old build walked into MY TEAM and the PACKS screen.
# ⛔⛔ OFF (Sep 24, Montrell: "we do not want to kick any field goals").
# Two independent reasons, either one sufficient:
#   1. A FIELD GOAL IS NOT IN THIS EVENT'S SCORING TABLE AT ALL. The house
#      rules list TD 4, safety 4 and the steals - no field goal. A 4th-&-goal
#      run that scores is worth 4; a kick is worth an unknown, probably 0.
#   2. `call_field_goal` presses FG_BUTTON (`pyramid`) after only reaching the
#      offense tab - it does NOT scroll to or verify a row containing
#      "FIELD GOAL". With FB DIVE now on triangle it would have selected the
#      DIVE and snapped it while reporting a kick. Its own comment warns:
#      "FAVORITES holds live offensive plays; a wrong button here calls one
#      and snaps it."
FG_ON_FOURTH_AND_GOAL = os.environ.get("MUT_EVENT_FG_4TH_GOAL", "0") == "1"
# ⭐ Montrell is FAVORITING the field goal, so selecting it is an ordinary
# FAVORITES button press - the same screen and the same mechanism as the dive
# and the pass. No unread special-teams screen involved.
# ⛔ Until he says WHICH button, this stays None and the kick is skipped rather
# than guessed. A wrong button on FAVORITES calls a live offensive play.
# ⭐ CONFIRMED BY MONTRELL (Sep 14), FAVORITES mapping:
#   square/box = BULLET PASS · cross/X = FULLBACK DIVE · triangle = FIELD GOAL
FG_BUTTON = os.environ.get("MUT_EVENT_FG_BUTTON", "pyramid")
FG_PLAY_NAME = os.environ.get("MUT_EVENT_FG_NAME", "FIELD GOAL")
# Only kick if it actually changes the game: tied, ahead, or down by 3 or less.
FG_MAX_DEFICIT = int(os.environ.get("MUT_EVENT_FG_MAX_DEFICIT", "3"))

# ⭐ DEFENSIVE MACRO: hold the play button, tap DOWN x3 inside the hold, release.
# (Sep 14, Montrell: "that will call the play but with my custom adjustments.")
# ⛔ ONE /combo CALL, held server-side. The taps must land INSIDE the hold, and
# an HTTP round trip between them is larger than the timings involved - the same
# reason the throw uses /combo rather than separate presses.
# ⛔ TURNED OFF Sep 15: Montrell observed it giving up MORE touchdowns than a
# plain play press. Kept intact to revisit.
# ⭐ VERIFIED LIVE (Sep 14, tier 4 game 1, FIRST attempt). Montrell confirmed the
# play came out with his custom adjustments applied. 1.0s before the first tap
# is enough for the adjustment menu to appear - do not shorten it on a hunch.
# ⭐ THE MACRO WORKS - IT RAN ALL DAY ON SQUARE WITH THREE D-PAD DOWNS.
# ⛔ (Sep 16) When it stopped selecting on triangle I started "fixing" the
# TIMINGS - pre 1.0 -> 0.8, post 0.0 -> 0.4 - and broke the one part that was
# proven. Montrell: "the macro didn't break it... the only thing we're changing
# is the initial button and how many times we press down."
# Keep pre/post/tap_hold/gap EXACTLY as they were. Change only the button and
# the tap count.
# ⭐ MID BLITZ, PLAIN PRESS (Sep 19, Montrell, tier 4 game 2): "go back to
# running the mid blitz play, which is mapped to square. No need for any
# macros." Macro OFF, button box. ⛔ TO REVERT: MUT_EVENT_DEF_MACRO=1 and
# MUT_EVENT_DEF_BUTTON=pyramid / MUT_EVENT_DEF_NAME="COVER 2 MAN".
# ⭐⭐ MID BLITZ WITH ITS MACRO (Sep 25, Montrell: "switch the defensive play
# to use the macro for mid blitz"). Air Raid's "Defense solved: MID BLITZ,
# combo(..., [down,down,down])" and the Sep 14 all-day run on square were both
# THREE downs. Still on square here. Timings untouched (see above).
# ⛔ TO REVERT to the plain press: MUT_EVENT_DEF_MACRO=0.
# ⛔ OFF AGAIN (Sep 25, 12:35, Montrell: "lets try a diffrent defense...just
# simply mid blitz no macro"). Plain press on square. MUT_EVENT_DEF_MACRO=1
# puts the down x3 macro back.
DEF_MACRO = os.environ.get("MUT_EVENT_DEF_MACRO", "0") == "1"
DEF_MACRO_PRE = float(os.environ.get("MUT_EVENT_DEF_MACRO_PRE", "1.0"))
DEF_MACRO_TAPS = os.environ.get("MUT_EVENT_DEF_MACRO_TAPS", "down down down").split()
DEF_MACRO_TAP_HOLD = float(os.environ.get("MUT_EVENT_DEF_MACRO_TAP_HOLD", "0.08"))
DEF_MACRO_GAP = float(os.environ.get("MUT_EVENT_DEF_MACRO_GAP", "0.14"))
# ⛔ HOW LONG TRIANGLE STAYS HELD *AFTER* THE D-PAD TAP, BEFORE RELEASING.
# (Sep 16) The defensive play is selected ON RELEASE, and we were releasing the
# instant after the tap (post=0). The adjustment never registered, so the play
# was never called - the loop just re-called defence every few seconds while the
# playcall screen sat there.
DEF_MACRO_POST = float(os.environ.get("MUT_EVENT_DEF_MACRO_POST", "0.0"))

HYBRID_TIERS = {int(t) for t in
                os.environ.get("MUT_EVENT_HYBRID_TIERS", "3 4").split()}
HYBRID_RUN_DOWNS = {int(d) for d in
                    os.environ.get("MUT_EVENT_HYBRID_RUN_DOWNS", "").split()}

# ⭐ PASS ON EVERY DOWN, EVERY TIER (Sep 14, Montrell: "lets stay away from fb
# dive and run the pass play each down for now... want to test it out some more
# and see some optimization"). The dive profile is left intact - flip
# MUT_EVENT_PASS_ALWAYS=0 to put tiers 1-2 back on it.
PASS_ALWAYS = os.environ.get("MUT_EVENT_PASS_ALWAYS", "1") == "1"

# ⭐⭐ QB SNEAK - THE OFFENCE, EVERY TIER (Sep 18, Montrell). Fresh run after
# the tier-3 loss. Favorites: X (cross). Play call -> snap floor (6.0s) -> hike.
# No throw, no stick, NO FLIP. "Maybe the simplest yet ... might be just simple
# enough to work as long as the QB doesn't fumble a ton." Defence unchanged.
# ⛔ TO REVERT: MUT_EVENT_SNEAK_ONLY=0 puts the pass/dive table back exactly.
_SNEAK = {"button": os.environ.get("MUT_EVENT_SNEAK_BUTTON", "cross"),
          "name": "QB SNEAK", "throw": False, "run": False, "flip": False}
SNEAK_ONLY = os.environ.get("MUT_EVENT_SNEAK_ONLY", "0") == "1"   # ⛔ OFF (Sep 18): 19 sneaks, 0 points

# ⭐⭐ INSIDE ZONE - THE OFFENCE, EVERY TIER (Sep 19, Montrell). Tier 4's
# defence read the RPO screen at the snap: 13 snaps, every drive a three-and-
# out, not one first down. He labbed a Gun inside zone run by hand and then
# through practice_macro.py (macros/inside_zone.json) against random defences:
# "it looks pretty decent". Favorites: X (cross). Play call -> snap floor ->
# hike, 1.0s, then L-stick UP + R2 held 3.0s, released. NO throw, NO flip ("no
# need to flip play on this one since it's a run play"). The whole snap+run is
# ONE daemon /sequence, exactly what practice ran - not run_phase, which
# refuses without a throw instant.
# ⛔ 2.0s was tried for the hold start (Montrell: "too late now"). 1.0s it is.
# ⛔ TO REVERT: MUT_EVENT_IZ_ONLY=0 puts the pass/dive table back exactly.
IZ_ONLY = os.environ.get("MUT_EVENT_IZ_ONLY", "1") == "1"
OFF_IZ_RUN_AFTER = float(os.environ.get("MUT_EVENT_IZ_RUN_AFTER", "1.0"))
OFF_IZ_RUN_HOLD = float(os.environ.get("MUT_EVENT_IZ_RUN_HOLD", "3.0"))
_IZ = {"button": os.environ.get("MUT_EVENT_IZ_BUTTON", "cross"),
       "name": "INSIDE ZONE", "throw": False, "run": False, "flip": False,
       "run_seq": {"after": OFF_IZ_RUN_AFTER, "hold": OFF_IZ_RUN_HOLD}}

# ⭐⭐ THE TIER 3-4 PASS (Sep 19, Montrell, after finishing tier 4 by hand).
# Inside zone moved the ball on COMP but "still not consistently scoring every
# drive". He labbed a new pass in practice; practice_macro.py ran it at 3.0s
# ("way longer than 3 seconds... seems like 6"), 1.5s, 1.75s, then 1.25s:
# "thats perfect". Favorites: SQUARE (box), selected the way the defence macro
# selects - HOLD the button, D-pad DOWN once inside the hold, release ("need
# macro hold square and down once on d pad to select"). Then play call ->
# snap floor -> hike, 1.25s, throw to X (cross, 0.3s). No stick, no sprint,
# NO flip. Tiers 1-2 stay on INSIDE ZONE.
# ⛔ The select macro's timings are the DEFENCE macro's, which ran all day
# on square with d-pad downs (Sep 14). Change the button/taps, not the
# timings.
# ⛔ MUT_EVENT_TX_NAME is what the favourites-row check looks for. Until
# Montrell gives the play's name it is blank, and the row is verified by
# INSIDE ZONE (the X slot on the same row) instead - see `row_name`.
# ⛔ TO REVERT: MUT_EVENT_TX=0 puts INSIDE ZONE back on tiers 3-4.
# ⛔⛔ OFF FOR THIS EVENT (Sep 24, Montrell: "lets run inside zone (x) on
# offense for now"). INSIDE ZONE on X is the ONLY offence: with TX_ON=0 both
# the ARCADE and COMP entries of OFF_BY_BADGE resolve to _IZ and RESCUE_PLAY
# resolves to _IZ as well, so NOTHING can switch the play mid-game. That is
# the point - one loss ends the run, so an untested play must never appear on
# its own. It also suits the house rules: a run cannot throw an incompletion,
# and an incompletion hands the CPU a point here.
# ⛔ MUT_EVENT_TX=1 brings the pass back once it is proven for this event.
TX_ON = os.environ.get("MUT_EVENT_TX", "0") == "1"
OFF_TX_THROW_AFTER = float(os.environ.get("MUT_EVENT_TX_THROW_AFTER", "1.25"))
OFF_TX_THROW_HOLD = float(os.environ.get("MUT_EVENT_TX_THROW_HOLD", "0.3"))
_TX = {"button": os.environ.get("MUT_EVENT_TX_BUTTON", "box"),
       # ⭐ (Sep 25, Montrell: "the pass play texas smash is square") - the
       # row check now verifies the pass itself, not a neighbour on the row.
       "name": os.environ.get("MUT_EVENT_TX_NAME", "") or "TEXAS SMASH",
       "row_name": os.environ.get("MUT_EVENT_TX_NAME", "") or "TEXAS SMASH",
       "throw": False, "run": False, "flip": False,
       "select_macro": {"taps": os.environ.get("MUT_EVENT_TX_TAPS", "down").split(),
                        "pre": DEF_MACRO_PRE, "tap_hold": DEF_MACRO_TAP_HOLD,
                        "gap": DEF_MACRO_GAP, "post": DEF_MACRO_POST},
       "throw_seq": {"after": OFF_TX_THROW_AFTER, "hold": OFF_TX_THROW_HOLD,
                     "button": os.environ.get("MUT_EVENT_TX_THROW_BUTTON", "cross")}}

# ⭐ MUT_EVENT_TX_ALL=1: the pass on EVERY tier (Montrell, Sep 19 15:20, tier-1
# game 3 tied 0-0 in Q4: "switch to that pass play... let it run that the
# rest of the game. Next game it can go back"). A one-game test knob.
TX_ALL = os.environ.get("MUT_EVENT_TX_ALL", "0") == "1"
OFF_BY_BADGE = {"ARCADE": _TX if (TX_ON and TX_ALL) else _IZ,
                "COMP": _TX if TX_ON else _IZ} if IZ_ONLY else \
    {"ARCADE": _SNEAK, "COMP": _SNEAK} if SNEAK_ONLY else {
    "ARCADE": _PASS if PASS_ALWAYS else _DIVE,
    "COMP": _DIVE if DIVE_ONLY else _PASS,
}
# ⛔ The tier 1-2 RESCUE (below) "switches to the pass" = the COMP entry. With
# the tier 3-4 pass on, that would run an untested play on tiers 1-2 in a
# close game - Montrell: "run in tier 3&4 only". So the rescue stays on the
# ARCADE play (INSIDE ZONE) while TX_ON; flip MUT_EVENT_RESCUE_TX=1 to let it
# use the pass.
RESCUE_PLAY = OFF_BY_BADGE["COMP"] if (
    not TX_ON or os.environ.get("MUT_EVENT_RESCUE_TX", "0") == "1") \
    else OFF_BY_BADGE["ARCADE"]

# ⭐⭐ FB DIVE ON CIRCLE - A TIMING EXPERIMENT, NOT A STRATEGY CHANGE.
# (Sep 24, Montrell: "next game, I want to switch to the fb dive play which is
# circle ... just to see if that changes the timing at all".)
#
# ⛔ ONE VARIABLE. The snap floor, the run sequence, the chew rules and the
# defence are all left EXACTLY as inside zone had them - only the play and its
# button change. Process rule 6: two changes at once cost a full day once,
# because one silently disabled the other.
#
# ⭐ The baseline to compare against is the WALL-CLOCK CYCLE between wins,
# measured from the log: inside zone ran **16.7 min / 38 plays** (win 1 -> 2,
# no restart in between) and 18.8 min / 45 plays (win 2 -> 3, including ~1 min
# of restart overhead). ⚠️ Use the log-derived cycle, NOT the history `min`
# field, for this comparison - games 1-3 wrote no rows at all and game 4 is
# flagged `partial`, so the cycle time is the only figure measured the same way
# on both sides.
#
# ⛔ `row_name` matching takes the FIRST TWO WORDS of the name, so the row check
# looks for "FB DIVE" - which is what the favourites row reads
# ("... | FB DIVE WEAK | GOAL ..."), spaces stripped.
# ⛔ TO REVERT: MUT_EVENT_FBD=0 puts INSIDE ZONE on X back, unchanged.
# ⛔ TRIANGLE IS `pyramid`. "triangle" is NOT a key - the daemon rejects it
# with a 400 and presses NOTHING, which looks exactly like a macro timing
# fault. config.py refuses to start on an unknown button name.
_FBD = {"button": os.environ.get("MUT_EVENT_FBD_BUTTON", "pyramid"),
        "name": "FB DIVE WEAK", "throw": False, "run": False, "flip": False,
        # ⭐ (Sep 25, Montrell's macro: wait 6000ms -> A 200ms -> LS_UP + RT
        # hold 1500ms.) The hold starts the moment the 200ms snap press ends
        # and lets go after 1.5s, so the back stops sprinting: "should prevent
        # really long runs scoring too quick". Was 1.0s after / 3.0s hold.
        # ⛔ TO REVERT: MUT_EVENT_FBD_RUN_AFTER=1.0 MUT_EVENT_FBD_RUN_HOLD=3.0
        "run_seq": {"after": float(os.environ.get("MUT_EVENT_FBD_RUN_AFTER", "1.0")),
                    "hold": float(os.environ.get("MUT_EVENT_FBD_RUN_HOLD", "3.0"))}}
# ⛔⛔⛔ REVERTED AFTER 9 PLAYS - CIRCLE IS ALREADY THE LOOP'S "BACK OUT" KEY.
# (Sep 24, 22:15. Montrell: "it's calling coach suggestions and then not hiking
# the ball in time".) Putting the play on circle collides head-on with the
# navigation: `moon` is what the loop presses to back out of any sub-screen it
# does not recognise, so on the playcall screen it lands on COACH SUGGESTIONS,
# takes the wrong play, backs out, and burns the play clock -> delay of game.
#
# MEASURED, both offences, same session:
#     INSIDE ZONE on cross : 0.17 - 0.23 sub-screen back-outs per play
#     FB DIVE on circle    : 0.44 per play   <- DOUBLE, in 9 plays
#
# ⭐ This is exactly what the archive's rule was protecting: "THE PRIMARY PLAY
# IS ON `cross` DELIBERATELY - the same button as the snap. The slot cannot be
# empty, so put the play we WANT there." The rule was about a stray SNAP press;
# the same reasoning kills circle for the opposite reason - a stray BACK press.
#
# ⭐ TO RUN THE FB DIVE TIMING TEST PROPERLY: move the dive onto **X** in the
# Madden favourites and set MUT_EVENT_FBD_BUTTON=cross MUT_EVENT_FBD=1. The
# button, not the play, was the problem - the dive itself called and snapped
# fine (`FB DIVE WEAK - snapped at +6.0s`).
# ⭐ RE-ENABLED ON TRIANGLE (Sep 24, Montrell: "it's not circle is triangle...
# X is still a good fallback if it accidentally presses"). Triangle is clean:
# the loop's escape key is CIRCLE, `_clear_held_overlay` taps square, and the
# only other pyramid user (the field goal) is now off. INSIDE ZONE stays in the
# X slot on purpose, so a stray press still calls a play we are happy to run -
# the archive's rule, applied as intended this time.
FBD_ON = os.environ.get("MUT_EVENT_FBD", "1") == "1"
# ⭐⭐ HYBRID DIVE (Sep 25, Montrell: "we use our original version of the fb
# dive that was putting up multiple scores a game and then when we are winning
# by 10 points or more we go back to the slow version"). Base run is the
# original 1.0s / 3.0s hold. With a CONFIRMED lead of FBD_SLOW_LEAD or more, the
# dive switches to the short hold (0.2s / 1.5s - the back stops running) and
# goes back to the full run the moment the lead drops below it.
# ⛔ MUT_EVENT_FBD_SLOW_LEAD=0 disables it (always the full run).
FBD_SLOW_LEAD = int(os.environ.get("MUT_EVENT_FBD_SLOW_LEAD", "10"))
FBD_SLOW_RUN = {"after": float(os.environ.get("MUT_EVENT_FBD_SLOW_AFTER", "0.2")),
                "hold": float(os.environ.get("MUT_EVENT_FBD_SLOW_HOLD", "1.5"))}
if FBD_ON:
    OFF_BY_BADGE = {"ARCADE": _FBD, "COMP": _FBD}
    RESCUE_PLAY = _FBD
# ⛔ What to run before the badge has been read. ARCADE/dive is the safe default:
# on tier 1-2 it is correct, and on tier 3 it costs a play or two of a weaker
# offence rather than burning time on every game of every tier.
OFF_DEFAULT_BADGE = os.environ.get("MUT_EVENT_DEFAULT_BADGE", "ARCADE")

# ⭐ THE RESCUE RULE (Montrell, Sep 13). On ARCADE we run the fast dive - but if
# a tier 1-2 game is actually CLOSE we would rather spend the minutes than risk
# the run. So: in the SECOND HALF, if our lead is under RESCUE_LEAD, switch to
# the pass until we are comfortably ahead again. Re-evaluated every play, so it
# switches back the moment the lead is safe.
#
# ⛔ SECOND HALF ONLY, on purpose. Every game starts 0-0, and a first-quarter
# "we are not ahead by 7" would run the slow offence in every single game and
# throw away the entire reason for using the dive.
#
# ⛔ Requires a CONFIRMED opponent score. The scoreboard is the least reliable
# thing we read (see hud.py), and acting on a phantom deficit costs time on
# every ARCADE game. If we cannot read it, stay on the dive - tiers 1-2 have
# been won comfortably every time.
# ⭐ BACK ON (Sep 13) now the dive-only experiment is finished. Tiers 1-2 run
# the fast dive, and this switches them to the pass if a game gets close.
RESCUE_PASS = os.environ.get("MUT_EVENT_RESCUE", "1") == "1"
RESCUE_LEAD = int(os.environ.get("MUT_EVENT_RESCUE_LEAD", "7"))
RESCUE_FROM_QUARTER = int(os.environ.get("MUT_EVENT_RESCUE_FROM_Q", "3"))

# ⭐⭐ SECOND-HALF PASS WHEN NOT WINNING (Sep 25, Montrell: "at the start of
# the third quarter if we're not winning ... switch to that play and then we
# can switch back to the run when we're winning in the second half. First half
# can remain on the run play always.")
# The pass is Clock's Ticking's _TX profile UNCHANGED: square, selected by
# the macro (hold square, D-pad DOWN once, release) on the defence macro's
# proven timings, snap, throw to X at 1.25s held 0.3s.
# Rides the existing RESCUE rule: Q3+, opponent score CONFIRMED, lead < 1
# (tied or behind) -> the pass; lead >= 1 -> back to the dive. Re-checked every
# play. An unconfirmed opponent score stays on the run.
# ⚠️ The pass can throw incompletions, and an incompletion hands the CPU a
# point in this event - that is the trade Montrell chose for a losing 2nd half.
# ⛔ TO REVERT: MUT_EVENT_2H_PASS=0 puts the rescue back on the dive (a no-op).
# ⛔ OFF (Sep 25, 13:35, Montrell watching its first live use in a Q3 down 4:
# "the texas smash isnt working we need to go back to fb dive").
SECOND_HALF_PASS = os.environ.get("MUT_EVENT_2H_PASS", "0") == "1"
if SECOND_HALF_PASS:
    RESCUE_PASS = True
    RESCUE_PLAY = _TX
    RESCUE_LEAD = int(os.environ.get("MUT_EVENT_RESCUE_LEAD", "1"))

OFF_THROW = os.environ.get("MUT_EVENT_THROW", "1") == "1"
OFF_THROW_BUTTON = os.environ.get("MUT_EVENT_THROW_BUTTON", "moon")
# ⭐ TIME FROM THE SNAP TO THE THROW. Montrell, Sep 13: the throw sometimes never
# registers and the QB takes a sack, and his read is that 2.0s lands slightly
# BEFORE the ball can actually be thrown - the input is ignored rather than
# dropped. Supported by the data: 3.0s is the only long wait we ever tried and it
# worked; every failure has been at 2.0s.
#
# ⭐ HISTORY OF THIS VALUE (all Sep 13):
#   2.0s  throws sometimes never registered - QB held the ball and got sacked
#   2.5s  reliable, but the receiver was not always led well
#   3.0s  tried briefly, reverted while the stick lead was added instead
#   3.0s  with the stick lead
#   3.5s  tried, reverted - too long
#   3.0s  NOW, with the stick lead and R1 SIMULTANEOUS (pre/post = 0)
#
# ⛔ Only ONE of these moved at a time except this deliberate experiment. If the
# throw regresses, go back to 2.5s before touching the stick.
#
# ⛔ Scheduled off the real snap instant, never off cumulative sleeps - see
# actions.chew_and_hike.
# ⭐ TUNED ON A LIVE CONSOLE IN PRACTICE MODE (Sep 14, Montrell watching).
# 1.6s does not throw AT ALL - the QB is not through his drop and the
# input is discarded, so the floor here is a cliff, not a gradient.
# 2.1s was chosen by eye against what the console actually did; the
# realised delay runs ~0.1s later than the setting (daemon + Remote Play
# round-trip, measured at every target), and that bias is INSIDE what he
# approved - do not "correct" it away.
# ⛔ 0.75 -> 0.45 (Sep 15). In a GAME the RPO is handing the ball off before our
# throw lands - Montrell watched it repeatedly. The read is decided early, and
# our pipeline adds ~0.09s on top of whatever we ask for, so 0.75 requested is
# ~0.84 delivered - past the handoff.
# ⛔ Practice mode tuned fine at 0.75, which is misleading: practice snaps with
# a 60ms press and no live defence, so the handoff timing is not the same.
# ⭐ 0.75s after the hike - the value tuned in practice on this exact play.
OFF_THROW_AFTER = float(os.environ.get("MUT_EVENT_THROW_AFTER", "0.65"))   # ⭐ 0.65 (Sep 18): realised 0.75-0.85 was handing off every few plays
# ⛔⛔ THERE IS A WINDOW, AND BOTH EDGES BITE. Measured live, Sep 13:
#
#     2.0s   throws, but TAKES CONTROL - the receiver catches it and stands
#            still, and the CPU running after the catch is the whole point
#     1.0s   mostly right, still took control occasionally
#     0.5s   sometimes DOES NOT THROW AT ALL - but that was measured at a 2.0s
#            WAIT, i.e. before the throw window had opened. The two were
#            CONFOUNDED: the input was being ignored for being early, not for
#            being brief. Retried at a 2.5s wait.
#
# ⭐ The mechanism that explains both: the takeover happens when the button is
# still held AS THE BALL ARRIVES, not when it is thrown. Ball flight is ~1s, so
# a hold released well before the catch is safe. Too short, and the keypress is
# simply lost across the stream - "pressed" means SENT, not received.
#
# So the safe value is bounded BELOW by "long enough to register" and ABOVE by
# "released before the catch". 0.75s splits them. If it drifts, move it INSIDE
# those bounds - do not go back outside them in either direction.
# ⭐⭐ THE RECEIVER MOVES WHEN THE PLAY IS FLIPPED. (Sep 15, Montrell.)
# On RPO READ SCREEN the outside receiver is on CIRCLE going right and SQUARE
# going left - so a flipped down throwing to circle picks nobody and the RPO
# hands off instead. Montrell spotted the pattern from the field: throw on play
# 1, handoff on play 2 (flipped), throw on play 3.
#
# Set this to the button the receiver occupies on a FLIPPED down. Empty = use
# the normal button regardless of flip (today's behaviour).
# ⛔ This is the THROW button during a live play - unrelated to the play-SELECT
# button on the playcall screen, which is also "box". Different screens.
# ⭐ ENABLED Sep 15. Montrell identified it from the field: "when the play is
# going to the left the receiver on the outside is square not circle". Flipped
# downs were throwing to a receiver who was not there, so the RPO handed off -
# which is exactly the throw/handoff/throw alternation he watched.
OFF_THROW_BUTTON_FLIPPED = os.environ.get("MUT_EVENT_THROW_BUTTON_FLIPPED", "box")

OFF_THROW_HOLD = float(os.environ.get("MUT_EVENT_THROW_HOLD", "0.55"))

# ⭐ LEAD THE RECEIVER: hold the LEFT STICK UP while throwing (Montrell, Sep 13).
# Pressed and released together with R1, same timing.
#
# ⛔ Sent as ONE /combo call - stick down, R1 tapped inside it, stick up - so
# the two cannot be separated by an HTTP round trip. Jitter between them would
# land inside the window the game is timing, which is the same reason the
# archive's stick-run had to be scheduled off the real snap instant.
#
# ⛔ The daemon's combo releases the held key in a `finally`. A stick left down
# wedges the game completely, so that guarantee is not optional.
# Set MUT_EVENT_THROW_STICK= (empty) to throw without leading.
# ⭐ CONFIRMED GOOD AND NOW THE DEFAULT EVERYWHERE (Montrell, Sep 13) - tier 3
# AND every rescue. There is only ONE throw implementation, in the shared snap
# path, so the rescue cannot drift out of sync with it.
# ⭐ STICK UP DURING THE THROW TOO (Montrell, Sep 13 - he wants both). It leads
# the pass, and then OFF_RUN_* below keeps it held with SPRINT to drive the
# receiver after the catch. In effect the stick is up continuously from the
# throw through the run.
OFF_THROW_STICK = os.environ.get("MUT_EVENT_THROW_STICK", "") or None

# ---------------------------------------------------------------------------
# ⭐⭐ RUN AFTER THE CATCH  (from a working setup Montrell was shown, Sep 13)
# ---------------------------------------------------------------------------
# Their full macro, translated from Xbox (A=cross, RB=r1, RT=r2):
#
#     wait 5100ms · X 200ms · wait 2100ms · R1 180ms · wait 100ms
#     · HOLD [left stick UP + R2] for 3000ms
#
# ⭐ THE PART WE HAD BACKWARDS: the stick goes AFTER the throw, together with
# SPRINT, to DRIVE THE RECEIVER UPFIELD once he has the ball. We were putting
# the stick *during* the throw to lead the pass, and then deliberately pressing
# nothing afterwards so the CPU would run.
#
# ⭐ It also explains the failure Montrell saw earlier: with a long R1 hold the
# receiver "caught it and just stood there". We WERE taking control of him - we
# simply were not giving him anywhere to go. Take control AND run.
#
# ⛔ This reverses the "press nothing after the throw" rule, and that rule was
# right for the old design. Do not reinstate it while OFF_RUN_HOLD is set.
# ⛔⛔ THE RUN HOLD MUST NEVER OUTLIVE THE PLAY. (Sep 14, Montrell.)
# A single 3s hold is posted as ONE /combo, and the daemon serialises - it
# cannot capture while it is pressing - so nothing could notice the play had
# ended. On an incompletion the play is over in ~1.5s and the REMAINDER of the
# hold landed on the next screen: scrolling the FAVORITES grid on the playcall
# screen (nearly calling the wrong play) and scrolling the PAUSE MENU.
# Montrell: "There should be no scenario where we're giving stick input outside
# of a live play."
#
# So the hold is broken into chunks with a screen check between them. It costs
# ~0.4s per check and makes the run slightly choppy; that is the right trade
# against pressing the stick into a menu.
# ⭐ THE DIVE SPRINTS ON COMP (Sep 14, Montrell): same stick-up + sprint as the
# pass, same 3s. Measured from the SNAP, not from a throw - there is no throw,
# and the handoff needs a moment before taking control of the back.
OFF_DIVE_RUN_AFTER = float(os.environ.get("MUT_EVENT_DIVE_RUN_AFTER", "0.5"))
DIVE_RUN_TIERS = {int(t) for t in
                  os.environ.get("MUT_EVENT_DIVE_RUN_TIERS", "1 2 3 4").split()}

# Minimum seconds between two stick+sprint holds. A legitimate repeat needs a
# whole playcall and snap in between, which cannot happen this fast - so a
# shorter gap means something asked twice for the same play.
RUN_COOLDOWN = float(os.environ.get("MUT_EVENT_RUN_COOLDOWN", "6.0"))

# ⛔ 0.5s, not 1.0 (Sep 18). With 1.0s chunks a play that ended early left up
# to a second of stick-UP on the playcall grid, which SCROLLED THE FAVOURITES
# ROWS - and cross then selected whatever play had landed in its slot. Montrell
# caught it from the couch. Halving the chunk halves the worst-case leak; the
# row check below (PLAY_ROW) is the part that actually guarantees the play.
OFF_RUN_CHUNK = float(os.environ.get("MUT_EVENT_RUN_CHUNK", "0.5"))

# ⭐⭐ VERIFY THE VISIBLE FAVOURITES ROW BEFORE PRESSING THE PLAY BUTTON.
# (Sep 18, Montrell: "figure out a way to make sure that we're not calling the
# wrong play before we select it".) The play buttons map to the ROW that is
# showing; 12 favourites = 4 rows, and any stray stick input scrolls them. This
# crop covers the three play-name cards under the grid. If our play's name is
# not on the row, scroll and re-check; if the names are unreadable, press
# anyway (a delay of game is worse than an unverified press).
PLAY_ROW = (70, 835, 1790, 70)          # the three play-name cards, points
# ⭐ The play-CARD band, for the daemon's /hold_watch: >= 0.92 dark on the
# playcall page and the pause menu, <= 0.39 on every live-play frame measured
# (Sep 18, 12 frames). The run hold is released the moment it goes dark.
PLAY_BAND = (80, 570, 1760, 250)
PLAY_BAND_DARK = float(os.environ.get("MUT_EVENT_PLAY_BAND_DARK", "0.70"))
# ⭐ The L1 badge on the playcall tab strip: lit ONLY on the playcall page
# (0.45 bright there; 0.0 on live play and the pause menu). The hold releases
# only when the band is dark AND this is lit - the band alone went dark during
# passes (Sep 18) and cut 9 of 24 in-game holds short.
PLAY_L1_BADGE = (72, 522, 44, 30)
PLAY_L1_BRIGHT = float(os.environ.get("MUT_EVENT_PLAY_L1_BRIGHT", "0.25"))
# Seconds between R2 re-presses inside the run hold (0 = hold only).
OFF_RUN_REPRESS = float(os.environ.get("MUT_EVENT_RUN_REPRESS", "0"))   # 0 = continuous hold (Montrell verified a pre-catch R2 hold sprints on his pad)
PLAY_ROW_CHECK = os.environ.get("MUT_EVENT_PLAY_ROW_CHECK", "1") == "1"
PLAY_ROW_SCROLL_TRIES = int(os.environ.get("MUT_EVENT_PLAY_ROW_TRIES", "4"))

# ⭐⭐ BACK ON (Sep 18, Montrell). The RPO is "so close to being the perfect
# set up" - it just does not convert the short ones. Same play, same timing,
# then stick UP + SPRINT for 3s to drive the receiver. Defence unchanged.
#   OFF_RUN_AFTER  seconds from the THROW press to the start of the hold. The
#                  ball arrives ~1s after the throw; the reference macro used
#                  0.1s. 3s would start AFTER most catches are already tackled.
#                  Montrell: "we can play with that timing" - this is the knob.
#   OFF_RUN_HOLD   0 = off. 3.0 = the reference macro.
OFF_RUN_AFTER = float(os.environ.get("MUT_EVENT_RUN_AFTER", "1.5"))   # ⭐ 1.5 (Sep 18, Montrell: R2 can be held before the catch; start at 1.5s)
# The hold must start within this many seconds of the THROW PRESS or it is
# refused outright. RUN_AFTER plus the screen gates (~1s) must fit inside it.
RUN_MAX_AGE = float(os.environ.get("MUT_EVENT_RUN_MAX_AGE", "3.0"))
OFF_RUN_HOLD = float(os.environ.get("MUT_EVENT_RUN_HOLD", "3.0"))
OFF_RUN_STICK = os.environ.get("MUT_EVENT_RUN_STICK", "lstick_up") or None
OFF_RUN_SPRINT = os.environ.get("MUT_EVENT_RUN_SPRINT", "r2") or None
# ⭐ COVER 2 MAN (Sep 16) - trying it in place of MID BLITZ on every tier.
# ⛔ TRIANGLE here is the DEFENSIVE favourites slot. Unrelated to FG_BUTTON,
# which is triangle on the OFFENSIVE favourites - different screens, no clash.
# ⛔ TO REVERT: box / "MID BLITZ", and set MUT_EVENT_DEF_MACRO=0.
# ⛔⛔ THE KEY MAP CALLS TRIANGLE "pyramid". (Sep 16 - this cost hours.)
# padd.py: {"cross","moon","pyramid","box",...}. There is NO "triangle" key, so
# a play mapped to "triangle" was rejected by the daemon with 400 and NOTHING
# WAS PRESSED - the farm navigated to FAVORITES and sat there until Madden
# picked a play for us. It looked exactly like a macro-timing problem, and I
# spent several restarts tuning timings that were never the issue.
DEF_PLAY_BUTTON = os.environ.get("MUT_EVENT_DEF_BUTTON", "box")      # ⭐ Sep 19: MID BLITZ on square, plain press
DEF_PLAY_NAME = os.environ.get("MUT_EVENT_DEF_NAME", "MID BLITZ")
# Which tab each side's play lives on. Both are FAVORITES today; kept named so a
# play move is a one-line change here rather than a hunt through the loop.
OFF_TAB = os.environ.get("MUT_EVENT_OFF_TAB", "FAVORITES")
DEF_TAB = os.environ.get("MUT_EVENT_DEF_TAB", "FAVORITES")

# ---------------------------------------------------------------------------
# FLIP PLAY  (Montrell, Sep 13 2026 — reinstated)
# ---------------------------------------------------------------------------
# Alternate which side the play runs to, so the defence cannot key one side.
#
# ⭐ ALWAYS ON FOR OFFENCE, WHATEVER THE PLAY (Montrell, Sep 13). It was briefly
# removed on the reasoning that a fullback dive has no wide side - true, but the
# press costs ~0.4s per snap and the simplicity of one unconditional rule is
# worth more than that. ⛔ So do NOT switch this off when flipping back to the
# dive: flipping the dive is fine, and a rule with no exceptions is a rule that
# cannot be mis-applied.
#
# ⛔⛔ PRESS IT ON EVERY OTHER OFFENSIVE PLAY, NOT EVERY PLAY. The flip does NOT
# persist: each play resets to the default side, so pressing R2 every time just
# runs the flipped side every time. Alternating requires ALTERNATING presses.
#
# ⛔ A BARE R2 is FLIP PLAY. R2 held together with a face button is PLAYCALL
# SUBSTITUTIONS, so a lone press is unambiguous - but it must be lone, and it
# must land BEFORE the play-select button.
# ⛔⛔ OFF WHILE THE THROW IS BEING DIAGNOSED (Sep 13). The flip was switched on
# at the same time the throw hold was being tuned - two changes at once - and
# throws started failing intermittently (QB holds the ball, takes a sack).
#
# ⭐ BACK ON (Sep 13) once the throw timing was isolated.
# ⛔ MY REASON FOR SUSPECTING IT WAS WRONG. I guessed that flipping reassigns the
# receiver icons. It does NOT — Montrell, Sep 13: "it's always R1. Flipping just
# swaps the side of the play, but the play itself runs the same."
#
# So the flip is NOT the cause of the missed throws and is safe to re-enable.
# It is off only to keep ONE variable moving while the snap-to-throw window is
# being tuned. Turn it back on once the throw is reliable.
# Below this play clock, do not spend time flipping - just snap.
FLIP_MIN_CLOCK = int(os.environ.get("MUT_EVENT_FLIP_MIN_CLOCK", "9"))

# ⭐ FLIP ON. Montrell asked for this originally and wants it kept - flipping
# every other play varies the look against the CPU. I turned it off on Sep 15
# as "simplification" without asking; that was my call to make and it was not.
# (It is an extra R2 press on a screen where R2 is bound to FLIP PLAY, so if a
# flip ever misfires this is the first thing to look at - but it stays ON.)
FLIP_PLAY = os.environ.get("MUT_EVENT_FLIP", "1") == "1"

# ---------------------------------------------------------------------------
# CLOCK - the strategy for this event
# ---------------------------------------------------------------------------
# TWO separate mechanisms, both wanted (Montrell, Sep 12):
#
#   1. CHEW CLOCK TEMPO - a coach adjustment (R3 -> TEMPO). Re-armed at the
#      start of Q1 and again at Q3, because halftime resets it.
#   2. CHEWING THE PLAY CLOCK - waiting until the play clock reaches HIKE_AT
#      before snapping.
#
# ⭐⭐ WHY (2) IS ON HERE WHEN IT FAILED ON AIR RAID. The archive records it
# plainly: `no chew 13.8 min/38.3 plays · chew 22.5 min/49.0 plays`. It engaged
# on only 170 of 369 snaps because "the game clock is stopped ~half the time".
# That is the whole explanation, and it was a property of the PLAY, not of the
# idea: Air Raid ran a JET SWEEP, which ends out of bounds and stops the clock.
# A FULLBACK DIVE ends in bounds and the clock keeps running. The term that
# made chewing useless is gone.
#
# ⛔ That reasoning is a PREDICTION, not a measurement. It is the ONE deliberate
# change from a straight port, and it is the first thing to A/B once a clean
# baseline exists. Set MUT_EVENT_HIKE_AT=99 to snap immediately and measure the
# other side.
#
# ⛔ NEVER BELOW 8. Measured at 4 on the old build: clock reads cost real time,
# so the snap landed AFTER the play clock expired -> delay of game -> the clock
# STOPS and the down gets longer. Nine straight plays ended "2ND & 67" with the
# game clock frozen. Penalties ADD plays, the exact opposite of the point.
# ⛔⛔ RAISED 8 -> 14 (Sep 14, repeated DELAY OF GAME).
# Chewing waits for the play clock to fall to this before snapping, to burn game
# clock. At :8 there is no margin left for the pipeline between READING the
# clock and the snap LANDING: an OCR pass, a focus call, the press itself, and
# Remote Play's own latency. A clock we read as :8 can already be :5 on the
# console - and with the stream stalling (11 freezes today) a frame can be
# seconds old, which takes it to zero.
#
# A delay of game is strictly worse than burning less clock: it STOPS the clock
# (the opposite of the point), costs 5 yards, and Montrell has had to take over
# and win those yards back by hand. Burn less, snap safely.
# Furthest out (seconds of play clock) we will schedule a snap from a single
# reading. Beyond this, close the gap and take a fresh look - a stale frame that
# far out would put the snap badly wrong.
SNAP_SCHEDULE_MAX = float(os.environ.get("MUT_EVENT_SNAP_SCHED_MAX", "12"))

# ⛔⛔ CHEWING IS OFF WHILE WE STABILISE (Sep 15). 99 = never wait.
# Watched live: play selected at 2.8s, then ELEVEN SECONDS standing at the line
# before the snap, because chewing waits for the play clock to fall to HIKE_AT.
# That is where the delay-of-games come from and why it looks like the ball is
# never being hiked. Clock burning is an optimisation; snapping reliably is the
# requirement. Put this back to 14 once the offence is trusted.
# ⛔⛔ NEVER WAIT BEFORE HIKING. 99 = no chewing, ever. (Sep 15, Montrell:
# "2 o'clock is just the setting we need to turn on, but we don't need to do any
# waiting before hiking the ball ever.")
# The CHEW CLOCK tempo adjustment is still SET at Q1/Q3 - that is the setting he
# wants. What is gone is standing at the line watching the play clock fall,
# which was costing ~11s a down and causing the delay-of-games.
# ⭐ CHEW THE PLAY CLOCK DOWN TO THIS BEFORE SNAPPING - but only while the GAME
# clock is actually running. (Sep 15, Montrell: "add the two clock back in, but
# I just don't want it waiting to snap the ball when the clock's not running.")
#
# ⛔ The stopped-clock test above is what enforces that: two game-clock reads
# 1.2s apart, and if it has not moved there is nothing to burn, so it snaps at
# once. Waiting on a stopped clock burns REAL time and gains nothing.
#
# ⛔ The snap is SCHEDULED from one reading, not polled toward - polling read the
# clock, slept, read again, and the clock fell 2-3s between looks, landing the
# snap at :7 instead of :14. See actions.chew_and_hike.
# Arrive with this much play clock or less and we stop trying to chew: the
# second clock read and the chew loop cost ~3s of margin and gain nothing,
# because at this point we are already burning the whole play clock anyway.
# ⛔⛔ 22 -> 8, 14 -> 6 (Sep 25, measured). With 22, EVERY snap of the day -
# 1,437 of 1,437 - took this skip: arrivals average :19, so the loop waited
# the floor and snapped at ~:13, leaving ~13s of RUNNING game clock unburned
# per snap. The comment above was wrong: at :20 we were NOT "already burning
# the whole play clock". ~4.8 min of game clock handed back per game = ~11
# extra plays = 18.5 min games while other players run 13-14 min with the same
# plays. Now the chew engages and the scheduled snap lands ~:3-:6.
# ⛔⛔ REVERTED THE SAME DAY - MEASURED WORSE. 5 games at :3 snaps averaged
# 21.1 min (26.7/18.1/20.9/18.5/21.2) vs ~18.5 before, with NO drop in play
# count (~42). The extra wait burns real time but not the expected game clock
# (accelerated clock). The arithmetic above was a prediction; this is the
# measurement. Back to 22/14.
# ⛔ TO REVERT: MUT_EVENT_CHEW_SKIP_BELOW=22 MUT_EVENT_HIKE_AT=14.
CHEW_SKIP_BELOW = int(os.environ.get("MUT_EVENT_CHEW_SKIP_BELOW", "22"))

HIKE_AT = int(os.environ.get("MUT_EVENT_HIKE_AT", "14"))

# ⭐⭐ DO NOT BURN CLOCK WHILE WE ARE NOT WINNING ON COMP (Montrell, Sep 13).
# On tier 3 the problem is SCORING, and both clock-burning mechanisms - the
# CHEW CLOCK tempo and waiting out the play clock - cost us the plays we need
# to score with. Burning clock only makes sense once there is a lead to protect.
#
# So on COMP tiers: no tempo, no play-clock chew, until we are confirmed ahead.
# The moment we lead, both switch on to protect it.
#
# ⛔ BOTH are gated together on purpose. Turning off the tempo while still
# waiting out the play clock would burn most of the same time for none of the
# benefit.
# ⭐ HOW BIG A LEAD BEFORE WE START BURNING CLOCK. (Sep 13, Montrell.)
# A one-point lead is not a lead worth protecting in a 3-minute quarter - one
# score flips it and we have spent the clock we needed to answer. Burning starts
# at a TWO-SCORE cushion and STOPS the moment the margin drops back under it.
# ⛔⛔ DO NOT WALK INTO THE TEMPO MENU DURING A GAME. (Sep 15.)
# set_chew_clock presses R3, steps through COACH ADJUSTMENTS, then backs out.
# Watched live: the loop was in "COACH ADJUSTMENTS | TEMPO ADJUSTMENT", and
# moments later a play was sitting SELECTED at the line that the loop had not
# called - so nothing snapped it, and only the pre-snap rescue saved the down.
# A menu excursion on the playcall screen can select a play, and that desyncs
# the whole loop.
#
# ⭐ We are not chewing anyway (HIKE_AT=99). And the CHEW CLOCK tempo can be set
# ONCE in the MUT gameplan settings, outside the game, where it persists - which
# is strictly better than re-entering a menu every half.
# ⭐⭐ ON, AND IT MUST STAY ON. (Sep 24, Montrell: "in this event we want to be
# chewing clock the ENTIRE GAME, no matter what, and that means turning it on
# in the first quarter and then in the third quarter".)
#
# This is the R3 -> COACH ADJUSTMENTS excursion that sets Madden's own tempo to
# CHEW CLOCK. Halftime resets the tempo unconditionally, which is exactly why
# it has to be armed TWICE: once in Q1 and again in Q3.
#
# ⛔ I DISABLED THIS IN THE SEP 24 AUDIT AND I WAS WRONG. The reasoning was
# that the menu walk could leave a play selected unsnapped (a real Sep 15
# incident) and that it matched Montrell's "calling coach suggestions and not
# hiking in time". But the measurement had ALREADY ruled it out: the run with
# that symptom logged ZERO `chew clock SET` lines - the cause was the play
# being on CIRCLE, colliding with the loop's back-out key. Do not disable a
# feature on a hypothesis the data has already contradicted.
#
# ⚠️ The Sep 15 hazard is still real, so watch for a play sitting selected at
# the line right after a `chew clock SET`. The pre-snap rescue covers it.
CHEW_SET_TEMPO = os.environ.get("MUT_EVENT_SET_TEMPO", "1") == "1"

CHEW_AHEAD_BY = int(os.environ.get("MUT_EVENT_CHEW_AHEAD_BY", "7"))

# ⭐⭐ EMPTY = CHEW ALWAYS, AHEAD OR BEHIND. (Sep 24, Montrell, explicit:
# "the ENTIRE GAME, no matter what".)
#
# ⛔ MY EARLIER REASONING IS OVERRULED, DELIBERATELY. I had gated this on
# leading, on the grounds that burning clock while 10 points down throws away
# the possessions needed to come back. Montrell knows this event and has said
# twice that it chews regardless - so it chews regardless. Recorded here only
# so the next session does not "helpfully" re-apply the gate.
# `burn_ok = (tier not in this set) or winning` - an EMPTY set makes burn_ok
# unconditionally true.
CHEW_ONLY_WHEN_AHEAD_TIERS = {int(t) for t in
                              os.environ.get("MUT_EVENT_CHEW_AHEAD_TIERS", "")
                              .replace(",", " ").split() if t.strip().isdigit()}

# ⭐ THE SINGLE BIGGEST UNTESTED LEVER, carried forward from the archive as the
# first thing to measure. The old build waited 6.0s before every snap on an
# unverified comment ("the game will not accept a snap sooner") - roughly
# 4 min/game. Nobody ever tested it.
#
# It matters LESS here than it did there: while chewing, the wait is dominated
# by the play clock, so this floor only binds on the plays where the game clock
# is already stopped and there is nothing to burn. Still worth finding - see
# `calibrate.py snapfloor`.
# ⭐ How long the SNAP button is held. The macro Montrell shared presses A for
# 200ms, not a flick - matched here rather than left at the old 60ms.
# ⛔ HOW LONG A PLAY-SELECT PRESS IS HELD. Was 60ms - right at the edge of what
# registers over Remote Play, which is why play selection was "inconsistent as
# hell": a dropped select left us on the playcall screen, and the snap press
# that followed selected whatever sits on CROSS instead of snapping.
# The macro Montrell shared uses 200ms presses; match that.
# ⭐⭐ THE PLAY WE RUN LIVES ON CROSS - DELIBERATELY. (Sep 15.)
# `cross` is the SNAP button, so any play sitting on cross can be selected by a
# snap press that arrives while the playcall screen is still up. That collision
# caused phantom play calls all day: a lost select, then our snap press picking
# whatever was on cross - QB POWER - and running it instead.
#
# ⛔ The slot cannot be left empty; something always occupies X. So Montrell put
# the play we ACTUALLY RUN there. Now the collision is harmless: a stray cross
# selects the RPO, which is what we were trying to call anyway. Worst case we
# lose a beat and the pre-snap rescue snaps it.
#
# ⛔ DO NOT "tidy" the offence onto another button without moving the favourite
# too. The whole point is that the snap button and the primary play are the same
# button.
OFF_SELECT_HOLD = float(os.environ.get("MUT_EVENT_SELECT_HOLD", "0.20"))

OFF_SNAP_HOLD = float(os.environ.get("MUT_EVENT_SNAP_HOLD", "0.20"))

# ⛔⛔ CUT 6.0 -> 3.0 FOR QB POWER (Sep 15, repeated DELAY OF GAME).
# This floor exists so a PASS play has time to register before the throw window
# opens - miss that and the ball never comes out. QB POWER has NO throw window:
# it snaps and we drive the runner. So the six seconds bought nothing and were
# spent out of a play clock that is often already low on arrival (measured:
# "snapped at play clock :11 (already low on arrival)").
#
# ⛔ If a PASS play is ever made primary again, put this back up - the floor is
# about the throw, not the snap.
# ⛔⛔ SIX SECONDS. THIS IS THE KNOWN-WORKING VALUE - DO NOT "OPTIMISE" IT.
# (Sep 15, Montrell: "set that back to the working method we had before which
# was like six seconds after the play call".) I cut it to 3.0 to buy margin on
# delay-of-games; the result was worse - the snap press lands before the game
# will accept it, gets swallowed, and the play then sits at the pre-snap with
# nobody hiking it. A swallowed snap costs the WHOLE DOWN. Waiting costs three
# seconds.
MIN_SNAP_WAIT = float(os.environ.get("MUT_EVENT_SNAP_WAIT", "6.0"))

# Hard ceiling on the pre-snap wait. Never risk a silent stall on a clock we
# cannot read: snap and take the down.
SNAP_DEADLINE = 42.0

# ---------------------------------------------------------------------------
# FIELD GOALS — WORKED OUT AND VERIFIED, BUT NOT WIRED IN YET
# ---------------------------------------------------------------------------
# ⭐ Montrell, Sep 13 2026. Kept as a LAST RESORT: he is first trying to fix the
# scoring problem with personnel (a better fullback for the dive) rather than by
# adding a kicking game. Nothing below is called by the loop.
#
# WHY IT MATTERS: on tier 3 (COMP) the dive offence cannot score, while the mid
# blitz shuts opponents out - so games end 0-0 and go to overtime. We do not need
# touchdowns to win those, we need THREE POINTS.
#
# ⭐⭐ THE KEY INSIGHT IS MONTRELL'S: DO NOT PRESS FOR POWER AT ALL.
# The meter is an L - a horizontal base curving up into a vertical bar, with an
# X marker at the top next to "100". The normal sequence is three presses:
# snap, then power near the top, then accuracy on the way back down.
#
# But if you never make the POWER press, the meter maxes out on its own and
# starts coming back down automatically. That collapses TWO timing windows into
# ONE, and one window is something we can hit reliably.
#
#       press X (snap)  ->  wait FG_PRESS_AFTER  ->  press X (accuracy)
#
# ⭐ 3.5s is MEASURED, not guessed. Swept 1.5/1.8/2.0/2.3 as three-press pairs
# (all bad), then single-press at 5.0/4.5/5.5 ("way off", far too late), then
# 3.5/3.0/2.5. **3.5s works really well.**
# ⭐⭐ KICK ONLY FROM INSIDE THIS DISTANCE. The special-teams screen prints the
# attempt in yards - "FIELD GOAL - 71 YDS" - which is FAR better evidence than
# inferring position from the yard line and an arrow that Vision renders as ^, ~
# or drops entirely (measured Sep 15). Read the distance; do not deduce it.
#
# ⛔ 3.5s was only ever verified at 27 YARDS in practice. Anything much longer is
# unproven, and a missed FG hands them the ball at the spot - worse than a punt.
# Raise this only after watching longer kicks actually go in.
# ⭐⭐ KICK ONLY FROM INSIDE THIS YARD LINE. (Sep 15, Montrell: "the threshold
# should be read right off of the field position.")
#
# ⛔ "THEIR 8" AND "OUR 8" BOTH READ AS 8. The arrow is the only thing that
# separates them, and Vision renders it as ^, ~, v or drops it entirely
# (measured). Kicking from our own 8 would be a ~92-yard attempt and a turnover
# at the spot. So the yard line alone is NEVER enough: we also require positive
# evidence of the opponent's half - a readable up-arrow, or GOAL TO GO. With
# neither, go for it.
FG_MAX_YARDLINE = int(os.environ.get("MUT_EVENT_FG_MAX_YARDLINE", "10"))

FG_PRESS_AFTER = float(os.environ.get("MUT_EVENT_FG_PRESS_AFTER", "3.5"))

# ⛔ WHAT IS STILL UNKNOWN - do not assume these before testing:
#   * Only verified at 27 YARDS in PRACTICE. Longer kicks may need a different
#     delay, and may need the power press after all.
#   * Only verified under the practice game style. The event forces ARCADE on
#     tiers 1-2 and COMP on 3-4, and COMP is exactly where kicking is hardest.
#   * Aiming is LEFT STICK. At short range Montrell says you cannot really miss,
#     so aim is ignored - that will not hold from distance.
#
# ⛔ HOW THE PRESSES MUST BE SENT (this part is not optional):
#   * Focus chiaki ONCE up front, then post every press with focus=False.
#     pad.press() re-focuses each time and costs ~0.5s - which is an eternity
#     inside a 3.5s window.
#   * The daemon SERIALISES requests behind a lock, so you CANNOT capture the
#     screen while a press sequence is running. Timing here is open-loop: send
#     the presses, then look at the result. Do not try to watch the meter.
#
# ---------------------------------------------------------------------------
# Q4 BAIL-OUT (Montrell, Sep 12: "just one this time")
# ---------------------------------------------------------------------------
# If we are LOSING at the start of the 4th quarter, PAUSE and ask. One check per
# game, every tier, 30 minutes. No answer -> un-pause and play it out.
#
# ⛔ It must NEVER block the cycle indefinitely. Losing one game is far cheaper
# than idling the farm for hours - the old build burned ~2h of idle across four
# pauses in one night with two waits stacked.
#
# ⛔ Un-pause with CIRCLE (back), never CROSS. The pause menu remembers its last
# position and QUIT GAME is on it.
# How many independent score reads to take before pausing. A pause costs up
# to 30 minutes and pulls Montrell away, so it must not ride on one frame.
BAILOUT_CONFIRM_READS = int(os.environ.get("MUT_EVENT_CONFIRM_READS", "5"))
# How long an "we are AHEAD" bail-out verdict stands before we spend five more
# captures re-confirming it. Cleared immediately if either score changes.
BAILOUT_RECHECK_SECS = int(os.environ.get("MUT_EVENT_BAILOUT_RECHECK", "90"))
# ⛔⛔ OFF FOR THIS EVENT (Montrell, Sep 24: "so no need to pause games etc
# yet"). Every game starts 10-0 down, so every pause alarm keys on a condition
# that is TRUE BY DESIGN at kickoff. Leaving them armed would pause and - with
# the auto-resume off - halt the farm in nearly every game.
# ⭐ The protection that remains is the right one for a one-loss event: play
# the game out, and let the LOSS HALT stop the farm on the progress screen
# afterwards. MUT_EVENT_INTERVENE=1 re-arms the pauses.
INTERVENE = os.environ.get("MUT_EVENT_INTERVENE", "0") == "1"
# ⛔⛔ THE PS5 SLEEPS AND THAT ENDS THE RUN. (Sep 14.)
# A pause ran long, the console went into REST MODE, the Remote Play connection
# was cut, and the event run died - not from a loss, from inactivity. Rest mode
# is driven by CONTROLLER idle time, so any input resets it. During a pause the
# loop deliberately sends nothing for up to 30 minutes, which is exactly the
# window that killed it.
#
# ⛔ The nudge must be NET ZERO on a menu: down then back up, so the highlighted
# item is unchanged. Never a face button - QUIT GAME is on the pause menu.
KEEPAWAKE_SECS = float(os.environ.get("MUT_EVENT_KEEPAWAKE", "240"))

# ⭐⭐ PAUSE IF WE FALL BEHIND BY MORE THAN THIS, AT ANY POINT IN THE GAME.
# (Sep 16, Montrell: "put in something that pauses the game if we're losing by
# more than seven points at any point in the game.")
#
# The Q4 bail-out only ever looked at the fourth quarter, by which time a
# two-score hole is usually unrecoverable in 3-minute quarters. Catching it when
# it OPENS gives him a whole game to take over instead of two minutes.
# ⛔ More than seven means 8+: a 7-point deficit is one score and recoverable.
# ⭐⭐ PAUSE IN Q3 IF WE ARE LOSING AT ALL - ANY MARGIN. (Sep 16, Montrell,
# one loss from elimination: "I want it paused in the third quarter if we are
# losing at all, and then again on our normal threshold in the fourth quarter.")
#
# ⛔ This is a SEPARATE alarm from the Q4 bail-out and must not consume it. Two
# pauses per game is the intent: one with a quarter still left to fix it, and
# the existing last-chance one in the fourth.
# ⛔ Requires a CONFIRMED opponent score - "losing" has to mean we actually read
# their number, not that we failed to. Q4 already handles the unreadable case.
PAUSE_Q3_IF_LOSING = os.environ.get("MUT_EVENT_PAUSE_Q3", "1") == "1"
# ⛔⛔ OFF FOR THIS EVENT (Sep 24). Last event, on tiers 1-2, the Q3-and-losing
# alarm switched the offence to the pass instead of pausing - correct there,
# because a tier-1 loss cost nothing. It is WRONG here, twice over:
#   1. With TIERS=1 every game reads ARCADE, so this would fire in EVERY game
#      and silently SKIP the alarm - in an event where one loss ends the run.
#   2. It switches to TEXAS SMASH, which is untested here and throws
#      incompletions, and an incompletion HANDS THE CPU A POINT under this
#      event's house rules.
# So a Q3 deficit PAUSES and calls Montrell. MUT_EVENT_Q3_PASS=1 re-enables
# the switch if a play is ever proven for it.
Q3_PASS_ON_ARCADE = os.environ.get("MUT_EVENT_Q3_PASS", "0") == "1"

# ⛔ 99 = never. A 10-point deficit is the STARTING SCORE of every game here,
# so the old 7 fired before the first snap. Only meaningful if INTERVENE=1.
PAUSE_IF_DOWN_BY = int(os.environ.get("MUT_EVENT_PAUSE_DOWN_BY", "99"))

INTERVENE_WAIT = float(os.environ.get("MUT_EVENT_INTERVENE_WAIT", "1800"))

# ⛔⛔⛔ THE AUTO-RESUME HAS COST THREE RUNS. IT IS OFF HERE.
# (Sep 19 x2 on Clock's Ticking tier 3, Sep 21 x1 on tier 2.) Every one of
# them was the same story: the loop paused correctly, nobody was awake to
# answer, the 30-minute timer expired, the loop un-paused and played on, and
# the bot lost a game it had already decided it could not win.
#
# It fires precisely when no one is watching, which is precisely when playing
# on is least defensible. In THIS event one loss throws away every win banked
# in the run, so the timeout now STOPS THE FARM with the game still paused:
# Montrell comes back to a paused game and a stopped loop, having lost
# nothing. Answer it with RESUME / INTERVENED / EXTEND as before.
#
# ⛔ To go back to the old behaviour: MUT_EVENT_AUTO_RESUME=1.
AUTO_RESUME_ON_TIMEOUT = os.environ.get("MUT_EVENT_AUTO_RESUME", "0") == "1"

# ---------------------------------------------------------------------------
# SCREEN REGIONS  (x, y, w, h) in display POINTS on the mini's 1920x1080 stream
# ---------------------------------------------------------------------------
# ⛔ UNVERIFIED FOR THIS EVENT until `calibrate.py verify` signs them off. They
# are the Air Raid values and the HUD is the same game on the same display, so
# they are good candidates - but "probably the same" is exactly the reasoning
# this project has been burned by. Look first.
TABSTRIP = (75, 515, 1160, 45)     # playcall tab strip, both sides
CLOCKS = (1180, 1005, 780, 80)     # "2nd | 1:07 | :26 | 4TH & 6 | A13"
SCORE_L = (520, 1006, 250, 76)     # opponent CODE + score
SCORE_R = (770, 1006, 270, 76)     # our score + CODE
ACTIONBAR = (380, 915, 1180, 48)   # "ADD/REMOVE FAVORITE ... BACK"
TEMPO_LABEL = (90, 585, 300, 48)   # the words "TEMPO ADJUSTMENT"
TEMPO_VALUE = (351, 580, 300, 60)  # the < NORMAL > box next to it

# ⛔ BOTH SCORE CROPS MUST INCLUDE THE TEAM ABBREVIATION. A crop holding only a
# bare digit returns EMPTY - Vision cannot recognise one isolated glyph with no
# textual context. The team code is what makes the digit readable.

# Tab layouts. The ACTIVE tab is a light box behind dark text and every other is
# light text on dark, so "which tab is active" is a brightness question, not an
# OCR one - far more robust. Centres are x-offsets RELATIVE to TABSTRIP's left
# edge.
OFF_TABS = ["COACH", "FORMATION", "CONCEPT", "PLAY TYPE", "PLAYER",
            "PERSONNEL", "FAVORITES", "RECENT"]
OFF_X = [149, 316, 436, 549, 654, 794, 949, 1056]
DEF_TABS = ["COACH", "PERSONNEL", "CONCEPT", "PLAY TYPE", "FAVORITES", "RECENT"]
DEF_X = [149, 313, 436, 548, 666, 772]
ST_TABS = ["NORMAL", "HEAVY", "PUNT"]
ST_X = [96, 189, 268]

# Which SIDE we are on is decided by how far right the strip's text extends, not
# by brightness. Scoring the layouts and taking the sharpest peak flip-flopped
# offense/defense on consecutive captures - on a punt screen the offense layout
# sampled empty grass and scored HIGHER than a real read.
EXTENT_OFFENSE = 980
EXTENT_DEFENSE = 600

# Minimum peak/median brightness ratio to ACT on a tab read. Good reads land
# 2.9-3.5; every navigation failure on the old build came from a 1.8-2.0 read,
# and one of those reported the WRONG SIDE. A marginal read is worse than none -
# waiting a second is free, acting on noise costs a play.
CONFIDENT = 2.4

# Words that only ever appear in a playcall tab strip. Brightness alone cannot
# tell a tab strip from any other bright band - the POSTGAME screen once scored
# 2.76 and the loop sat navigating a screen with no tabs at all.
TAB_WORDS = ("COACH", "SUGGESTIONS", "FORMATION", "CONCEPT", "PLAY TYPE",
             "PLAYER", "PERSONNEL", "GROUP", "FAVORITES", "RECENT",
             "NORMAL", "HEAVY", "PUNT")

# ---------------------------------------------------------------------------
# PACING AND WATCHDOGS
# ---------------------------------------------------------------------------
LOOP_SLEEP = float(os.environ.get("MUT_EVENT_LOOP_SLEEP", "1.0"))
# ⭐ (Sep 25) Poll interval while the tab band is blank (a live play - a pixel
# scan, no OCR) and right after a play. The flat 1.0s cost ~1.5s per play on
# both sides before the next playcall screen was noticed. MUT_EVENT_LOOP_SLEEP_LIVE=1.0 reverts.
LOOP_SLEEP_LIVE = float(os.environ.get("MUT_EVENT_LOOP_SLEEP_LIVE", "0.3"))
# The full-screen-OCR slow path, now on a clock rather than every 4th pass.
SLOW_PATH_EVERY = float(os.environ.get("MUT_EVENT_SLOW_PATH_EVERY", "4.0"))
# ⭐ (Sep 25) The held-button overlay check (0.8s OCR) runs after any macro
# press, and otherwise on every Nth play call instead of every one. 1 reverts.
OVERLAY_CHECK_EVERY = int(os.environ.get("MUT_EVENT_OVERLAY_CHECK_EVERY", "5"))
SCORE_EVERY = int(os.environ.get("MUT_EVENT_SCORE_EVERY", "2"))
# ⭐ Retries when the post-snap read finds the stat ticker instead of the
# score (Q3+). Each look costs ~1s of in-play dead time. See grind.py.
SCORE_TICKER_RETRIES = int(os.environ.get("MUT_EVENT_SCORE_RETRIES", "1"))   # 2 -> 1 (Sep 25): each look pushed Q4 arrivals toward a delay of game
SCORE_TICKER_GAP = float(os.environ.get("MUT_EVENT_SCORE_RETRY_GAP", "1.0"))

# The most points one play can add (TD + 2pt). Used to reject impossible score
# JUMPS - a real 14-3 once read as "0-72", and the phantom lead changed play
# calling while we were losing by 11.
# How many times a LOWER score must repeat before we conclude our own stored
# value is the wrong one. Higher than the increase threshold on purpose: a
# decrease is impossible in football, so this is only ever a statement about our
# bookkeeping being corrupt - never about the game.
# ⛔⛔ 2 FOR THIS EVENT, NOT 4 - SCORES GO DOWN HERE. (Sep 24, measured.)
# This is the only place the "a score never decreases" guard can be overruled,
# and in a STEAL-POINTS event a decrease is not a misread, it is the rules
# working: game 2 ran 10-0 -> 8-2 -> 0-21, so the CPU's score fell to zero as
# we made big plays.
#
# Measured live in game 2: the reader latched `ours=57` (a misread) and
# `theirs=8`, then rejected the TRUE readings on every play - the scoreboard
# said BAL 0 - 21 JOH while the loop believed 8-57 and reported "lead +49".
# At 4 the guard needs four identical lower reads to yield, which a real
# steal-driven drift rarely produces in a row.
#
# 2 keeps the project's own standard - never act on a single OCR read, two
# agreeing reads then act - while letting a genuine steal through in a play or
# two. ⛔ Do NOT set this to 1: one bad frame would then rewrite the score.
# ⚠️ W/L never depended on this (it comes from the record delta and the
# progress screen), so the corruption cost DATA, not the run. What it does
# feed is the chew-clock "are we ahead" test.
SCORE_CONTRADICT = int(os.environ.get("MUT_EVENT_SCORE_CONTRADICT", "2"))

# ⛔⛔ "1 IS AN IMPOSSIBLE SCORE" IS FALSE IN THIS EVENT. (Sep 24, measured.)
# In real football nothing scores a single point, so a read of 1 was rejected
# outright - correct for Clock's Ticking. But this event STEALS points ONE AT
# A TIME (forced fumble/sack, incomplete pass), so 1, 2, 3, 5 are all legal
# scores here. Seen live in game 4: the CPU's score fell 10 -> 8 -> 3, and a
# read of `theirs 1` was then thrown away as "impossible in football" - which
# would leave us holding a stale higher value for the rest of the game, the
# exact failure the SCORE_CONTRADICT fix was for.
# ⛔ 1 is still rejected in a NORMAL event - set MUT_EVENT_ALLOW_ONE=0 there.
ALLOW_SCORE_OF_ONE = os.environ.get("MUT_EVENT_ALLOW_ONE", "1") == "1"

SCORE_JUMP_MAX = 8
# ⛔ ABSOLUTE cap on a single-read jump, whatever the elapsed plays. (Sep 18)
# The per-play room above scaled with plays-since-last-read, so after ~6 quiet
# plays a SINGLE read of "ours 60" (real: 0) was accepted on sight, the loop
# believed 60-3, and the Q4 alarm stayed silent in a 3-0 game on tier 3.
# 16 = two unread touchdowns with 2-pt tries; more than that in one read is
# a misread until it repeats 3x.
SCORE_JUMP_ABS = int(os.environ.get("MUT_EVENT_SCORE_JUMP_ABS", "16"))
# Q4 with no score ever read: below this many plays it is a fresh restart
# (do not pause on our own zeros); at or above it the score is UNREADABLE and
# the Q4 alarm pauses. (Sep 18 - a whole game of "U" for 0 slipped through.)
NEVER_READ_MAX_PLAYS = int(os.environ.get("MUT_EVENT_NEVER_READ_MAX_PLAYS", "12"))

# ⛔ Nothing above this is a score. The HUD strip carries field position
# and stat numbers that can land in the score slot - a stray "735" was
# recorded as our score once.
SCORE_MAX = int(os.environ.get("MUT_EVENT_SCORE_MAX", "99"))

# Stall handling: WARN once, then ABORT. Never sit and hammer a dead screen -
# the old build alerted 89 times across 4h15m against a frozen game because it
# reset its counter after each alert instead of escalating.
# ⛔ 8 WAS FAR TOO TIGHT for this event. Chewing the play clock produces long
# sustained drives, and eight consecutive offensive plays is a GOOD drive, not a
# freeze - it cried wolf on a perfectly healthy game. The counter is now also
# reset by a moving game clock (see play_loop), which is the real signal; this
# threshold is only the backstop for when the clock cannot be read at all.
STALL_WARN = int(os.environ.get("MUT_EVENT_STALL_WARN", "16"))
STALL_ABORT = int(os.environ.get("MUT_EVENT_STALL_ABORT", "40"))

# ⛔ Well ABOVE the longest legitimate game. A 4x3:00 game is much shorter than
# Air Raid's, but keep generous headroom: an alert that fires on normal play
# trains you to ignore it, which is worse than no alert.
# ⛔ 1500s (25 min) WAS TOO TIGHT and cried wolf on a perfectly healthy game.
# Measured games run 18-25 min, and OVERTIME adds several more on top - so the
# longest legitimate game comfortably exceeded the alarm. The archive says it
# plainly: "this must sit well ABOVE the longest legitimate game, or the alert
# trains you to ignore it." 45 min clears a 25-min game plus a full OT.
GAME_STALL_SECS = int(os.environ.get("MUT_EVENT_GAME_STALL", "2700"))

# Consecutive byte-identical captures that mean the chiaki feed is FROZEN. A
# frozen stream reads as a perfectly valid screen forever - it once "punted"
# into a stale image for 18 minutes with every watchdog happy, because plays
# were being called. Frame identity is the only signal that distinguishes
# "nothing is changing" from "the screen legitimately looks the same".
# Only believe the frozen-feed signal if a playcall screen was seen this
# recently. Menus are legitimately static; a live game is not.
FROZEN_ONLY_WITHIN = float(os.environ.get("MUT_EVENT_FROZEN_WITHIN", "120"))
# ⛔⛔ CONFIRM BEFORE RESTARTING THE STREAM. (Sep 14)
# A chiaki restart costs 25-220 SECONDS - measured: one took 220s across three
# attempts and swallowed a whole defensive series. The freeze check fires on 6
# byte-identical frames, which is also what a brief network hiccup, a paused
# game and a genuinely static screen look like. Eight of these fired in one
# session and they cost more game time than any bug fixed today.
#
# So: re-focus, wait, look again. ~4s to rule out a transient, against 25-220s
# to act on one wrongly.
# Byte-identical consecutive captures after which a reading is STALE and must
# not be acted on. Lower than FROZEN_RESTART: we stop TRUSTING the picture long
# before we conclude the stream is dead and pay for a restart.
# Play clock at or below this, while OFF the playcall screen, means a play is
# selected and unhiked - snap it rather than let the clock die.
# ⛔ RAISED 12 -> 22 (Sep 15). This catches a play that got selected without us
# snapping it - the cross/QB POWER collision - but at :12 the loop SAT AT THE
# LINE for ~15 seconds first, and Montrell watched it hike with :3 left. There
# is nothing to gain by waiting: if a play is selected and the clock is running,
# the only useful action is to snap it.
PRESNAP_RESCUE_AT = int(os.environ.get("MUT_EVENT_PRESNAP_RESCUE", "22"))

STALE_FRAMES = int(os.environ.get("MUT_EVENT_STALE_FRAMES", "3"))

FROZEN_CONFIRM_SECS = float(os.environ.get("MUT_EVENT_FROZEN_CONFIRM", "4.0"))

FROZEN_RESTART = 6
FROZEN_ALERT = 14

PS5_HOST = os.environ.get("MUT_PS5_HOST", "192.168.1.50")

# ---------------------------------------------------------------------------
# PATHS
# ---------------------------------------------------------------------------
# ⭐ Deliberately NOT the Air Raid paths. Mixing 311 games of a different event
# with different rules into one history would make every per-game statistic
# meaningless.
RUN_DIR = "/tmp/mut-event"
SHOT_DIR = RUN_DIR
STUCK_DIR = f"{RUN_DIR}/stuck"
# ⛔ A NEW FILE PER EVENT. Clock's Ticking's rows stay in
# ~/.mut_event_history.jsonl and Air Raid's are archived separately; mixing
# events in one file makes every per-game average meaningless.
HISTORY = os.path.expanduser(os.environ.get(
    "MUT_EVENT_HISTORY", "~/.mut_unstoppable_history.jsonl"))
STATE_FILE = os.path.expanduser("~/.mut_event_state.json")
CALIB_FILE = os.path.expanduser("~/.mut_event_calibration.json")

ALERT_FILE = f"{RUN_DIR}/ALERT"
STICKY_ALERT = f"{RUN_DIR}/ALERT.STICKY"
HALT_FILE = f"{RUN_DIR}/HALT"   # a tier 3/4 loss; nothing restarts over this
FROZEN_FILE = f"{RUN_DIR}/FROZEN"
INTERVENE_FILE = f"{RUN_DIR}/INTERVENE"
RESUME_FILE = f"{RUN_DIR}/RESUME"          # "let it play out"
INTERVENED_FILE = f"{RUN_DIR}/INTERVENED"  # "I have the pad"
EXTEND_FILE = f"{RUN_DIR}/EXTEND"          # "give me another 30 min"

# macOS keycodes the daemon maps to stick-click buttons. '6' = R3, verified as
# COACH ADJUSTMENTS on the playcall screen.
R3_KEYCODE = 22


# ⛔⛔ EVERY CONFIGURED BUTTON MUST EXIST IN THE DAEMON'S KEY MAP.
# (Sep 16) "triangle" is not a key - it is "pyramid" - and a play mapped to it
# was silently rejected by the daemon for hours while it LOOKED like a macro
# timing problem. A typo in a button name must be loud and immediate, not a
# mystery that costs a tier-4 run.
def _validate_buttons():
    try:
        import pad
        keys = set(getattr(pad, "KEYS", {}) or {})
        if not keys:                       # pad may not expose the map
            import json as _json, os as _os
            return
    except Exception:
        return
    named = {
        "DEF_PLAY_BUTTON": DEF_PLAY_BUTTON,
        "FG_BUTTON": FG_BUTTON,
        "OFF_THROW_BUTTON": OFF_THROW_BUTTON,
        "OFF_THROW_BUTTON_FLIPPED": OFF_THROW_BUTTON_FLIPPED or None,
        "OFF_RUN_SPRINT": OFF_RUN_SPRINT,
        "OFF_RUN_STICK": OFF_RUN_STICK,
        "ARCADE play": OFF_BY_BADGE["ARCADE"]["button"],
        "COMP play": OFF_BY_BADGE["COMP"]["button"],
        "TX throw": _TX["throw_seq"]["button"],
    }
    for i, t in enumerate(_TX["select_macro"]["taps"]):
        named[f"TX select tap {i + 1}"] = t
    bad = {k: v for k, v in named.items() if v and v not in keys}
    if bad:
        raise SystemExit(
            "\n⛔ CONFIG ERROR - these buttons do not exist in the pad key map:\n"
            + "\n".join(f"    {k} = {v!r}" for k, v in bad.items())
            + f"\n\n  valid keys: {', '.join(sorted(keys))}\n"
              "  (triangle is 'pyramid', circle is 'moon', square is 'box')\n")


_validate_buttons()
