#!/usr/bin/env python3
"""Everything that PRESSES A BUTTON. Reading lives in screen.py.

⛔ THE RULE EVERY FUNCTION HERE OBEYS: never trust a press count. The playcall
tab resets to COACH SUGGESTIONS after every play and every penalty, and
individual L1/R1 presses drop. A fixed number of presses is wrong twice over.
Press, re-read, and confirm the screen actually got there.

⛔ A log line saying a button was pressed proves it was SENT, not received.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C  # noqa: E402
import pad  # noqa: E402
import screen  # noqa: E402


# ---------------------------------------------------------------------------
# PLAYCALL NAVIGATION
# ---------------------------------------------------------------------------

def wait_for_playcall(side=None, timeout=45):
    """Block until a playcall screen is genuinely up. Presses NOTHING.

    Time between plays is dynamic - it depends entirely on how long the play
    took - so the loop must watch for the screen rather than sleep a guessed
    number of seconds.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        got, i, name, ratio = screen.read_both()
        if got is not None and ratio >= C.CONFIDENT and (side in (None, got)):
            return got, name
        time.sleep(1.0)
    return None, None


def goto_tab(side, target_name, tries=3, known=None):
    """Press L1/R1 until `target_name` is genuinely the active tab.

    `known` is the tab index the CALLER just read. Re-reading here costs a full
    capture out of a ~15s playcall clock for information we already have, so the
    first pass uses it and we pay for ONE verification instead of one per step.
    """
    names = screen.tab_names(side)
    if target_name not in names:
        return False
    target = names.index(target_name)
    n = len(names)
    for _ in range(tries):
        if known is not None:
            i, ratio, seen = known, 9.9, side
            known = None
        else:
            seen, i, _name, ratio = screen.read_both()
        if seen != side or ratio < C.CONFIDENT:
            # Not on this playcall screen (mid-play, replay, cutscene). WAIT.
            # ⛔ Pressing here is what put the old build on the wrong play twice.
            time.sleep(1.5)
            continue
        if i == target:
            return True
        # Shortest wrapped path, sent as ONE daemon call. Re-reading after every
        # single press cost ~1.5s each and blew the play clock; the loop still
        # catches dropped presses because it re-reads before giving up.
        right = (target - i) % n
        left = (i - target) % n
        btn, count = ("r1", right) if right <= left else ("l1", left)
        pad.press_many([btn] * count, hold=0.06, gap=0.16)
        time.sleep(0.35)
    return False


# ---------------------------------------------------------------------------
# TEMPO: THE CHEW CLOCK
# ---------------------------------------------------------------------------

def set_tempo(target="CHEW", tries=5, log=print):
    """R3 -> step TEMPO to `target` (VERIFIED) -> circle back.

    Only ever call this on an OFFENSIVE playcall screen: tempo is an offensive
    setting and the menu is not reachable on defense. Needed at the start of Q1
    and again at Q3, because halftime resets it.

    ⛔ NOT a blind press. From NORMAL it is one LEFT, but if the value is
    already CHEW CLOCK a blind LEFT walks PAST it.

    ⛔⛔ NO HUDDLE IS THE OPPOSITE OF WHAT WE WANT AND IT IS ONE STEP AWAY. The
    values are CHEW CLOCK / NORMAL / NO HUDDLE and the list WRAPS, so one extra
    LEFT lands on NO HUDDLE - which speeds the game up and adds plays. The old
    build once logged "chew clock SET" while the console sat on NO HUDDLE,
    because a STALE frame read NORMAL after the value had already moved. Hence:
    fresh reads, and TWO of them must agree.
    """
    pad.press("r3", hold=0.10)
    time.sleep(1.3)

    # Prove the panel actually opened before pressing anything. If R3 did not
    # register we are still on the playcall screen, where blind LEFT presses
    # scroll the play grid - that cost a play the first time this ran.
    if "TEMPO" not in screen.tempo_label():
        pad.press("moon", hold=0.06)
        time.sleep(0.6)
        return False

    ok = False
    val = ""
    for _ in range(tries):
        val = screen.tempo_value()
        if target in val:
            time.sleep(0.4)
            if target in screen.tempo_value():     # a second, independent read
                ok = True
                break
        pad.press("left", hold=0.06)
        time.sleep(0.9)                            # settle before reading again
    if not ok:
        log(f"    ! tempo NOT set to {target} (last read: {val!r})")
    pad.press("moon", hold=0.06)
    time.sleep(0.9)
    return ok


def set_chew_clock(tries=5, log=print):
    """Tempo -> CHEW CLOCK. Burns game clock to protect a lead."""
    return set_tempo("CHEW", tries=tries, log=log)


def clear_chew_clock(tries=5, log=print):
    """Tempo -> NORMAL. Give the clock back when the lead is gone.

    ⛔⛔ (Sep 13) Nothing ever walked tempo BACK. set_chew_clock was a one-way
    door: once CHEW CLOCK was on it stayed on for the whole half, so a lead that
    evaporated left us still burning the clock we now needed to score with -
    the exact opposite of the intent.

    ⛔ NORMAL sits between CHEW CLOCK and NO HUDDLE in a list that WRAPS, so this
    must step-and-verify like set_chew_clock does. One blind LEFT too many lands
    on NO HUDDLE. Do not turn this into a blind press.
    """
    return set_tempo("NORMAL", tries=tries, log=log)


# ---------------------------------------------------------------------------
# THE SNAP
# ---------------------------------------------------------------------------
# Returns (snapped: bool, status: str, wait_hint: float).
# `snapped` False means we deliberately did NOT spend a play - the caller must
# not count it, and should sleep `wait_hint` seconds before looking again.

_LAST_RUN_END = 0.0     # when the last stick+sprint hold finished


def _play_clock_counting(gap=0.8):
    """True if the PLAY CLOCK is still COUNTING DOWN - i.e. the ball never went
    live. Two reads `gap` seconds apart; a lower second value means pre-snap.

    ⛔⛔ "A visible play clock means pre-snap" is FALSE. (Sep 18, seen on a
    frame: 1.8s after a snap at :04 the receiver is running with the ball and
    the HUD still shows ":03" in red - it FREEZES at the snap and stays up.)
    That gate refused the run on every play of a game. The frozen-vs-counting
    tell survives video latency because both frames carry the same delay.
    Any read failure -> False: the other gates decide, and they fail closed."""
    try:
        import hud
        ts = time.strftime("%H%M%S")
        pa = f"{C.RUN_DIR}/run-gate-{ts}-a.png"
        pb = f"{C.RUN_DIR}/run-gate-{ts}-b.png"
        t0 = time.time()
        a = hud.read_clocks_fast(path=pa)["play"]
        if a is None:
            return False
        time.sleep(max(0.0, gap - (time.time() - t0)))
        b = hud.read_clocks_fast(path=pb)["play"]
        counting = b is not None and b < a
        if counting:
            # ⭐ Keep the evidence. A refusal is either a swallowed snap or a
            # misread, and only the two frames can say which. (Sep 18.)
            for src, dst in ((pa, f"{C.RUN_DIR}/run-refused-{ts}-a-{a}.png"),
                             (pb, f"{C.RUN_DIR}/run-refused-{ts}-b-{b}.png")):
                try:
                    os.replace(src, dst)
                except OSError:
                    pass
        else:
            for src in (pa, pb):
                try:
                    os.remove(src)
                except OSError:
                    pass
        return counting
    except Exception:
        return False


