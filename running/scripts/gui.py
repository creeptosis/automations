"""Localhost GUI for the training plan.

Serves the plan with concrete paces (from the current fitness anchor) and
completion status (from synced Garmin runs). No database - everything is
computed live from plans/plan-fullspectrum.json (+ per-day edits in
plans/overrides.json) + data/.

    python scripts/gui.py   ->  http://127.0.0.1:5001
"""

import json
import math
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
from flask import Flask, jsonify, redirect, request, send_from_directory

import analyze
import percent as pctmod
import plan as planmod
import vdot as vdotmod
import workout as workoutmod

BASE_DIR = Path(__file__).resolve().parent.parent  # project root
app = Flask(__name__, static_folder=str(BASE_DIR / "static"))

# label -> % of 10k pace (Full-Spectrum PDF page 5)
LEGEND_ZONES = [
    ("very easy", 45, 55), ("easy", 55, 65), ("moderate", 70, 80),
    ("steady/LT1", 85, 85), ("strong/marathon", 90, 90),
    ("sub-threshold", 91, 93), ("HM pace", 95, 95), ("threshold", 96, 97),
    ("10k", 100, 100), ("CV/8k", 102, 102), ("5k", 105, 105),
    ("3k/vVO2max", 108, 110), ("mile/R", 115, 115),
]


def build_legend(base: float) -> list:
    out = []
    for label, lo, hi in LEGEND_ZONES:
        # higher % = faster, so hi% gives the fast end of the pace range
        fast = pctmod.fmt(pctmod.pace_at_percent(base, hi))
        slow = pctmod.fmt(pctmod.pace_at_percent(base, lo))
        out.append({
            "label": label,
            "pct": f"{lo}%" if lo == hi else f"{lo}-{hi}%",
            "pace": fast if lo == hi else f"{slow}-{fast}",
        })
    return out


def anchor_summary(base: float) -> str:
    """Compact one-liner for the plan header; details live in the Paces tab."""
    v = vdotmod.vdot_from_race(10000, base * 10)
    return f"VDOT {v:.1f} · base {pctmod.fmt(base)}"


def anchor_rows(base: float, source: str) -> list:
    """Key-value rows for the anchor table in the Paces tab."""
    races = [r for r in analyze.config_races()
             if (datetime.now() - r["dt"]).days <= analyze.RECENT_RACE_DAYS]
    if races:
        best = max(races, key=lambda r: r["vdot"])
        rows = [
            ("Anchor race", best["event"]),
            ("Date", best["dt"].date().isoformat()),
            ("Result", f"{int(best['distance_m'])} m in {vdotmod.time_str(best['time_s'])}"),
            ("VDOT", f"{best['vdot']:.1f}"),
            ("10k equivalent", vdotmod.time_str(vdotmod.race_time(best["vdot"], 10000))),
        ]
    else:
        rows = [("Source", source)]
    rows.append(("Base pace (100%)", pctmod.fmt(base)))
    return [{"k": k, "v": val} for k, val in rows]


# steady-day duration estimate: makes the time cost of the prescribed km
# visible, so rising fitness (faster anchor) visibly shrinks these numbers
# and flags when a day has become too short for the level
STEADY_RANGES = {"easy": (55, 65), "long": (60, 70)}


def duration_estimate(day: dict, base: float) -> str | None:
    rng = STEADY_RANGES.get(day["type"])
    if not rng or not day.get("km") or day.get("workout"):
        return None
    lo, hi = rng
    fast = day["km"] * pctmod.pace_at_percent(base, hi) / 60
    slow = day["km"] * pctmod.pace_at_percent(base, lo) / 60
    return f"{round(fast)}-{round(slow)} min"


