#!/usr/bin/env python3
"""The event farm loop.

    read the screen -> work out the situation -> act -> repeat

Nothing here is time-based. Play length, penalties, turnovers and possession
changes are all handled by re-reading the screen on every pass. When a read is
not confident, the loop waits: sitting still costs at most a delay of game,
pressing blind can call the wrong play.

Event settings live in config.py, reading in screen.py / hud.py, pressing in
actions.py. This file is the loop and the between-game menus.

    ./grind.py loop [max_plays]   the farm (use farm.sh, which logs it)
    ./grind.py menus|event|lineup|chew|off|def   one step, for testing
"""
import atexit
import functools
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import actions  # noqa: E402
import config as C  # noqa: E402
import hud  # noqa: E402
import pad  # noqa: E402
import screen  # noqa: E402

STOP_FILE = "/tmp/mut-event/stop"


# However we exit (normal return, exception, SIGTERM), lift every key. A crash
# inside a hold otherwise leaves the stick and R2 down on the console.
@atexit.register
def _release_pad_on_exit():
    try:
        pad._remote_post("/release", {}, timeout=5)
    except Exception:
        pass


os.makedirs(C.RUN_DIR, exist_ok=True)
os.makedirs(C.STUCK_DIR, exist_ok=True)

CURRENT_RECORD = None      # the event card's W-L, e.g. "3-0"
CURRENT_BADGE = None       # ARCADE / COMP, read off the HUD during a play
LOSSES_SEEN = None         # last "N/1 LOSSES" count (only used with HALT_ON_ANY_LOSS)

# Set when a screen that only appears after a game (FINISH GAME, RETURN TO HUB,
# the progress screen) is seen. A game is booked only when this is set.
SAW_FINISH_GAME = False
FINAL_SCORE = None         # (theirs, ours) from the end-of-game banner

# The event's own record is the trustworthy result: the in-play score strip
# misreads often. W/L is corrected from the record change between games.
RECORD_AT_LAST_GAME = None
# The row _end_game last wrote. A correction may only ever touch that row.
LAST_ROW_TS = None


# ---------------------------------------------------------------------------
# STATE, HISTORY, ALERTS
# ---------------------------------------------------------------------------

def _save_state():
    try:
        with open(C.STATE_FILE, "w") as fh:
            json.dump({"record": CURRENT_RECORD, "badge": CURRENT_BADGE,
                       "losses_seen": LOSSES_SEEN}, fh)
    except OSError:
        pass


def _load_state():
    global CURRENT_RECORD, CURRENT_BADGE, LOSSES_SEEN
    try:
        with open(C.STATE_FILE) as fh:
            d = json.load(fh)
        CURRENT_RECORD = d.get("record")
        CURRENT_BADGE = d.get("badge")
        LOSSES_SEEN = d.get("losses_seen")
    except (OSError, ValueError):
        pass


_load_state()


def _parse_record(rec):
    try:
        w, l = rec.split("-")
        return int(w), int(l)
    except (AttributeError, ValueError):
        return None


def _patch_last_result(result, why, log=print):
    """Rewrite the result of the row this loop last wrote, and no other."""
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
        log(f"    CORRECTING last game: {last.get('result')} -> {result} ({why})")
        last["result"] = result
        last["result_source"] = "event record"
        last["result_was"] = f"{last.get('theirs')}-{last.get('ours')}"
        rows[-1] = json.dumps(last) + "\n"
        with open(C.HISTORY, "w") as fh:
            fh.writelines(rows)
    except (OSError, ValueError) as e:
        log(f"    ! could not correct last result: {e}")


def _record_game(**row):
    """Append one completed game to the history file. Returns its timestamp.

    The JSONL history is append-only and survives restarts; the log does not.
    A score the validators would reject is written as null, never as a number.
    """
    row.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S"))
    row.setdefault("date", time.strftime("%Y-%m-%d"))
    for k in ("ours", "theirs"):
        v = row.get(k)
        if v is not None and (v < 0 or v > C.SCORE_MAX
                              or (v == 1 and not C.ALLOW_SCORE_OF_ONE)):
            row[k + "_rejected"] = v
            row[k] = None
    row.setdefault("record", CURRENT_RECORD)
    try:
        with open(C.HISTORY, "a") as fh:
            fh.write(json.dumps(row) + "\n")
    except OSError:
        pass
    return row["ts"]


