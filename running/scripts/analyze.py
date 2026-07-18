"""Current-fitness report from synced Garmin data.

Reports weekly volume, best rolling efforts (computed from per-run distance/time
streams), Garmin physiology (VO2max, lactate threshold, race predictions), and a
current VDOT estimate to anchor training paces.

Usage: python scripts/analyze.py
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

import vdot

# Windows consoles default to a legacy codepage; activity names contain emoji
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent.parent  # project root
DATA_DIR = BASE_DIR / "data"
ACT_DIR = DATA_DIR / "activities"

CONFIG_PATH = BASE_DIR / "config.json"
EFFORT_TARGETS = [1000, 1609, 3000, 5000, 10000]
EFFORT_WINDOW_DAYS = 56  # "current fitness" = what you've shown in ~8 weeks
RECENT_RACE_DAYS = 90  # a race older than this no longer reflects current fitness
MIN_PLAUSIBLE_S_PER_KM = 150  # faster than 2:30/km is GPS noise, not running
INDOOR_TYPES = {"treadmill_running", "indoor_running", "virtual_running"}  # pace unreliable


def load_index() -> pd.DataFrame:
    path = DATA_DIR / "activities.csv"
    if not path.exists():
        raise SystemExit("No data yet. Run: python scripts/sync.py")
    df = pd.read_csv(path, parse_dates=["start_time"])
    return df.dropna(subset=["start_time"])


def load_streams(activity_id) -> list | None:
    """Return [(elapsed_s, distance_m, hr), ...] from a run's detail stream."""
    path = ACT_DIR / f"{int(activity_id)}.json"
    if not path.exists():
        return None
    details = json.loads(path.read_text(encoding="utf-8")).get("details") or {}
    descriptors = details.get("metricDescriptors") or []
    rows = details.get("activityDetailMetrics") or []
    idx = {d.get("key"): d.get("metricsIndex") for d in descriptors}
    dist_i = idx.get("sumDistance")
    dur_i = next(
        (idx[k] for k in ("sumDuration", "sumElapsedDuration", "sumMovingDuration") if k in idx),
        None,
    )
    hr_i = idx.get("directHeartRate")
    if dist_i is None or dur_i is None:
        return None
    pts = []
    for row in rows:
        arr = row.get("metrics") or []
        if dist_i >= len(arr) or dur_i >= len(arr):
            continue
        d, t = arr[dist_i], arr[dur_i]
        if d is None or t is None:
            continue
        hr = arr[hr_i] if hr_i is not None and hr_i < len(arr) else None
        pts.append((t, d, hr))
    pts.sort()
    return pts or None


def best_effort(pts, target_m: float) -> dict | None:
    """Fastest rolling `target_m` within one run (two-pointer scan).

    Returns {'time_s', 'avg_hr'} — avg HR over the winning window lets callers
    reject GPS-noise "efforts" that show race pace at easy-run heart rates.
    """
    best = None
    best_window = None
    i = 0
    for j in range(len(pts)):
        tj, dj = pts[j][0], pts[j][1]
        if dj - pts[i][1] < target_m:
            continue
        while i + 1 < j and dj - pts[i + 1][1] >= target_m:
            i += 1
        t0, d0 = pts[i][0], pts[i][1]
        t1, d1 = pts[i + 1][0], pts[i + 1][1]
        want = dj - target_m
        ts = t0 + (t1 - t0) * (want - d0) / (d1 - d0) if d1 > d0 and d0 <= want <= d1 else t0
        elapsed = tj - ts
        if elapsed <= 0 or (elapsed / target_m) * 1000 < MIN_PLAUSIBLE_S_PER_KM:
            continue
        if best is None or elapsed < best:
            best = elapsed
            best_window = (i, j)
    if best is None:
        return None
    lo, hi = best_window
    hrs = [p[2] for p in pts[lo:hi + 1] if p[2]]
    return {"time_s": best, "avg_hr": sum(hrs) / len(hrs) if hrs else None}


def recent_best_efforts(df: pd.DataFrame, window_days: int = EFFORT_WINDOW_DAYS) -> dict:
    """{target_m: {'time_s', 'date', 'vdot'}} across all runs in the window."""
    cutoff = datetime.now() - timedelta(days=window_days)
    recent = df[(df["start_time"] >= cutoff) & ~df["type"].isin(INDOOR_TYPES)]
    bests = {}
    for _, run in recent.iterrows():
        pts = load_streams(run["activity_id"])
        if not pts:
            continue
        for target in EFFORT_TARGETS:
            b = best_effort(pts, target)
            if b is None:
                continue
            if target not in bests or b["time_s"] < bests[target]["time_s"]:
                bests[target] = {
                    **b,
                    "date": run["start_time"].date().isoformat(),
                    "vdot": vdot.vdot_from_race(target, b["time_s"]),
                }
    return bests