def reeval_info() -> dict:
    """When should paces be re-evaluated? Anchor race + 4 weeks (article rule)."""
    races = [r for r in analyze.config_races()
             if (datetime.now() - r["dt"]).days <= analyze.RECENT_RACE_DAYS]
    if not races:
        return {"status": "overdue", "anchor_date": None, "age_days": None,
                "message": "No race within 90 days - anchor is inferred. "
                           "Race a parkrun/5k time trial to set a solid anchor."}
    best = max(races, key=lambda r: r["vdot"])
    anchor_date = best["dt"].date()
    age = (date.today() - anchor_date).days
    due_date = anchor_date + timedelta(days=28)
    if age > 42:
        return {"status": "overdue", "anchor_date": anchor_date.isoformat(), "age_days": age,
                "message": f"Anchor ({best['event']}) is {age} days old - re-anchor now: "
                           "race a parkrun/5k time trial or review with coach."}
    if age >= 28:
        return {"status": "due", "anchor_date": anchor_date.isoformat(), "age_days": age,
                "message": f"Anchor ({best['event']}) is {age} days old - re-evaluation window "
                           "open (~4 weeks): review at the next coach check-in."}
    return {"status": "fresh", "anchor_date": anchor_date.isoformat(), "age_days": age,
            "message": f"Anchor ({best['event']}) is {age} days old - fresh. "
                       f"Next review from {due_date.isoformat()}."}


# one-shot workouts pushed to Garmin from the calendar, keyed by ISO date -
# remembered so the GUI can offer "delete from Garmin" after the page reloads
CREATED_FILE = BASE_DIR / "data" / "created_workouts.json"


def load_created() -> dict:
    if CREATED_FILE.exists():
        return json.loads(CREATED_FILE.read_text(encoding="utf-8"))
    return {}