def run_phase(log=print, tag="", after_throw_at=None):
    """Stick UP + SPRINT, bounded to the live play. Returns a status suffix.

    ⛔⛔ ONLY EVER AFTER A THROW. (Sep 18, Montrell: "we need controls in place
    to make sure it only ever fires after we've thrown the ball.") The caller
    must pass the wall-clock instant of the throw press; anything else, or a
    stale one, is refused here regardless of what the caller thinks it is
    doing. This is the structural half. The screen gates below are the other.

    ⛔⛔ SHARED BY THE PASS AND THE DIVE ON PURPOSE. Montrell asked for the same
    3s sprint on the fullback dive; copying the block would mean two places to
    forget the gate and the chunking, and the gate is the whole reason stick
    input stopped landing in menus.
    """
    global _LAST_RUN_END
    if not (C.OFF_RUN_HOLD and C.OFF_RUN_STICK and C.OFF_RUN_SPRINT):
        return ""
    if after_throw_at is None or (time.time() - after_throw_at) > C.RUN_MAX_AGE:
        log("    ⛔ run refused - not directly after a throw "
            f"(after_throw_at={after_throw_at}) - no stick input")
        return " (run refused - no throw)"

    # ⛔⛔ ONE HOLD PER SNAP. NEVER RE-ENGAGE INSIDE A LIVE PLAY.
    # (Sep 15, Montrell: "would prefer it only trigger after that ball snap and
    # be consistent in not reengaging until another playcall is completed and
    # ball is snapped again.")
    #
    # The screen gate below asks "is a playcall screen up?" - but DURING a live
    # play the answer is also no, so a second call while the ball is in the air
    # sails straight through it and grabs the stick again. A cooldown is the
    # only thing that can tell those two apart, because it does not depend on
    # reading the screen at all.
    #
    # A real sequence is: playcall -> snap -> run. That cannot legitimately
    # repeat inside the hold plus the rest of a play, so anything arriving
    # sooner is a duplicate and is refused.
    since = time.time() - _LAST_RUN_END
    if since < C.RUN_COOLDOWN:
        log(f"    run already ran {since:.1f}s ago (< {C.RUN_COOLDOWN}s) "
            f"- NOT grabbing the stick again")
        return " (run suppressed - too soon after the last one)"
    # ⛔ NEVER START THE RUN BLIND. If a playcall screen is up the play is not
    # live - it never started, or it is already over - and driving the stick
    # here scrolls the favourites grid or the pause menu.
    try:
        _side, _i, _n, _ratio = screen.read_both()
    except Exception:
        _side, _ratio = None, 0.0
    if _side is not None and _ratio >= C.CONFIDENT:
        log("    playcall screen is up - NOT running the stick "
            "(no input outside a live play)")
        return " (run skipped - play not live)"
    # ⛔⛔ A COUNTING PLAY CLOCK MEANS THE HIKE NEVER TOOK. (Sep 18.) The gate
    # above cannot see this case: pre-snap at the line is NOT the playcall
    # screen, so a swallowed snap sailed through it, the stick + R2 went into
    # the formation, and the play clock ran out - the delay-of-game loop that
    # has cost drives. Skipping a legitimate run costs a few yards; running
    # pre-snap costs the down. Fail toward skipping.
    if _play_clock_counting():
        log("    ⛔ PLAY CLOCK STILL COUNTING after the throw - the snap did not "
            "take; NOT running the stick (would be a delay of game)")
        return " (run refused - play clock counting, snap did not take)"
    # ⭐ The gates above took ~1-1.5s. Start the hold at throw + OFF_RUN_AFTER
    # (the catch), or right now if the gates already used that time.
    time.sleep(max(0.0, (after_throw_at + C.OFF_RUN_AFTER) - time.time()))
    try:
        # ⭐⭐ ONE CONTINUOUS HOLD, ENDED BY THE DAEMON'S OWN EYES. (Sep 18.)
        # The chunked version (0.5-1.0s /combo bursts with a ~0.5s screen
        # check between them) had two faults Montrell watched from the couch:
        # R2 delivered in stabs never actually sprinted, and the tail of a
        # chunk landed on the playcall grid, scrolled the favourites rows and
        # cross then picked QB KNEEL. /hold_watch holds stick+R2 together for
        # the whole run and releases within ~50ms of the play-card band going
        # dark (the playcall page or the pause menu). The daemon releases every
        # key in a finally, so a crash mid-hold cannot strand one.
        r = pad._remote_post("/hold_watch", {
            "keys": [C.OFF_RUN_STICK, C.OFF_RUN_SPRINT],
            "max_seconds": C.OFF_RUN_HOLD,
            "interval": 0.02,
            "min_hold": 0.15,
            "region": list(C.PLAY_BAND),
            "dark_fraction": C.PLAY_BAND_DARK,
            "confirm_region": list(C.PLAY_L1_BADGE),
            "confirm_bright": C.PLAY_L1_BRIGHT,
            # ⭐ R2 re-pressed during the hold so a fresh edge lands AFTER the
            # catch (Sep 18, Montrell: "the R2 sprint is not happening" with
            # R2 held from before the catch). The stick stays down throughout.
            "repress": [C.OFF_RUN_SPRINT] if C.OFF_RUN_REPRESS else [],
            "repress_every": C.OFF_RUN_REPRESS or 0.4,
            "focus": False})
        if r.get("reason") == "screen":
            log(f"    play over - run released by the screen after "
                f"{r.get('held')}s (dark {r.get('dark')})")
    finally:
        # ⛔ Stamp the end on EVERY exit path, including an exception - a hold
        # that died halfway is still a hold, and re-grabbing on top of it is
        # precisely what jams the stick.
        _LAST_RUN_END = time.time()
        try:
            pad.release()
        except Exception:
            pass
    return f" +run{tag} {C.OFF_RUN_HOLD:.0f}s"


def _t(t0, what, log):
    """⭐ MEASURE THE SNAP PATH. Montrell watched it sit at the pre-snap for
    ~8s and I kept guessing at why. Every step that can block is timed now."""
    log(f"      +{time.time() - t0:4.1f}s  {what}")


