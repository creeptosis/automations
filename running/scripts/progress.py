"""Fitness and pace progression over time.

Combines the race history (config.json) with every saved pace snapshot
(data/paces_history/) into a chronological view: is VDOT trending up, and
what training paces were prescribed when.

Usage: python scripts/progress.py
"""

import json

import analyze
import vdot

HISTORY_DIR = analyze.DATA_DIR / "paces_history"


def main():
    print("--- Race fitness over time (config.json) ---")
    for r in analyze.config_races():
        velocity = float(r["distance_m"]) / (r["time_s"] / 60)
        print(f"  {r['dt'].date()}  VDOT {r['vdot']:.1f}  {vdot.pace_str(velocity):>8}  {r['event']}")

    snaps = sorted(HISTORY_DIR.glob("vdot-*.json"))
    if snaps:
        print("\n--- Prescribed training paces over time (paces.py runs) ---")
        for path in snaps:
            s = json.loads(path.read_text(encoding="utf-8"))
            tp = s["training_paces"]
            print(f"  {s['calculated_at'][:10]}  VDOT {s['vdot']:>4}  "
                  f"T {tp['T']}  I {tp['I']}  10k eq {s['equivalent_race_times']['10k']}")

    snaps = sorted(HISTORY_DIR.glob("percent-*.json"))
    if snaps:
        print("\n--- Plan base pace over time (percent.py runs) ---")
        for path in snaps:
            s = json.loads(path.read_text(encoding="utf-8"))
            base = s["base_pace_s_per_km"]
            print(f"  {s['calculated_at'][:10]}  100% = {int(base // 60)}:{int(round(base % 60)):02d}/km")

    print("\nImprovement = VDOT trending up, same-percentage paces getting faster.")


if __name__ == "__main__":
    main()