def save_created(created: dict) -> None:
    CREATED_FILE.parent.mkdir(parents=True, exist_ok=True)
    CREATED_FILE.write_text(json.dumps(created, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8")


def raw_text(day: dict) -> str:
    """The day as plan shorthand - what the inline editor prefills with."""
    if day["type"] == "off":
        return "rest"
    if day.get("workout"):
        return day["workout"]
    if day.get("km"):
        return f"{day['km']}km {day['type']}"
    return ""


def next_checkin(p: dict) -> str:
    start = date.fromisoformat(p["start_date"])
    d = start + timedelta(days=13)  # Sunday of week 2, then fortnightly
    while d < date.today():
        d += timedelta(days=14)
    return d.isoformat()


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/paces")
def paces_page():
    return redirect("/")  # paces is a tab on the main page now


# data/ is deliberately not watched: sync writes constantly, and the sync
# button already re-fetches the plan when it finishes
WATCH_PATHS = [BASE_DIR / "config.json", BASE_DIR / "static",
               BASE_DIR / "plans", BASE_DIR / "scripts"]


@app.route("/api/version")
def api_version():
    """Newest mtime across watched files - the pages poll this and reload
    themselves when it changes (hot reload without pressing F5)."""
    latest = 0.0
    for root in WATCH_PATHS:
        for p in ([root] if root.is_file() else root.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts:
                latest = max(latest, p.stat().st_mtime)
    return jsonify({"version": latest})


@app.route("/api/plan")
@app.route("/api/plan/<name>")
def api_plan(name=None):
    name = name or planmod.active_plan()
    if name not in planmod.PLAN_FILES:
        return jsonify({"error": f"unknown plan '{name}'"}), 404
    p = planmod.apply_overrides(planmod.load_plan(name))
    notes = p.get("notes") or []
    tips = notes if isinstance(notes, list) else [notes]
    base, source = planmod.current_anchor()
    actuals = planmod.actual_km_by_date()
    created = load_created()
    results = {r["date"]: r["time"]
               for r in json.loads((BASE_DIR / "config.json")
                                   .read_text(encoding="utf-8")).get("races", [])}

    weeks = []
    for w in p["weeks"]:
        dates = planmod.week_dates(p, w["week"])
        days = []
        for d in planmod.DAY_ORDER:
            day = w["days"][d]
            days.append({
                "day": d,
                "date": dates[d],
                "type": day["type"],
                "km": day.get("km", 0),
                "text": planmod.describe(day, base),
                "raw": raw_text(day),
                "sessions": planmod.split_sessions(day),
                "result": results.get(dates[d]) if day["type"] == "race" else None,
                "edited": bool(day.get("_edited")),
                "garmin": {"day": created.get(dates[d]),
                           "am": created.get(dates[d] + ":am"),
                           "pm": created.get(dates[d] + ":pm")},
                "est": duration_estimate(day, base),
                "status": planmod.status_mark(day, dates[d], actuals).strip() or "upcoming",
                "actual_km": round(actuals.get(dates[d], 0.0), 1),
            })
        weeks.append({
            "week": w["week"],
            "phase": w["phase"],
            "volume_km": w["volume_km"],
            "actual_km": round(sum(d["actual_km"] for d in days), 1),
            "days": days,
        })

    return jsonify({
        "name": p["name"],
        "config": planmod.plan_config(),
        "next_race": planmod.next_race(),
        "start_date": p["start_date"],
        "tips": tips,
        "anchor": source,
        "anchor_short": anchor_summary(base),
        "anchor_rows": anchor_rows(base, source),
        "base_pace_s_per_km": round(base, 1),
        "today": date.today().isoformat(),
        "current_week": planmod.current_week_no(p),
        "legend": build_legend(base),
        "reeval": reeval_info(),
        "next_checkin": next_checkin(p),
        "weeks": weeks,
    })


@app.route("/api/paces/refresh", methods=["POST"])
def api_paces_refresh():
    """Recompute the anchor and persist a dated snapshot (house rule: every
    pace calculation is saved). Re-pressing on the same day just overwrites
    the day's snapshot - a no-op."""
    base, source = planmod.current_anchor()
    rows = {f"{p:g}%": pctmod.fmt(pctmod.pace_at_percent(base, p))
            for p, _ in pctmod.STANDARD_ZONES}
    pctmod.HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    snap = {
        "calculated_at": datetime.now().isoformat(timespec="seconds"),
        "convention": "linear percent of pace: target = base_pace * (2 - pct/100)",
        "base_pace_s_per_km": round(base, 1),
        "anchor": source,
        "paces": rows,
    }
    out = pctmod.HISTORY_DIR / f"percent-{date.today().isoformat()}.json"
    out.write_text(json.dumps(snap, indent=2), encoding="utf-8")
    return jsonify({"ok": True, "anchor": source})


@app.route("/api/stats")
def api_stats():
    """Health metrics + lifetime mileage summary for the Stats tab."""
    try:
        df = analyze.load_index()
    except SystemExit:
        return jsonify({"health": [], "monthly": [], "weekly": []})
    physio = analyze.load_physiology()

    health = []
    mm = physio.get("max_metrics")
    if isinstance(mm, list) and mm:
        mm = mm[0]
    vo2 = None
    if isinstance(mm, dict):
        vo2 = (analyze.find_key(mm, {"vo2maxprecisevalue"})
               or analyze.find_key(mm, {"vo2maxvalue"}))
    if not vo2:
        rec = df["vo2max"].dropna()
        vo2 = rec.iloc[-1] if len(rec) else None
    if vo2:
        health.append({"k": "VO2max", "v": f"{float(vo2):g}"})
    lthr = analyze.athlete_setting("lactate_threshold_hr") or analyze.find_key(
        physio.get("lactate_threshold"), {"heartrate", "lactatethresholdheartrate"})
    if lthr:
        health.append({"k": "Lactate threshold HR", "v": f"{int(lthr)} bpm"})
    lt_speed = analyze.find_key(physio.get("lactate_threshold"),
                                {"speed", "lactatethresholdspeed"})
    if lt_speed:  # Garmin reports LT speed in 0.1 m/s units
        health.append({"k": "Lactate threshold pace", "v": vdotmod.pace_str(lt_speed * 600)})
    max_hr = analyze.athlete_setting("max_hr") or analyze.observed_max_hr(df)
    if max_hr:
        health.append({"k": "Max HR (12 mo)", "v": f"{int(max_hr)} bpm"})
    rhr = analyze.find_key(physio.get("resting_hr"), {"value"})
    if rhr:
        health.append({"k": "Resting HR (today)", "v": f"{int(rhr)} bpm"})
    preds = analyze.garmin_predictions(physio)
    if preds.get("10k"):
        health.append({"k": "Garmin 10k prediction", "v": vdotmod.time_str(preds["10k"])})
    if physio.get("fetched_at"):
        health.append({"k": "Garmin data as of", "v": physio["fetched_at"]})

    # treadmill/indoor runs count toward volume but are excluded from the
    # weekly avg pace (their pace data is unreliable). One row per calendar
    # week from the first synced run through the current week - zero weeks
    # included, so gaps are visible and the safe-cap line stays continuous.
    by_week = {}
    for wk, g in df.groupby(df["start_time"].dt.to_period("W").dt.start_time.dt.date):
        outdoor = g[~g["type"].isin(analyze.INDOOR_TYPES)]
        km_out = float(outdoor["distance_km"].sum())
        pace_s = outdoor["duration_min"].sum() * 60 / km_out if km_out else None
        hg = g.dropna(subset=["avg_hr", "duration_min"])
        hr = (float((hg["avg_hr"] * hg["duration_min"]).sum() / hg["duration_min"].sum())
              if len(hg) and hg["duration_min"].sum() else None)
        by_week[wk] = {"runs": int(len(g)),
                       "km": round(float(g["distance_km"].sum()), 1),
                       "longest": round(float(g["distance_km"].max()), 1),
                       "pace_s": round(pace_s, 1) if pace_s else None,
                       "hr": round(hr) if hr else None}

    this_monday = date.today() - timedelta(days=date.today().weekday())
    weekly, cursor = [], min(by_week)
    while cursor <= this_monday:
        row = by_week.get(cursor) or {"runs": 0, "km": 0, "longest": 0,
                                      "pace_s": None, "hr": None}
        weekly.append({"week": cursor.isoformat(), **row})
        cursor += timedelta(days=7)

    # injury-risk heuristics (skip the still-in-progress week):
    # - volume spike vs the previous 3 weeks (load-management rule of thumb)
    # - HR high for the pace: efficiency (speed/HR) well below the athlete's
    #   recent baseline - pace-adjusted, so a hard-workout week doesn't
    #   false-flag, but fatigue/illness/overreaching does
    for i, w in enumerate(weekly):
        flags = []
        prev3 = weekly[max(0, i - 3):i]
        avg3 = sum(p["km"] for p in prev3) / 3 if len(prev3) == 3 else None
        # safe weekly ceiling = the same 1.4x 3-week-avg rule the spike flag
        # uses; shown as a tick on the volume bar (current week included)
        w["cap"] = round(1.4 * avg3, 1) if avg3 else None
        if w["week"] != this_monday.isoformat():
            if avg3:
                if avg3 >= 15 and w["km"] > 1.4 * avg3:
                    sev = min(5, 1 + int((w["km"] / avg3 - 1.4) / 0.2))
                    flags.append({"text": f"volume spike: {w['km']:g} km vs "
                                          f"{avg3:.0f} km 3-week avg", "sev": sev})
            # single-run weeks are excluded: one walk-run or race skews the
            # weekly average too much to judge efficiency
            if w["pace_s"] and w["hr"] and w["runs"] >= 2:
                base = [60000 / p["pace_s"] / p["hr"]
                        for p in weekly[max(0, i - 6):i]
                        if p["pace_s"] and p["hr"] and p["runs"] >= 2]
                if len(base) >= 3:
                    base_ef = sorted(base)[len(base) // 2]
                    ef = 60000 / w["pace_s"] / w["hr"]
                    if ef < 0.90 * base_ef:
                        drop = 1 - ef / base_ef
                        sev = min(5, 1 + int((drop - 0.10) / 0.04))
                        flags.append({"text": f"HR high for the pace "
                                              f"({drop * 100:.0f}% below usual efficiency)",
                                      "sev": sev})
        w["flags"] = flags
        w["pace"] = pctmod.fmt(w["pace_s"]) if w["pace_s"] else "-"
        w["hr"] = w["hr"] if w["hr"] else "-"
    weekly.reverse()

    return jsonify({"health": health, "weekly": weekly})


@app.route("/api/efforts")
def api_efforts():
    """Best rolling efforts (last 8 weeks) computed from raw GPS streams.
    Separate endpoint because parsing every stream takes a few seconds."""
    try:
        df = analyze.load_index()
    except SystemExit:
        return jsonify({"efforts": [], "window_days": analyze.EFFORT_WINDOW_DAYS})
    bests = analyze.recent_best_efforts(df)
    max_hr_ref = analyze.athlete_setting("max_hr") or analyze.observed_max_hr(df)
    worthy = analyze.race_worthy_efforts(bests, max_hr_ref)
    labels = {1000: "1 km", 1609: "1 mile", 3000: "3 km", 5000: "5 km", 10000: "10 km"}
    efforts = []
    for target in sorted(bests):
        b = bests[target]
        efforts.append({
            "dist": labels.get(target, f"{target} m"),
            "time": vdotmod.time_str(b["time_s"]),
            "pace": vdotmod.pace_str(target / (b["time_s"] / 60)),
            "vdot": round(b["vdot"], 1),
            "hr": round(b["avg_hr"]) if b.get("avg_hr") else None,
            "date": b["date"],
            "anchor_grade": target in worthy,
        })
    return jsonify({"efforts": efforts, "window_days": analyze.EFFORT_WINDOW_DAYS})


# effort score = Banister TRIMP: duration x an exponential of heart-rate
# reserve, so twenty hard minutes outweigh an hour of jogging. Buckets are
# quantiles of the athlete's own history - "hard" means hard *for Ben*, and
# the scale recalibrates itself as fitness and volume evolve.
EFFORT_LABELS = ["easy", "moderate", "hard", "very hard", "max"]
EFFORT_QUANTILES = [0.35, 0.65, 0.85, 0.95]


def trimp(duration_min, avg_hr, max_hr, rest_hr) -> float | None:
    if not (duration_min and avg_hr and max_hr and max_hr > rest_hr):
        return None
    hrr = min(1.0, max(0.0, (avg_hr - rest_hr) / (max_hr - rest_hr)))
    return duration_min * hrr * 0.64 * math.exp(1.92 * hrr)


@app.route("/api/activities")
def api_activities():
    """Every synced run for the Activities tab, newest first, each carrying
    a projected effort level (see trimp above)."""
    try:
        df = analyze.load_index()
    except SystemExit:
        return jsonify({"activities": [], "athlete_max_hr": None, "rest_hr": None})
    athlete_max = analyze.athlete_setting("max_hr") or analyze.observed_max_hr(df)
    rest_hr = analyze.find_key(analyze.load_physiology().get("resting_hr"),
                               {"value"}) or 60

    def num(v):
        return float(v) if pd.notna(v) else None

    acts = []
    for _, r in df.sort_values("start_time", ascending=False).iterrows():
        dur, hr, km = num(r["duration_min"]), num(r["avg_hr"]), num(r["distance_km"])
        load = trimp(dur, hr, athlete_max, rest_hr)
        acts.append({
            "date": r["start_time"].strftime("%Y-%m-%d"),
            "name": str(r["name"]),
            "type": str(r["type"]),
            "indoor": r["type"] in analyze.INDOOR_TYPES,
            "km": round(km, 2) if km else 0,
            "duration_min": round(dur, 1) if dur else None,
            "pace_s": num(r["avg_pace_s_per_km"]),
            "avg_hr": round(hr) if hr else None,
            "max_hr": round(num(r["max_hr"])) if num(r["max_hr"]) else None,
            "pct_max": round(100 * hr / athlete_max) if hr and athlete_max else None,
            "elev": round(num(r["elevation_gain_m"]) or 0),
            "cadence": round(num(r["avg_cadence"])) if num(r["avg_cadence"]) else None,
            "aerobic_te": num(r["aerobic_te"]),
            "load": round(load) if load else None,
        })

    loads = sorted(a["load"] for a in acts if a["load"])
    cuts = ([loads[min(len(loads) - 1, int(q * len(loads)))] for q in EFFORT_QUANTILES]
            if loads else [])
    for a in acts:
        lvl = 1 + sum(a["load"] > c for c in cuts) if a["load"] else None
        a["effort"] = lvl
        a["effort_label"] = EFFORT_LABELS[lvl - 1] if lvl else None
    return jsonify({"activities": acts, "athlete_max_hr": athlete_max, "rest_hr": rest_hr})


@app.route("/api/workout", methods=["POST"])
def api_workout():
    """Create the day's session as a structured Garmin workout and schedule
    it on that date. Body: {plan, week, day, session?} - session 'am'/'pm'
    picks one half of a doubles day ('AM: ...; PM: ...'); the whole-day
    string is never uploaded as one mashed workout. Quality days use the
    plan's own workout string (workout.py grammar); plain easy/long days
    become a single target-free step."""
    req = request.get_json(force=True)
    try:
        p = planmod.apply_overrides(planmod.load_plan(req.get("plan")))
        week_no = int(req["week"])
        day_key = req["day"]
        day = p["weeks"][week_no - 1]["days"][day_key]
        day_date = planmod.week_dates(p, week_no)[day_key]
        session = (req.get("session") or "").lower() or None
    except (KeyError, IndexError, ValueError) as e:
        return jsonify({"ok": False, "error": f"bad request: {e}"}), 400

    spec = day.get("workout")
    name = None
    sessions = planmod.split_sessions(day)
    if session:
        if not sessions or session not in sessions:
            return jsonify({"ok": False, "error": "no AM/PM sessions on this day"}), 400
        spec = sessions[session]
        # tag AM/PM so the day's two library entries are telling apart
        name = f"{session.upper()} {workoutmod.auto_name(workoutmod.parse_spec(spec))}"
    elif sessions:
        return jsonify({"ok": False, "error": "doubles day - pass session 'am' or 'pm'"}), 400
    if not spec:
        if day["type"] in ("easy", "long") and day.get("km"):
            spec = f"{day['km']}km {day['type']}"
            name = f"{day['km']}km {day['type']}"
        else:
            return jsonify({"ok": False, "error": "no session on this day"}), 400
    try:
        r = workoutmod.create(spec, name=name, date_str=day_date)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    created = load_created()
    key = f"{day_date}:{session}" if session else day_date
    created[key] = {"id": r["id"], "name": r["name"], "url": r["url"]}
    save_created(created)
    return jsonify({"ok": True, **r})


@app.route("/api/garmin-workouts")
def api_garmin_workouts():
    """The whole Garmin workout library for the Workouts tab, newest first.
    Workouts created from the calendar carry their scheduled date."""
    try:
        raw = workoutmod.get_client().get_workouts(0, 200)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    scheduled = {v["id"]: day for day, v in load_created().items()}
    outs = [{
        "id": w["workoutId"],
        "name": w.get("workoutName") or str(w["workoutId"]),
        "description": w.get("description") or "",
        "sport": (w.get("sportType") or {}).get("sportTypeKey"),
        "created": (w.get("createdDate") or "")[:10],
        "est_min": round(w["estimatedDurationInSecs"] / 60)
                   if w.get("estimatedDurationInSecs") else None,
        "scheduled": scheduled.get(w["workoutId"]),
        # Garmin refuses to delete workouts owned by a (Garmin Coach /
        # adaptive) training plan - flag them so the GUI doesn't offer it
        "locked": bool(w.get("atpPlanId") or w.get("trainingPlanId")),
    } for w in raw]
    outs.sort(key=lambda w: w["created"], reverse=True)
    return jsonify({"ok": True, "workouts": outs})


@app.route("/api/workout/<int:wid>", methods=["DELETE"])
def api_workout_delete(wid):
    """Remove a one-shot workout from the Garmin library (and its calendar
    schedule) once it's no longer needed, and forget it locally."""
    try:
        workoutmod.get_client().delete_workout(str(wid))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    created = {k: v for k, v in load_created().items() if v.get("id") != wid}
    save_created(created)
    return jsonify({"ok": True})


@app.route("/api/plan-config", methods=["POST"])
def api_plan_config():
    """Update the program dates in config.json's plan block. The start date
    snaps to its week's Monday; a blank end date clears it (the program then
    runs to the auto-detected next race, or default_weeks). The next race
    itself lives in the races list (settings modal), not here."""
    req = request.get_json(force=True)
    path = BASE_DIR / "config.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    plan = cfg.setdefault("plan", {})
    try:
        if req.get("start_date"):
            d = date.fromisoformat(req["start_date"])
            plan["start_date"] = (d - timedelta(days=d.weekday())).isoformat()
        if "end_date" in req:
            if req["end_date"]:
                plan["end_date"] = date.fromisoformat(req["end_date"]).isoformat()
            else:
                plan.pop("end_date", None)
    except (ValueError, TypeError) as e:
        return jsonify({"ok": False, "error": f"bad request: {e}"}), 400
    if plan.get("end_date") and plan["end_date"] < plan.get("start_date", ""):
        return jsonify({"ok": False, "error": "end date is before the start date"}), 400
    path.write_text(dump_config(cfg), encoding="utf-8")
    return jsonify({"ok": True, "plan": plan})


def dump_config(cfg: dict) -> str:
    """config.json stays hand-editable: normal 2-space indent, but each past
    race keeps to one line the way Ben formats them."""
    out = json.dumps(cfg, indent=2)
    races = cfg.get("races")
    if isinstance(races, list) and races:
        compact = ",\n".join(
            "    " + json.dumps(r, separators=(", ", ": ")) for r in races)
        out = re.sub(r'"races": \[.*\n  \]',
                     lambda m: '"races": [\n' + compact + "\n  ]", out, flags=re.S)
    return out + "\n"


@app.route("/api/races", methods=["GET", "PUT"])
def api_races():
    """The race history behind the pace anchor, editable from the GUI's
    settings modal. PUT replaces the whole list (validated), so add / edit /
    delete are all one operation - no hand-editing config.json."""
    path = BASE_DIR / "config.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    if request.method == "GET":
        today = date.today().isoformat()
        future = [r["date"] for r in cfg.get("races", []) if r.get("date", "") >= today]
        nxt = min(future) if future else None
        recent = [r for r in analyze.config_races()
                  if (datetime.now() - r["dt"]).days <= analyze.RECENT_RACE_DAYS]
        anchor = max(recent, key=lambda r: r["vdot"])["date"] if recent else None
        out = []
        for r in cfg.get("races", []):
            e = dict(r)
            if str(r.get("time") or "").strip():
                try:
                    e["vdot"] = round(vdotmod.vdot_from_race(
                        float(r["distance_m"]), vdotmod.parse_time(str(r["time"]))), 1)
                except (KeyError, ValueError, TypeError):
                    pass
            e["upcoming"] = r.get("date", "") >= today
            e["next"] = r.get("date") == nxt and not str(r.get("time") or "").strip()
            e["anchor"] = bool(anchor) and r.get("date") == anchor and bool(e.get("vdot"))
            out.append(e)
        return jsonify({"races": out})
    races = []
    try:
        for r in request.get_json(force=True).get("races", []):
            entry = {
                "event": str(r.get("event") or "").strip() or "Race",
                "date": date.fromisoformat(str(r["date"]).strip()).isoformat(),
                "distance_m": int(r["distance_m"]),
                "time": str(r["time"]).strip(),
            }
            if entry["distance_m"] <= 0:
                raise ValueError(f"bad distance for {entry['event']}")
            # no time = an upcoming race: it becomes "next race" on the plan
            # and is skipped by the pace anchor until the result lands
            if entry["time"] and not re.fullmatch(r"(\d+:)?[0-5]?\d:[0-5]\d", entry["time"]):
                raise ValueError(f"bad time '{entry['time']}' - use mm:ss or h:mm:ss")
            races.append(entry)
    except (KeyError, ValueError, TypeError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    races.sort(key=lambda r: r["date"])
    cfg["races"] = races
    path.write_text(dump_config(cfg), encoding="utf-8")
    return jsonify({"ok": True, "races": races})


@app.route("/api/race-result", methods=["POST"])
def api_race_result():
    """Record a race result straight from the calendar's race-day cell.
    Body: {date, time, distance_km?, event?}. Appends to config.json races
    (replacing a same-date entry), so a recent result immediately becomes
    the pace anchor - no hand-editing."""
    req = request.get_json(force=True)
    try:
        day = date.fromisoformat(req["date"]).isoformat()
    except (KeyError, ValueError) as e:
        return jsonify({"ok": False, "error": f"bad request: {e}"}), 400
    time_str = str(req.get("time") or "").strip()
    if not re.fullmatch(r"(\d+:)?[0-5]?\d:[0-5]\d", time_str):
        return jsonify({"ok": False, "error": "time must look like 52:30 or 1:53:44"}), 400
    path = BASE_DIR / "config.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    races = cfg.setdefault("races", [])
    # fill the result into the planned entry for that date (keeps the event
    # name/distance from settings); only create one if none exists
    existing = next((r for r in races if r.get("date") == day), None)
    try:
        km = float(req.get("distance_km") or 0) or (
            existing["distance_m"] / 1000 if existing else 10)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "bad distance"}), 400
    entry = existing or {"event": "", "date": day, "distance_m": 0, "time": ""}
    entry["event"] = (str(req.get("event") or "").strip()
                      or entry["event"] or f"{km:g}km race")
    entry["distance_m"] = int(round(km * 1000))
    entry["time"] = time_str
    if not existing:
        races.append(entry)
    races.sort(key=lambda r: r["date"])
    path.write_text(dump_config(cfg), encoding="utf-8")
    return jsonify({"ok": True, "entry": entry})


@app.route("/api/day", methods=["POST"])
def api_day_edit():
    """Override one plan day. Body: {date, text} - text in plan shorthand;
    'rest' (or blank) makes it an off day. Saved to plans/overrides.json."""
    req = request.get_json(force=True)
    try:
        day_date = date.fromisoformat(req["date"]).isoformat()
    except (KeyError, ValueError) as e:
        return jsonify({"ok": False, "error": f"bad request: {e}"}), 400
    overrides = planmod.load_overrides()
    overrides[day_date] = planmod.day_from_text(str(req.get("text", "")))
    planmod.save_overrides(overrides)
    return jsonify({"ok": True})


@app.route("/api/day/<day_date>", methods=["DELETE"])
def api_day_restore(day_date):
    """Drop the override for a date - the day reverts to the plan's original."""
    overrides = planmod.load_overrides()
    if day_date in overrides:
        del overrides[day_date]
        planmod.save_overrides(overrides)
    return jsonify({"ok": True})


@app.route("/api/sync", methods=["POST"])
def api_sync():
    """Incremental Garmin sync - idempotent, safe to press any time."""
    try:
        r = subprocess.run([sys.executable, "scripts/sync.py"], capture_output=True,
                           text=True, cwd=str(BASE_DIR), timeout=600)
        lines = (r.stdout or r.stderr or "").strip().splitlines()
        return jsonify({"ok": r.returncode == 0, "output": "\n".join(lines[-4:])})
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "output": "sync timed out"}), 500


if __name__ == "__main__":
    print("Training plan GUI: http://127.0.0.1:5001")
    app.run(host=os.getenv("HOST", "127.0.0.1"), port=5001,
            debug=os.getenv("FLASK_DEBUG", "0") == "1")