def chew_and_hike(log=print, allow_skip=True, chew=True, throw=None,
                  run=False, flipped=False, run_seq=None, throw_seq=None):
    """Wait out the play clock, then snap.

    ⭐ THE POINT: the GAME clock runs down while the PLAY clock does, so every
    second spent pre-snap burns game clock. With a FULLBACK DIVE - in bounds,
    clock keeps running - that burn is real. (With Air Raid's jet sweep it was
    not, because the play ended out of bounds and stopped the clock. That is the
    whole reason this is back on.)

    ⭐ IF THE QUARTER ENDS FIRST, DO NOT SNAP AT ALL. Spending a play to run out
    a clock that was going to run out anyway is pure waste.
    """
    t0 = time.time()

    # ⛔⛔ NEVER TIME A SNAP AGAINST A FROZEN PICTURE. (Sep 14 - delay of games.)
    # Measured: the game clock read EXACTLY 133s on two plays 62 SECONDS apart,
    # and chiaki dropped a minute later. The clock was not stopped - we were
    # looking at a stale frame. Every timing decision below reads the play clock
    # and waits for it to fall; against a frozen frame it never falls, so the
    # loop waits out the real play clock and takes a DELAY OF GAME.
    #
    # screen.FROZEN_STREAK already counts byte-identical captures - the snap
    # path simply never asked. When the picture is not moving, the honest answer
    # is "I cannot see the clock", so stop pretending to chew and just snap on
    # the floor. A slightly early snap costs nothing; a delay of game stops the
    # clock, lengthens the down, and is what Montrell has had to fix by hand.
    if screen.FROZEN_STREAK >= C.STALE_FRAMES:
        # ⛔ DO NOT PRESS INTO A PICTURE THAT IS NOT MOVING. We cannot even be
        # sure a playcall screen is still up - the last frame that said so may
        # be seconds old. Pressing anyway is how the loop "called a play"
        # against a frozen image while the real play clock ran out.
        # Hand back without spending a play; the caller re-reads, and the
        # frozen-feed watchdog restarts the stream if it persists.
        log(f"    ⚠️ picture frozen ({screen.FROZEN_STREAK} identical frames) "
            f"- NOT pressing until it moves")
        return False, "frozen picture - no play called", 1.5

    def snap(why, urgent=False):
        # ⛔⛔ DO NOT HONOUR THE FLOOR WHEN THE PLAY CLOCK IS ABOUT TO EXPIRE.
        # (Sep 13: DELAY OF GAME.) MIN_SNAP_WAIT is a 6s floor measured from the
        # START of this function, on the untested belief that the game will not
        # accept a snap sooner. But when we arrive at a playcall screen that
        # ALREADY has a low play clock - after a penalty, a quick turnaround, or
        # because set_chew_clock just spent several seconds - waiting out that
        # floor runs the play clock to ZERO.
        #
        # A delay of game is far worse than a possibly-early snap: it STOPS the
        # clock (the opposite of what chewing is for) and lengthens the down.
        if not urgent:
            time.sleep(max(0.0, (t0 + C.MIN_SNAP_WAIT) - time.time()))

        # ⛔ FOCUS ONCE HERE, then post with focus=False, so `t_snap` is the true
        # instant the snap went out. pad.press() re-focuses chiaki on every call
        # and costs ~0.5s - which would land the throw half a second late inside
        # a 2.0s window. This is the same discipline the archive's stick-run
        # needed, and the reason that one kept "not working" until it was fixed.
        _t(t0, "SNAPPING", log)
        pad._remote_post("/focus", {})
        time.sleep(0.35)
        # ⭐ A FLIPPED PLAY PUTS THE RECEIVER ON A DIFFERENT BUTTON.
        throw_btn = C.OFF_THROW_BUTTON
        if flipped and C.OFF_THROW_BUTTON_FLIPPED:
            throw_btn = C.OFF_THROW_BUTTON_FLIPPED

        want_throw = C.OFF_THROW if throw is None else throw
        t_snap = time.time()
        seq_sent = False
        if not want_throw and run_seq:
            # ⭐⭐ INSIDE ZONE (Sep 19): snap, then stick-up + R2 from
            # run_seq["after"] for run_seq["hold"] seconds - the macro Montrell
            # labbed in practice mode (macros/inside_zone.json). NO throw, and
            # run_phase is NOT used - it refuses without a throw instant.
            #
            # ⛔ THE HOLD IS /hold_watch, NOT A BLIND /sequence. (Sep 19, game 2:
            # Montrell from the couch: "it's still flipping the play".) The
            # loop's own flip is off for this profile, so the flip was the
            # macro's R2 landing on the playcall screen after a quick tackle -
            # a bare R2 there IS "flip play". /hold_watch lets go within 20ms
            # of the play-card band + L1 badge, exactly like the pass's run.
            global _LAST_RUN_END
            a = float(run_seq["after"]); h = float(run_seq["hold"])
            pad._remote_post("/press", {"buttons": ["cross"],
                                        "hold": C.OFF_SNAP_HOLD,
                                        "gap": 0.0, "focus": False})
            time.sleep(max(0.0, (t_snap + a) - time.time()))
            t_hold = time.time()
            try:
                r = pad._remote_post("/hold_watch", {
                    "keys": [C.OFF_RUN_STICK, C.OFF_RUN_SPRINT],
                    "max_seconds": h,
                    "interval": 0.02,
                    "min_hold": 0.15,
                    "region": list(C.PLAY_BAND),
                    "dark_fraction": C.PLAY_BAND_DARK,
                    "confirm_region": list(C.PLAY_L1_BADGE),
                    "confirm_bright": C.PLAY_L1_BRIGHT,
                    "repress": [], "repress_every": 0.4,
                    "focus": False})
            finally:
                _LAST_RUN_END = time.time()
                try:
                    pad.release()
                except Exception:
                    pass
            tail = ""
            if isinstance(r, dict):
                if r.get("error"):
                    log(f"    ⛔ inside-zone hold rejected: {r['error']}")
                elif r.get("reason") == "screen":
                    tail = f", released by the screen at {r.get('held')}s"
            return True, (why + f" + run @{t_hold - t_snap:.2f}s "
                          f"hold {h:.1f}s{tail}"), 0.0
        if not want_throw and throw_seq:
            # ⭐⭐ THE TIER 3-4 PASS (Sep 19): snap, then throw_seq["after"]
            # seconds later press throw_seq["button"] for throw_seq["hold"] -
            # exactly the macro practice_macro.py ran (macros/throw_x.json,
            # 1.25s: "thats perfect"). ONE /sequence on the daemon's clock, the
            # same shape as the RPO's snap+throw below. No stick, no sprint, so
            # nothing is held that could land on the playcall screen.
            a = float(throw_seq["after"]); h = float(throw_seq["hold"])
            tb = throw_seq.get("button", "cross")
            pad._remote_post("/sequence", {"events": [
                {"t": 0.0, "key": "cross", "down": True},
                {"t": C.OFF_SNAP_HOLD, "key": "cross", "down": False},
                {"t": a, "key": tb, "down": True},
                {"t": a + h, "key": tb, "down": False},
            ], "focus": False, "max_seconds": 5.0})
            return True, why + f" + throw {tb} @{a:.2f}s", 0.0
        if want_throw and not C.OFF_THROW_STICK:
            # ⭐⭐ SNAP + THROW IN ONE DAEMON CALL, TIMED ON THE DAEMON'S CLOCK.
            # (Sep 18) The old path blocked on the snap /press (0.27-0.6s with
            # lock jitter) and only then slept to the target, so the throw went
            # out at "whenever the press returned" - 0.74-0.85s - and lowering
            # OFF_THROW_AFTER changed nothing. Montrell: "it didn't throw... we
            # can't win games like this". /sequence measured 0.0ms late; the
            # target is now a real knob.
            pad._remote_post("/sequence", {"events": [
                {"t": 0.0, "key": "cross", "down": True},
                {"t": C.OFF_SNAP_HOLD, "key": "cross", "down": False},
                {"t": C.OFF_THROW_AFTER, "key": throw_btn, "down": True},
                {"t": C.OFF_THROW_AFTER + C.OFF_THROW_HOLD, "key": throw_btn,
                 "down": False},
            ], "focus": False, "max_seconds": 5.0})
            seq_sent = True
        else:
            pad._remote_post("/press", {"buttons": ["cross"],
                                        "hold": C.OFF_SNAP_HOLD,
                                        "gap": 0.0, "focus": False})
        if not want_throw:
            # ⭐ THE DIVE SPRINTS TOO on tiers 3-4 (Sep 14, Montrell): same
            # stick-up + sprint, same 3s, just with no throw before it. The
            # delay is measured from the SNAP rather than from a throw, because
            # there is no throw - the handoff needs a moment first.
            if run:
                time.sleep(max(0.0,
                               (t_snap + C.OFF_DIVE_RUN_AFTER) - time.time()))
                # ⛔ No throw here, so no run: run_phase refuses without a
                # throw instant (Sep 18 rule). The dive sprint is retired.
                return True, why + run_phase(log=log, tag=""), 0.0
            return True, why, 0.0

        # ⛔⛔ DO NOT ADD A "CONFIRM THE SNAP" CHECK HERE. TRIED, FAILED, REVERTED.
        # (Sep 13, 22:39) I gated this macro on reading the play clock 0.55s
        # after the hike, on the theory that a visible play clock means the ball
        # never went live. It fires on GOOD snaps: between Remote Play's video
        # latency and the HUD not clearing instantly, the captured frame still
        # shows the pre-snap play clock. First live play after the change:
        #   "hike did not take (play clock still 14s) - re-snapping"
        #   "SNAP DID NOT TAKE, macro withheld"
        # The ball had been hiked correctly. The throw was withheld, the QB held
        # the ball, we took a SACK on a drive that was working, and Montrell had
        # to take over and settle for a field goal.
        #
        # The pre-snap jam this was meant to prevent (R2 held, phantom R1 hike)
        # had a DIFFERENT cause: a crash inside a 3s hold left 24 keys physically
        # down, and the restart inherited them. That is fixed by releasing the
        # pad on startup, on any exit, and after a stream restart - not here.
        #
        # If this is ever revisited: the HUD is NOT a usable snap oracle at this
        # latency. Find evidence that leads the video, or leave it open-loop.

        # ⭐ Everything is scheduled off t_snap, never off a cumulative sleep.
        time.sleep(max(0.0, (t_snap + C.OFF_THROW_AFTER) - time.time()))
        # ⭐ MEASURE WHAT WE ACTUALLY ACHIEVED, do not assume it. "The timing
        # should be the same every snap" is a claim worth checking: if the
        # realised delay jitters, the cause is ours (daemon queueing, focus,
        # scheduling). If it is rock steady and throws still fail, the cause is
        # the game's own throw window and no amount of tuning the delay by
        # fractions will fix the failures - only moving it further out will.
        t_throw = time.time()
        actual = t_throw - t_snap
        if seq_sent:
            # The daemon already pressed the throw at exactly OFF_THROW_AFTER;
            # t_throw for the run gates is that instant, not "now".
            t_throw = t_snap + C.OFF_THROW_AFTER
            actual = C.OFF_THROW_AFTER
        # THE THROW - a short TAP, not a hold. A long hold takes control of the
        # receiver; the run phase below takes control deliberately instead.
        if seq_sent:
            pass
        elif C.OFF_THROW_STICK:
            # Stick UP held across the throw so the pass is led, then held
            # again with sprint below - effectively continuous.
            pad._remote_post("/combo", {
                "hold": C.OFF_THROW_STICK,
                "taps": [throw_btn],
                "pre": 0.0,
                "tap_hold": C.OFF_THROW_HOLD,
                "gap": 0.0,
                "post": 0.0,
                "focus": False})
        else:
            pad._remote_post("/press", {"buttons": [throw_btn],
                                        "hold": C.OFF_THROW_HOLD,
                                        "gap": 0.0, "focus": False})
        # ⛔ The throw combo holds the stick too. Release it here rather than
        # relying on the run block below, which is conditional.
        try:
            pad.release()
        except Exception:
            pass

        # ⭐⭐ THEN RUN HIM. Hold left stick UP + SPRINT so the receiver drives
        # upfield after the catch. This is the piece we had backwards: the stick
        # belongs AFTER the throw, with sprint, not during it.
        # ⛔ Compute the status pieces BEFORE the run block. The run block has
        # an early return, and defining these after it is exactly how `actual`
        # and `tier` crashed the farm mid-game (Sep 13, twice).
        lead = "+lead" if C.OFF_THROW_STICK else ""

        # ⭐ run_phase runs its gates DURING the OFF_RUN_AFTER wait and starts
        # the hold at t_throw + OFF_RUN_AFTER - never later than it must.
        run_note = run_phase(log=log, tag="", after_throw_at=t_throw)
        return True, (f"{why} + throw[{throw_btn}]{lead} @{actual:.2f}s"
                      f"{' seq' if seq_sent else ''}{run_note} "
                      f"(target {C.OFF_THROW_AFTER})"), 0.0

    if C.HIKE_AT >= 99 or not chew:
        # ⛔⛔ EVEN WHEN NOT CHEWING, LOOK AT THE PLAY CLOCK ONCE.
        # (Sep 13: repeated DELAY OF GAME on tier 3, where chewing is held off
        # until we lead.) Without chewing we never read the clock at all - we
        # just wait out MIN_SNAP_WAIT and snap blind. But the play clock starts
        # during the PREVIOUS play's wrap-up, so by the time we reach the
        # playcall screen it can already be low, and a 6s floor then runs it to
        # zero.
        #
        # The earlier urgent-snap fix only covered the CHEWING path, because
        # that is the only one that looked at the clock. Turning chewing off
        # re-opened the same hole.
        _q, _gs, ps0 = screen.read_clocks()
        if ps0 is not None and ps0 <= C.MIN_SNAP_WAIT + 3:
            return snap(f"snapped NOW (play clock :{ps0} - no time for the floor)",
                        urgent=True)
        return snap(f"snapped at +{C.MIN_SNAP_WAIT:.1f}s (chew OFF)")

    # ⭐⭐ IS THE GAME CLOCK EVEN RUNNING? Chewing the play clock exists ONLY to
    # burn GAME clock. If the clock is stopped (incompletion, out of bounds,
    # after a score, between quarters) then waiting burns REAL time and gains
    # nothing at all. Measure it once, up front, rather than polling hopefully
    # for 42 seconds - the old build sat out the full deadline on those plays.
    # ⛔⛔ LOOK AT THE PLAY CLOCK BEFORE SPENDING 2.2s ON ANYTHING ELSE.
    # (Sep 14.) The stopped-clock test below costs TWO OCR passes and a 1.2s
    # sleep. Measured: by the time it finished, the first play-clock reading was
    # already :9 - so the scheduling fix never even ran, and every chewed snap
    # went out on the urgent path with almost no margin. We were not chewing too
    # long, we were ARRIVING LATE and then spending the little time we had.
    #
    # If the clock is already near the target there is nothing to decide: snap.
    # ⭐⭐ THE ARCHIVE'S SHAPE (Air Raid, 251W-5L). THE WAIT *IS* THE TEST.
    # (Sep 15 - Montrell: "go back and look at the code for the old event...
    # that was working just fine, we didn't have as many glitches.")
    #
    # That build did ONE sleep that served both purposes at once:
    #   read game clock -> sleep MIN_SNAP_WAIT -> read game clock again
    # The wait the game needs before it will accept a snap is the SAME interval
    # we need to see whether the game clock moved. My version stacked them - an
    # entry read, a separate 1.2s stopped-clock test with two more reads, and
    # THEN the floor - roughly four extra seconds and two extra OCR passes on
    # every down, out of a play clock we cannot afford.
    _t(t0, "game clock read 1", log)
    _q0, ga, ps_now = screen.read_clocks()

    # Already low on arrival? Nothing to decide - snap.
    if ps_now is not None and ps_now <= C.HIKE_AT:
        _t(t0, f"play clock {ps_now} on arrival - snapping", log)
        return snap(f"snapped at play clock :{ps_now} (already low on arrival)",
                    urgent=True)

    # ⛔⛔ IF THE CLOCK IS ALREADY LOW, THERE IS NOTHING LEFT TO CHEW.
    # (Sep 15) Measured: 18 of 18 snaps in one game landed at :0-:5. We arrive
    # with ~14s and then spend ~9 more - read, 6s floor, second read, chew-loop
    # read. The archive spent the same time but ARRIVED with a full play clock.
    #
    # Chewing exists to burn game clock. When we get here at :20 or less we are
    # already burning all of it, so the second read and the chew loop buy
    # nothing and cost the margin that keeps us out of a delay of game. Wait the
    # floor the snap needs, then take it.
    if ps_now is not None and ps_now <= C.CHEW_SKIP_BELOW:
        time.sleep(C.MIN_SNAP_WAIT)
        _t(t0, f"arrived at :{ps_now} - nothing left to chew, snapping", log)
        return snap(f"snapped at +{C.MIN_SNAP_WAIT:.1f}s "
                    f"(arrived at :{ps_now})", urgent=True)

    # ⛔⛔ PLAY CLOCK UNREAD ON ARRIVAL -> ASSUME IT IS LOW. (Sep 25, a delay of
    # game on the last snap of a Q4.) Arrivals in Q4 were already down to :13
    # - :14; with the arrival read blank the loop spent the floor PLUS a second
    # read and the stopped-clock test (7.9s) on a play clock it could not see.
    # Not knowing is not the same as having time: take the floor, then snap.
    if ps_now is None:
        time.sleep(C.MIN_SNAP_WAIT)
        _t(t0, "play clock unread on arrival - snapping on the floor", log)
        return snap("snapped on the floor (play clock unread on arrival)",
                    urgent=True)

    time.sleep(C.MIN_SNAP_WAIT)        # the game will not take a snap sooner
    _t(t0, "game clock read 2", log)
    _q1, gb, _ps = screen.read_clocks()

    # ⛔⛔ UNREADABLE CLOCK -> SNAP. DO NOT GO LOOKING FOR MORE.
    # (Sep 15) Seven snaps landed at :0-:5 in one game. When the game clock
    # cannot be read we fell through into the chew loop, which spends MORE
    # captures trying to answer a question we already failed to answer - while
    # the play clock keeps running. We have already waited the full snap floor
    # by this point, so the ball is ready: take it.
    if ga is None or gb is None:
        _t(t0, "clock unreadable after the floor - snapping rather than "
               "spending more play clock", log)
        return snap("snapped on the floor (clock unreadable)", urgent=True)

    if ga is not None and gb is not None and gb >= ga:
        # ⛔ A frozen PICTURE looks like a stopped clock. Check before acting.
        if screen.FROZEN_STREAK >= C.STALE_FRAMES:
            log(f"    clock looks stopped but the PICTURE is frozen "
                f"({screen.FROZEN_STREAK} identical frames) - not acting")
            return False, "frozen picture - no play called", 1.5
        _t(t0, "game clock stopped - snapping now", log)
        return snap(f"snapped now (game clock stopped at {gb}s - nothing to "
                    f"burn)", urgent=True)

    deadline = t0 + C.SNAP_DEADLINE
    misses = 0
    while time.time() < deadline:
        _q, gs, ps = screen.read_clocks()
        if ps is None:
            # ⛔ Do NOT sit on an unreadable clock until the deadline. Look a few
            # times, then snap and take the down - a delay of game STOPS the
            # clock and lengthens the down, which is the opposite of the point.
            misses += 1
            if misses >= 4:
                break
            time.sleep(0.8)
            continue
        misses = 0

        # ⭐ QUARTER ENDS FIRST. The game clock is confirmed running (checked
        # above), so if less of it remains than the play clock, the quarter
        # expires while we stand here - for free, with no play spent and no
        # delay-of-game risk. The +3 is read latency; without a margin a
        # gs == ps case walks into the penalty this is avoiding.
        if allow_skip and gs is not None and gs + 3 < ps:
            return (False,
                    f"quarter ends first (game {gs}s < play {ps}s) - NOT snapping",
                    min(float(gs) + 3.0, 25.0))

        if ps <= C.HIKE_AT:
            # Urgent: the clock is at the threshold, so go now.
            return snap(f"snapped at play clock :{ps}", urgent=True)

        # ⛔⛔ SCHEDULE THE SNAP, DO NOT POLL TOWARDS IT. (Sep 14.)
        # Polling read the clock, slept, and read again - but each read is a
        # capture plus an OCR pass, so the clock fell 2-3s BETWEEN LOOKS. It saw
        # :15, then :12, then :9, and snapped at :9. Raising HIKE_AT from 8 to
        # 14 barely moved the landing point (measured: still :8 and :9) because
        # the overshoot, not the threshold, was the problem - and :8 with a
        # laggy stream is a DELAY OF GAME.
        #
        # The play clock ticks one per second, so once we have read it we know
        # exactly when it reaches the target. Sleep that long and snap. One read
        # instead of four also takes load off the decoder, which is the thing
        # dropping frames in the first place.
        wait = ps - C.HIKE_AT
        if wait <= C.SNAP_SCHEDULE_MAX:
            time.sleep(max(0.0, wait))
            return snap(f"snapped at play clock :~{C.HIKE_AT} "
                        f"(scheduled from :{ps})", urgent=True)
        # Too far out to trust a single reading - close the gap and look again.
        time.sleep(max(0.6, min(4.0, wait - C.SNAP_SCHEDULE_MAX)))
    return snap("snapped (fallback - clock unreadable)")