def race_worthy_efforts(bests: dict, max_hr_ref: float | None) -> dict:
    """Efforts solid enough to anchor fitness: 3k+ AND run at a plausibly hard
    heart rate. A genuine 3k+ best sits near/above threshold (~87% max HR);
    race pace at easy-run HR means the GPS flattered the distance."""
    out = {}
    for target, b in bests.items():
        if target < 3000:
            continue
        if b.get("avg_hr") and max_hr_ref and b["avg_hr"] < 0.87 * max_hr_ref:
            continue
        out[target] = b
    return out


def find_key(obj, names: set):
    """Depth-first search for the first numeric value under any of these keys."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.lower() in names and isinstance(v, (int, float)):
                return v
        for v in obj.values():
            r = find_key(v, names)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = find_key(v, names)
            if r is not None:
                return r
    return None


def load_physiology() -> dict:
    path = DATA_DIR / "physiology.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def load_config() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {}


def athlete_setting(key: str):
    return (load_config().get("athlete") or {}).get(key)


def config_races() -> list[dict]:
    """Races from config.json, parsed and sorted by date, with computed VDOT."""
    races = []
    for r in load_config().get("races", []):
        if not str(r.get("time") or "").strip():
            continue  # upcoming race - no result yet, nothing to anchor on
        try:
            dt = datetime.strptime(r["date"], "%Y-%m-%d")
            time_s = vdot.parse_time(str(r["time"]))
            races.append({
                **r,
                "dt": dt,
                "time_s": time_s,
                "vdot": vdot.vdot_from_race(float(r["distance_m"]), time_s),
            })
        except (KeyError, ValueError) as e:
            print(f"  warning: skipping malformed race entry {r}: {e}")
    return sorted(races, key=lambda x: x["dt"])


def garmin_predictions(physio: dict) -> dict:
    rp = physio.get("race_predictions")
    if isinstance(rp, list) and rp:
        rp = rp[0]
    if not isinstance(rp, dict):
        return {}
    labels = {"time5K": "5k", "time10K": "10k", "timeHalfMarathon": "half", "timeMarathon": "marathon"}
    return {label: rp[k] for k, label in labels.items() if rp.get(k)}


def observed_max_hr(df: pd.DataFrame, months: int = 12) -> float | None:
    cutoff = datetime.now() - timedelta(days=months * 30)
    recent = df[df["start_time"] >= cutoff]["max_hr"].dropna()
    return float(recent.max()) if len(recent) else None


def weekly_summary(df: pd.DataFrame, weeks: int = 12) -> pd.DataFrame:
    cutoff = datetime.now() - timedelta(weeks=weeks)
    recent = df[df["start_time"] >= cutoff].copy()
    recent["week"] = recent["start_time"].dt.to_period("W").dt.start_time.dt.date
    return recent.groupby("week").agg(
        runs=("activity_id", "count"),
        km=("distance_km", "sum"),
        minutes=("duration_min", "sum"),
        avg_hr=("avg_hr", "mean"),
    ).round(1)


def main():
    df = load_index()
    physio = load_physiology()

    print("=" * 62)
    print("CURRENT FITNESS REPORT")
    print("=" * 62)

    print(f"\n--- Weekly volume (last 12 weeks) ---")
    weekly = weekly_summary(df)
    print(weekly.to_string())
    if len(weekly):
        last4 = weekly.tail(4)
        print(f"\n4-week average: {last4['km'].mean():.1f} km/wk over {last4['runs'].mean():.1f} runs/wk")

    races = config_races()
    if races:
        print("\n--- Race history (config.json) ---")
        for r in races:
            velocity = float(r["distance_m"]) / (r["time_s"] / 60)
            print(
                f"  {r['dt'].date()}  {r['event']:<22} {int(r['distance_m']):>6}m  "
                f"{vdot.time_str(r['time_s']):>8}  {vdot.pace_str(velocity)}  VDOT {r['vdot']:.1f}"
            )

    print(f"\n--- Best rolling efforts (last {EFFORT_WINDOW_DAYS} days, from GPS streams) ---")
    bests = recent_best_efforts(df)
    if bests:
        for target in sorted(bests):
            b = bests[target]
            velocity = target / (b["time_s"] / 60)
            hr = f"avg HR {b['avg_hr']:.0f}" if b.get("avg_hr") else "no HR"
            print(
                f"  {target:>6}m  {vdot.time_str(b['time_s']):>8}  "
                f"({vdot.pace_str(velocity)})  VDOT {b['vdot']:.1f}  {hr}  on {b['date']}"
            )
        print("  note: race pace at easy-run HR = GPS noise; such efforts are")
        print("  excluded from the verdict below")
    else:
        print("  no stream data available in window")

    print("\n--- Garmin physiology ---")
    mm = physio.get("max_metrics")
    if isinstance(mm, list) and mm:
        mm = mm[0]
    vo2 = None
    if isinstance(mm, dict):
        vo2 = find_key(mm, {"vo2maxprecisevalue"}) or find_key(mm, {"vo2maxvalue"})
    if not vo2:
        recorded = df["vo2max"].dropna()
        if len(recorded):
            vo2 = f"{recorded.iloc[-1]} (from latest run summary)"
    print(f"  VO2max estimate: {vo2 if vo2 else 'n/a'}")

    lthr = find_key(physio.get("lactate_threshold"), {"heartrate", "lactatethresholdheartrate"})
    lt_speed = find_key(physio.get("lactate_threshold"), {"speed", "lactatethresholdspeed"})
    print(f"  Lactate threshold HR: {lthr if lthr else 'n/a'}")
    if lt_speed:  # Garmin reports LT speed in 0.1 m/s units
        print(f"  Lactate threshold pace: {vdot.pace_str(lt_speed * 600)}")

    cfg_max = athlete_setting("max_hr")
    max_hr = observed_max_hr(df)
    print(f"  Max HR: config {cfg_max or 'n/a'} / observed in runs (12 mo) {max_hr or 'n/a'}")
    rhr = find_key(physio.get("resting_hr"), {"value"})
    print(f"  Resting HR (today): {rhr if rhr else 'n/a'}")

    preds = garmin_predictions(physio)
    if preds:
        print("  Garmin race predictions:")
        for label, secs in preds.items():
            print(f"    {label:>9}: {vdot.time_str(secs)}"
                  f"  (implies VDOT {vdot.vdot_from_race(vdot.DISTANCES_M[label], secs):.1f})")

    print("\n--- Current VDOT verdict ---")
    recent_races = [r for r in races if (datetime.now() - r["dt"]).days <= RECENT_RACE_DAYS]
    best_race = max(recent_races, key=lambda r: r["vdot"]) if recent_races else None
    max_hr_ref = cfg_max or max_hr
    race_worthy = race_worthy_efforts(bests, max_hr_ref)
    measured = max((b["vdot"] for b in race_worthy.values()), default=None)
    garmin_vdot = (
        vdot.vdot_from_race(vdot.DISTANCES_M["10k"], preds["10k"]) if preds.get("10k") else None
    )
    if best_race:
        print(f"  Recent race ({best_race['event']}, {best_race['dt'].date()}): "
              f"VDOT {best_race['vdot']:.1f}  <- best possible anchor")
    elif races:
        last = races[-1]
        age = (datetime.now() - last["dt"]).days
        print(f"  Last race was {age} days ago ({last['event']}, VDOT {last['vdot']:.1f})"
              f" - older than {RECENT_RACE_DAYS}d, no longer current fitness")
    if measured:
        print(f"  Measured (best 3k+ effort, {EFFORT_WINDOW_DAYS}d): VDOT {measured:.1f}")
    if garmin_vdot:
        print(f"  Garmin predictor (race-day, optimistic):  VDOT {garmin_vdot:.1f}")
    if best_race:
        print("  A real race inside the window is the truest measure of current fitness.")
        print("\nNext: python scripts/paces.py")
    elif measured:
        print("  Anchor plan paces on the MEASURED number - train where you are,")
        print("  not where the watch thinks you could be on a perfect day.")
        print("\nNext: python scripts/paces.py")
    elif garmin_vdot:
        print("  No trustworthy measured effort in the window - falling back to")
        print("  Garmin's predictor. Confirm with a real race or all-out time trial.")
        print("\nNext: python scripts/paces.py")
    else:
        print("  Not enough data. If you have a recent race: python scripts/paces.py --race 10k 52:30")


if __name__ == "__main__":
    main()