def _alert(msg, log=print):
    """A clearable alert file a human or a watcher can poll for."""
    try:
        with open(C.ALERT_FILE, "w") as fh:
            fh.write(f"{time.strftime('%H:%M:%S')}  {msg}\n")
    except OSError:
        pass
    log(f"    !!!! ALERT: {msg}")


def _alert_sticky(msg, log=print):
    """An alert only a human clears (health.sh reports each new line)."""
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


def _halt(reason, log=print):
    """Stop the farm and leave a HALT file that farm.sh refuses to start over."""
    try:
        with open(C.HALT_FILE, "w") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {reason}\n")
    except OSError:
        pass
    log(f"    HALT: {reason}")
    _alert_sticky(f"FARM STOPPED - {reason}", log)


def dump_stuck(tag, log=print):
    """Save a screenshot and the screen's OCR text when the loop cannot proceed."""
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
# BETWEEN GAMES
# ---------------------------------------------------------------------------
# These screens have no clock pressure, so they are identified by full-screen
# OCR text rather than by pixel geometry.

def _has(txt, *needles):
    return all(n.upper() in txt for n in needles)


def enter_event(log=print, tries=18):
    """From the events list, find our event card by its text and press X.

    Never by list position: EA reorders the list, and X on the wrong card
    enters a different mode.
    """
    global CURRENT_RECORD, RECORD_AT_LAST_GAME
    if not C.EVENT_MATCH:
        _alert_sticky("EVENT_MATCH is not set - cannot pick the event card. "
                      "Run `calibrate.py event` and set it in config.py.", log)
        return False
    for _ in range(tries):
        txt = screen.screen_text()
        for m in re.finditer(C.EVENT_MATCH, txt, re.I):
            title = txt[m.start():m.start() + C.EVENT_TITLE_WINDOW]
            if any(re.search(bad, title, re.I) for bad in C.EVENT_REJECT):
                log(f"    events: skipping sibling card {title[:40]!r}")
                continue
            if not all(req.upper() in title.upper() for req in C.EVENT_REQUIRE):
                continue
            # The card's button follows its description (~250 chars), so look
            # for it within 900 chars of the title, not on the whole screen.
            window = txt[m.start():m.start() + 900]
            if not any(k in window for k in ("START", "CONTINUE", "FINISH EVENT")):
                continue
            # The record is printed on the card once it is non-zero. Search
            # after OUR title: other cards carry their own records.
            r = re.search(r"RECORD\s*:?\s*(\d+)\s*[-–—]\s*(\d+)", window)
            new_rec = f"{r.group(1)}-{r.group(2)}" if r else None
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
                if C.HALT_ON_ANY_LOSS and after[1] > before[1]:
                    _halt(f"LOSS ({RECORD_AT_LAST_GAME} -> {new_rec}). Farm "
                          f"STOPPED before entering another game.", log)
                    return False

            RECORD_AT_LAST_GAME = new_rec
            CURRENT_RECORD = new_rec
            _save_state()
            log(f"    events: {C.EVENT_LABEL} selected"
                + (f" (record {CURRENT_RECORD})" if CURRENT_RECORD else ""))
            pad.press("cross", hold=0.06)
            time.sleep(2.5)
            return True
        # Our card is not on screen yet: scroll and look again. Never press
        # cross on whatever happens to be focused.
        pad.press("down", hold=0.06)
        time.sleep(0.9)
    dump_stuck("enter_event", log)
    _alert_sticky("could not find our event card in the events list", log)
    return False