# ---------------------------------------------------------------------------
# CALLING THE PLAYS
# ---------------------------------------------------------------------------


def _play_row_ok(play, log=print):
    """True if `play` is on the visible favourites row (or the row is
    unreadable). Scrolls with the d-pad to find it when a DIFFERENT row shows.

    Returns False only when the names are readable and ours is not among them
    after PLAY_ROW_SCROLL_TRIES scrolls - the caller then refuses the press.
    """
    if not C.PLAY_ROW_CHECK:
        return True
    import ocr
    # `row_name` lets a profile verify the row by a NEIGHBOUR on it (the tier
    # 3-4 pass, until its own name is known - config.py).
    want = (play.get("row_name") or play["name"]).upper().split()[0:2]   # "RPO READ" - Vision-proof
    want = " ".join(want)
    scroll = ["up", "down", "down", "up"]            # net zero if all fail
    for attempt in range(C.PLAY_ROW_SCROLL_TRIES + 1):
        try:
            row = str(ocr.ocr(C.PLAY_ROW, path=f"{C.SHOT_DIR}/playrow.png")).upper()
        except Exception:
            row = ""
        # ⛔ Vision reads "INSIDE ZONE" as "INSIDEZONE" about half the time
        # (Sep 19, tier 4): the row was RIGHT and the check scrolled away from
        # it, up to 4 times a play. Compare with the spaces stripped.
        if want in row or want.replace(" ", "") in row.replace(" ", ""):
            if attempt:
                log(f"    play row FIXED after {attempt} scroll(s): {row[:60]!r}")
            return True
        readable = len(row.replace("|", "").strip()) >= 8
        if not readable:
            log(f"    play row unreadable ({row[:30]!r}) - pressing unverified")
            return True
        if attempt >= C.PLAY_ROW_SCROLL_TRIES:
            break
        key = scroll[attempt % len(scroll)]
        log(f"    ⛔ WRONG FAVOURITES ROW ({row[:60]!r}) - {want} not visible, "
            f"scrolling {key}")
        pad.press(key, hold=0.10)
        time.sleep(0.45)
    log(f"    ⛔⛔ {want} NOT FOUND on any row reached - NOT pressing "
        f"{play['button']} (would call the wrong play)")
    return False


