"""Sync running data from Garmin Connect into data/.

- data/activities/<id>.json : summary + detail streams + splits + HR-in-zones
  per run (incremental: already-downloaded activities are skipped)
- data/activities.csv       : one-row-per-run index for quick analysis
- data/physiology.json      : latest VO2max, lactate threshold, race
  predictions, training status, PRs, user profile

Usage:
    python scripts/sync.py            # last 365 days
    python scripts/sync.py --days 90
"""

import argparse
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from garmin_client import get_client

BASE_DIR = Path(__file__).resolve().parent.parent  # project root
DATA_DIR = BASE_DIR / "data"
ACT_DIR = DATA_DIR / "activities"

# Windows consoles default to a legacy codepage; activity names contain emoji
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def try_fetch(label, fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        print(f"  warning: could not fetch {label}: {e}")
        return None


def incremental_start() -> str:
    """Resume from the newest synced run (2-day overlap); first sync = 365 days."""
    index = DATA_DIR / "activities.csv"
    if index.exists():
        try:
            latest = pd.read_csv(index)["start_time"].max()
            if isinstance(latest, str) and latest:
                return (date.fromisoformat(latest[:10]) - timedelta(days=2)).isoformat()
        except Exception:
            pass
    return (date.today() - timedelta(days=365)).isoformat()


def sync_activities(client, start: str) -> None:
    ACT_DIR.mkdir(parents=True, exist_ok=True)
    end = date.today().isoformat()
    print(f"Fetching running activities {start} .. {end}")
    activities = client.get_activities_by_date(start, end, "running")
    print(f"Found {len(activities)} runs")

    new = 0
    for act in activities:
        aid = str(act["activityId"])
        path = ACT_DIR / f"{aid}.json"
        if path.exists():
            continue
        name = act.get("activityName", "")
        when = act.get("startTimeLocal", "")
        print(f"  downloading {when} {name} ({aid})")
        record = {
            "summary": act,
            "details": try_fetch("details", client.get_activity_details, aid),
            "splits": try_fetch("splits", client.get_activity_splits, aid),
            "hr_zones": try_fetch("hr zones", client.get_activity_hr_in_timezones, aid),
        }
        path.write_text(json.dumps(record), encoding="utf-8")
        new += 1
        time.sleep(0.4)  # be polite to Garmin's servers
    print(f"Downloaded {new} new runs ({len(activities) - new} already cached)")


def build_index() -> None:
    rows = []
    for path in sorted(ACT_DIR.glob("*.json")):
        s = json.loads(path.read_text(encoding="utf-8")).get("summary", {})
        dist_m = s.get("distance") or 0
        dur_s = s.get("duration") or 0
        rows.append({
            "activity_id": s.get("activityId"),
            "start_time": s.get("startTimeLocal"),
            "name": s.get("activityName"),
            "type": (s.get("activityType") or {}).get("typeKey"),
            "distance_km": round(dist_m / 1000, 2),
            "duration_min": round(dur_s / 60, 1),
            "avg_pace_s_per_km": round(dur_s / (dist_m / 1000), 1) if dist_m else None,
            "avg_hr": s.get("averageHR"),
            "max_hr": s.get("maxHR"),
            "elevation_gain_m": s.get("elevationGain"),
            "avg_cadence": s.get("averageRunningCadenceInStepsPerMinute"),
            "aerobic_te": s.get("aerobicTrainingEffect"),
            "anaerobic_te": s.get("anaerobicTrainingEffect"),
            "vo2max": s.get("vO2MaxValue"),
        })
    df = pd.DataFrame(rows).sort_values("start_time")
    df.to_csv(DATA_DIR / "activities.csv", index=False)
    print(f"Index written: {DATA_DIR / 'activities.csv'} ({len(df)} runs)")


def sync_physiology(client) -> None:
    today = date.today().isoformat()
    physio = {
        "fetched_at": today,
        "max_metrics": try_fetch("VO2max", client.get_max_metrics, today),
        "race_predictions": try_fetch("race predictions", client.get_race_predictions),
        "lactate_threshold": try_fetch(
            "lactate threshold", client.get_lactate_threshold, latest=True
        ),
        "training_status": try_fetch("training status", client.get_training_status, today),
        "personal_records": try_fetch("personal records", client.get_personal_record),
        "user_profile": try_fetch("user profile", client.get_user_profile),
        "resting_hr": try_fetch("resting HR", client.get_rhr_day, today),
    }
    out = DATA_DIR / "physiology.json"
    out.write_text(json.dumps(physio, indent=2), encoding="utf-8")
    print(f"Physiology snapshot written: {out}")


def main():
    parser = argparse.ArgumentParser(description="Sync runs from Garmin Connect")
    parser.add_argument("--days", type=int, default=None,
                        help="how far back to sync (default: incremental, since last synced run)")
    args = parser.parse_args()

    if args.days:
        start = (date.today() - timedelta(days=args.days)).isoformat()
    else:
        start = incremental_start()

    client = get_client()
    sync_activities(client, start)
    build_index()
    sync_physiology(client)
    print("\nDone. Next: python scripts/analyze.py")


if __name__ == "__main__":
    main()
