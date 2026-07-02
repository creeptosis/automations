"""Localhost GUI for the training plan.

Serves the plan with concrete paces (from the current fitness anchor) and
completion status (from synced Garmin runs). No database - everything is
computed live from plans/plan.json + data/.

    python scripts/gui.py   ->  http://127.0.0.1:5001
"""

import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import Flask, jsonify, redirect, send_from_directory

import analyze
import percent as pctmod
import plan as planmod
import vdot as vdotmod

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
    p = planmod.load_plan(name)
    notes = p.get("notes") or []
    tips = notes if isinstance(notes, list) else [notes]
    base, source = planmod.current_anchor()
    actuals = planmod.actual_km_by_date()

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
        "plan_key": name,
        "plans": list(planmod.PLAN_FILES),
        "name": p["name"],
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
