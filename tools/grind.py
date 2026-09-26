#!/usr/bin/env python3
"""The event farm loop.

    read the screen -> classify the situation -> act -> verify -> repeat

⛔ NOTHING HERE IS TIME-BASED. Play length, penalties, turnovers and possession
changes are all handled by re-deriving the situation from the screen every
iteration. That structure survived 311 games of the last event and is the one
part of it worth copying wholesale.

⛔ WHEN THE READ IS NOT CONFIDENT, WAIT. Sitting still costs a delay of game;
pressing blind costs the wrong play - and twice cost a whole run.

Event-specific knowledge lives in config.py. Reading lives in screen.py.
Pressing lives in actions.py. This file is the loop and the menus.
"""
import atexit
import functools
import json
import re
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import actions  # noqa: E402
import config as C  # noqa: E402
import hud  # noqa: E402
import pad  # noqa: E402
import screen  # noqa: E402

STOP_FILE = "/tmp/mut-event/stop"


# ⛔⛔ NO MATTER HOW WE EXIT, LIFT EVERY KEY.
# (Sep 13) The NameError crash killed the loop inside a 3s stick+sprint hold.
# The keys stayed DOWN on the console - forever, through the restart - because
# nothing on any error path lifted them. atexit fires on a normal return, an
# unhandled exception, and SIGTERM (which farm.sh sends), so this closes every
# exit path at once rather than one try/except at a time.
@atexit.register
def _release_pad_on_exit():
    try:
        pad._remote_post("/release", {}, timeout=5)
    except Exception:
        pass

os.makedirs(C.RUN_DIR, exist_ok=True)
os.makedirs(C.STUCK_DIR, exist_ok=True)

CURRENT_TIER = None
CURRENT_RECORD = None
# ⭐ The last badge we actually saw. The badge is only readable DURING a live
# play, so without this every game would open on the default (dive) for a snap
# or two - which on tier 3 is exactly the offence that cannot score.
CURRENT_BADGE = None
# ⭐ (Sep 21) The "N/2 LOSSES" count last read off the progress screen on a
# tier 3-4 run. Persisted so a restart after Montrell clears a HALT does not
# re-halt on the loss he already knows about. None = not seen yet.
LOSSES_SEEN = None

# ⭐ Set by advance_menus when it actually SEES the end-of-game menu. That menu
# IS the end of the game; everything else is inference.
SAW_FINISH_GAME = False
FINAL_SCORE = None          # (theirs, ours) read off the end-of-game banner

# ⭐⭐ THE EVENT'S OWN W-L RECORD IS THE ONLY TRUSTWORTHY RESULT.
#
# Measured across a full tier on Sep 12: the record read correctly EVERY time
# (4-0, 5-0, 6-0), while BOTH score sources produced garbage in the same game -
# the in-play bar reported our score as 34, then 24, then 6, and the end-of-game
# banner said "6-6" for a game we won by 24.
#
# That is not surprising in hindsight. The score is drawn large, stylised, over
# team logos, and shares its strip with a play clock, a down marker, a
# possession arrow and cycling stat pop-ups. The record is small, plain,
# high-contrast text on a menu with nothing moving.
#
# So: the score is still RECORDED, because it is interesting. But W/L comes from
# the record delta, and when the two disagree the record wins and the row is
# corrected.
RECORD_AT_LAST_GAME = None
# ⛔ The timestamp of the row _end_game last wrote. A correction may ONLY touch
# that row. Without this, a record change with no row behind it patches whatever
# happens to be last in the file - which on Sep 13 flipped a PREVIOUS DAY'S
# overtime WIN into a loss, because the record moved when Madden finally applied
# a forfeit from a game the loop never recorded.
LAST_ROW_TS = None


# ---------------------------------------------------------------------------
# STATE, HISTORY, ALERTS
# ---------------------------------------------------------------------------

def _save_state():
    try:
        with open(C.STATE_FILE, "w") as fh:
            json.dump({"tier": CURRENT_TIER, "record": CURRENT_RECORD,
                       "badge": CURRENT_BADGE, "losses_seen": LOSSES_SEEN}, fh)
    except OSError:
        pass


def _load_state():
    global CURRENT_TIER, CURRENT_RECORD, CURRENT_BADGE, LOSSES_SEEN
    try:
        with open(C.STATE_FILE) as fh:
            d = json.load(fh)
        CURRENT_TIER = d.get("tier")
        CURRENT_RECORD = d.get("record")
        CURRENT_BADGE = d.get("badge")
        LOSSES_SEEN = d.get("losses_seen")
    except (OSError, ValueError):
        pass


_load_state()


# ⭐⭐ THE TIER IS PRINTED IN THE CARD TITLE. "GT: CLOCK'S TICKING T3 (CPU)".
# Tier 1 has NO suffix; tiers 2+ carry T2/T3/T4.
#
# ⛔ This is better than deriving it from the record, because the RECORD GOES
# STALE: it is only re-read when the loop passes the events screen, and the
# quarter-reset boundary path skips that walk entirely. Measured Sep 13 - the
# record sat at "3-0" for three games after we had already won five.
#
# The title, by contrast, appears on the events list AND on every post-game
# progress screen, so it refreshes constantly.
_TITLE_TIER = re.compile(r"CLOCK.{0,3}S\s*TICKING\s*T(\d)", re.I)
_TITLE_ANY = re.compile(r"CLOCK.{0,3}S\s*TICKING", re.I)


def tier_from_title(txt):
    """Tier number from any screen showing the event card title, or None."""
    up = str(txt).upper()
    m = _TITLE_TIER.search(up)
    if m:
        n = int(m.group(1))
        return n if 1 <= n <= C.TIERS else None
    # The title with NO T-suffix is tier 1 - but only believe that if we can
    # actually see the title, not merely fail to find a suffix.
    return 1 if _TITLE_ANY.search(up) else None