def _progress_screen(txt, log):
    """The event progress screen ("x/1 LOSSES", "x/10 WINS"). It only appears
    after a game, so it is a game boundary. Returns False to stop the loop."""
    global SAW_FINISH_GAME, LOSSES_SEEN
    if re.search(r"\d\s*/\s*\d+\s*WINS", txt) and "LOSSES" in txt:
        if not SAW_FINISH_GAME:
            log("    progress screen = game boundary (no RETURN TO HUB was shown)")
        SAW_FINISH_GAME = True
    if "YOUR REWARDS" in txt:
        try:
            d = f"{C.RUN_DIR}/rewards"
            os.makedirs(d, exist_ok=True)
            pad.shot(None, f"{d}/{time.strftime('%H%M%S')}.png")
            log("    [reward screen captured for review]")
        except Exception:
            pass
    m_loss = re.search(r"(\d)\s*/\s*(\d)\s*LOSS", txt)
    if m_loss and C.HALT_ON_ANY_LOSS:
        # This is the last screen before the next game starts, so it is where
        # a loss has to be caught. LOSSES_SEEN is persisted so that restarting
        # after a halt does not halt again on the same loss.
        n = int(m_loss.group(1))
        if n > (LOSSES_SEEN or 0):
            LOSSES_SEEN = n
            _save_state()
            _halt(f"LOSS - progress screen reads {m_loss.group(0)}. Farm "
                  f"STOPPED before entering another game. To play on (a fresh "
                  f"run): rm {C.HALT_FILE} and ./farm.sh", log)
            return False
        LOSSES_SEEN = n
        _save_state()
    elif m_loss and LOSSES_SEEN is not None:
        LOSSES_SEEN = None
        _save_state()
    log(f"    rewards/progress -> advancing  |RAW| {txt[:160]}")
    for _ in range(2):
        pad.press("cross", hold=0.06)
        time.sleep(0.7)
    return True


def advance_menus(log=print, tries=25):
    """Walk postgame -> hub -> event -> entry options -> back into a game.

    Returns True once a playcall screen is up again.
    """
    global SAW_FINISH_GAME, FINAL_SCORE
    unknown_presses = 0
    loading_waits = 0
    # Start from a neutral pad: a key-up lost to a focus change would otherwise
    # scroll every menu below.
    try:
        pad.release()
    except Exception:
        pass
    for _ in range(tries):
        side, _i, _name, ratio = screen.read_both()
        if side is not None and ratio >= C.CONFIDENT:
            try:
                _q, _g, ps = screen.read_clocks()
            except Exception:
                ps = None
            if ps is not None:
                log(f"    playcall screen is back (play clock :{ps})")
                if ps <= 6:
                    log(f"    ! only {ps}s of play clock at handover - a delay "
                        f"of game may be unavoidable")
            else:
                log("    playcall screen is back")
            return True

        txt = screen.screen_text()
        if not txt:
            time.sleep(1.5)
            continue

        if _has(txt, "FINISH GAME"):
            # Madden's own end-of-game menu. Record the boundary and the banner
            # score before pressing anything.
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
            # This event's usual game boundary (not on the pause menu).
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
            ok, detail = actions.choose_lineup(log=log)
            if not ok:
                dump_stuck("entry-options", log)
                _alert_sticky(
                    f"ENTRY OPTIONS: could not confirm the {C.LINEUP_WANT} "
                    f"lineup ({detail}). NOT entering. Screen dumped to "
                    f"{C.STUCK_DIR}.", log)
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
            # MUT hub, PLAY tab: down into the tile row, right to EVENTS.
            log("    MUT hub -> EVENTS")
            pad.press("down", hold=0.06)
            time.sleep(0.6)
            pad.press("right", hold=0.06)
            time.sleep(0.6)
            pad.press("cross", hold=0.06)
            time.sleep(2.0)

        elif _has(txt, "CHIAKI-NG") or _has(txt, "REFRESH PSN HOSTS"):
            # The stream dropped to chiaki's host list. Restart it; never press
            # into the chiaki UI.
            log("    chiaki dropped -> restarting stream")
            try:
                pad.restart_stream()
            except Exception as e:
                log(f"    ! stream restart failed: {e}")
            time.sleep(6.0)

        elif any(k in txt for k in ("YOUR REWARDS", "YOUR PROGRESS", "ADVANCE",
                                    "SCROLL REWARDS", "OBJECTIVE PROGRESS")):
            if not _progress_screen(txt, log):
                return False

        elif len(txt) < 45 or (len(txt) < 140
                               and any(k in txt for k in ("EASPORTS", "MADDEN",
                                                          "SPORTS"))):
            # Loading / transition: almost no text. Wait, never press. The
            # length bound matters: "SPORTS" also appears in the watermark on
            # real screens.
            loading_waits += 1
            # A frozen chiaki feed looks exactly like a static loading screen.
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
            # Unknown screen: back out with circle, never cross. Cross confirms
            # and walks deeper into menus (My Team, packs...).
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
# PER-GAME STATE AND THE SCORE
# ---------------------------------------------------------------------------