_OVERLAY_CALLS = 0
MACRO_PRESSED = False   # set by any hold-and-tap macro; forces the next overlay check


def _clear_held_overlay(log=print):
    """If Madden thinks a play button is being HELD, tap it to clear that.

    ⛔⛔ (Sep 18) The playcall action bar read "[RELEASE] SELECT STUNT" for 43
    minutes: Madden had latched into the hold-to-select state after the
    defence macro's triangle key-up was lost, and NOTHING cleared it - not a
    focused /release, not a full chiaki restart (fresh all-up controller state)
    - only a press-and-release of the SAME button. Meanwhile every cross press
    read as "still holding": 16 delay-of-game flags, 1st & 42, and the freeze
    guard exited the loop. Costs one action-bar read per play call.
    """
    # ⭐ (Sep 25) 0.8s of OCR on every play call, both sides, for a latch seen
    # ONCE (Sep 18) and caused by a macro's lost key-up. Check after any macro
    # press, and on every OVERLAY_CHECK_EVERY-th call as a backstop - a latch
    # that slips through is caught a few plays later instead of instantly.
    global _OVERLAY_CALLS, MACRO_PRESSED
    _OVERLAY_CALLS += 1
    if not MACRO_PRESSED and _OVERLAY_CALLS % max(1, C.OVERLAY_CHECK_EVERY):
        return
    MACRO_PRESSED = False
    try:
        bar = screen.action_bar()
    except Exception:
        return
    if "RELEASE" not in bar:
        return
    log(f"    ⛔ HELD-BUTTON OVERLAY on the playcall screen ({bar[:40]!r}) "
        f"- tapping {C.DEF_PLAY_BUTTON} to clear the latch")
    for key in (C.DEF_PLAY_BUTTON, "box"):
        pad.press(key, hold=0.12)
        time.sleep(0.8)
        try:
            bar = screen.action_bar()
        except Exception:
            bar = ""
        if "RELEASE" not in bar:
            log(f"    latch cleared by tapping {key}")
            return
    log(f"    ! overlay still present after taps: {bar[:40]!r}")

