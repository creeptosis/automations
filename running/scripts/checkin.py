"""Coach check-in digest: the last 14 days vs the plan, in one compact block.

Run after a sync, then hand the output to Claude (the coach) for the
fortnightly review. It deliberately outputs data, not judgments - the
knowledge base rules are applied by the coach.

Usage: python scripts/checkin.py [--days 14]
"""

import argparse
import sys
from datetime import date, datetime, timedelta

import pandas as pd

import analyze
import plan as planmod

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main():
    parser = argparse.ArgumentParser(description="Coach check-in digest")
    parser.add_argument("--days", type=int, default=14)
    args = parser.parse_args()

    df = analyze.load_index()
    cutoff = datetime.now() - timedelta(days=args.days)
    recent = df[df["start_time"] >= cutoff].copy()

    print(f"=== CHECK-IN DIGEST: last {args.days} days (generated {date.today()}) ===")

    print("\n-- Runs --")
    if recent.empty:
        print("  none")
    for _, r in recent.iterrows():
        pace = r["avg_pace_s_per_km"]
        pace_s = f"{int(pace // 60)}:{int(pace % 60):02d}/km" if pd.notna(pace) else "?"
        ef = (1000 / pace) * 60 / r["avg_hr"] if pd.notna(pace) and pd.notna(r["avg_hr"]) and r["avg_hr"] else None
        ef_s = f"  EF {ef:.2f}" if ef else ""
        print(f"  {str(r['start_time'])[:10]}  {r['distance_km']:>5.1f}km  {pace_s:>8}  "
              f"HR {r['avg_hr'] if pd.notna(r['avg_hr']) else '?'}/{r['max_hr'] if pd.notna(r['max_hr']) else '?'}"
              f"{ef_s}")

    print(f"\n-- Plan adherence ({planmod.active_plan()}) --")
    p = planmod.load_plan()
    actuals = planmod.actual_km_by_date()
    start = date.fromisoformat(p["start_date"])
    for w in p["weeks"]:
        dates = planmod.week_dates(p, w["week"])
        if date.fromisoformat(dates["sun"]) < date.today() - timedelta(days=args.days):
            continue
        if date.fromisoformat(dates["mon"]) > date.today():
            break
        marks = "".join(planmod.status_mark(w["days"][d], dates[d], actuals) for d in planmod.DAY_ORDER)
        actual = sum(actuals.get(dates[d], 0) for d in planmod.DAY_ORDER)
        print(f"  week {w['week']:>2} ({dates['mon']})  [{marks}]  planned ~{w['volume_km']}km, ran {actual:.0f}km")

    print("\n-- Quality-day detail (planned tempo/interval days) --")
    for w in p["weeks"]:
        dates = planmod.week_dates(p, w["week"])
        for d in planmod.DAY_ORDER:
            day = w["days"][d]
            if day["type"] not in ("tempo", "intervals", "race"):
                continue
            dd = dates[d]
            if not (date.today() - timedelta(days=args.days) <= date.fromisoformat(dd) <= date.today()):
                continue
            runs = recent[recent["start_time"].astype(str).str.startswith(dd)]
            if runs.empty:
                print(f"  {dd} planned: {day.get('workout', day['type'])[:60]}  -> NOT RUN")
            for _, r in runs.iterrows():
                pace = r["avg_pace_s_per_km"]
                pace_s = f"{int(pace // 60)}:{int(pace % 60):02d}/km" if pd.notna(pace) else "?"
                print(f"  {dd} planned: {day.get('workout', day['type'])[:60]}")
                print(f"           ran: {r['distance_km']:.1f}km @ {pace_s}, HR {r['avg_hr']}/{r['max_hr']}, "
                      f"aerobicTE {r['aerobic_te']}, anaerobicTE {r['anaerobic_te']}")

    print("\n-- Physiology now --")
    physio = analyze.load_physiology()
    lthr = analyze.find_key(physio.get("lactate_threshold"), {"heartrate"})
    vo2 = df["vo2max"].dropna()
    print(f"  VO2max (latest run): {vo2.iloc[-1] if len(vo2) else 'n/a'}   LTHR: {lthr or 'n/a'}")
    preds = analyze.garmin_predictions(physio)
    if preds.get("10k"):
        import vdot
        print(f"  Garmin 10k prediction: {vdot.time_str(preds['10k'])}")

    print("\n-- Coach checklist (subjective - ask Ben) --")
    print("  1. Any soreness lasting >48h? Localized/one-sided?")
    print("  2. Do the first minutes of runs feel unusually hard?")
    print("  3. Motivation normal?")
    print("  4. How did the 95-100% workouts FEEL - controlled or strained?")


if __name__ == "__main__":
    main()