class Game:
    """Per-game state, replaced wholesale at every game boundary."""

    def __init__(self, joined=False):
        # `joined`: the loop attached to a game already in progress (every
        # restart does). Its result is real; its duration is not comparable, so
        # it is recorded as partial and excluded from pace statistics.
        self.joined = joined
        self.partial = joined
        self.t0 = time.time()
        self.plays = 0
        self.theirs = 0
        self.ours = 0
        self.since_theirs = 0    # plays since each side last read acceptably
        self.since_ours = 0
        self.opp_confirmed = False   # the opponent's score has read at least once
        self.pend = {}           # an out-of-range value awaiting repeats
        self.contra = {}         # a lower value awaiting repeats
        self.score_suspect = False   # our tally has been corrected once
        self.quarter = None
        self.first_quarter = None
        self.seen_q4 = False     # overtime is only possible after Q4
        self.overtime = False
        self.badge = None
        self.need_chew = True    # the chew-clock tempo must be (re-)set
        self.fbd_slow = False    # the hybrid dive is on its short run
        self.skips = 0           # consecutive deliberate no-snaps
        self.layout = None       # broadcast presentation, recorded only
        self.clock_x = None
        self.offense_used = None

    @property
    def result(self):
        """W / L / T from the score, or None when the score cannot carry it.
        Equal scores are the most common misread, so a tie needs a confirmed,
        never-corrected score. The event record fixes it up afterwards."""
        if self.ours > self.theirs:
            return "W"
        if self.ours < self.theirs:
            return "L"
        if self.opp_confirmed and not self.score_suspect:
            return "T"
        return None


def _accept_score(g, which, value, log):
    """Validate one side's score before believing it. Returns True to accept.

    - Nothing above SCORE_MAX, and 1 only if ALLOW_SCORE_OF_ONE.
    - A LOWER value (points can be stolen in this event) needs SCORE_CONTRADICT
      identical reads in a row; the tally is then marked suspect.
    - A jump larger than plausible for the plays since the last read needs 3
      identical reads, and a far larger one is never accepted.
    """
    if value == 1 and not C.ALLOW_SCORE_OF_ONE:
        log(f"    ! REJECTED {which} score 1 - impossible in football")
        return False
    if value > C.SCORE_MAX:
        log(f"    ! REJECTED {which} score {value} - above {C.SCORE_MAX}, "
            f"not a football score")
        return False
    have = g.theirs if which == "theirs" else g.ours
    since = g.since_theirs if which == "theirs" else g.since_ours

    if value < have:
        k = which + "_lower"
        if g.contra.get(k) == value:
            g.contra[k + "_n"] = g.contra.get(k + "_n", 0) + 1
        else:
            g.contra[k], g.contra[k + "_n"] = value, 1
        if g.contra[k + "_n"] >= C.SCORE_CONTRADICT:
            log(f"    !! {which} score read as {value} "
                f"{g.contra[k + '_n']}x in a row while we hold {have} - "
                f"OUR VALUE WAS WRONG, correcting to {value}")
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
        slack = room + C.SCORE_JUMP_MAX * 2
        if value - have > slack:
            log(f"    !! REJECTED {which} score {value} as IMPOSSIBLE "
                f"(was {have}, {since} plays ago, max plausible {slack})")
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