def select_play(play):
    """Press the play's favourites button - plain, or HOLD + d-pad taps when
    the profile carries a `select_macro` (the tier 3-4 pass, Sep 19: "hold
    square and down once on d pad to select"). Same /combo the defence macro
    uses: one daemon call, the taps land inside the hold, key-up in a finally.
    Every caller that used to `pad.press(play["button"])` goes through here so
    the 4th-down paths in grind.py select the play the same way."""
    m = play.get("select_macro")
    if not m:
        pad.press(play["button"], hold=C.OFF_SELECT_HOLD)
        return
    global MACRO_PRESSED
    MACRO_PRESSED = True       # forces the next overlay check (Sep 25)
    try:
        pad._remote_post("/combo", {
            "hold": play["button"],
            "taps": list(m["taps"]),
            "pre": m["pre"],
            "tap_hold": m["tap_hold"],
            "gap": m["gap"],
            "post": m["post"],
            "focus": True})
    finally:
        try:
            pad.release()
        except Exception:
            pass


def call_offense(known=None, log=print, allow_skip=True, chew=True, flip=False,
                 play=None):
    """FAVORITES -> [flip] -> play button -> chew -> snap -> [throw].

    `play` is one entry of config.OFF_BY_BADGE: which button selects the play,
    what to call it, and whether this play throws after the snap.
    """
    # ⛔⛔ NOTHING IS PRESSED INTO A PICTURE THAT IS NOT MOVING.
    # This must be the FIRST thing here, not inside chew_and_hike - the tab
    # walk, the flip and the play-select button all fire before the snap, and
    # they are presses into a screen we cannot confirm is still there.
    if screen.FROZEN_STREAK >= C.STALE_FRAMES:
        log(f"    ⚠️ picture frozen ({screen.FROZEN_STREAK} identical frames) "
            f"- NOT pressing until it moves")
        return False, "frozen picture - no play called", 1.5
    # ⛔⛔ START FROM A NEUTRAL PAD ON EVERY PLAY CALL.
    # (Sep 15) Montrell watched R2 being held while the config made it
    # IMPOSSIBLE for the farm to send R2 at all - so it was a STUCK key: a
    # key-down whose key-up was lost. With the stream dropping ~14 times a day,
    # any hold spanning a disconnect releases into a window that no longer
    # exists, and chiaki goes on believing the trigger is down.
    #
    # A stuck trigger poisons everything downstream - the QB sprints on his own,
    # selections do not register, plays look random. Releasing here costs one
    # call and nothing when no key is held, and it bounds the damage to a single
    # play instead of the rest of the session.
    try:
        pad.release()
    except Exception:
        pass
    _clear_held_overlay(log)
    play = play or C.OFF_BY_BADGE[C.OFF_DEFAULT_BADGE]
    if not goto_tab("offense", C.OFF_TAB, known=known):
        return False, f"could not reach {C.OFF_TAB}", 0.0
    if not _play_row_ok(play, log):
        return False, "wrong favourites row - play not called", 1.0
    if flip:
        # ⛔⛔ NOT WHEN THE PLAY CLOCK IS NEARLY DEAD. (Sep 13) Flipping costs
        # ~0.4s plus a press, and on a resume-from-pause we can arrive with the
        # clock already inside single digits. A flipped play we get penalised
        # for is worth less than a straight one we actually snap.
        try:
            _q, _g, _ps = screen.read_clocks()
        except Exception:
            _ps = None
        if _ps is not None and _ps <= C.FLIP_MIN_CLOCK:
            log(f"    play clock :{_ps} - skipping the flip to save the down")
            flip = False
    if flip:
        # ⛔ A LONE R2, before the play-select button. R2 plus a face button is
        # PLAYCALL SUBSTITUTIONS, which is a very different screen.
        pad.press("r2", hold=0.06)
        time.sleep(0.35)
    # ⛔ For the DIVE this button is CROSS - the same button that snaps. That is
    # fine sequentially (select, then snap) but it means a log line showing two
    # crosses is normal here, not a double-press bug.
    # ⛔⛔ CONFIRM THE TAB IMMEDIATELY BEFORE PRESSING. (Sep 15.)
    # goto_tab trusts the tab index the CALLER read a moment earlier, and if
    # that says FAVORITES it returns without looking again. A cutscene can drop
    # us back on COACH SUGGESTIONS in between - and then this press calls
    # whatever play happens to sit in that slot. Montrell watched exactly that
    # happen; it scored by luck, but it could as easily have cost the drive.
    #
    # ⭐ This checks the TAB, not the play state - the same tab-strip read the
    # loop already trusts everywhere - and it happens BEFORE any press, so the
    # worst it can do is navigate tabs again (harmless L1/R1) rather than fire a
    # button into the wrong screen. That is what makes it safe where my earlier
    # guards were not.
    try:
        _side, _i, _name, _ratio = screen.read_both()
        if _side == "offense" and _ratio >= C.CONFIDENT and _name != C.OFF_TAB:
            log(f"    tab drifted to {_name} before the press "
                f"(cutscene?) - re-navigating to {C.OFF_TAB}")
            if not goto_tab("offense", C.OFF_TAB):
                return False, f"could not re-reach {C.OFF_TAB}", 1.0
    except Exception:
        pass

    select_play(play)

    # ⛔⛔ CONFIRM THE PLAY WAS ACTUALLY SELECTED BEFORE ANYTHING PRESSES CROSS.
    # (Sep 14 - Montrell watched a FULLBACK DIVE run and take a delay of game
    # while the log insisted it had called the pass.)
    #
    # THE TRAP: `cross` is the SNAP, and `cross` is also the dive's slot on
    # FAVORITES. So a dropped play-select press does not merely fail - the snap
    # press that follows SELECTS THE DIVE instead of snapping. The throw macro
    # then fires into a pre-snap that never happened and the play clock expires.
    # One lost press turns into the wrong play AND a penalty.
    #
    # If the playcall screen is still up, the select did not land: press the
    # PLAY button again, never cross. This is a tab-strip read - the same
    # detection the loop trusts everywhere - not a HUD timing guess.
    # ⛔⛔ CONFIRM THE PRE-SNAP POSITIVELY. DO NOT INFER IT FROM AN ABSENCE.
    # (Sep 15 - QB POWER ran again.) The old test asked "is the playcall screen
    # gone?" and treated ANY unclear read as success - so a stale or ambiguous
    # frame let us press CROSS while still on the playcall screen, where cross
    # SELECTS QB POWER instead of snapping. Absence of evidence was being taken
    # for evidence of absence, on the one decision that must not be wrong.
    #
    # "PREPLAY"/"SUBS" appear ONLY once we are at the line with a play called.
    # Wait for that. If it never comes, re-press the PLAY button - never cross.
    # ⛔⛔ NO SELECTION-CONFIRMATION HERE. TRIED THREE WAYS, ALL WORSE.
    # (Sep 15) The archive - 251W-5L - went tab, press play, chew, snap, with no
    # confirmation at all. Every guard I added to this build cost more than it
    # saved:
    #   * "is the playcall screen gone?" - inferred success from an unclear read
    #     and let CROSS be pressed on the playcall screen anyway.
    #   * re-press the play button - at the line that button is the AUDIBLE, and
    #     it drew a DELAY OF GAME.
    #   * wait for "PREPLAY" - refuses to call the play at all whenever that
    #     text is not readable, which stops the farm dead.
    #
    # The real fix for a dropped select is a LONGER PRESS (OFF_SELECT_HOLD, now
    # 200ms vs the original 60ms), not more logic on top. If a select is still
    # missed, the pre-snap rescue in grind.py catches the unhiked play.
    snapped, status, hint = chew_and_hike(log=log, allow_skip=allow_skip,
                                          chew=chew, throw=play["throw"],
                                          run=bool(play.get("run")),
                                          flipped=flip,
                                          run_seq=play.get("run_seq"),
                                          throw_seq=play.get("throw_seq"))
    label = play["name"] + (" FLIPPED" if flip else "")
    return snapped, f"{label} - {status}", hint