def tier_from_record(rec):
    """Total wins -> which tier we are on. Exact, from a static menu."""
    parsed = _parse_record(rec)
    if not parsed:
        return None
    wins, _losses = parsed
    return min(C.TIERS, wins // C.WINS_PER_TIER + 1)


def badge_for_tier(tier):
    """Which offence profile a tier wants."""
    if tier is None:
        return None
    return "ARCADE" if tier in C.ARCADE_TIERS else "COMP"


def _parse_record(rec):
    try:
        w, l = rec.split("-")
        return int(w), int(l)
    except (AttributeError, ValueError):
        return None


def _patch_last_result(result, why, log=print):
    """Rewrite the result of the row THIS loop last wrote - never any other.

    ⛔ A record delta is only evidence about the game we actually recorded. If we
    have no row for it (a forfeit applied late, a boundary we missed, a restart),
    the honest move is to say so and leave the history alone.
    """
    if LAST_ROW_TS is None:
        log(f"    ! record changed ({why}) but this loop has recorded no game "
            f"- NOT touching the history")
        return
    try:
        with open(C.HISTORY) as fh:
            rows = [l for l in fh if l.strip()]
        if not rows:
            return
        last = json.loads(rows[-1])
        if last.get("ts") != LAST_ROW_TS:
            log(f"    ! record changed ({why}) but the last row is not the game "
                f"this loop recorded - NOT touching it")
            return
        if last.get("result") == result:
            return
        log(f"    ⭐ CORRECTING last game: {last.get('result')} -> {result} ({why})")
        last["result"] = result
        last["result_source"] = "event record"
        last["result_was"] = f"{last.get('theirs')}-{last.get('ours')}"
        rows[-1] = json.dumps(last) + "\n"
        with open(C.HISTORY, "w") as fh:
            fh.writelines(rows)
    except (OSError, ValueError) as e:
        log(f"    ! could not correct last result: {e}")


def _record_game(**row):
    """Append one completed game. Returns the row's timestamp."""
    """Append one completed game to the history file.

    ⛔ RESTARTS DESTROY DATA. The log is volatile and a restart truncates the
    picture; this JSONL is append-only and is the ONLY trustworthy record. Every
    statistic anyone quotes about this farm should come from here, never from a
    log file.
    """
    row.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S"))
    row.setdefault("date", time.strftime("%Y-%m-%d"))

    # ⛔⛔ NEVER RECORD A SCORE THE VALIDATORS WOULD HAVE REJECTED.
    # (Sep 14) 29 games of history were unusable for the one question Montrell
    # actually asked - "how often do we fail to score?" - because the score slot
    # had swallowed field-position junk: a recorded MAX of 735 points and a 43.9
    # average. The in-play validators reject these, but whatever survived to the
    # end of a game was written down unchecked.
    #
    # A row with a null score is honest and still countable. A row claiming 735
    # poisons every average computed from the file, forever, and this file is
    # append-only by design.
    for k in ("ours", "theirs"):
        v = row.get(k)
        if v is not None and (v == 1 or v < 0 or v > C.SCORE_MAX):
            row[k + "_rejected"] = v
            row[k] = None

    # ⭐ ALWAYS record the tier. It was present on 5 of 29 rows, which made it
    # impossible to separate COMP games from ARCADE ones - the split that
    # decides every offence question we have. It is derivable from the record,
    # so there is no excuse for a null.
    if row.get("tier") is None:
        row["tier"] = CURRENT_TIER or tier_from_record(CURRENT_RECORD)
    row.setdefault("record", CURRENT_RECORD)
    try:
        with open(C.HISTORY, "a") as fh:
            fh.write(json.dumps(row) + "\n")
    except OSError:
        pass
    return row["ts"]


def _alert(msg, log=print):
    """A visible, clearable alert a human or a watcher can poll for."""
    try:
        with open(C.ALERT_FILE, "w") as fh:
            fh.write(f"{time.strftime('%H:%M:%S')}  {msg}\n")
    except OSError:
        pass
    log(f"    !!!! ALERT: {msg}")


def _keep_awake(log=print):
    """A net-zero nudge so the PS5 does not fall asleep while we wait.

    ⛔⛔ (Sep 14) A pause ran long, the console entered REST MODE, the Remote
    Play connection was cut, and the run ENDED - not from a loss, from
    inactivity. Rest mode keys off controller idle time, so any input resets it.

    ⛔ DOWN then UP, nothing else. The pause menu has QUIT GAME on it, so a face
    button here could end the game outright; a down/up pair leaves the
    highlighted item exactly where it was. If one of the two were ever dropped
    the selection would sit one row off - which is harmless on its own, because
    nothing in this loop presses a face button while paused.
    """
    try:
        pad.press("lstick_down", hold=0.06)
        time.sleep(0.35)
        pad.press("lstick_up", hold=0.06)
        time.sleep(0.2)
        pad.release()
        log("    (keep-awake nudge - console must not sleep)")
    except Exception as e:
        log(f"    ! keep-awake failed: {e}")


def _halt(reason, log=print):
    """Stop the farm for good and leave a marker no restart can step over.

    ⛔ A file, not a flag: Montrell must be able to walk away knowing nothing
    resumes on its own. farm.sh refuses to start while this exists, so an
    absent-minded restart cannot burn the run he was protecting.
    """
    try:
        with open(C.HALT_FILE, "w") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {reason}\n")
    except OSError:
        pass
    log(f"    ⛔⛔ HALT: {reason}")
    _alert_sticky(f"FARM STOPPED - {reason}", log)


def _alert_sticky(msg, log=print):
    """An alert only a human clears.

    ⛔⛔ RUN-ENDING EVENTS MUST BE STICKY. On the old build a game was lost, the
    alert fired correctly, and a routine recovery `_clear_alert()`d it minutes
    later - so every status check afterwards reported "no alerts" while the run
    was already dead.
    """
    _alert(msg, log)
    try:
        with open(C.STICKY_ALERT, "a") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n")
    except OSError:
        pass


def _clear_alert():
    try:
        os.remove(C.ALERT_FILE)
    except OSError:
        pass


def dump_stuck(tag, log=print):
    """Save a full screenshot AND the OCR text when the loop cannot proceed.

    The menu layer matches OCR strings and Madden keeps changing them - five
    separate stalls on the old build, each a different text surprise. A dump
    turns the next one into a two-minute fix instead of having to catch it live.
    """
    ts = time.strftime("%Y%m%d-%H%M%S")
    png = f"{C.STUCK_DIR}/{ts}-{tag}.png"
    try:
        pad.shot(None, png)
        with open(f"{C.STUCK_DIR}/{ts}-{tag}.txt", "w") as fh:
            fh.write(screen.screen_text())
        log(f"    !! STUCK ({tag}) - dumped {png}")
    except Exception as e:
        log(f"    !! STUCK ({tag}) - dump failed: {e}")


# ---------------------------------------------------------------------------
# THE Q4 BAIL-OUT
# ---------------------------------------------------------------------------

_G = {"bailout_ok_until": 0.0, "heal": None}   # passed back to the loop


def maybe_intervene(theirs, ours, log=print):
    """Losing at the start of Q4 -> pause and ask. ONE check per game.

    Returns True if Montrell took over (the loop should stop and leave the game
    paused), False otherwise.

    ⛔⛔ THAT RULE IS REVERSED FOR THIS EVENT (Sep 24). It used to read "no
    answer inside the window means un-pause and play it out - losing one game
    is far cheaper than idling the farm for hours". That was written for an
    event where a loss cost a few coins. Here a loss throws away every win
    banked in the run, and the old default has already lost three runs, so an
    unanswered window now HALTS with the game still paused
    (C.AUTO_RESUME_ON_TIMEOUT restores the old behaviour).
    """
    # ⛔ CONFIRM BEFORE PAUSING. The score misreads - measured badly enough on
    # Sep 12 that a game won by 24 was reported as a 6-6 tie. Pausing costs up to
    # 30 minutes of farm time, so spend one extra look first and fail safe
    # towards PLAYING ON rather than towards idling.
    # ⛔⛔ CONFIRM BEFORE WAKING HIM. (Montrell, Sep 13, after a false pause:
    # "double check and verify though whenever it's paused before alerting me,
    # but I do want to be alerted if it's an actual tie or about to lose.")
    #
    # A single re-read once reported 20-20 during a 20-0 WIN and made him take
    # over for nothing. Take SEVERAL independent looks and let a clear majority
    # decide. Reads are ~1s each and a pause costs up to 30 minutes, so this is
    # cheap insurance in both directions - it suppresses false alarms without
    # suppressing real ones.
    votes = []
    for _ in range(C.BAILOUT_CONFIRM_READS):
        v = screen.read_hud_full()
        if v and v.get("theirs") is not None and v.get("ours") is not None:
            votes.append((v["theirs"], v["ours"]))
        time.sleep(0.6)
    if votes:
        from collections import Counter
        ahead = sum(1 for t, o in votes if o > t)
        log(f"    bail-out confirm: {votes}  ({ahead}/{len(votes)} say AHEAD)")
        if ahead > len(votes) / 2:
            log("    -> majority say we are AHEAD, playing on")
            # ⛔⛔ AND IF THEY ALL AGREE, STOP DOUBTING THE TALLY.
            # (Sep 14) Marking a tally "suspect" made `winning` permanently
            # False, so a game being won 30-7 re-entered the bail-out on every
            # play and eventually PAUSED - reporting "LOSING (down -29)", which
            # is a 29-point LEAD written as a deficit. Montrell has been woken
            # by a false pause before and it is corrosive: an alert that cries
            # wolf is worse than no alert.
            #
            # Five fresh independent reads that all agree are better evidence
            # than a stale flag about something that happened earlier in the
            # game. Adopt them and clear the suspicion.
            if ahead == len(votes) and len(votes) >= 3:
                _G["heal"] = Counter(votes).most_common(1)[0][0]
            # ⛔ AND DO NOT ASK AGAIN NEXT DOWN. Each confirm is five captures
            # plus OCR - about fifteen seconds - and a flickering opponent score
            # re-triggered it play after play. Montrell: "it'll pick the play
            # quickly one down and the next time it'll just sit there for 15
            # seconds." Once a majority says we are ahead, that verdict holds
            # for BAILOUT_RECHECK_SECS unless the score actually moves.
            _G["bailout_ok_until"] = time.time() + C.BAILOUT_RECHECK_SECS
            return "declined"
        # ⛔⛔ NEVER PUT AN UNVALIDATED NUMBER IN THE ALERT.
        # (Sep 13) This pushed "LOSING (down 30) 33-3" to his phone during a
        # game that was actually 3-3, and later "33-5" during a 5-0 WIN. The
        # votes come straight off the HUD with none of the plausibility checks
        # that _accept_score applies, so a systematic misread reads as fact.
        # Drop impossible values first, and if what survives still disagrees
        # with the score the loop has been tracking, SAY SO rather than assert
        # a number. The decision to pause does not depend on this - only the
        # wording does - so an honest "score uncertain" is strictly better than
        # a confident fiction.
        from collections import Counter
        clean = [(t, o) for t, o in votes
                 if t != 1 and o != 1 and t <= C.SCORE_MAX and o <= C.SCORE_MAX]
        if clean:
            (theirs, ours), _n = Counter(clean).most_common(1)[0]
            if len(set(clean)) > 1:
                log(f"    ⚠️ score reads disagree {sorted(set(clean))} - "
                    f"reporting the most common, treat it as approximate")
        else:
            log("    ⚠️ every confirm read was implausible - "
                "reporting the tracked score, not the HUD")

    fresh = None
    if fresh and fresh.get("theirs") is not None and fresh.get("ours") is not None:
        # ⛔ Same rule as the trigger: a TIE still counts as danger. Using
        # ">=" here would re-read a 0-0 game and decide it was fine - which is
        # exactly the game we lost.
        # ⛔ Only a CONFIRMED LEAD on the re-read cancels the pause. Same rule
        # as the trigger - anything else, including an unreadable score, pauses.
        if fresh["ours"] > fresh["theirs"]:
            log(f"    bail-out: re-read says {fresh['theirs']}-{fresh['ours']}"
                f" - we are AHEAD, playing on")
            # ⛔ "declined", not False. A re-read that finds us AHEAD must NOT
            # consume the game's single bail-out - nothing was wrong, so the
            # check should stay armed in case the game turns later. Returning
            # False here marked the game as already-intervened and disarmed the
            # protection for the rest of it.
            return "declined"
        theirs, ours = fresh["theirs"], fresh["ours"]

    q, gs, _ps = screen.read_clocks()
    mins, secs = divmod(int(gs), 60) if gs is not None else (0, 0)
    deficit = theirs - ours
    # ⛔ A NEGATIVE DEFICIT IS A LEAD. This printed "LOSING (down -29)" for a
    # 29-point lead - the single most confusing thing we could put in front of
    # him at a glance on a phone.
    state = ("TIED" if ours == theirs else
             f"LOSING (down {deficit})" if deficit > 0 else
             f"AHEAD by {-deficit} (paused for another reason)")
    # ⛔ Say WHICH quarter. (Sep 17) The Q3 alarm reuses this path and its
    # message read "in Q4/OT, 0:09 left" for a Q3 pause - which was read as a
    # misfire and cost a wrong first call. The quarter was just read above.
    where = f"in Q{q}" if q in (1, 2, 3) else "in Q4/OT"
    detail = (f"{state} {theirs}-{ours} {where}"
              + (f", {mins}:{secs:02d} left" if gs is not None else "")
              + (f" - tier {CURRENT_TIER}" if CURRENT_TIER else ""))

    log(f"    !! {detail} - PAUSING")
    pad.press("options", hold=0.08)
    time.sleep(2.5)

    wait = C.INTERVENE_WAIT
    try:
        with open(C.INTERVENE_FILE, "w") as fh:
            json.dump({"detail": detail, "theirs": theirs, "ours": ours,
                       "deficit": deficit, "tier": CURRENT_TIER,
                       "secs_left": gs, "ts": time.strftime("%H:%M:%S"),
                       "wait_min": int(wait / 60),
                       "wait_until": time.strftime(
                           "%H:%M:%S", time.localtime(time.time() + wait))},
                      fh, indent=1)
    except OSError:
        pass
    _alert_sticky(f"PAUSED - {detail}. Options: let it play out / I intervened / "
                  f"extend. Auto-resumes in {wait/60:.0f} min.", log)

    deadline = time.time() + wait
    action = "timed out"
    last_nudge = time.time()
    while time.time() < deadline:
        # ⛔ The console must not sleep while we hold. This wait is the longest
        # silent stretch in the whole system and it is what killed a run.
        if time.time() - last_nudge >= C.KEEPAWAKE_SECS:
            last_nudge = time.time()
            _keep_awake(log)
        # ⛔ The 30-minute pause is the single longest place the loop sits. A
        # stop request here must not wait it out - the game is already paused,
        # so this is the safest possible moment to exit.
        # ⛔ Second net. If a halt was raised while a game was already under
        # way, do not play it out - PAUSE it and stop, so he can take over.
        if os.path.exists(C.HALT_FILE):
            log(f"[{stamp()}]   HALT file present -> pausing the game and stopping")
            try:
                pad.release()
                pad.press("options", hold=0.08)
            except Exception:
                pass
            return

        if os.path.exists(STOP_FILE):
            action = "STOP requested"
            break
        if os.path.exists(C.INTERVENED_FILE):
            action = "INTERVENED"
            break
        if os.path.exists(C.RESUME_FILE):
            action = "play it out"
            break
        if os.path.exists(C.EXTEND_FILE):
            deadline += wait
            try:
                os.remove(C.EXTEND_FILE)
            except OSError:
                pass
            until = time.strftime("%H:%M", time.localtime(deadline))
            log(f"    -> window EXTENDED, now waiting until {until}")
            _alert_sticky(f"still PAUSED - window extended to {until}", log)
        time.sleep(5)
    for f in (C.RESUME_FILE, C.INTERVENED_FILE, C.EXTEND_FILE, C.INTERVENE_FILE):
        try:
            os.remove(f)
        except OSError:
            pass

    if action == "INTERVENED":
        # ⛔ He has the pad and has almost certainly un-paused already. Pressing
        # anything here could re-open the pause menu - or worse, land on QUIT
        # GAME, which the menu may still be sitting on. Touch NOTHING.
        log("    -> INTERVENED: he has it. Resuming WITHOUT pressing anything.")
        time.sleep(3.0)
        return True

    # ⛔⛔ A TIMEOUT NO LONGER PLAYS ON. (Sep 24.) Three runs died to the old
    # behaviour - the window expired with nobody watching and the loop resumed
    # a game it had already judged lost. Here one loss ends the run, so an
    # unanswered pause STOPS THE FARM with the game still paused. Nothing is
    # lost: he comes back to a paused game and can finish it by hand.
    if action == "timed out" and not C.AUTO_RESUME_ON_TIMEOUT:
        _halt(f"PAUSE UNANSWERED for {wait/60:.0f} min - {detail}. The game is "
              f"STILL PAUSED and the farm is stopped; nothing was played on. "
              f"Finish it by hand, or rm the HALT file and ./farm.sh to hand "
              f"it back. (MUT_EVENT_AUTO_RESUME=1 restores playing on.)", log)
        # True = "stop and leave the game paused", per this function's
        # contract. The loop's play-boundary HALT check then exits it.
        return True

    # ⛔ Un-pause with CIRCLE (back), never CROSS. The pause menu remembers its
    # last position and QUIT GAME is on it - a blind cross could end the run.
    log(f"    -> {action}: un-pausing and playing it out")
    pad.press("moon", hold=0.08)
    time.sleep(2.5)
    return False


# ---------------------------------------------------------------------------
# BETWEEN GAMES
# ---------------------------------------------------------------------------
# None of these screens have a clock, so unlike the playcall path they can
# afford a full-screen Vision pass and be identified by their TEXT rather than
# by pixel geometry. Far more robust, and far easier to extend when Madden adds
# another interstitial - which it keeps doing.

def _has(txt, *needles):
    return all(n.upper() in txt for n in needles)


def enter_event(log=print, tries=18):
    """From the events list, land on our event card and press X.

    ⛔ PRESSING X ON THE WRONG CARD ENTERS A DIFFERENT MODE. Verify by text,
    never by list position. Ours is 6th down the list today (Montrell, Sep 12),
    and EA can reorder the list at any point in the promo's run - so the
    position is logged as context, never used as a shortcut. `tries` only has
    to be larger than the list, not accurate.

    ⛔ Requires config.EVENT_MATCH. It is empty until someone reads the real
    title off the screen (`calibrate.py event`), and an empty matcher would
    match the FIRST card, so this refuses rather than guesses.
    """
    global CURRENT_TIER, CURRENT_RECORD
    if not C.EVENT_MATCH:
        _alert_sticky("EVENT_MATCH is not set - cannot pick the event card. "
                      "Run `calibrate.py event` and set it in config.py.", log)
        return False
    for _ in range(tries):
        txt = screen.screen_text()
        for m in re.finditer(C.EVENT_MATCH, txt, re.I):
            # ⛔⛔ FOUR CARDS OF THIS PROMO ARE ON THIS PAGE AND ONLY ONE IS
            # OURS - two H2H, two CPU, and two of the four marked SQ (SQUADS).
            # The title alone does NOT identify our card. Check the markers in
            # the TITLE WINDOW, and reject before requiring: a card that says
            # SQ can never be ours no matter what else it says.
            title = txt[m.start():m.start() + C.EVENT_TITLE_WINDOW]
            if any(re.search(bad, title, re.I) for bad in C.EVENT_REJECT):
                log(f"    events: skipping sibling card {title[:40]!r}")
                continue
            if not all(req.upper() in title.upper() for req in C.EVENT_REQUIRE):
                continue
            # The expanded card puts its action button after its title, so
            # require the action word to follow the title CLOSELY. Searching the
            # whole screen would match a button belonging to a different card.
            # ⛔ 900 chars, not 260: the event DESCRIPTION sits between the title
            # and the button and is ~250 chars on its own, so a short window ends
            # before "Start" and the loop spins on the events list forever.
            window = txt[m.start():m.start() + 900]
            if any(k in window for k in ("START", "CONTINUE", "FINISH EVENT")):
                # ⛔⛔ DO NOT SCRAPE THE TIER OFF THIS CARD. (Measured live,
                # Sep 12: it reported "tier 3" during a tier-1 game.) The card's
                # own description reads "...escalates with each tier. TIER 3 & 4
                # has a loss limit of two", so ANY `TIER \d` regex over the card
                # window matches the BLURB, not our progress. There is no tier
                # number on this card at all.
                #
                # The honest answer is that we do not know the number, so we do
                # not record one. What we DO observe is the live ARCADE/COMP
                # badge (tiers 1-2 vs 3-4), and that is what goes in the history.
                # ⭐ Nothing branches on the tier in this build, so an unknown
                # tier costs a label, not a run.
                # ⛔ Search AFTER our title. Other events are listed above ours
                # and carry their OWN "CURRENT RECORD:" - a whole-screen search
                # returns the wrong one, and six straight games once logged an
                # impossible "1-0".
                r = re.search(r"RECORD\s*:?\s*(\d+)\s*[-–—]\s*(\d+)",
                              window)
                new_rec = f"{r.group(1)}-{r.group(2)}" if r else None
                # ⭐ THE RECORD DECIDES THE RESULT. Compare with the record as of
                # the last completed game: +1 win means we won, +1 loss means we
                # lost, whatever the scoreboard claimed.
                global RECORD_AT_LAST_GAME
                before = _parse_record(RECORD_AT_LAST_GAME)
                after = _parse_record(new_rec)
                if before and after:
                    dw, dl = after[0] - before[0], after[1] - before[1]
                    if dw == 1 and dl == 0:
                        _patch_last_result("W", f"record {RECORD_AT_LAST_GAME} "
                                           f"-> {new_rec}", log)
                    elif dl == 1 and dw == 0:
                        _patch_last_result("L", f"record {RECORD_AT_LAST_GAME} "
                                           f"-> {new_rec}", log)
                    elif (dw, dl) != (0, 0):
                        log(f"    ! record jumped {RECORD_AT_LAST_GAME} -> "
                            f"{new_rec}; not correcting on an ambiguous delta")
                # ⛔⛔⛔ A LOSS ON TIER 3 OR 4 STOPS THE FARM. DEAD. HERE.
                # (Sep 14, Montrell: "if we suffer a single loss in tier 3 or
                # four we want the farm to completely stop... I don't wanna have
                # to keep starting this event over and not getting the rewards.")
                #
                # This is the LAST moment before the button that enters the next
                # game, and it is the right place: the alternative is discovering
                # the loss from inside a live game we should never have started.
                # Tiers 3-4 allow two losses, so one loss means the run is one
                # mistake from over - and every restart so far has cost hours.
                # Stopping idle is cheap; losing the run is not.
                # ⛔ (Sep 24) The gate was `tier >= 3`, which can never be
                # true in a ONE-TIER event - it would have been dead code and
                # this halt would never fire. C.HALT_ON_ANY_LOSS opens it: any
                # loss, any time, stops the farm here.
                # ⭐ The card DOES print a record once one exists (verified
                # after game 1: `record 1-0`). It is blank at 0-0, which is
                # why it looked absent. So this halt is live, and the PROGRESS
                # screen halt is a second, independent net.
                _t_now = tier_from_record(new_rec) or CURRENT_TIER
                if (before and after and after[1] > before[1]
                        and (C.HALT_ON_ANY_LOSS or (_t_now or 0) >= 3)):
                    _halt(f"LOSS ({RECORD_AT_LAST_GAME} -> {new_rec}). Farm "
                          f"STOPPED before entering another game. A loss ends "
                          f"this run - the next game would start a fresh 10.",
                          log)
                    return False

                RECORD_AT_LAST_GAME = new_rec
                CURRENT_RECORD = new_rec
                _save_state()
                log(f"    events: {C.EVENT_LABEL} selected "
                    f"(tier {CURRENT_TIER or '?'}"
                    + (f", record {CURRENT_RECORD}" if CURRENT_RECORD else "")
                    + ")")
                pad.press("cross", hold=0.06)
                time.sleep(2.5)
                return True
        # Our card is not on screen (or not expanded yet). Scroll and look
        # again - never press cross on whatever happens to be focused.
        pad.press("down", hold=0.06)
        time.sleep(0.9)
    dump_stuck("enter_event", log)
    _alert_sticky("could not find our event card in the events list", log)
    return False


def advance_menus(log=print, tries=25):
    """Walk postgame -> hub -> event -> entry options -> back into a game.

    Returns True once a playcall screen is up again.
    """
    global CURRENT_TIER
    unknown_presses = 0
    loading_waits = 0
    # ⛔⛔ START FROM A NEUTRAL PAD EVERY TIME WE RETAKE CONTROL.
    # (Sep 14) Montrell watched the pause menu SCROLL as soon as the farm took
    # over - long after any 3s hold could explain it. A burst is a hold; a
    # continuous scroll is a key that is still DOWN.
    #
    # We post presses with focus=False for speed. If chiaki loses focus between
    # a key-down and its key-up - he alt-tabs, takes the pad, a notification
    # steals it - the key-up is delivered somewhere else and chiaki goes on
    # believing the stick is held. Nothing in the loop would ever notice.
    # Menus are where that does the damage, so neutralise before touching one.
    try:
        pad.release()
    except Exception:
        pass
    for _ in range(tries):
        side, _i, _name, ratio = screen.read_both()
        if side is not None and ratio >= C.CONFIDENT:
            # ⭐ WHOSE SECONDS WERE THEY? (Sep 13) We resumed from a pause and
            # snapped with the play clock on :1 - a delay of game. From the log
            # alone it was impossible to tell whether WE burned the clock after
            # resuming, or whether it was already nearly dead when control came
            # back. Read it here, at the handover, so the next one is measured
            # instead of argued about.
            try:
                _q, _g, ps = screen.read_clocks()
            except Exception:
                ps = None
            if ps is not None:
                log(f"    playcall screen is back (play clock :{ps})")
                if ps <= 6:
                    log(f"    ⚠️ only {ps}s of play clock at handover - "
                        f"snapping immediately, a delay of game may be "
                        f"unavoidable")
            else:
                log("    playcall screen is back")
            return True

        txt = screen.screen_text()
        if not txt:
            time.sleep(1.5)
            continue

        # ⭐ Refresh the tier from the card title on ANY menu screen that shows
        # it - the events list, the progress screens, the reward screens.
        seen_tier = tier_from_title(txt)
        if seen_tier is not None and seen_tier != CURRENT_TIER:
            log(f"    TIER FROM TITLE: {seen_tier}")
            CURRENT_TIER = seen_tier
            _save_state()

        if _has(txt, "FINISH GAME"):
            # ⭐ A full four-quarter game ends on Madden's own menu (FINISH GAME
            # / VIEW HIGHLIGHTS / PLAYER STATS / ...). Air Raid never showed it.
            #
            # ⭐⭐ THIS SCREEN IS THE GAME BOUNDARY, and its banner carries the
            # FINAL SCORE in huge unambiguous numerals. Both are recorded here
            # before anything is pressed - see hud.read_final_score for the false
            # LOSS that came from inferring either one.
            global SAW_FINISH_GAME, FINAL_SCORE
            SAW_FINISH_GAME = True
            fs = hud.read_final_score()
            if fs:
                FINAL_SCORE = fs
                log(f"    end of game: FINAL {fs[0]}-{fs[1]} (from the banner)")
            else:
                log("    end of game: banner score unreadable")
            ok, detail = actions.choose_finish_game(log=log)
            if not ok:
                dump_stuck("finish-game", log)
                _alert_sticky(f"END OF GAME: could not confirm FINISH GAME "
                              f"({detail}). Screen dumped to {C.STUCK_DIR}.", log)
                return False
            log(f"    end of game -> {detail}")

        elif _has(txt, "RETURN TO HUB"):
            # ⛔⛔ THIS IS THIS EVENT'S GAME BOUNDARY, AND IT WAS NOT BEING
            # BOOKED. (Sep 24, measured: two games won, ZERO history rows and
            # no `=== GAME N END` line.) Clock's Ticking ended on Madden's
            # own "FINISH GAME" menu, so that is the only screen that set
            # SAW_FINISH_GAME - and the recorder books a game only when that
            # flag is set. Unstoppable ends on RETURN TO HUB instead, so every
            # game fell through to "break handled in Ns" and was never
            # recorded. The handoff's own rule - per-game history BEFORE any
            # optimisation - was quietly impossible to satisfy.
            #
            # Same treatment as FINISH GAME: record the boundary and grab the
            # banner's final score before pressing anything.
            # ⚠️ The `g.plays > 0` guard at the recorder is what stops a
            # stray sighting from splitting a game in two. RETURN TO HUB is
            # not on the pause menu (checked: RESUME / INSTANT REPLAY / ... /
            # QUIT GAME), so it should only ever appear at a true end.
            # ⛔ No `global` statement here - this function already declares
            # SAW_FINISH_GAME / FINAL_SCORE global in the FINISH GAME branch
            # above, and a second declaration after an assignment is a
            # SyntaxError.
            SAW_FINISH_GAME = True
            fs = hud.read_final_score()
            if fs:
                FINAL_SCORE = fs
                log(f"    postgame: RETURN TO HUB - FINAL {fs[0]}-{fs[1]} "
                    f"(from the banner)")
            else:
                log("    postgame: RETURN TO HUB - banner score unreadable")
            pad.press("cross", hold=0.06)
            time.sleep(2.2)

        elif _has(txt, "SELECT GAME MODE"):
            log("    events list")
            if not enter_event(log=log):
                return False

        elif _has(txt, "ENTRY OPTIONS") or ("LINEUP" in txt and
                                            "RESTRICTED" in txt):
            # ⛔⛔ NEVER a blind directional press here. See actions.choose_lineup
            # for the ~11 rewards that mistake cost last event.
            ok, detail = actions.choose_lineup(log=log)
            if not ok:
                dump_stuck("entry-options", log)
                _alert_sticky(
                    f"ENTRY OPTIONS: could not confirm the {C.LINEUP_WANT} "
                    f"lineup ({detail}). NOT entering - a wrong pick costs the "
                    f"whole run's rewards. Screen dumped to {C.STUCK_DIR}.", log)
                return False
            log(f"    entry options -> {detail}")

        elif _has(txt, "HOW TO PLAY") or _has(txt, "REQUIREMENTS"):
            log("    intro -> continue")
            pad.press("cross", hold=0.06)
            time.sleep(2.5)

        elif _has(txt, "FINISH EVENT"):
            log("    FINISH EVENT -> collecting rewards")
            pad.press("cross", hold=0.06)
            time.sleep(2.0)

        elif _has(txt, "EVENTS") and _has(txt, "CHALLENGES"):
            # MUT hub, PLAY tab. Focus starts on Binder in the middle row.
            log("    MUT hub -> EVENTS")
            pad.press("down", hold=0.06)
            time.sleep(0.6)
            pad.press("right", hold=0.06)
            time.sleep(0.6)
            pad.press("cross", hold=0.06)
            time.sleep(2.0)

        elif _has(txt, "CHIAKI-NG") or _has(txt, "REFRESH PSN HOSTS"):
            # ⛔ THE STREAM DIED. Pressing here does nothing useful and, once it
            # reconnects, every queued press lands somewhere arbitrary in
            # Madden. Restart the stream - never press into the chiaki UI.
            log("    chiaki dropped -> restarting stream")
            try:
                pad.restart_stream()
            except Exception as e:
                log(f"    ! stream restart failed: {e}")
            time.sleep(6.0)

        elif any(k in txt for k in ("YOUR REWARDS", "YOUR PROGRESS", "ADVANCE",
                                    "SCROLL REWARDS", "OBJECTIVE PROGRESS")):
            # ⛔⛔ THE EVENT'S PROGRESS SCREEN IS ALSO A GAME BOUNDARY.
            # (Sep 25, 01:00, measured.) `FINISH GAME` and `RETURN TO HUB` were
            # the only two screens that set SAW_FINISH_GAME, and the recorder
            # books a game ONLY when that flag is set. Measured in the run that
            # started 00:26: the postgame went STRAIGHT to the progress screen
            # with no RETURN TO HUB at all, so the game fell through to
            # `break handled in 25s` - 76 plays, a completed game, ZERO rows.
            #
            # `ELIMINATION ... x/1 LOSSES` + `x/10 WINS` only ever appears
            # after a game has finished, so it is a sound third trigger. The
            # `g.plays > 0` guard at the recorder still stops a stray sighting
            # from splitting a live game.
            # ⚠️ The same panel can be reached by hand from entry options with
            # SQUARE, but the loop never presses square there.
            if re.search(r"\d\s*/\s*\d+\s*WINS", txt) and "LOSSES" in txt:
                if not SAW_FINISH_GAME:
                    log("    progress screen = game boundary (no RETURN TO HUB "
                        "was shown)")
                SAW_FINISH_GAME = True
            # ⭐ Capture reward screens for review. Last event we took the wrong
            # reward path ~10 times before anyone looked at one of these.
            if "YOUR REWARDS" in txt:
                try:
                    d = f"{C.RUN_DIR}/rewards"
                    os.makedirs(d, exist_ok=True)
                    pad.shot(None, f"{d}/{time.strftime('%H%M%S')}.png")
                    log("    [reward screen captured for review]")
                except Exception:
                    pass
            # ⛔⛔ ELIMINATION IS READ HERE, NOT FROM THE RECORD. (Sep 17.) The
            # tier-3 run ended 3-0; this screen read "2/2 LOSSES", the loop
            # pressed through it, Madden rolled straight into a FRESH tier-1
            # run and the record-delta halt (on the events list) never got its
            # turn - the events list was never shown. The progress screen is
            # the LAST screen before the new run, so this is where to stop.
            m_loss = re.search(r"(\d)\s*/\s*(\d)\s*LOSS", txt)
            _t = CURRENT_TIER or 0
            # ⛔ "/2 LOSSES" IS ITSELF THE TIER 3-4 SIGNAL. (Sep 21) Tiers 1-2
            # read "x/1 LOSSES"; today's progress text carried no "T2" at all
            # and CURRENT_TIER was stale (the events list is skipped when the
            # progress screen goes straight to the next game), so neither of
            # the other two gates could be trusted alone.
            # ⛔⛔ UNSTOPPABLE: ANY LOSS IS FATAL, SO THE GATE IS OPEN.
            # (Sep 24) Last event this asked "is this tier 3 or 4", because
            # tiers 1-2 could absorb a loss. This event is 0/1 LOSSES with no
            # tiers: every loss ends the run. C.HALT_ON_ANY_LOSS makes the
            # gate unconditional; the tier tests below are kept only so the
            # file still works if this code is carried to a tiered event.
            _t34 = (C.HALT_ON_ANY_LOSS
                    or _t >= 3 or bool(re.search(r"\bT[34]\b", txt))
                    or (m_loss is not None and m_loss.group(2) == "2"))
            if m_loss and m_loss.group(1) == m_loss.group(2) and _t34:
                _halt(f"ELIMINATED - progress screen reads "
                      f"{m_loss.group(0)}. The run is OVER; Madden will roll "
                      f"into a FRESH run of 10. Farm STOPPED before it could. "
                      f"Decide, then rm the HALT file.", log)
                return False
            # ⛔⛔ ANY NEW LOSS ON TIER 3-4 STOPS THE FARM HERE. (Sep 21,
            # Montrell: "prevent the farm from entering another game after a
            # loss ... stop the farm after a loss and wait for my guidance"
            # - the Sep 19 run ended on two tier-3 losses while he was away.)
            # The record-delta halt on the events list already existed, but
            # this screen's CONTINUE goes STRAIGHT into the next game and the
            # events list is never shown - so it never got its turn. This is
            # the last screen before the next game. Compare with the count
            # last seen (persisted in the state file) so that after he clears
            # the HALT to play on, the loss he already knows about does not
            # halt again.
            global LOSSES_SEEN
            if m_loss and _t34:
                _n = int(m_loss.group(1))
                # ⛔ Unset baseline = 0. The tier-3 count starts at 0, so a
                # first sighting of "1/2" IS a new loss (Saturday's game 1).
                # After a HALT the count is persisted, so a deliberate
                # restart does not re-halt on the loss he already knows about.
                if _n > (LOSSES_SEEN or 0):
                    LOSSES_SEEN = _n
                    _save_state()
                    _halt(f"LOSS - progress screen reads "
                          f"{m_loss.group(0)}. Every loss ends this run. Farm "
                          f"STOPPED before entering another game; waiting for "
                          f"guidance. To play on (a FRESH run of 10): "
                          f"rm {C.HALT_FILE} and ./farm.sh", log)
                    return False
                if _n != LOSSES_SEEN:
                    log(f"    progress: loss count = {_n}")
                LOSSES_SEEN = _n
                _save_state()
            elif m_loss and not _t34 and LOSSES_SEEN is not None:
                LOSSES_SEEN = None          # tiers 1-2 / fresh run: reset
                _save_state()
            log(f"    rewards/progress -> advancing  |RAW| {txt[:160]}")
            for _ in range(2):
                pad.press("cross", hold=0.06)
                time.sleep(0.7)

        elif len(txt) < 45 or (len(txt) < 140
                               and any(k in txt for k in ("EASPORTS", "MADDEN",
                                                          "SPORTS"))):
            # LOADING / TRANSITION - wait it out, never press.
            #
            # ⛔ Do NOT match an exact banner string. Five times a hardcoded
            # phrase has failed here: the EA splash once OCR'd as
            # "SPORTS | MADDEN | NFL", matching neither "EASPORTS" nor
            # "MADDEN NFL". A loading screen's real signature is that it has
            # almost NO TEXT - that holds however Vision mangles it.
            #
            # ⛔⛔ AND THE KEYWORDS MUST BE BOUNDED BY LENGTH. (Sep 12, first
            # live run.) "SPORTS" is a substring of the EA SPORTS watermark that
            # sits on REAL screens too - the 293-character end-of-game menu
            # OCR'd as "...ZASPORTS..." and matched here, so the loop called it
            # a loading screen, waited 18 times, and then restarted chiaki
            # against a game that was only waiting for a button press. The
            # length bound is what keeps this branch meaning "nearly no text".
            loading_waits += 1
            # ⛔ A FROZEN CHIAKI FEED looks exactly like a static loading screen:
            # identical captures, console pings fine, nothing changes. Restart
            # the stream BEFORE concluding anything about the game.
            if loading_waits in (8, 20):
                log("    same screen too long - restarting chiaki (may be frozen)")
                try:
                    pad.restart_stream()
                except Exception as e:
                    log(f"    ! stream restart failed: {e}")
                time.sleep(6.0)
                continue
            if loading_waits % 10 == 0 and not screen.console_up():
                dump_stuck("console-offline", log)
                _alert_sticky("PS5 UNREACHABLE - console likely powered off", log)
                return False
            if loading_waits > 40:
                dump_stuck("loading-forever", log)
                _alert(f"stuck on a loading screen ({loading_waits} waits)", log)
                return False
            log(f"    loading/transition -> waiting ({txt[:40]})")
            time.sleep(3.0)

        else:
            # ⛔⛔ DO NOT PRESS CROSS HERE. Cross CONFIRMS, so on an unrecognised
            # screen it navigates DEEPER into the game - once walking into MY
            # TEAM, player attributes and the PACKS screen. `moon` is BACK; it
            # retreats toward the hub, which is where we can re-find our way.
            # ⛔⛔ A STOP REQUEST MUST BE HONOURED HERE TOO.
            # (Sep 14) The boundary check lives at the top of the play loop, but
            # menus, loading and pauses are where the loop spends MINUTES - so
            # `farm.sh stop` timed out and force-killed on three of four stops.
            # Forcing was safe each time only because no down was live; that is
            # luck, not a guarantee. Menus are a safe place to stop: nothing is
            # in flight and no down can be lost.
            if os.path.exists(STOP_FILE):
                log("    STOP requested -> exiting from menus")
                return False
            unknown_presses += 1
            if unknown_presses > 8:
                dump_stuck("unknown-screen-loop", log)
                _alert(f"lost in unknown menus: {txt[:60]}", log)
                return False
            log(f"    unknown screen, backing out (moon): {txt[:60]}")
            pad.press("moon", hold=0.06)
            time.sleep(1.2)
    return False


# ---------------------------------------------------------------------------
# THE LOOP
# ---------------------------------------------------------------------------

class Game:
    """Per-game state. Reset wholesale at every game boundary.

    ⛔ A dedicated object, not a pile of locals, because the old build's game
    reset was fifteen separate assignments and forgetting one leaked a stale
    value into the next game - which is how four games in a row were logged with
    the wrong tier.
    """

    def __init__(self, joined=False):
        # ⭐ `joined` means the loop did NOT see this game start - it attached to
        # a game already in progress, which is what every restart does. Its
        # RESULT is real; its duration and play count are not comparable to a
        # game played end to end, so it is recorded and then excluded from pace.
        #
        # ⛔ This is more reliable than inferring it from the first quarter seen:
        # a restart early in Q1 still loses the opening drive, and would
        # otherwise be recorded as a complete game and drag the median down.
        self.joined = joined
        self.t0 = time.time()
        self.plays = 0
        self.theirs = 0          # every game kicks off 0-0; seed with the truth
        self.ours = 0
        self.since_theirs = 0    # plays since each box last read acceptably
        self.since_ours = 0
        self.opp_confirmed = False   # did the opponent score EVER read as digits
        self.pend = {}           # value awaiting a confirming repeat, per side
        self.contra = {}         # readings that CONTRADICT our stored score
        self.score_suspect = False   # our tally has been proven wrong once
        self.quarter = None
        self.overtime = False
        # ⛔ A GAME CANNOT REACH OVERTIME WITHOUT PASSING THROUGH Q4. Tracking
        # that breaks a circularity: when the HUD shows OT it does NOT show a
        # quarter, so "quarter is unknown" was being accepted as "might be OT" -
        # and a stray token in the quarter slot then declared overtime in the
        # FIRST QUARTER of a brand-new 0-0 game (measured twice, Sep 13).
        #
        # False overtime is expensive: it is sticky for the game and switches
        # OFF both clock chewing and the quarter-end skip.
        self.seen_q4 = False
        self.tier_logged = None
        self.chew_note = False   # have we logged that burning is now allowed
        self.badge = None        # ARCADE / COMP, observed live
        self.intervened = False  # the Q4 bail-out has already run this game
        self.fieldpos_dumped = False   # one-off field-position diagnostic
        self.q3_paused = False         # the third-quarter alarm has fired
        self.q3_pass = False           # tiers 1-2: the Q3 alarm has fired (sticky trigger)
        self.q3_pass_on = False        # ...and the pass is currently in (off once ahead)
        self.blowout_paused = False    # the two-score check has fired this game
        self.bailout_ok_until = 0.0    # "we are ahead" verdict holds until this
        self.bailout_ok_score = None   # ...and only for THIS score
        self.need_chew = True    # tempo must be (re-)armed
        self.skips = 0           # consecutive deliberate no-snaps
        # ⭐ Which broadcast presentation this game is using. Recorded, never
        # branched on - see hud.layout_name.
        self.layout = None
        self.clock_x = None
        self.rescued = False     # the rescue rule is currently overriding
        self.rescue_used = False # the rescue fired at any point this game
        # ⛔ Wall-clock spent PAUSED waiting on a human. Subtracted from the
        # recorded duration: a 30-minute bail-out hold is not the game taking
        # 30 minutes longer, and leaving it in made a rescued game look like it
        # cost 36.9 min when it really costs ~22-26.
        self.paused_secs = 0.0
        # ⛔ WHAT WE ACTUALLY RAN, not what config defaults to. The offence is
        # chosen per play from the live badge, so recording C.OFF_PLAY_NAME
        # logged "BULLET PASS" for games played entirely with the DIVE - which
        # would silently corrupt the very comparison this field exists for.
        self.offense_used = None
        # ⛔ A GAME THE LOOP DID NOT START IS NOT A TIMED GAME. The archive says
        # it plainly - "a mid-game restart voids that game's timing" - and the
        # first row this build ever wrote was exactly that trap: a restart
        # landed in Q4, played 11 plays, won, and recorded "11 plays / 6.4 min",
        # which reads like a complete game and would have dragged the median
        # down to a number no full game can hit.
        #
        # `partial` is set when the first quarter we ever observe is not Q1.
        # The row is still WRITTEN - the result is real and worth keeping - but
        # status.sh excludes it from pace statistics.
        self.first_quarter = None
        self.partial = joined

    @property
    def result(self):
        """W / L / T from the score - or None when the score cannot carry it.

        ⛔⛔ A TIE IS THE MOST CONSEQUENTIAL VERDICT THIS SYSTEM PRODUCES: the
        event counts it as a LOSS, and on tiers 1-2 one loss ends the run. It is
        also the verdict the SCORE is least able to support, because EQUAL
        SCORES ARE THE MOST COMMON OCR ARTIFACT - both boxes misreading to the
        same value. Measured in one session: 6-6 (a win), 20-20 (a 20-0 win),
        3-3, 33-3. On Sep 14 this reported "6-6 -> T" for a game the event
        recorded as a WIN (record 2-0 -> 3-0, elimination still 0/1).
        ⭐ The EVENT'S OWN RECORD is the truth and the record-delta correction
        fills this in. Returning None says "I do not know" and lets that happen,
        instead of asserting the one answer that would look like a lost run.
        """
        if self.ours > self.theirs:
            return "W"
        if self.ours < self.theirs:
            return "L"
        if self.opp_confirmed and not self.score_suspect:
            return "T"
        return None

    @property
    def tier_guess(self):
        """What the live badge says about the tier, as a label - never a number.

        ⭐ ARCADE means tier 1 or 2, COMP means tier 3 this event (the split
        moved: it was 1 vs 2/3 last event). The badge cannot tell 1 from 2, so
        it is recorded as what was SEEN rather than converted into a guess.
        """
        return self.badge


def _accept_score(g, which, value, log):
    """Validate one side's score before believing it. Returns True if accepted.

    ⛔ Scores only ever go UP, and only so fast. Both failure shapes have been
    seen live: "0-72" was an impossible LEAP, and the "14 -> 10" that followed
    was an impossible DROP.

    ⭐ SELF-HEALING: a wild read must never poison the baseline permanently, but
    a genuine jump we mis-bounded must still get through. So an out-of-range
    value is believed only if the SAME value comes back on the very next read -
    "0-72" appeared once and was gone; a real score sticks.
    """
    # ⛔ 1 IS AN IMPOSSIBLE FOOTBALL SCORE. Safety 2, field goal 3, touchdown 6 -
    # nothing scores a single point, and no combination sums to 1. Observed live
    # on Sep 12 ("score 1-0"), and it slipped through the jump bound because
    # 0 -> 1 is a perfectly small increase. An impossible value must be rejected
    # on its own terms, not merely bounded.
    #
    # It matters: a phantom 1-0 deficit is enough to trigger the Q4 bail-out and
    # idle the farm for 30 minutes over a game we are actually winning.
    if value == 1 and not C.ALLOW_SCORE_OF_ONE:
        log(f"    ! REJECTED {which} score 1 - impossible in football")
        return False
    # ⛔ AND AN UPPER BOUND. A real game cannot reach three figures, but the HUD
    # carries other numbers the parser can grab - a "735" on the special-teams
    # strip is what produced a recorded score of "0-735". Anything this large is
    # a field-position or stat token that wandered into the score slot.
    if value > C.SCORE_MAX:
        log(f"    ! REJECTED {which} score {value} - above {C.SCORE_MAX}, "
            f"not a football score")
        return False
    have = g.theirs if which == "theirs" else g.ours
    since = g.since_theirs if which == "theirs" else g.since_ours

    # ⛔⛔ A SCORE NEVER GOES DOWN. Reject a decrease outright - do NOT let it
    # through the confirm-twice path.
    #
    # That escape hatch exists for an impossible-looking JUMP: a real score that
    # my per-play bound was too tight for, which comes back identical on the next
    # read. A DECREASE is not mis-bounded, it is physically impossible, and
    # "confirm twice" just means the same misread arrived twice - which it does,
    # because OCR failures on this strip are systematic, not random.
    #
    # Observed Sep 12: "ours score 6 confirmed twice - accepting (was 25)". That
    # wipes a 25-point lead, and the Q4 bail-out reads these numbers - a phantom
    # deficit would idle the farm for 30 minutes.
    if value < have:
        # ⛔⛔ THE STORED VALUE IS NOT SACRED. (Sep 14 - this cost a run.)
        # Scores never decrease, so a lower reading looks like a misread. But
        # that reasoning assumes what WE hold is correct. When a bad read gets
        # in first, this guard locks the corruption in PERMANENTLY and rejects
        # every correct reading forever after.
        #
        # Measured: a phantom "ours 34" arrived in Q1, and from then on the true
        # "theirs 0" was rejected on every single play. The farm finished the
        # game believing 38-30 in a game that was actually 0-0, played into a
        # tied overtime with the Q4 bail-out disabled (it thought it was 8 up),
        # and turned clock-burning ON to protect a lead that did not exist.
        #
        # Reality is persistent in a way a misread is not, so a value that keeps
        # coming back wins. A decrease needs MORE agreement than an increase,
        # because it is impossible in football and we should only ever conclude
        # it about OUR OWN bookkeeping.
        k = which + "_lower"
        if g.contra.get(k) == value:
            g.contra[k + "_n"] = g.contra.get(k + "_n", 0) + 1
        else:
            g.contra[k], g.contra[k + "_n"] = value, 1
        if g.contra[k + "_n"] >= C.SCORE_CONTRADICT:
            log(f"    !! {which} score read as {value} "
                f"{g.contra[k + '_n']}x in a row while we hold {have} - "
                f"OUR VALUE WAS WRONG, correcting to {value}")
            # ⛔ And the whole tally is now suspect. Anything derived from it -
            # above all the Q4/OT bail-out - must stop trusting it.
            g.score_suspect = True
            g.contra[k] = None
            g.contra[k + "_n"] = 0
            return True
        log(f"    ! REJECTED {which} score {value} - scores never decrease "
            f"(have {have}, seen {g.contra[k + '_n']}x)")
        return False

    room = min(C.SCORE_JUMP_MAX * max(1, since), C.SCORE_JUMP_ABS)
    if value - have > room:
        if g.pend.get(which) == value:
            g.pend[which + "_n"] = g.pend.get(which + "_n", 0) + 1
        else:
            g.pend[which], g.pend[which + "_n"] = value, 1
        # ⛔⛔ TWO IDENTICAL MISREADS ARE STILL A MISREAD.
        # (Sep 13) This accepted "theirs 33" over a real 0 during a 5-0 WIN,
        # because the same bad read arrived twice. OCR failures on this strip
        # are SYSTEMATIC, not random - the whole reason the decrease-guard above
        # exists - so repetition is weak evidence. The phantom 28-point deficit
        # then made the Q4 bail-out re-confirm on EVERY play: five captures a
        # time, ~15s per down, which is what Montrell saw as the farm "sitting
        # there". Jump size must be bounded no matter how often it repeats.
        slack = room + C.SCORE_JUMP_MAX * 2
        if value - have > slack:
            log(f"    !! REJECTED {which} score {value} as IMPOSSIBLE "
                f"(was {have}, {since} plays ago, max plausible {slack}) "
                f"- repeated misread, not a score")
            g.pend[which] = None
            g.pend[which + "_n"] = 0
            return False
        if g.pend[which + "_n"] >= 3:
            log(f"    {which} score {value} confirmed 3x - accepting "
                f"(was {have})")
            g.pend[which] = None
            g.pend[which + "_n"] = 0
            return True
        log(f"    ! REJECTED {which} score {value} "
            f"(last {have}, {since} plays ago)")
        return False
    g.pend[which] = None
    g.pend[which + "_n"] = 0
    return True


def play_loop(max_plays=99999, log=print):
    global CURRENT_TIER, CURRENT_BADGE
    t_run = time.time()
    # The first game of any run is one we attached to, unless the loop walks
    # into it through the menus (in which case _end_game makes a fresh Game).
    g = Game(joined=True)
    game_no = 1
    total_plays = 0
    idle = 0
    idle_since = None
    # ⭐ (Sep 25) Time-based cadences. These used to be `idle % N`, which was
    # only right while every pass slept LOOP_SLEEP=1.0s. The live-play poll is
    # now 0.3s, and counting passes would run the full-screen OCR 3x as often.
    _t_slow = _t_console = _t_waitlog = 0.0
    dead_t0 = None
    last_play_t = time.time()
    ever_played = False        # has a playcall screen been seen this run at all
    last_game_t = time.time()
    stuck_dumped = False
    game_stall_alerted = False
    last_situation = None
    same_situation = 0
    last_clock = None          # game clock at the previous progress check
    off_plays = 0              # offensive snaps this run - drives the flip toggle
    st_captured = False        # one-off diagnostic capture of the 4th-down screen

    def stamp():
        el = int(time.time() - t_run)
        return f"{el // 60:02d}:{el % 60:02d}"

    # ⛔ Report what will ACTUALLY run, not the legacy static name. The banner
    # said "BULLET PASS" during a dive-only run, which is exactly the kind of
    # misleading log that has cost hours today.
    _arc = C.OFF_BY_BADGE["ARCADE"]["name"]
    _cmp = C.OFF_BY_BADGE["COMP"]["name"]
    log(f"[{stamp()}] === FARM START ===  "
        f"chew={'ON @ :%d' % C.HIKE_AT if C.HIKE_AT < 99 else 'OFF'}"
        f" (held until ahead on tiers {sorted(C.CHEW_ONLY_WHEN_AHEAD_TIERS)})"
        f"  snap_floor={C.MIN_SNAP_WAIT}s")
    log(f"           offense: ARCADE={_arc} · COMP={_cmp}"
        f"  rescue={'on' if C.RESCUE_PASS else 'OFF'}"
        f"  defense={C.DEF_PLAY_NAME}")

    while total_plays < max_plays:
        # ⛔⛔ GRACEFUL STOP - CHECK BETWEEN PLAYS, NEVER MID-PLAY.
        # (Sep 13) I restarted the farm four times in one game with a bare
        # `pkill`, and one of them landed BETWEEN THE HIKE AND THE THROW. The
        # loop died holding the ball, the QB took the sack, and Montrell had to
        # take over to win the yards back. From the log it looked exactly like a
        # game bug - play [12] simply had no snap line - and I nearly "fixed"
        # the throw sequence over it.
        #
        # A config change is NEVER worth a live down. `farm.sh stop` touches
        # this file; we notice here, at a play boundary, and exit clean.
        if os.path.exists(STOP_FILE):
            try:
                os.remove(STOP_FILE)
            except OSError:
                pass
            log(f"[{stamp()}]   STOP requested -> exiting at a play boundary")
            return

        # ⛔⛔ A HALT MUST END THE LOOP, NOT JUST WRITE A FILE. (Sep 19, 21:45.)
        # The elimination halt fires on the progress screen and returns False
        # from advance_menus - which nothing treated as "stop". The loop came
        # back 55s later, re-read the same screen, re-halted, 24 times in a
        # row; then the stream dropped, chiaki's reconnect raised the PS5's
        # "WHO'S USING THIS CONTROLLER?" prompt, and the menu handler mashed
        # circle at it for 20 minutes. The only in-loop HALT check was inside
        # the pause branch, which a menu screen never reaches.
        if os.path.exists(C.HALT_FILE):
            log(f"[{stamp()}]   HALT file present -> exiting the loop")
            return

        _t_iter = time.time()
        side, i, name, ratio = screen.read_both()

        # FROZEN FEED. Identical frames mean a stale image, not a real screen.
        # ⛔ A frozen chiaki stream reads as a perfectly valid screen forever -
        # it once "punted" into a stale frame for 18 minutes with every watchdog
        # happy, because plays WERE being called.
        # ⛔ A STATIC MENU IS NOT A FROZEN STREAM. The frozen check compares
        # consecutive tab-strip crops, and on the events list / entry options
        # that region is legitimately identical frame after frame - so starting
        # the farm on a menu tripped it immediately and burned a chiaki restart
        # (Sep 13). Needless restarts are not free: one of them is what left the
        # stream behind other windows and had the loop reading the Mac desktop.
        #
        # Only trust the signal while we believe a game is actually live, i.e.
        # we have seen a playcall screen recently. The menu path has its own
        # watchdogs (loading-forever, console_up) and does not need this one.
        # ⛔ AND ONLY AFTER WE HAVE ACTUALLY PLAYED SOMETHING. `last_play_t` is
        # initialised to NOW at loop start, so on a fresh start the loop counts
        # as "recently in play" before it has seen a single screen - and a farm
        # started on a static menu then trips the frozen check and burns a
        # chiaki restart within 20 seconds. (Measured twice, Sep 13.)
        in_play_recently = (ever_played
                            and (time.time() - last_play_t) < C.FROZEN_ONLY_WITHIN)
        if in_play_recently and screen.FROZEN_STREAK >= C.FROZEN_RESTART:
            # ⛔ CONFIRM FIRST. A restart is the most expensive thing this loop
            # can do (25-220s, measured) and identical frames are also what a
            # network hiccup or a static screen produce. Re-focus and look again
            # before paying for it.
            before = screen.FROZEN_STREAK
            try:
                pad._remote_post("/focus", {})
            except Exception:
                pass
            time.sleep(C.FROZEN_CONFIRM_SECS)
            try:
                screen.read_both()
            except Exception:
                pass
            if screen.FROZEN_STREAK < before:
                log(f"[{stamp()}]   feed moved again after {before} identical "
                    f"frames - NOT restarting (transient, not frozen)")
                continue

            log(f"[{stamp()}]   FROZEN FEED ({screen.FROZEN_STREAK} identical "
                f"frames, confirmed after {C.FROZEN_CONFIRM_SECS:.0f}s) "
                f"-> restarting chiaki")
            try:
                pad.restart_stream()
            except Exception as e:
                log(f"    ! stream restart failed: {e}")
            time.sleep(6.0)
            if screen.FROZEN_STREAK >= C.FROZEN_ALERT:
                dump_stuck("frozen-feed", log)
                _alert("feed frozen and a chiaki restart did not clear it", log)
            continue

        # -------------------------------------------------------------------
        # NOT ON A PLAYCALL SCREEN
        # -------------------------------------------------------------------
        if side is None or ratio < C.CONFIDENT:
            idle += 1
            if idle_since is None:
                idle_since = time.time()
            idle_secs = time.time() - idle_since
            if time.time() - _t_waitlog >= 20:
                _t_waitlog = time.time()
                log(f"  ... waiting ({name}, ratio {ratio:.2f})")

            # Console reachability - cheap, and catches the one failure no
            # screen-based check can tell apart from a loading screen.
            _console_due = time.time() - _t_console >= 40
            if _console_due:
                _t_console = time.time()
            if _console_due and not screen.console_up():
                dump_stuck("console-offline", log)
                _alert_sticky("PS5 UNREACHABLE - console likely powered off", log)
                time.sleep(30)
                continue

            # GAME-LEVEL STALL. The play watchdog only catches a loop that stops
            # PRESSING; this catches one that keeps pressing but never finishes
            # a game - e.g. spinning on the events list.
            if (not game_stall_alerted
                    and (time.time() - last_game_t) > C.GAME_STALL_SECS):
                game_stall_alerted = True
                mins = (time.time() - last_game_t) / 60
                dump_stuck("game-stall", log)
                _alert(f"no game completed in {mins:.0f} min - check if stuck", log)

            if not stuck_dumped and (time.time() - last_play_t) > 300:
                stuck_dumped = True
                dump_stuck("no-play-5min", log)
                log(f"[{stamp()}]   watchdog: backing out to find a known screen")
                for _ in range(3):
                    pad.press("moon", hold=0.06)
                    time.sleep(1.2)
                advance_menus(log=log)
                idle, idle_since = 0, None
                continue

            # SUB-SCREEN RECOVERY.
            # ⛔ The action bar is on the NORMAL playcall screen too, not just
            # sub-screens. Firing `moon` on "action bar present" alone backed the
            # old build OUT of good playcall screens whenever a brightness read
            # came in marginal. The condition must be that the tab strip is
            # genuinely ABSENT, not merely low-confidence.
            #
            # "NO-TABSTRIP" means the band is blank, i.e. a LIVE PLAY - skip the
            # expensive checks entirely and keep polling cheaply.
            if name not in ("NO-TABSTRIP",):
                has_tabs, _txt = screen.has_tab_words()
                if not has_tabs:
                    bar = screen.action_bar()
                    if any(k in bar for k in ("ADD/REMOVE FAVORITE",
                                              "COACH ADJUSTMENTS", "FLIP PLAY",
                                              "PLAYCALL SUBSTITUTIONS")):
                        log(f"[{stamp()}]   playcall UI, NO tab strip "
                            f"-> backing out of sub-screen (moon)")
                        pad.press("moon", hold=0.06)
                        time.sleep(0.9)
                        idle, idle_since = 0, None
                        continue

            # SLOW PATH - full-screen OCR, for things with no clock pressure.
            if time.time() - _t_slow >= C.SLOW_PATH_EVERY:
                _t_slow = time.time()
                txt = screen.screen_text()
                # ⛔⛔ ARE WE EVEN LOOKING AT THE CONSOLE? If chiaki has fallen
                # behind another window the daemon captures the Mac's desktop,
                # and every button we "press" goes into whatever app is focused -
                # RETURN and BACKSPACE into a terminal, for instance.
                #
                # ABORT, do not retry. Unlike a frozen feed there is nothing to
                # wait out, and unlike a dead console the presses are NOT inert.
                if screen.looks_like_mac(txt):
                    dump_stuck("mac-desktop", log)
                    _alert_sticky(
                        "CAPTURING THE MAC DESKTOP, NOT THE PS5 - chiaki is not "
                        "frontmost. STOPPING: every press would go to whatever "
                        "app has focus. Bring chiaki back up, then restart.", log)
                    log(f"[{stamp()}] === ABORTING: not looking at the console ===")
                    return total_plays
                # ⛔⛔ WE MAY BE AT THE LINE WITH A PLAY ALREADY SELECTED.
                # (Sep 14, repeated DELAY OF GAME.) This loop only ever acts on
                # a PLAYCALL screen. But a play can get selected without us
                # snapping it - the ACCEPT press below is `cross`, and `cross`
                # is also the dive's slot, so an ACCEPT that lands a moment late
                # picks a play and drops us straight at the line. From there the
                # loop waits 45s for a playcall screen that will never come,
                # while the play clock runs to zero.
                #
                # ⭐ A VISIBLE PLAY CLOCK IS THE TELL: it exists ONLY pre-snap,
                # so seeing one while off the playcall screen means the play is
                # picked and nobody has hiked it. Snap it.
                # ⛔ Gate on the clock being LOW, so this cannot fire during
                # normal pre-play where the loop is about to act anyway.
                try:
                    _pq, _pg, _pp = screen.read_clocks()
                except Exception:
                    _pp = None
                if (_pp is not None and _pp <= C.PRESNAP_RESCUE_AT
                        and ever_played and "ACCEPT" not in txt):
                    log(f"[{stamp()}]   at the line with a play selected and "
                        f"the clock at :{_pp} - SNAPPING to avoid a delay of game")
                    pad._remote_post("/focus", {})
                    time.sleep(0.25)
                    pad._remote_post("/press", {"buttons": ["cross"],
                                                "hold": C.OFF_SNAP_HOLD,
                                                "gap": 0.0, "focus": False})
                    idle, idle_since = 0, None
                    last_play_t = time.time()
                    continue

                if "ACCEPT" in txt and "DECLINE" in txt:
                    # ⭐ ACCEPT is right for this event: a defensive penalty on
                    # our drive means a first down, which keeps possession and
                    # burns more clock - exactly what we are here for.
                    log(f"[{stamp()}]   penalty prompt -> ACCEPT (cross)")
                    pad.press("cross", hold=0.06)
                    time.sleep(2.0)
                    idle, idle_since = 0, None
                    continue
                if any(k in txt for k in ("FINISH GAME", "RETURN TO HUB",
                                          "YOU WON", "YOU LOST",
                                          "POST GAME SUMMARY", "YOUR REWARDS",
                                          "SELECT GAME MODE", "ENTRY OPTIONS")):
                    log(f"[{stamp()}]   postgame detected -> menu handling")
                    idle_secs = 999
                    dead_t0 = time.time()     # real overhead starts HERE

            if idle_secs >= 45:
                if dead_t0 is None:
                    log(f"[{stamp()}]   no playcall for 45s -> menu handling")
                    dead_t0 = time.time()
                got = advance_menus(log=log)
                # ⛔ Measure overhead from POSTGAME DETECTION, not from when
                # idling began - idle_since starts the moment a play is called,
                # so it swallows the whole final play.
                menu_secs = time.time() - (dead_t0 or idle_since)
                dead_t0 = None
                if got:
                    # ⛔⛔ THE GAME ENDED ONLY IF WE SAW THE END-OF-GAME MENU.
                    # The old rule - "the menu walk took more than 25 seconds" -
                    # is inference, and on Sep 12 it fired on a mid-game cutscene
                    # and SPLIT one game into two records: a phantom "35 plays,
                    # 17.7 min, 12-2 LOSS" followed by a "2 plays, 2.4 min". The
                    # real game was a 12-0 WIN. A false loss alert is the single
                    # most expensive thing this loop can produce.
                    #
                    # A missed boundary is cheap by comparison, and the
                    # quarter-reset check below still catches it.
                    global SAW_FINISH_GAME, FINAL_SCORE
                    if SAW_FINISH_GAME and g.plays > 0:
                        if FINAL_SCORE:
                            # ⭐ The banner wins over anything read mid-play.
                            g.theirs, g.ours = FINAL_SCORE
                            g.opp_confirmed = True
                        g = _end_game(g, game_no, menu_secs, stamp, log)
                        game_no += 1
                        last_game_t = time.time()
                        game_stall_alerted = False
                        _clear_alert()
                    else:
                        log(f"[{stamp()}]   break handled in {menu_secs:.0f}s")
                        g.need_chew = True
                        g.quarter = None
                    SAW_FINISH_GAME = False
                    FINAL_SCORE = None
                idle, idle_since = 0, None
                continue
            time.sleep(1.0)
            continue

        # -------------------------------------------------------------------
        # ON A PLAYCALL SCREEN
        # -------------------------------------------------------------------
        idle, idle_since = 0, None
        last_play_t = time.time()
        ever_played = True
        stuck_dumped = False

        log(f"[{stamp()}] [{total_plays + 1}] {side.upper():13s} "
            f"tab={name:<10s} ratio={ratio:.2f}")

        if side == "specialteams":
            # ⭐ ONE-OFF DIAGNOSTIC: capture the 4th-down screen so we can see
            # what it actually offers. We punt on every 4th down today, which
            # HANDS BACK POSSESSION - and possessions are what drive play count,
            # so punting is lengthening our games as well as wasting the down.
            # ⛔ The first capture caught a KICKOFF, which is not the case we
            # care about - kicking off is correct. We want a 4TH-DOWN PUNT
            # screen. Keep looking until we see one that is not a kickoff.
            if not st_captured:
                try:
                    sttxt = screen.screen_text()
                    if "KICKOFF" not in sttxt.upper():
                        st_captured = True
                        ts = time.strftime("%H%M%S")
                        pad.shot(None, f"{C.STUCK_DIR}/punt-{ts}.png")
                        with open(f"{C.STUCK_DIR}/punt-{ts}.txt", "w") as fh:
                            fh.write(sttxt)
                        log(f"    [PUNT screen captured: "
                            f"{C.STUCK_DIR}/punt-{ts}.png]")
                except Exception as e:
                    log(f"    ! special teams capture failed: {e}")
            # ⭐⭐ NEVER PUNT. (Sep 14, Montrell: "we shouldn't be doing that,
            # that's insane" - and "go for it every time".) A punt hands back
            # possession, and possessions are what drive play count, so punting
            # lengthens the game AND wastes the down.
            #
            # ⛔ A KICKOFF IS NOT A PUNT. The same screen serves both, and
            # kicking off is CORRECT and unavoidable - skipping it would wedge
            # the game. So discriminate on the screen text and only refuse the
            # punt. Field goals stay here too: if the screen offers one we take
            # the normal special-teams path rather than fighting it.
            sttxt = ""
            try:
                sttxt = (screen.screen_text() or "").upper()
            except Exception:
                sttxt = ""

            # ⛔⛔ A FIELD GOAL IS NOT A PUNT AND NOT A KICKOFF.
            # (Sep 15) On 4th down Madden offers the special-teams screen, and
            # the middle play there can be the FIELD GOAL. call_special_teams
            # takes that play and snaps it with its generic two-press routine -
            # second press at MIN_SNAP_WAIT (6.0s). A field goal needs the
            # ACCURACY press at FG_PRESS_AFTER (3.5s, measured). So we selected
            # a field goal and then butchered the kick. Montrell watched it.
            # ⭐ FIELD POSITION decides the kick, not the printed distance.
            _yl = _arrow = None
            _goal = False
            try:
                _h = hud.read_hud()
                _yl = _h.get("yardline")
                _arrow = _h.get("yard_arrow")
                _goal = bool(_h.get("goal"))
            except Exception:
                pass

            # ⛔ Opponent's half must be POSITIVELY established. An up-arrow, or
            # goal-to-go. "10" on its own could be our own 10.
            _their_half = (_arrow in ("^", "\u25b2")) or _goal
            _in_range = (_yl is not None and _yl <= C.FG_MAX_YARDLINE
                         and _their_half)

            if ("FIELD GOAL" in sttxt and "KICKOFF" not in sttxt
                    and "ONSIDE" not in sttxt and not _in_range):
                log(f"[{stamp()}]   FG offered but NOT inside their "
                    f"{C.FG_MAX_YARDLINE} (yard={_yl} arrow={_arrow!r} "
                    f"goal={_goal}) - going for it")
                if actions.goto_tab("offense", C.OFF_TAB):
                    play = C.OFF_BY_BADGE["COMP"]
                    actions.select_play(play)
                    snapped, status, hint = actions.chew_and_hike(
                        log=log, allow_skip=False, chew=False,
                        throw=play["throw"], flipped=False,
                        run_seq=play.get("run_seq"),
                        throw_seq=play.get("throw_seq"))
                    log(f"    4TH DOWN GO - {status}")
                    total_plays += 1
                    last_play_t = time.time()
                    continue
                log("    ! could not reach FAVORITES - taking the kick anyway")

            if ("FIELD GOAL" in sttxt and "KICKOFF" not in sttxt
                    and "ONSIDE" not in sttxt):
                log(f"[{stamp()}]   FIELD GOAL"
                    + (f" (their {_yl})" if _yl is not None else "")
                    + f" -> kicking with the meter timing "
                      f"({C.FG_PRESS_AFTER}s), not the punt routine")
                pad.press("cross", hold=C.OFF_SELECT_HOLD)   # take the kick
                time.sleep(1.0)
                pad._remote_post("/focus", {})
                time.sleep(0.3)
                _tk = time.time()
                pad._remote_post("/press", {"buttons": ["cross"],
                                            "hold": C.OFF_SNAP_HOLD,
                                            "gap": 0.0, "focus": False})
                time.sleep(max(0.0, (_tk + C.FG_PRESS_AFTER) - time.time()))
                pad._remote_post("/press", {"buttons": ["cross"], "hold": 0.06,
                                            "gap": 0.0, "focus": False})
                log(f"    kicked @{time.time() - _tk:.2f}s "
                    f"(target {C.FG_PRESS_AFTER})")
                total_plays += 1
                last_play_t = time.time()
                continue
            is_punt = ("PUNT" in sttxt
                       and "KICKOFF" not in sttxt
                       and "ONSIDE" not in sttxt)
            if is_punt and C.GO_FOR_IT_ON_FOURTH:
                # Walk back to the offensive favourites and run a real play.
                # ⛔ If that navigation fails, PUNT rather than stand here: a
                # delay of game on 4th down is worse than the punt we were
                # trying to avoid.
                log("    PUNT screen -> going for it instead")
                if actions.goto_tab("offense", C.OFF_TAB):
                    play = C.OFF_BY_BADGE["COMP"]
                    log(f"    4th down -> {play['name']}")
                    actions.select_play(play)
                    snapped, status, hint = actions.chew_and_hike(
                        log=log, allow_skip=False, chew=False,
                        throw=play["throw"], run_seq=play.get("run_seq"),
                        throw_seq=play.get("throw_seq"))
                    status = f"4TH DOWN GO - {status}"
                else:
                    log("    ! could not reach FAVORITES from the punt screen "
                        "- punting rather than risking a delay of game")
                    snapped, status, hint = actions.call_special_teams(log=log)
            else:
                snapped, status, hint = actions.call_special_teams(log=log)
        elif side == "offense":
            # ⛔ TIER FIRST. Everything below depends on it - the chew gate
            # and the play choice both read `tier`, and computing it later
            # crashed the loop with UnboundLocalError (Sep 13), which left
            # the farm DEAD mid-game taking repeated delay-of-game penalties.
            t_title = CURRENT_TIER
            t_record = tier_from_record(CURRENT_RECORD)
            # ⛔⛔ THE BADGE GETS A VOTE TOO. A COMP badge means tier 3 AT LEAST,
            # whatever the other two say.
            #
            # I demoted the badge entirely when the title/record sources were
            # added, and on Sep 13 that ran the FULLBACK DIVE on a COMP game -
            # the exact failure that lost the previous run - because the record
            # was still reading 8-0 (tier 2) while the console was already on
            # tier 3. The badge was screaming COMP and nothing listened.
            #
            # Every source is now allowed to RAISE the tier and none can lower
            # it. Under-reporting runs the dive on COMP and loses runs;
            # over-reporting merely runs the slower offence.
            t_badge = 3 if (g.badge or CURRENT_BADGE) == "COMP" else None
            tier = max([x for x in (t_title, t_record, t_badge) if x],
                       default=None)
            srcs = {"title": t_title, "record": t_record, "badge": t_badge}
            if len({v for v in srcs.values() if v}) > 1:
                log(f"    tier sources differ {srcs} - taking the HIGHEST: {tier}")
            badge = (badge_for_tier(tier) or g.badge or CURRENT_BADGE
                     or C.OFF_DEFAULT_BADGE)
            if tier is not None and g.tier_logged != tier:
                g.tier_logged = tier
                log(f"    tier {tier} (from record {CURRENT_RECORD}) "
                    f"-> {badge} offence")
            # ⛔ If the live badge later DISAGREES with the record, say so
            # loudly - one of them is wrong and we want to know which.
            if g.badge and badge_for_tier(tier) and g.badge != badge_for_tier(tier):
                log(f"    ⚠️ badge says {g.badge} but record {CURRENT_RECORD} "
                    f"implies tier {tier} ({badge_for_tier(tier)}) - "
                    f"trusting the RECORD")

            # ⭐ Are we allowed to burn clock right now? On COMP we only do it
            # once we are CONFIRMED ahead - before that, every second spent
            # pre-snap is a play we do not get to score with.
            # ⭐ A TWO-SCORE CUSHION, NOT A ONE-POINT ONE. (Sep 13, Montrell.)
            # Burning clock on a 1-point lead spends the very clock we need to
            # answer the score that takes the lead back.
            margin = (g.ours - g.theirs) if g.opp_confirmed else 0
            winning = g.opp_confirmed and margin >= C.CHEW_AHEAD_BY
            burn_ok = (tier not in C.CHEW_ONLY_WHEN_AHEAD_TIERS) or winning
            if burn_ok and not g.chew_note:
                g.chew_note = True
                if tier in C.CHEW_ONLY_WHEN_AHEAD_TIERS:
                    log(f"    ahead {g.ours}-{g.theirs} (+{margin}) on tier "
                        f"{tier} -> clock burning ON to protect the lead")
            elif not burn_ok and g.chew_note:
                g.chew_note = False
                # ⛔⛔ THE LEAD IS GONE - GIVE THE CLOCK BACK.
                # Dropping burn_ok stops us WAITING on the play clock, but the
                # CHEW CLOCK tempo adjustment is a console setting that persists
                # until something walks it back. Before this, it never did: we
                # kept running a slow-tempo offence while trailing.
                log(f"    lead down to +{margin} on tier {tier} "
                    f"-> clock burning OFF, reverting tempo")
                if actions.clear_chew_clock(log=log):
                    g.need_chew = True   # re-arm: set it again if we go back up
                else:
                    log("    ! tempo revert FAILED - will retry next playcall")

            # ⛔⛔ NO CLOCK BURNING IN OVERTIME - TEMPO INCLUDED.
            # Sudden death is won by SCORING; every second spent pre-snap is a
            # second closer to the clock expiring on a TIE, which counts as a
            # LOSS. The snap path already refused to chew in OT, but the TEMPO
            # adjustment had no such guard and was set anyway (measured Sep 14:
            # "ahead 38-30 -> clock burning ON" followed by "chew clock SET",
            # in a 0-0 overtime).
            if g.need_chew and burn_ok and not g.overtime and C.CHEW_SET_TEMPO:
                # Tempo is offense-only, so this waits for an offensive playcall
                # even when a half opens on defense.
                got = actions.set_chew_clock(log=log)
                log(f"    chew clock {'SET' if got else 'FAILED'}")
                g.need_chew = not got
            # ⛔ Never skip forever. Four deliberate quarter-end skips in a row
            # means the clock is not doing what we read, so take the down rather
            # than stand here until a watchdog fires.
            # ⛔⛔ NO CLOCK BURNING IN OVERTIME. Sudden death is won by SCORING,
            # and every second spent pre-snap is a second closer to the clock
            # expiring on a TIE. Chewing is the right strategy for exactly the
            # opposite situation - a lead to protect in regulation.
            #
            # Observed live Sep 12: a 0-0 game reached OT with the loop still
            # chewing to :8, spending ~30s of a 3-minute sudden-death period per
            # snap. `g.overtime` was being set and logged but nothing acted on it.
            #
            # Skipping snaps because "the quarter ends first" is wrong here too:
            # letting an OT period expire is precisely the outcome to avoid.
            # ⭐ Alternate the flip. Counted on OFFENSIVE plays only, so a run
            # of defensive series cannot desynchronise it.
            flip = C.FLIP_PLAY and (off_plays % 2 == 1)
            off_plays += 1

            # ⭐⭐ WHICH OFFENCE. Keyed to the live ARCADE/COMP badge, which is
            # the only tier signal that does not drift.
            # ⭐⭐ TIER FROM THE RECORD FIRST. It is read off the events
            # screen before the game starts and is exact; the live badge is a
            # fallback and a cross-check, never the primary source.
            # ⭐⭐ TAKE THE HIGHER OF THE TWO. Both sources under-report in
            # different situations and NEITHER is safe alone:
            #
            #   * the CARD TITLE is stale right after a game - it still shows
            #     the tier just finished until the event advances (the archive
            #     hit this too: "it showed tier one after the game, then moved
            #     to tier 2 before allowing us to hit start")
            #   * the RECORD is only re-read on the events screen, so it goes
            #     stale whenever the quarter-reset path skips that walk
            #     (measured: stuck at 3-0 for three games)
            #
            # Under-reporting the tier is the dangerous direction: it runs the
            # DIVE on COMP, which is how we lost a run. Over-reporting merely
            # runs the slower pass offence. So take the max.
            play = C.OFF_BY_BADGE.get(badge, C.OFF_BY_BADGE[C.OFF_DEFAULT_BADGE])

            # ⭐ HYBRID: DIVE ON 1ST/2ND, PASS ON 3RD/4TH (tiers 3-4).
            # The down comes from the same HUD parse as everything else, so this
            # costs one read. An UNREADABLE down falls through to the PASS -
            # see config: diving on 3rd and long gives the ball away, whereas
            # passing on 1st is just the offence we already ran.
            if tier in C.HYBRID_TIERS:
                dn = None
                try:
                    dn = screen.read_down()
                except Exception:
                    dn = None
                # ⭐ ONE-OFF: what does the screen actually say about field
                # position? Written to disk so it can be read at leisure rather
                # than raced against a live game.
                if C.DUMP_FIELD_POS and not g.fieldpos_dumped:
                    try:
                        g.fieldpos_dumped = True
                        ts = time.strftime("%H%M%S")
                        txt = screen.screen_text() or ""
                        h_all = hud.read_hud()
                        with open(f"{C.STUCK_DIR}/fieldpos-{ts}.txt", "w") as fh:
                            fh.write("FULL SCREEN TEXT:\n" + txt + "\n\n")
                            fh.write("HUD ROWS:\n")
                            for r in (h_all.get("rows") or []):
                                fh.write("  " + " | ".join(t for t, _ in r) + "\n")
                        pad.shot(None, f"{C.STUCK_DIR}/fieldpos-{ts}.png")
                        log(f"    [FIELD POSITION dump: "
                            f"{C.STUCK_DIR}/fieldpos-{ts}.txt]")
                    except Exception as e:
                        log(f"    ! field position dump failed: {e}")

                goal = False
                try:
                    goal = bool(hud.read_hud().get("goal"))
                except Exception:
                    goal = False

                # ⭐ 4TH & GOAL -> KICK IT, if it actually changes the game.
                # Montrell: kick "unless we're losing... by more than three".
                # A field goal that neither ties nor takes the lead is worth
                # less than a 4th-down attempt, so a bigger deficit plays on.
                if (goal and dn == 4 and C.FG_ON_FOURTH_AND_GOAL
                        and C.FG_BUTTON):
                    deficit = (g.theirs - g.ours) if g.opp_confirmed else 0
                    if deficit <= C.FG_MAX_DEFICIT:
                        log(f"    4TH & GOAL, deficit {deficit} "
                            f"(<= {C.FG_MAX_DEFICIT}) -> FIELD GOAL")
                        kicked, kstat, _ = actions.call_field_goal(known=i,
                                                                   log=log)
                        log(f"    {kstat}")
                        if kicked:
                            total_plays += 1
                            last_play_t = time.time()
                            continue
                        log("    field goal not attempted - playing the down")
                    else:
                        log(f"    4TH & GOAL but down {deficit} "
                            f"(> {C.FG_MAX_DEFICIT}) - going for it")

                # ⭐ On COMP the dive sprints too. A COPY, never a mutation of
                # the shared OFF_BY_BADGE entry - tiers 1-2 use the same dict
                # and must not inherit this.
                def _dive():
                    d = dict(C.OFF_BY_BADGE["ARCADE"])
                    # A profile that says run=False (QB SNEAK) stays that way.
                    if tier in C.DIVE_RUN_TIERS and d.get("run", True):
                        d["run"] = True
                    return d

                if goal and C.GOALLINE_DIVE:
                    # ⭐ GOAL TO GO -> DIVE, whatever the down. Montrell: the
                    # pass "doesn't work too well in a goal line situation" -
                    # there is no field left for the back to run into after the
                    # catch, which is the half of the play that does the work.
                    play = _dive()
                    log(f"    GOAL TO GO (down {dn if dn else '?'}) "
                        f"-> {play['name']} (no pass at the goal line)")
                elif dn in C.HYBRID_RUN_DOWNS:
                    play = _dive()                      # the dive
                    log(f"    hybrid: down {dn} -> {play['name']}")
                else:
                    play = C.OFF_BY_BADGE["COMP"]       # the pass
                    log(f"    hybrid: down {dn if dn else '?'} -> "
                        f"{play['name']}"
                        + ("" if dn else "  (down unreadable - passing)"))

            # ⭐ THE RESCUE RULE: on ARCADE, in the second half, if the game is
            # close, spend the minutes and switch to the pass until the lead is
            # safe again. Re-checked every play, so it reverts on its own.
            if (C.RESCUE_PASS and badge == "ARCADE"
                    and (g.quarter or 1) >= C.RESCUE_FROM_QUARTER
                    and g.opp_confirmed
                    and (g.ours - g.theirs) < C.RESCUE_LEAD):
                play = C.RESCUE_PLAY
                if not g.rescued:
                    g.rescued = True
                    # ⛔ Separate from `rescued`: this one is STICKY for the
                    # game. `rescued` toggles back off when the lead is safe
                    # again, so recording it at game end would say "no rescue"
                    # for a game the rescue actually saved.
                    g.rescue_used = True
                    log(f"    ⭐ RESCUE: Q{g.quarter}, lead "
                        f"{g.ours - g.theirs:+d} (< {C.RESCUE_LEAD}) "
                        f"-> switching to {play['name']}")
            elif g.rescued and (g.ours - g.theirs) >= C.RESCUE_LEAD:
                g.rescued = False
                log(f"    lead {g.ours - g.theirs:+d} is safe -> back to "
                    f"{play['name']}")

            # ⭐ (Sep 21) The Q3 switch on tiers 1-2. Once the Q3 alarm has
            # fired: behind or tied -> the pass; ahead -> back to the run.
            # Montrell: "switching to the pass play only stays until we take
            # the lead and then it goes back to the run play." Re-checked every
            # play, so it re-engages if they retake the lead. Wins over the
            # rescue rule. Same profile the Sep 19 tier-1 TX_ALL game ran.
            if g.q3_pass:
                _behind = (g.ours - g.theirs) <= 0
                if _behind and not g.q3_pass_on:
                    g.q3_pass_on = True
                    log(f"    Q3 switch: {g.theirs}-{g.ours}, not ahead -> "
                        f"{C.OFF_BY_BADGE['COMP']['name']}")
                elif not _behind and g.q3_pass_on:
                    g.q3_pass_on = False
                    log(f"    Q3 switch: lead {g.ours - g.theirs:+d} -> back "
                        f"to {play['name']}")
                if g.q3_pass_on:
                    play = C.OFF_BY_BADGE["COMP"]

            # ⭐⭐ HYBRID DIVE (Sep 25): full run until we lead by FBD_SLOW_LEAD,
            # then the short hold so the back stops short of long scores. A COPY
            # of the profile - the shared dict must keep the full run.
            if (C.FBD_SLOW_LEAD and play.get("run_seq")
                    and play["name"] == "FB DIVE WEAK"):
                _slow = (g.opp_confirmed
                         and (g.ours - g.theirs) >= C.FBD_SLOW_LEAD)
                if _slow != getattr(g, "fbd_slow", False):
                    g.fbd_slow = _slow
                    log(f"    HYBRID DIVE: lead {g.ours - g.theirs:+d} -> "
                        + ("SHORT run (hold stops early)" if _slow
                           else "FULL run"))
                if _slow:
                    play = dict(play, run_seq=dict(C.FBD_SLOW_RUN))
            g.offense_used = play["name"]
            # ⭐ A profile may opt out of the flip (QB SNEAK: "no need to flip").
            # The alternation counter above still advances, so a later profile
            # that does flip stays in step.
            if not play.get("flip", True):
                flip = False
            snapped, status, hint = actions.call_offense(
                known=i, log=log,
                allow_skip=(g.skips < 4) and not g.overtime,
                chew=(not g.overtime) and burn_ok, flip=flip, play=play)
        else:
            snapped, status, hint = actions.call_defense(known=i, log=log)
        log(f"    {status}")

        if not snapped:
            # A deliberate no-snap (the quarter expires first) or a failed
            # navigation. Neither spent a play, so neither counts toward the
            # stall detector - it exists to catch plays that go nowhere.
            g.skips += 1
            time.sleep(max(1.0, hint))
            continue
        g.skips = 0

        # REPEATED-SITUATION STALL. Counted only on real snaps: calling the same
        # situation over and over without finishing a game means something is
        # wrong even though plays are "working" - the play watchdog cannot see
        # it, because plays ARE being called.
        if (side, name) == last_situation:
            same_situation += 1
        else:
            same_situation = 0
        last_situation = (side, name)
        if same_situation == C.STALL_WARN:
            dump_stuck("repeated-situation", log)
            _alert(f"same situation {same_situation}x in a row "
                   f"({side}/{name}) - not progressing", log)
        if same_situation >= C.STALL_ABORT:
            # ⛔⛔ ALERT ONCE, THEN ABORT. The old build reset this counter after
            # alerting, so a frozen game re-alerted every 8 plays FOREVER - 89
            # times across 4h15m overnight, burning the whole play budget on
            # retries into a dead screen. A stall this long is never
            # self-healing.
            dump_stuck("frozen-game", log)
            try:
                q, gs, _ps = screen.read_clocks()
                with open(C.FROZEN_FILE, "w") as fh:
                    json.dump({"situation": f"{side}/{name}",
                               "repeats": same_situation, "quarter": q,
                               "clock": gs, "score": f"{g.theirs}-{g.ours}",
                               "ts": time.strftime("%H:%M:%S")}, fh, indent=1)
            except Exception:
                pass
            _alert_sticky(
                f"FROZEN: {same_situation}x {side}/{name} with no progress - "
                f"STOPPING THE LOOP. This is the known Madden freeze (pause "
                f"works, play-call does not); the game has to be quit by hand. "
                f"Nothing is recoverable by pressing more buttons.", log)
            log(f"[{stamp()}] === ABORTING: game frozen ===")
            return total_plays

        total_plays += 1
        g.plays += 1
        g.since_ours += 1
        g.since_theirs += 1

        # -------------------------------------------------------------------
        # POST-SNAP READS. All of this happens in the DEAD TIME while the play
        # runs, never before it is called - the playcall clock cannot afford it.
        # -------------------------------------------------------------------
        # ⭐ THE TIER BADGE renders only during a LIVE PLAY. Read it right after
        # the snap, and only until it answers.
        if g.badge is None and side == "offense":
            g.badge = screen.read_tier_badge()
            if g.badge:
                CURRENT_BADGE = g.badge
                _save_state()
                tiers = (C.ARCADE_TIERS if g.badge == "ARCADE" else C.COMP_TIERS)
                log(f"    badge: {g.badge} -> tier "
                    f"{'/'.join(str(t) for t in sorted(tiers))}")

        # ⭐ ONE HUD CAPTURE gives the score, the quarter AND the presentation.
        # They can never disagree about which moment they describe, and it costs
        # one look instead of three.
        # ⭐ EVERY PLAY FROM Q3 (Sep 25, Montrell: "make sure that the score is
        # checked periodically ... beginning of the third quarter and the
        # beginning of the fourth"). The second-half pass-when-not-winning
        # switch decides on the score before every offensive play, so from Q3
        # every read counts. Post-snap dead time - costs no play clock.
        want_hud = ((g.quarter or 1) >= 3) or (g.plays % C.SCORE_EVERY == 0)
        h = screen.read_hud_full() if want_hud else None
        # ⛔⛔ THE STAT TICKER HIDES THE SCORE (Sep 25, captured). Right after a
        # play is called, this presentation swaps the score block for the ball
        # carrier's line ("PATRICK RICARD | 12 RUSH | 80 YDS") for a few
        # seconds - exactly when this read lands. A whole game logged ZERO
        # score reads, so the 2nd-half pass switch was blind. The quarter and
        # clocks stay visible, so only the score is retried. From Q3 only, a
        # couple of looks ~1s apart while the play is still running.
        _tries = 0
        while (h is not None and h.get("theirs") is None
               and (g.quarter or 1) >= 3 and _tries < C.SCORE_TICKER_RETRIES):
            _tries += 1
            time.sleep(C.SCORE_TICKER_GAP)
            h2 = screen.read_hud_full()
            if h2 and h2.get("theirs") is not None:
                h = h2
        if h:
            if g.layout is None and h.get("clock_x") is not None:
                g.clock_x = h["clock_x"]
                g.layout = hud.layout_name(h["clock_x"])
                log(f"    presentation: {g.layout} (clock at x={g.clock_x})")
            if h["theirs"] is not None and h["ours"] is not None:
                if _accept_score(g, "ours", h["ours"], log):
                    g.ours, g.since_ours = h["ours"], 0
                if _accept_score(g, "theirs", h["theirs"], log):
                    g.theirs, g.since_theirs = h["theirs"], 0
                    g.opp_confirmed = True
                log(f"    score {g.theirs}-{g.ours} "
                    f"(lead {g.ours - g.theirs:+d})"
                    + ("" if g.opp_confirmed else "  [opp score NEVER read]"))

                # ⭐⭐ TWO SCORES DOWN, ANY QUARTER -> PAUSE AND TELL HIM.
                # (Sep 16.) The Q4 bail-out fires far too late for this: by the
                # fourth quarter of a 3-minute-quarter game a two-score hole is
                # usually gone. Catching it the moment it OPENS hands him the
                # whole rest of the game.
                #
                # ⛔ Once per game - `blowout_paused` - so a game we are simply
                # losing does not pause on every single play. It confirms with
                # fresh reads first, exactly like the Q4 check, because a false
                # pause that cries wolf is worse than no pause at all.
                _deficit = g.theirs - g.ours

                # ⭐ RE-ARM WHEN WE CLIMB BACK OUT. (Sep 16, Montrell: "there
                # could be a situation where it pauses because I'm losing by two
                # scores and then I take over, I bring it back and we're winning
                # again, and then it happens again that same game - I wouldn't
                # want to miss that.")
                #
                # So this is EDGE-TRIGGERED, not once-per-game: it fires when we
                # cross INTO a two-score hole, and resets the moment we are back
                # within one score. A game can therefore pause more than once,
                # which is the point - each time is a NEW collapse he has not
                # seen yet. It still cannot pause every play, because it only
                # fires on the crossing.
                if _deficit <= C.PAUSE_IF_DOWN_BY and g.blowout_paused:
                    g.blowout_paused = False
                    log(f"    back within one score ({_deficit}) "
                        f"- two-score alarm re-armed")

                if (C.INTERVENE and g.opp_confirmed and not g.blowout_paused
                        and _deficit > C.PAUSE_IF_DOWN_BY):
                    g.blowout_paused = True
                    log(f"    !! DOWN {_deficit} (> {C.PAUSE_IF_DOWN_BY}) in "
                        f"Q{g.quarter or '?'} - checking before pausing")
                    _t_bp = time.time()
                    outcome = maybe_intervene(g.theirs, g.ours, log=log)
                    if outcome != "declined":
                        # ⛔ Do NOT set g.intervened here. That flag belongs to
                        # the Q4/OT bail-out, and consuming it would mean a
                        # two-score pause in the first quarter silently disables
                        # the fourth-quarter protection for the rest of the
                        # game. They are separate alarms for separate problems.
                        g.paused_secs += time.time() - _t_bp
                        last_play_t = time.time()
                        idle, idle_since = 0, None

        # OVERTIME. Only reachable from Q4 on, and it costs an OCR, so do not
        # look sooner. Once true it stays true for the game.
        if not g.overtime and g.seen_q4 and g.plays > 4:
            if screen.read_is_overtime():
                g.overtime = True
                log("    !! OVERTIME - sudden death, clock burning is off")

        q = h.get("quarter") if h else None
        # ⭐⭐ A MOVING GAME CLOCK MEANS WE ARE NOT FROZEN. Reset the
        # repeated-situation counter on real progress.
        #
        # ⛔ The counter alone measures the wrong thing. It fired "same situation
        # 8x in a row (offense/FAVORITES) - not progressing" during a perfectly
        # healthy game (Sep 12): eight consecutive OFFENSIVE plays is what a
        # SUSTAINED DRIVE looks like, and chewing the play clock deliberately
        # makes drives longer. The archive hit the identical trap on Air Raid's
        # defence - "8-20 consecutive is NORMAL play, not a freeze".
        #
        # The freeze this watchdog exists for is a game where NOTHING changes,
        # and a stopped clock is precisely that signature. So gate on the clock,
        # not on how the situation happens to be labelled.
        if h and h.get("game") is not None:
            if last_clock is not None and h["game"] != last_clock:
                same_situation = 0
            last_clock = h["game"]

        if q is not None and g.first_quarter is None:
            g.first_quarter = q
            if q != 1:
                g.partial = True
                log(f"    ⚠️ joined this game already in Q{q} - timing is NOT "
                    f"comparable, recording it as partial")
            elif g.joined and h and h.get("game") is not None \
                    and h["game"] >= C.FULL_GAME_CLOCK:
                # ⭐ The first game of every run starts out flagged `joined`,
                # because a restart usually lands mid-game. But if the FIRST
                # thing we ever see is Q1 with a near-full clock, we did not miss
                # anything - the loop is watching from kickoff and the timing IS
                # comparable.
                #
                # ⛔ Without this, every restart permanently poisons a game, and
                # during a session with many code fixes NO game ever qualifies as
                # full - which is exactly what happened on Sep 12.
                g.partial = False
                g.joined = False
                log(f"    started from Q1 with {h['game']}s on the clock - "
                    f"counting this as a FULL game")

        # ⭐⭐ A QUARTER RESET IS A GAME BOUNDARY. Without this the only boundary
        # signal is "the menu walk took >25s", and a quicker transition MERGES
        # two games into one record - which is where the old build's "31.7 min,
        # 74 play" game came from. Q3/Q4 back to Q1 can only mean a new game.
        # ⛔⛔ THE CLOCK MUST AGREE, OR IT IS A MISREAD NOT A NEW GAME.
        # (Sep 24, measured.) A real game opens Q1 at a FULL 180s. This fired
        # on `quarter -> Q1 (game clock 41s)` in the middle of a live game,
        # booked a phantom "28 plays, 11.3 min" row, and the loop carried on
        # playing with NO postgame walk at all - a real ending always goes
        # through RETURN TO HUB and the progress screens first.
        # ⛔ Split rows are not harmless: they are exactly the junk that makes
        # per-game timing worthless, and timing is what this event is being
        # measured on. The postgame path is the reliable boundary; this one is
        # the backstop, so it can afford to demand corroboration.
        # ⚠️ An unreadable clock is NOT taken as agreement - the postgame path
        # still catches a genuine boundary a moment later.
        # ⛔⛔ Q4 ONLY, NEVER Q3 (Sep 25, measured). The clock test above let a
        # misread through at the START of Q3: `quarter -> Q3 (game clock 180s
        # - FULL)` then a Q1 read with the clock still at 180s, which booked a
        # 20-play "game" and a 19-play "game" out of one. A game never ends in
        # Q3, so Q3 -> Q1 can only be a misread.
        _q1_clock = (h or {}).get("game")
        if (q == 1 and g.quarter == 4 and g.plays > 0
                and _q1_clock is not None and _q1_clock >= C.FULL_GAME_CLOCK):
            g = _end_game(g, game_no, 0, stamp, log, reason="quarter reset")
            game_no += 1
            last_game_t = time.time()
            game_stall_alerted = False

        # ⛔⛔ QUARTERS ADVANCE BY ONE. A JUMP IS A MISREAD, NOT A QUARTER.
        # (Sep 16) Measured live: "quarter -> Q1" then "quarter -> Q4" in the
        # same game, with the screen plainly showing 1st and 0:47. A 4TH-DOWN
        # ordinal whose "&" went unread falls through to the "any ordinal that
        # is not a down" path and is taken for the quarter.
        #
        # The cost was not cosmetic: believing it was Q4 fired the Q4/OT
        # bail-out and PAUSED a game we were losing by 3 in the FIRST quarter -
        # a false alarm of exactly the kind that makes the real ones easy to
        # ignore. Football only ever goes 1 -> 2 -> 3 -> 4, so anything else is
        # the parser being wrong about a down.
        elif (q and q != g.quarter and g.quarter is not None
                and q > g.quarter + 1):
            log(f"    ! IGNORED quarter Q{q} - cannot jump from "
                f"Q{g.quarter} (almost certainly a 4TH-down misread)")

        # ⛔⛔ A QUARTER CANNOT GO BACKWARDS EITHER. (Sep 24, measured.)
        # The jump guard above only catches quarters going UP. Game 3 logged
        # `quarter -> Q1`, `-> Q2`, `-> Q1` with no boundary between them: a
        # DECREASE was accepted silently. Football only goes 1 -> 2 -> 3 -> 4,
        # so a step backwards is the same down-vs-quarter misread seen from the
        # other side. The one legitimate decrease is Q3/Q4 -> Q1, which is a
        # new game and is handled by the reset branch above.
        elif (q and g.quarter is not None and q < g.quarter
                and not (q == 1 and g.quarter in (3, 4))):
            log(f"    ! IGNORED quarter Q{q} - cannot go BACKWARDS from "
                f"Q{g.quarter} (almost certainly a down misread)")

        elif q and q != g.quarter:
            # ⭐ THE CLOCK IS LOGGED AT EVERY QUARTER CHANGE (Sep 24, Montrell:
            # "check clock all game double check on 1st qtr and 3rd qtr as
            # usual"). A fresh quarter should read the full 180s; anything else
            # at Q1 or Q3 means the clock crop or the quarter read is wrong.
            # ⛔ Logged from the HUD dict the loop ALREADY has - never spend a
            # second capture on it. One screen reader at a time.
            _gc = h.get("game") if h else None
            log(f"    quarter -> Q{q}"
                + (f"  (game clock {_gc}s"
                   + (" - FULL" if _gc >= C.FULL_GAME_CLOCK else "")
                   + ")" if _gc is not None else "  (clock unreadable)"))
            if q == 4:
                g.seen_q4 = True
            # ⛔ Entering Q3 ALWAYS re-arms the chew clock. Halftime resets tempo
            # unconditionally, so this must not depend on whether an earlier
            # attempt succeeded. It is only APPLIED on an offensive playcall, so
            # a Q3 that opens on defense correctly waits.
            if q == 3:
                log("    Q3 -> chew clock re-armed (applies on next offense)")
                g.need_chew = True
            g.quarter = q



        # ⭐ THE Q4 BAIL-OUT. STILL ONE PAUSE PER GAME (`g.intervened` guards it),
        # but armed for the WHOLE of Q4 rather than only the instant it opens.
        #
        # ⛔ Why: these games are routinely LEVEL when Q4 starts - 0-0 has been
        # the normal state at that point - and a tie is not "losing", so a check
        # fired only at the transition disarms itself for the rest of the
        # quarter. The deficit that matters usually appears later.
        #
        # ⛔ And the score is the LEAST reliable read on the screen (see
        # RECORD_AT_LAST_GAME). A single bad frame must not cost 30 minutes of
        # idle farm, so maybe_intervene re-reads before it commits.
        # ⛔⛔ "NOT WINNING", NOT "LOSING". A TIE IS JUST AS DANGEROUS.
        #
        # This is the gap that cost us the first tier-3 game (Sep 13): it sat
        # 0-0 through Q3, Q4 and into sudden-death overtime, and the bail-out
        # never fired because 0-0 is not "losing". Montrell was never asked, the
        # game went to OT, and we lost one of our two tier-3 lives without him
        # knowing it was in danger.
        #
        # ⭐ A tie at the end of regulation goes to sudden death, where one play
        # ends the run. That deserves the same pause a deficit gets.
        #
        # ⭐ And OVERTIME ITSELF QUALIFIES. If we are in OT at all we did not win
        # in regulation, whatever the score reads.
        # ⛔⛔⛔ IN Q4 OR OVERTIME: PAUSE UNLESS WE CAN PROVE WE ARE AHEAD.
        # (Montrell, Sep 13, after losing a run: "If it's tied or about to lose
        # in 4th quarter it needs paused and notified period.")
        #
        # ⛔ THE DEFAULT IS TO PAUSE. Every earlier version required something to
        # be TRUE before pausing - "we are losing", "the opponent score is
        # confirmed" - and each of those requirements failed in the exact games
        # that mattered:
        #   * a 0-0 tie is not "losing", so it sailed through
        #   * in a scoreless game the score NEVER READS, so `opp_confirmed`
        #     stayed False and the check could not fire at all
        # Two tier-3 runs died that way, unwatched.
        #
        # ⭐ So invert it: the only thing that lets the loop play on is POSITIVE
        # PROOF we are winning - a confirmed opponent score AND a lead. Anything
        # else - tied, behind, or unreadable - pauses and notifies.
        #
        # ⛔ An unreadable score therefore PAUSES. That is deliberate: "we cannot
        # tell" is not "we are fine". A needless pause costs 30 minutes and
        # auto-resumes; a missed one costs the run.
        # ⭐⭐ THIRD-QUARTER ALARM: LOSING BY ANY MARGIN.
        # (Sep 16.) The Q4 bail-out is a last chance - by then, in 3-minute
        # quarters, there is often nothing to be done. Catching a deficit in Q3
        # hands him a whole quarter to take over and fix it, which is the
        # difference between a recoverable game and a lost run when one loss
        # ends it.
        # ⛔ Deliberately does NOT set g.intervened: that belongs to the Q4
        # check, and consuming it here would silently disable the last-chance
        # pause for the rest of the game.
        if (C.INTERVENE and C.PAUSE_Q3_IF_LOSING and not g.q3_paused
                and g.quarter == 3 and g.opp_confirmed
                and g.ours < g.theirs):
            g.q3_paused = True
            # ⭐ (Sep 21) TIERS 1-2: DO NOT PAUSE - SWITCH TO THE PASS. Montrell:
            # "when we hit the third-quarter guard instead of pausing the game
            # ... switch to the pass play. Then the Q4 guard can still operate
            # as intended if we are tied or losing." Sticky for the game; the
            # offence picker honours g.q3_pass. Badge unknown -> pause as
            # before (an unknown tier must not skip the alarm).
            _q3_badge = badge_for_tier(CURRENT_TIER) or g.badge or CURRENT_BADGE
            if C.Q3_PASS_ON_ARCADE and _q3_badge == "ARCADE":
                g.q3_pass = True
                log(f"    !! Q3 AND LOSING {g.theirs}-{g.ours} on {_q3_badge} "
                    f"-> {C.OFF_BY_BADGE['COMP']['name']} until we lead, then "
                    f"back to the run (no pause; Q4 guard still armed)")
            else:
                log(f"    !! Q3 AND LOSING {g.theirs}-{g.ours} - checking "
                    f"before pausing (a quarter still left to fix it)")
                _t_q3 = time.time()
                outcome = maybe_intervene(g.theirs, g.ours, log=log)
                if outcome != "declined":
                    g.paused_secs += time.time() - _t_q3
                    last_play_t = time.time()
                    idle, idle_since = 0, None

        if C.INTERVENE and not g.intervened and (g.quarter == 4 or g.overtime):
            # ⛔⛔ OVERTIME ALWAYS PAUSES, WHATEVER THE SCORE SAYS.
            # A game only REACHES overtime by being TIED at the end of Q4, and
            # Montrell's rule is absolute: "If it's tied or about to lose in 4th
            # quarter it needs paused and notified period." On Sep 14 the loop
            # played a 0-0 overtime unattended because a corrupt tally told it
            # it was 8 points up. Overtime is itself proof the game was level,
            # so no score reading can override it.
            #
            # ⛔ And a tally that has ALREADY been proven wrong once cannot be
            # used to decide whether to wake him. Suspect -> pause.
            # ⛔⛔ DO NOT FIRE ON OUR OWN STARTING ZEROS. (Sep 16 - three false
            # pauses in a row.) A Game starts at 0-0, and a RESTART mid-game
            # creates a fresh Game. If we reach Q4 having never actually read a
            # score, "0-0" is not a tie - it is "I have not looked yet" - and
            # pausing on it wakes him for a game he is winning 14-0.
            #
            # `opp_confirmed` only tells us their side was read. Require that we
            # have read a score AT ALL this game before the alarm may speak.
            _never_read = (not g.opp_confirmed and g.ours == 0 and g.theirs == 0)
            # ⛔⛔ BUT "NEVER READ" OVER A WHOLE GAME IS "UNREADABLE", AND
            # UNREADABLE PAUSES. (Sep 18) The reader returned nothing for an
            # entire game (our 0 OCR'd as "U"), this guard waved Q4 through,
            # and the loop played out a 3-0 loss on tier 3 with 1:01 left
            # while Montrell watched it not pause. The guard exists for a
            # RESTART a few plays before Q4 - so it only applies while the
            # game is young. A game with this many plays and no score is a
            # reading failure, and the Sep 16 rule stands: cannot tell = pause.
            if _never_read and g.plays >= C.NEVER_READ_MAX_PLAYS:
                if not getattr(g, "_warned_unreadable", False):
                    g._warned_unreadable = True
                    log(f"    ⛔ Q4 and NO score read in {g.plays} plays - "
                        f"treating the score as UNREADABLE, not as 0-0")
                _never_read = False
                g.score_suspect = True
            if _never_read:
                if not getattr(g, "_warned_noscore", False):
                    g._warned_noscore = True
                    log("    Q4 reached but NO score has ever been read this "
                        "game - not pausing on our own zeros")
            winning = (g.opp_confirmed and (g.ours > g.theirs)
                       and not g.overtime and not g.score_suspect)
            # ⛔ A recent "we are ahead" verdict stands until the score moves.
            # Re-confirming every down costs five captures (~15s) and stalls the
            # play call. Any change in either score clears the cache instantly,
            # so a real collapse is still caught on the very next read.
            if (g.ours, g.theirs) != g.bailout_ok_score:
                g.bailout_ok_until = 0.0
            cached_ok = time.time() < g.bailout_ok_until
            if not winning and not cached_ok and not _never_read:
                why = ("OVERTIME (a tie got us here)" if g.overtime else
                       "SCORE NEVER READ" if _never_read else
                       "SCORE TALLY PROVEN WRONG" if g.score_suspect else
                       "TIED" if g.opp_confirmed and g.ours == g.theirs else
                       "LOSING" if g.opp_confirmed else
                       "SCORE UNREADABLE in Q4")
                log(f"    !! Q4/OT BAIL-OUT ({why}) - checking")
                _t_pause = time.time()
                outcome = maybe_intervene(g.theirs, g.ours, log=log)
                if _G.get("heal"):
                    _t, _o = _G["heal"]
                    log(f"    ⭐ every confirm read agreed {_t}-{_o} - "
                        f"adopting it and clearing the suspect flag")
                    g.theirs, g.ours = _t, _o
                    g.score_suspect = False
                    g.opp_confirmed = True
                    _G["heal"] = None
                if outcome == "declined" and _G["bailout_ok_until"]:
                    g.bailout_ok_until = _G["bailout_ok_until"]
                    g.bailout_ok_score = (g.ours, g.theirs)
                    _G["bailout_ok_until"] = 0.0
                if outcome != "declined":
                    g.paused_secs += time.time() - _t_pause
                # ⛔⛔ A PAUSE IS NOT A STALL. Every watchdog measures elapsed
                # time, and a 30-minute pause looks exactly like 30 minutes of
                # being wedged. On Sep 13 the resume immediately tripped
                # no-play-5min, whose recovery PRESSED MOON THREE TIMES INTO A
                # LIVE Q4 of a tied game, which then tripped unknown-screen-loop
                # and game-stall in turn.
                #
                # Reset the clocks the moment we resume: we were not stuck, we
                # were waiting on a human by design.
                last_play_t = time.time()
                last_game_t = time.time()
                idle, idle_since = 0, None
                stuck_dumped = False
                game_stall_alerted = False
                if outcome != "declined":
                    # Only a real pause consumes the one check per game.
                    g.intervened = True
                    if outcome:
                        log(f"[{stamp()}] === STOPPING: Montrell is taking over ===")
                        return total_plays

        # ⭐ (Sep 25) POLL FAST WHERE IT IS CHEAP. A blank tab band (a live
        # play) is a single pixel scan, and right after a play there is
        # nothing to wait for - the old flat 1.0s cost ~1.5s per play on both
        # sides before the next playcall screen was even noticed.
        _cheap = (name == "NO-TABSTRIP") or (last_play_t >= _t_iter)
        time.sleep(C.LOOP_SLEEP_LIVE if _cheap else C.LOOP_SLEEP)
    return total_plays


def _end_game(g, game_no, menu_secs, stamp, log, reason="postgame"):
    """Log, alert and record a finished game. Returns a fresh Game."""
    secs = max(0.0, (time.time() - g.t0) - g.paused_secs)
    if g.paused_secs:
        log(f"    (excluding {g.paused_secs/60:.1f} min paused for a decision)")
    log(f"[{stamp()}] === GAME {game_no} END ({reason}): "
        f"{g.plays} plays, {secs/60:.1f} min"
        + (f" | between-games {menu_secs:.0f}s" if menu_secs else "") + " ===")
    log(f"    final {g.theirs}-{g.ours} -> {g.result}"
        + ("" if g.opp_confirmed else
           "   ⚠️ opp score NEVER confirmed - result unreliable"))
    if g.result == "L":
        # ⭐ Worded from the event card, not from Air Raid's rules: tiers 3 and 4
        # allow TWO losses here, so a loss is worth waking someone for but is
        # NOT automatically the end of the run.
        _alert_sticky(
            f"GAME {game_no} LOST {g.theirs}-{g.ours}"
            + (f" (badge {g.badge})" if g.badge else "")
            + f" - tiers {'/'.join(str(t) for t in sorted(C.LOSS_LIMIT_TIERS))}"
            f" allow {C.LOSS_LIMIT} losses; check where the event now stands", log)
    elif g.result is None:
        log("    ⚠️ RESULT UNKNOWN from the score (equal boxes, unconfirmed) "
            "- leaving it for the record delta to decide")
    elif g.result == "T":
        log("    ⚠️ TIE - recorded as a tie, not assumed to be a win")
    global LAST_ROW_TS
    LAST_ROW_TS = _record_game(tier=CURRENT_TIER, record=CURRENT_RECORD,
                               badge=g.badge,
                 hud_layout=g.layout, hud_clock_x=g.clock_x,
                 partial=g.partial, first_quarter=g.first_quarter,
                 paused_min=round(g.paused_secs / 60, 1) or None,
                 plays=g.plays, min=round(secs / 60, 1), gap=int(menu_secs),
                 theirs=g.theirs, ours=g.ours, result=g.result,
                 opp_confirmed=g.opp_confirmed, overtime=g.overtime,
                 hike_at=C.HIKE_AT, snap_wait=C.MIN_SNAP_WAIT,
                 # ⭐ Which offence this game was played with - the whole point
                 # of the dive-vs-pass comparison is that these stay separable.
                 offense=g.offense_used, rescue_used=g.rescue_used,
                 q3_pass=g.q3_pass,
                 throw_after=C.OFF_THROW_AFTER)
    global RECORD_AT_LAST_GAME
    RECORD_AT_LAST_GAME = CURRENT_RECORD
    _save_state()
    return Game(joined=False)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _require_calibration(log=print):
    """⛔ REFUSE TO FARM ON UNVERIFIED CROPS.

    Every region in config.py is carried over from a different event. They are
    probably right - the display and the HUD are the same - but "probably the
    same" is the reasoning this project has lost the most hours to. Looking at
    one screen takes two minutes; `calibrate.py verify` does it and writes the
    stamp this checks for.
    """
    if os.environ.get("MUT_EVENT_FORCE") == "1":
        log("  ⚠️ MUT_EVENT_FORCE=1 - running on UNVERIFIED crop regions")
        return True
    if os.path.exists(C.CALIB_FILE):
        try:
            with open(C.CALIB_FILE) as fh:
                d = json.load(fh)
            log(f"  calibration: verified {d.get('ts', '?')}")
            return True
        except (OSError, ValueError):
            pass
    print("REFUSING TO START: the crop regions have not been verified for this "
          "event.\n"
          "  Bring the stream up, get to a playcall screen, and run:\n"
          "      ./calibrate.py verify\n"
          "  Override (not recommended) with MUT_EVENT_FORCE=1.")
    return False


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "loop"
    arg = sys.argv[2] if len(sys.argv) > 2 else None
    if cmd == "loop":
        if not _require_calibration():
            sys.exit(2)
        # ⛔⛔ LIFT EVERY KEY BEFORE THE FIRST PLAY.
        # (Sep 13) A crash inside a hold - the NameError in actions.snap - killed
        # the process with lstick_up + r2 STILL DOWN. Nothing lifted them, so the
        # next run inherited a jammed stick: buttons held with no play running,
        # and a pre-snap menu that could not be driven -> DELAY OF GAME.
        # Montrell watched this happen. Start from a known-neutral pad, always.
        try:
            pad.release()
        except Exception:
            pass
        play_loop(max_plays=int(arg) if arg else 99999,
                  log=functools.partial(print, flush=True))
    elif cmd == "menus":
        print(advance_menus())
    elif cmd == "event":
        print(enter_event())
    elif cmd == "lineup":
        print(actions.choose_lineup())
    elif cmd == "chew":
        print("chew clock:", actions.set_chew_clock())
    elif cmd == "off":
        print(actions.call_offense())
    elif cmd == "def":
        print(actions.call_defense())
    else:
        print(__doc__)