# ---------------------------------------------------------------------------
# THE LOOP
# ---------------------------------------------------------------------------

def _special_teams(stamp, log):
    """4th down / kickoff screen. Returns (snapped, status, hint).

    Kickoffs are taken normally. On 4th down the loop never punts and never
    kicks a field goal (GO_FOR_IT_ON_FOURTH): it goes back to the offensive
    FAVORITES and runs the play.
    """
    try:
        sttxt = (screen.screen_text() or "").upper()
    except Exception:
        sttxt = ""
    kick_screen = "KICKOFF" in sttxt or "ONSIDE" in sttxt
    fourth_down = ("PUNT" in sttxt or "FIELD GOAL" in sttxt) and not kick_screen
    if not (fourth_down and C.GO_FOR_IT_ON_FOURTH):
        return actions.call_special_teams(log=log)

    if not actions.goto_tab("offense", C.OFF_TAB):
        # Never fall back to a kick: look again on the next pass.
        return False, "4th down: could not reach FAVORITES - retrying", 0.5
    log(f"[{stamp()}]   4th down: going for it -> {C.OFFENSE['name']}")
    pad.press(C.OFFENSE["button"], hold=C.OFF_SELECT_HOLD)
    snapped, status, hint = actions.chew_and_hike(
        C.OFFENSE["run_seq"], log=log, allow_skip=False, chew=False)
    return snapped, f"4TH DOWN GO - {status}", hint