def call_defense(known=None, log=print):
    """FAVORITES -> BOX (mid blitz). Nothing to snap - the CPU does that."""
    # ⛔⛔ NOTHING IS PRESSED INTO A PICTURE THAT IS NOT MOVING.
    # This must be the FIRST thing here, not inside chew_and_hike - the tab
    # walk, the flip and the play-select button all fire before the snap, and
    # they are presses into a screen we cannot confirm is still there.
    if screen.FROZEN_STREAK >= C.STALE_FRAMES:
        log(f"    ⚠️ picture frozen ({screen.FROZEN_STREAK} identical frames) "
            f"- NOT pressing until it moves")
        return False, "frozen picture - no play called", 1.5
    # ⛔⛔ START FROM A NEUTRAL PAD ON EVERY PLAY CALL.
    # (Sep 15) Montrell watched R2 being held while the config made it
    # IMPOSSIBLE for the farm to send R2 at all - so it was a STUCK key: a
    # key-down whose key-up was lost. With the stream dropping ~14 times a day,
    # any hold spanning a disconnect releases into a window that no longer
    # exists, and chiaki goes on believing the trigger is down.
    #
    # A stuck trigger poisons everything downstream - the QB sprints on his own,
    # selections do not register, plays look random. Releasing here costs one
    # call and nothing when no key is held, and it bounds the damage to a single
    # play instead of the rest of the session.
    try:
        pad.release()
    except Exception:
        pass
    _clear_held_overlay(log)
    if not goto_tab("defense", C.DEF_TAB, known=known):
        return False, f"could not reach {C.DEF_TAB}", 0.0

    if not C.DEF_MACRO:
        pad.press(C.DEF_PLAY_BUTTON, hold=C.OFF_SELECT_HOLD)
        return True, f"{C.DEF_PLAY_NAME} called on {C.DEF_TAB}", 0.0

    # ⭐ MONTRELL'S CUSTOM-ADJUSTMENT MACRO: hold the play button, tap DOWN a
    # few times INSIDE that hold, then release. Selecting the play this way
    # applies his adjustments rather than calling it plain.
    #
    # ⛔ ONE /combo CALL. The daemon holds the key down server-side and taps
    # inside it, with the key-up in a `finally`. Doing this as separate presses
    # would put an HTTP round trip between the hold and each tap - larger than
    # the timings involved - and a key-down that never gets its key-up wedges
    # the console outright.
    global MACRO_PRESSED
    MACRO_PRESSED = True       # forces the next overlay check (Sep 25)
    try:
        pad._remote_post("/combo", {
            "hold": C.DEF_PLAY_BUTTON,
            "taps": list(C.DEF_MACRO_TAPS),
            "pre": C.DEF_MACRO_PRE,
            "tap_hold": C.DEF_MACRO_TAP_HOLD,
            "gap": C.DEF_MACRO_GAP,
            # ⛔ Keep the button held after the tap - the play is selected on
            # RELEASE, so releasing instantly discards the adjustment.
            "post": C.DEF_MACRO_POST,
            "focus": True})
    finally:
        try:
            pad.release()
        except Exception:
            pass
    taps = "+".join(C.DEF_MACRO_TAPS)
    return True, (f"{C.DEF_PLAY_NAME} called on {C.DEF_TAB} "
                  f"[macro: hold {C.DEF_PLAY_BUTTON} {C.DEF_MACRO_PRE}s "
                  f"-> {taps}]"), 0.0


def call_field_goal(known=None, log=print):
    """FAVORITES -> the favorited FG play -> snap -> wait -> accuracy press.

    ⭐ TWO PRESSES, NOT THREE. Skipping the POWER press lets the meter max out
    and start back down on its own, collapsing two timing windows into one - and
    one window is something we can hit reliably.

        press X (snap)  ->  wait FG_PRESS_AFTER (3.5s)  ->  press X (accuracy)

    ⭐ 3.5s is MEASURED, not guessed - swept against 1.5/1.8/2.0/2.3 as
    three-press pairs, then 5.0/4.5/5.5 (far too late), then 3.5/3.0/2.5.

    ⛔ STILL UNVERIFIED: only ever kicked at 27 YARDS, in PRACTICE, under the
    practice game style. The event forces COMP on tiers 3-4 and COMP is exactly
    where kicking is hardest. Longer kicks may need the power press after all.
    Treat the first live kick as a test, not as a solved thing.
    """
    if not C.FG_BUTTON:
        # ⛔ Never guess this. FAVORITES holds live offensive plays; a wrong
        # button here calls one and snaps it.
        return False, "no FG button configured - not guessing on FAVORITES", 0.0
    if not goto_tab("offense", C.OFF_TAB, known=known):
        return False, f"could not reach {C.OFF_TAB}", 0.0
    pad.press(C.FG_BUTTON, hold=C.OFF_SELECT_HOLD)

    # ⛔ Focus ONCE, then post with focus=False, so the 3.5s is measured from the
    # true snap instant. pad.press() re-focuses every call and costs ~0.5s.
    pad._remote_post("/focus", {})
    time.sleep(0.35)
    t_snap = time.time()
    pad._remote_post("/press", {"buttons": ["cross"], "hold": 0.06,
                                "gap": 0.0, "focus": False})
    time.sleep(max(0.0, (t_snap + C.FG_PRESS_AFTER) - time.time()))
    actual = time.time() - t_snap
    pad._remote_post("/press", {"buttons": ["cross"], "hold": 0.06,
                                "gap": 0.0, "focus": False})
    return True, f"{C.FG_PLAY_NAME} - kicked @{actual:.2f}s (target {C.FG_PRESS_AFTER})", 0.0