def play_loop(max_plays=99999, log=print):
    global CURRENT_BADGE, SAW_FINISH_GAME, FINAL_SCORE
    t_run = time.time()
    g = Game(joined=True)      # the first game of any start is one we joined
    game_no = 1
    total_plays = 0
    idle_since = None
    _t_slow = _t_console = _t_waitlog = 0.0
    dead_t0 = None
    last_play_t = time.time()
    ever_played = False        # has a playcall screen been seen at all
    last_game_t = time.time()
    stuck_dumped = False
    game_stall_alerted = False
    last_situation = None
    same_situation = 0
    last_clock = None

    def stamp():
        el = int(time.time() - t_run)
        return f"{el // 60:02d}:{el % 60:02d}"

    log(f"[{stamp()}] === FARM START ===  "
        f"chew={'ON @ :%d' % C.HIKE_AT if C.HIKE_AT < 99 else 'OFF'}"
        f"  snap_floor={C.MIN_SNAP_WAIT}s")
    log(f"           offense={C.OFFENSE['name']} (short run at +{C.FBD_SLOW_LEAD})"
        f"  defense={C.DEF_PLAY_NAME}")

    while total_plays < max_plays:
        # Stop requests (farm.sh stop) are honoured between plays, never
        # mid-play: a kill between the snap and the run leaves the down to the
        # CPU.
        if os.path.exists(STOP_FILE):
            try:
                os.remove(STOP_FILE)
            except OSError:
                pass
            log(f"[{stamp()}]   STOP requested -> exiting at a play boundary")
            return total_plays
        if os.path.exists(C.HALT_FILE):
            log(f"[{stamp()}]   HALT file present -> exiting the loop")
            return total_plays

        _t_iter = time.time()
        side, i, name, ratio = screen.read_both()

        # FROZEN FEED. Only trusted while a game is live (menus are static),
        # and confirmed once more before paying for a stream restart.
        in_play_recently = (ever_played
                            and (time.time() - last_play_t) < C.FROZEN_ONLY_WITHIN)
        if in_play_recently and screen.FROZEN_STREAK >= C.FROZEN_RESTART:
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
                    f"frames - NOT restarting")
                continue
            log(f"[{stamp()}]   FROZEN FEED ({screen.FROZEN_STREAK} identical "
                f"frames) -> restarting chiaki")
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
            if idle_since is None:
                idle_since = time.time()
            idle_secs = time.time() - idle_since
            if time.time() - _t_waitlog >= 20:
                _t_waitlog = time.time()
                log(f"  ... waiting ({name}, ratio {ratio:.2f})")

            # Console reachability: the one failure a screen cannot show.
            if time.time() - _t_console >= 40:
                _t_console = time.time()
                if not screen.console_up():
                    dump_stuck("console-offline", log)
                    _alert_sticky("PS5 UNREACHABLE - console likely powered off",
                                  log)
                    time.sleep(30)
                    continue

            # A loop that keeps pressing but never finishes a game.
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
                idle_since = None
                continue

            # A playcall sub-screen: the action bar is there but the tab strip
            # is genuinely absent (not just a marginal read). "NO-TABSTRIP"
            # means a live play, which needs no checks.
            if name != "NO-TABSTRIP":
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
                        idle_since = None
                        continue

            # Full-screen OCR, rate-limited.
            if time.time() - _t_slow >= C.SLOW_PATH_EVERY:
                _t_slow = time.time()
                txt = screen.screen_text()
                # If chiaki is not frontmost the daemon captures the Mac
                # desktop, and every press would go to whatever app has focus.
                if screen.looks_like_mac(txt):
                    dump_stuck("mac-desktop", log)
                    _alert_sticky(
                        "CAPTURING THE MAC DESKTOP, NOT THE PS5 - chiaki is not "
                        "frontmost. STOPPING: every press would go to whatever "
                        "app has focus. Bring chiaki back up, then restart.", log)
                    log(f"[{stamp()}] === ABORTING: not looking at the console ===")
                    return total_plays
                # A visible play clock off the playcall screen means a play is
                # selected at the line and nobody has snapped it.
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
                    idle_since = None
                    last_play_t = time.time()
                    continue

                if "ACCEPT" in txt and "DECLINE" in txt:
                    # A defensive penalty on our drive: a first down keeps the
                    # ball and the clock running.
                    log(f"[{stamp()}]   penalty prompt -> ACCEPT (cross)")
                    pad.press("cross", hold=0.06)
                    time.sleep(2.0)
                    idle_since = None
                    continue
                if any(k in txt for k in ("FINISH GAME", "RETURN TO HUB",
                                          "YOU WON", "YOU LOST",
                                          "POST GAME SUMMARY", "YOUR REWARDS",
                                          "SELECT GAME MODE", "ENTRY OPTIONS")):
                    log(f"[{stamp()}]   postgame detected -> menu handling")
                    idle_secs = 999
                    dead_t0 = time.time()

            if idle_secs >= 45:
                if dead_t0 is None:
                    log(f"[{stamp()}]   no playcall for 45s -> menu handling")
                    dead_t0 = time.time()
                got = advance_menus(log=log)
                menu_secs = time.time() - (dead_t0 or idle_since)
                dead_t0 = None
                if got:
                    # The game ended only if an end-of-game screen was seen.
                    # A long cutscene is not a game boundary.
                    if SAW_FINISH_GAME and g.plays > 0:
                        if FINAL_SCORE:
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
                idle_since = None
                continue
            time.sleep(1.0)
            continue

        # -------------------------------------------------------------------
        # ON A PLAYCALL SCREEN
        # -------------------------------------------------------------------
        idle_since = None
        last_play_t = time.time()
        ever_played = True
        stuck_dumped = False

        log(f"[{stamp()}] [{total_plays + 1}] {side.upper():13s} "
            f"tab={name:<10s} ratio={ratio:.2f}")

        if side == "specialteams":
            snapped, status, hint = _special_teams(stamp, log)
        elif side == "offense":
            # The chew-clock tempo: first offensive play of Q1 and of Q3. Not
            # in overtime, where the clock running out on a tie is a loss.
            if g.need_chew and not g.overtime and C.CHEW_SET_TEMPO:
                got = actions.set_chew_clock(log=log)
                log(f"    chew clock {'SET' if got else 'FAILED'}")
                g.need_chew = not got

            play = C.OFFENSE
            # Hybrid dive: short run while CONFIRMED ahead by FBD_SLOW_LEAD.
            if C.FBD_SLOW_LEAD:
                slow = (g.opp_confirmed
                        and (g.ours - g.theirs) >= C.FBD_SLOW_LEAD)
                if slow != g.fbd_slow:
                    g.fbd_slow = slow
                    log(f"    HYBRID DIVE: lead {g.ours - g.theirs:+d} -> "
                        + ("SHORT run (hold stops early)" if slow
                           else "FULL run"))
                if slow:
                    play = dict(play, run_seq=dict(C.FBD_SLOW_RUN))
            g.offense_used = play["name"]
            # No quarter-end skipping after four in a row, and none in OT.
            snapped, status, hint = actions.call_offense(
                known=i, log=log,
                allow_skip=(g.skips < 4) and not g.overtime,
                chew=not g.overtime, play=play)
        else:
            snapped, status, hint = actions.call_defense(known=i, log=log)
        log(f"    {status}")

        if not snapped:
            # A deliberate no-snap or a failed navigation: no play spent.
            g.skips += 1
            time.sleep(max(1.0, hint))
            continue
        g.skips = 0

        # REPEATED-SITUATION STALL: plays are being called but nothing moves.
        # Reset below whenever the game clock changes (a long drive is not a
        # freeze).
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
                f"works, play calling does not); quit the game by hand.", log)
            log(f"[{stamp()}] === ABORTING: game frozen ===")
            return total_plays

        total_plays += 1
        g.plays += 1
        g.since_ours += 1
        g.since_theirs += 1

        # -------------------------------------------------------------------
        # POST-SNAP READS, in the dead time while the play runs.
        # -------------------------------------------------------------------
        # The ARCADE/COMP badge only renders during a live play. Logged only.
        if g.badge is None and side == "offense":
            g.badge = screen.read_tier_badge()
            if g.badge:
                CURRENT_BADGE = g.badge
                _save_state()
                log(f"    badge: {g.badge}")

        # One HUD capture gives score, quarter, clocks and presentation.
        want_hud = ((g.quarter or 1) >= 3) or (g.plays % C.SCORE_EVERY == 0)
        h = screen.read_hud_full() if want_hud else None
        # From Q3, a stat ticker can cover the score right after the snap.
        tries = 0
        while (h is not None and h.get("theirs") is None
               and (g.quarter or 1) >= 3 and tries < C.SCORE_TICKER_RETRIES):
            tries += 1
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

        if not g.overtime and g.seen_q4 and g.plays > 4:
            if screen.read_is_overtime():
                g.overtime = True
                log("    !! OVERTIME - sudden death, clock burning is off")

        q = h.get("quarter") if h else None
        if h and h.get("game") is not None:
            if last_clock is not None and h["game"] != last_clock:
                same_situation = 0
            last_clock = h["game"]

        if q is not None and g.first_quarter is None:
            g.first_quarter = q
            if q != 1:
                g.partial = True
                log(f"    ! joined this game already in Q{q} - timing is NOT "
                    f"comparable, recording it as partial")
            elif g.joined and h and h.get("game") is not None \
                    and h["game"] >= C.FULL_GAME_CLOCK:
                # Joined, but at Q1 with a near-full clock: nothing was missed.
                g.partial = False
                g.joined = False
                log(f"    started from Q1 with {h['game']}s on the clock - "
                    f"counting this as a FULL game")

        # Quarters only go 1 -> 2 -> 3 -> 4. Q4 back to Q1 with a full clock is
        # a new game (a backstop for a missed postgame); any other jump or step
        # back is a down misread as a quarter.
        _q1_clock = (h or {}).get("game")
        if (q == 1 and g.quarter == 4 and g.plays > 0
                and _q1_clock is not None and _q1_clock >= C.FULL_GAME_CLOCK):
            g = _end_game(g, game_no, 0, stamp, log, reason="quarter reset")
            game_no += 1
            last_game_t = time.time()
            game_stall_alerted = False
        elif (q and q != g.quarter and g.quarter is not None
                and q > g.quarter + 1):
            log(f"    ! IGNORED quarter Q{q} - cannot jump from "
                f"Q{g.quarter} (almost certainly a 4TH-down misread)")
        elif (q and g.quarter is not None and q < g.quarter
                and not (q == 1 and g.quarter in (3, 4))):
            log(f"    ! IGNORED quarter Q{q} - cannot go BACKWARDS from "
                f"Q{g.quarter} (almost certainly a down misread)")
        elif q and q != g.quarter:
            _gc = h.get("game") if h else None
            log(f"    quarter -> Q{q}"
                + (f"  (game clock {_gc}s"
                   + (" - FULL" if _gc >= C.FULL_GAME_CLOCK else "")
                   + ")" if _gc is not None else "  (clock unreadable)"))
            if q == 4:
                g.seen_q4 = True
            if q == 3:
                # Halftime resets the tempo; set it again on the next offence.
                log("    Q3 -> chew clock re-armed (applies on next offense)")
                g.need_chew = True
            g.quarter = q

        # Poll fast during a live play (a cheap pixel scan) and right after one.
        _cheap = (name == "NO-TABSTRIP") or (last_play_t >= _t_iter)
        time.sleep(C.LOOP_SLEEP_LIVE if _cheap else C.LOOP_SLEEP)
    return total_plays


def _end_game(g, game_no, menu_secs, stamp, log, reason="postgame"):
    """Log, alert and record a finished game. Returns a fresh Game."""
    global LAST_ROW_TS, RECORD_AT_LAST_GAME
    secs = time.time() - g.t0
    log(f"[{stamp()}] === GAME {game_no} END ({reason}): "
        f"{g.plays} plays, {secs/60:.1f} min"
        + (f" | between-games {menu_secs:.0f}s" if menu_secs else "") + " ===")
    log(f"    final {g.theirs}-{g.ours} -> {g.result}"
        + ("" if g.opp_confirmed else
           "   ! opp score NEVER confirmed - result unreliable"))
    if g.result == "L":
        # From the score reader, which misreads. The progress screen's
        # "x/1 LOSSES" is the truth: check it.
        _alert_sticky(f"GAME {game_no} LOST {g.theirs}-{g.ours} by the score "
                      f"reader - check the progress screen / event record", log)
    elif g.result is None:
        log("    ! RESULT UNKNOWN from the score - leaving it for the record "
            "change to decide")
    elif g.result == "T":
        log("    ! TIE - recorded as a tie, not assumed to be a win")
    LAST_ROW_TS = _record_game(
        record=CURRENT_RECORD, badge=g.badge,
        hud_layout=g.layout, hud_clock_x=g.clock_x,
        partial=g.partial, first_quarter=g.first_quarter,
        plays=g.plays, min=round(secs / 60, 1), gap=int(menu_secs),
        theirs=g.theirs, ours=g.ours, result=g.result,
        opp_confirmed=g.opp_confirmed, overtime=g.overtime,
        hike_at=C.HIKE_AT, snap_wait=C.MIN_SNAP_WAIT,
        offense=g.offense_used)
    RECORD_AT_LAST_GAME = CURRENT_RECORD
    _save_state()
    return Game(joined=False)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _require_calibration(log=print):
    """Refuse to farm on crop regions nobody has checked on this setup."""
    if os.environ.get("MUT_EVENT_FORCE") == "1":
        log("  ! MUT_EVENT_FORCE=1 - running on UNVERIFIED crop regions")
        return True
    if os.path.exists(C.CALIB_FILE):
        try:
            with open(C.CALIB_FILE) as fh:
                d = json.load(fh)
            log(f"  calibration: verified {d.get('ts', '?')}")
            return True
        except (OSError, ValueError):
            pass
    print("REFUSING TO START: the crop regions have not been verified.\n"
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
        # Start from a known-neutral pad: a previous crash may have left keys down.
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