def call_special_teams(log=print):
    """Punt and kickoff share the same mechanics: take the middle play, snap.

    Verified on the old build - this ran all day with no special handling.
    """
    t = time.time()
    pad.press("cross", hold=0.06)
    time.sleep(max(0.0, (t + C.MIN_SNAP_WAIT) - time.time()))
    pad.press("cross", hold=0.06)
    return True, "special teams: selected + snapped", 0.0


# ---------------------------------------------------------------------------
# THE ENTRY-OPTIONS SCREEN
# ---------------------------------------------------------------------------
# ⛔⛔ THE MISTAKE THIS REPLACES. Last event this screen offered Coins / Packs,
# the code assumed which row had focus based on a COMMENT, the comment was
# BACKWARDS, and ~11 tier rewards went down the Packs path before anyone looked
# at the screen. The fix is not a better assumption - it is to stop assuming.
#
# So: find both options by their WORDS wherever they are, measure which row is
# actually highlighted, step toward the one we want, and re-verify. A layout
# change during the event's run makes this slower, never wrong.

def _rows_from(path, spec=None):
    """One capture -> [{key, text, cy, bright}] for the options we care about.

    `spec` is a {key: {"want": (...), "not": (...)}} map - config.LINEUP_ROWS
    for the entry screen, config.POSTGAME_ROWS for the end-of-game menu.

    ⛔ TEXT AND BRIGHTNESS COME FROM THE SAME FRAME. Capturing twice lets the
    highlight move between the read and the decision, which is the exact class
    of bug this function exists to prevent.
    """
    boxes = screen.ocr_boxes_file(path)
    buf, w, h, bpr, bpp = screen.load(path)
    found = []
    for b in boxes:
        up = b["text"].upper()
        for key, rule in (spec or C.LINEUP_ROWS).items():
            # ⛔ REJECTS FIRST. "RESTRICTED" is a substring of "UNRESTRICTED",
            # so a row matching the reject list can never be taken as this key.
            if any(bad in up for bad in rule["not"]):
                continue
            if not any(good in up for good in rule["want"]):
                continue
            # ⛔ Sample the BUTTON, not the whole row. A full-width band is
            # ~78% background on this screen and averaged a real highlight away
            # (41.7 vs 43.4 on a row that was visibly lit). Pad outward from the
            # text so the button's fill and border are included, not just the
            # glyphs.
            half = max(12.0, (b["y1"] - b["y0"]) * 0.9)
            padx = max(20.0, (b["x1"] - b["x0"]) * 0.12)
            found.append({
                "key": key,
                "text": b["text"],
                "cy": b["cy"],
                "bright": screen.box_mean(buf, w, h, bpr, bpp,
                                          b["x0"] - padx, b["x1"] + padx,
                                          b["cy"] - half, b["cy"] + half),
            })
            break
    # ⛔ KEEP EVERY HIT, not just the topmost per key. The options are named
    # "Clock's Ticking - Lineup Restricted" / "- Lineup Free", and a heading or
    # a description line on the same screen can repeat those words. Picking the
    # topmost match would then hand back a static title as though it were the
    # row - and a title is never highlighted, so focus would read as "not
    # decisive" forever.
    #
    # Carrying duplicates costs nothing and fails safe: a row that is not
    # highlighted cannot win the brightness test, so only the real focused row
    # can ever be selected.
    return sorted(found, key=lambda r: r["cy"])


def _highlighted(rows, margin=1.18):
    """Which row has focus, or None if the read is not decisive.

    A focused Madden row is a light box behind dark text - the same signal the
    tab strip uses. `margin` is how much brighter it must be than the runner-up
    before we believe it. ⛔ A marginal read is worse than no read: waiting and
    looking again is free, pressing on noise costs an entry.
    """
    if len(rows) < 2:
        return None
    ordered = sorted(rows, key=lambda r: r["bright"], reverse=True)
    top, second = ordered[0], ordered[1]
    if second["bright"] <= 0 or top["bright"] / second["bright"] < margin:
        return None
    return top


def select_row(spec, want, label="menu", log=print, tries=6, shot=None):
    """Put focus on the row matching `want` and confirm it. Verified, not assumed.

    Returns (ok, detail). ⛔ FAILS SAFE: if focus can never be read confidently
    it presses NOTHING, so the caller can raise an alert rather than commit to
    whatever happened to be highlighted.

    ⭐ ONE selector for every menu that matters. The entry-options screen and
    the end-of-game menu use identical highlight styling (a light box behind
    dark text), so they get identical, already-verified handling instead of a
    second hand-rolled guess.
    """
    shot = shot or f"{C.SHOT_DIR}/_select.png"
    unknown = 0
    for _attempt in range(tries):
        pad.shot(None, shot)
        rows = _rows_from(shot, spec)
        if len({r["key"] for r in rows}) < 2:
            names = ", ".join(sorted({r["key"] for r in rows})) or "none"
            log(f"    {label}: only found [{names}] - looking again")
            time.sleep(1.0)
            unknown += 1
            if unknown >= 3:
                return False, f"could not find both options (saw {names})"
            continue

        focus = _highlighted(rows)
        detail = "  ".join(f"{r['key']}={r['bright']:.0f}" for r in rows)
        if focus is None:
            unknown += 1
            log(f"    {label}: focus not decisive ({detail}) - looking again")
            if unknown >= 3:
                return False, f"focus never read confidently ({detail})"
            time.sleep(1.0)
            continue

        if focus["key"] == want:
            # ⛔ TWO AGREEING READS before a press that commits. Never gate a
            # costly action on a single OCR read.
            time.sleep(0.5)
            pad.shot(None, shot)
            again = _highlighted(_rows_from(shot, spec))
            if again is not None and again["key"] == want:
                log(f"    {label}: {want} focused and confirmed twice "
                    f"({detail}) -> cross")
                pad.press("cross", hold=0.06)
                time.sleep(3.0)
                return True, f"selected {want}"
            log(f"    {label}: second read disagreed - looking again")
            continue

        # Step toward the row we want. Direction comes from where it actually
        # sits relative to the focused row, never from a remembered layout.
        #
        # ⭐ NEAREST candidate, because duplicates are kept on purpose (see
        # _rows_from). A heading repeating the words sits far from the option
        # list; the real row is the one adjacent to the focused one.
        cands = [r for r in rows if r["key"] == want]
        if not cands:
            return False, f"{want} not on screen"
        want_row = min(cands, key=lambda r: abs(r["cy"] - focus["cy"]))
        btn = "down" if want_row["cy"] > focus["cy"] else "up"
        log(f"    {label}: focus on {focus['key']}, {want} is {btn} "
            f"({detail}) -> {btn}")
        pad.press(btn, hold=0.06)
        time.sleep(0.8)
    return False, f"gave up after {tries} attempts"


def choose_lineup(log=print, tries=6, shot=None):
    """Select the RESTRICTED lineup on the ENTRY OPTIONS screen."""
    return select_row(C.LINEUP_ROWS, C.LINEUP_WANT, "entry options",
                      log=log, tries=tries, shot=shot)


def choose_finish_game(log=print, tries=6, shot=None):
    """Select FINISH GAME on Madden's end-of-game menu.

    ⛔ This screen is why the first test run wedged (Sep 12): nothing matched
    it, so it fell through to the loading-screen branch, waited 18 times, and
    then restarted chiaki against a game that was simply waiting for a press.
    """
    return select_row(C.POSTGAME_ROWS, C.POSTGAME_WANT, "end of game",
                      log=log, tries=tries, shot=shot)
