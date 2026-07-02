# Handover — Double-Threshold Training Plan

`training-plan.gs` used to generate a full Ingebrigtsen-style running week (3 tabs) alongside the gym and diet content. The running side was removed on 2026-07-02; the script now builds a gym-and-diet-only tracker (2 tabs: **Weekly Plan** and **Guide & Diet**).

This document is the handover: it preserves everything needed to understand, run, or re-implement the double-threshold plan. **Important:** the running version of the script was never committed to git, so this README is the only record — do not delete it if there is any chance of returning to running.

---

## 1. What "double threshold" is and why it works

Double threshold (the "Norwegian model", popularized by Marius Bakken and the Ingebrigtsen brothers) means running **two threshold sessions on the same day** — one AM, one PM — twice a week, with everything else easy.

The logic:

- **Threshold volume is the main driver of distance fitness**, but a single big threshold session generates too much fatigue and lactate to repeat often.
- Splitting the same total work into **two controlled, sub-threshold sessions** keeps lactate low (~2–3.5 mmol) in each, so you recover overnight and can absorb far more weekly threshold volume than with traditional "one hard workout" training.
- The cost is discipline: **every session must stay controlled**. The moment a threshold session becomes a race, the system collapses — you carry fatigue into the next key day and the volume becomes unsustainable.
- Everything that is not threshold or hills is **genuinely easy** (Zone 1, conversational). Roughly 70% of weekly kilometres are easy.

The plan was deliberately a **single fixed week repeated year-round** — no week-by-week periodization. Progression comes from slowly growing volume within the same structure over months/years, not from changing the structure.

## 2. The zone system

Zones were anchored to **Max HR** (the script used `MAX_HR = 188`; there was an editable copy in the Guide tab cell B2 that live zone formulas referenced).

| Zone | Name | Lactate (mmol) | % Max HR | Trains | % of weekly km |
|------|------|----------------|----------|--------|----------------|
| 1 | Easy distance | 0.7–2.0 | 62–82% | Recovery / aerobic base | ~70% |
| 2 | Threshold | 2.0–4.0 | 82–92% | Endurance | ~25% |
| 3 | Intervals / hills | 4.0–8.0 | 92–97% | Max endurance | ~3% |
| 4 | Anaerobic | >8.0 | >97% | Anaerobic capacity | ~1% |
| 5 | Speed | – | max (not HR-paced) | Max speed | ~0.5% |

Key nuance: Zone 1 technically spans 62–82%, but **82% is the line where threshold begins, not a target**. Daily easy runs live at the low end (~65–75% MHR); recovery-day doubles even lower. Easy runs creeping toward 80%+ = grey zone = stagnation or overtraining.

## 3. The full reference week (as it existed in the script)

This was the exact `weekStructure_()` content. Gym items marked ✱ still exist in the current gym-only plan.

| Day | Focus | Sessions |
|-----|-------|----------|
| **Mon** | Easy + Upper A | AM easy 10 km (Z1) · PM easy 10 km + 6–8 strides · Upper body A ✱ · Abs ✱ |
| **Tue** | **Double threshold (key day)** | AM threshold 5 × 6 min (1 min jog rec) · PM threshold 10 × 1000 m (1 min rec) |
| **Wed** | Easy + Upper B + prevention | AM easy 10 km · Upper body B ✱ · light prevention (calves/tibialis/feet/hips) ✱ · Abs ✱ |
| **Thu** | **Double threshold (key day)** | AM threshold 5 × 2 km (1 min rec) · PM threshold 25 × 400 m (30 s rec) |
| **Fri** | Easy + Leg day | AM easy 10 km · PM leg day (strength + plyo contrast) ✱ + finisher: 10 min easy run + 5 strides · Abs ✱ |
| **Sat** | Hills + Upper C | AM hill run 20 × 200 m (70 s jog rec, Z3 92–97% MHR — the only true high-intensity run) · PM easy 10 km · Upper body C ✱ |
| **Sun** | Long run + Leg day | AM long run 20 km (Z1, fuel if >90 min) · PM leg day (same as Fri, autoregulated) ✱ · Abs ✱ |

Strides = 15–20 s smooth fast with full recovery — technique and leg speed, not a workout.

The leg-day **finisher (10 min easy run + 5 strides)** existed to convert strength/plyo work into running coordination; it was removed with the running content. Re-add it if running returns.

## 4. The four threshold sessions in detail

Two intensities, deliberately different between AM and PM:

| Session | Lactate | % Max HR | Feel |
|---------|---------|----------|------|
| **AM (controlled / sub-threshold)** | ~2.0–2.5 mmol | 80–85% | Comfortably hard but EASY to finish. Err on the easy side. |
| **PM (a notch harder)** | ~3.0–3.5 mmol | 85–89% | One small step up from AM, still controlled — never racing. |

The specific workouts:

- **Tue AM — 5 × 6 min, 1 min jog recovery.** 15 min warm-up + drills, 10 min cool-down. Finish with reps in the tank.
- **Tue PM — 10 × 1000 m, 1 min recovery.** Only slightly harder than AM.
- **Thu AM — 5 × 2 km, 1 min recovery.** Longer reps, same controlled effort as Tue AM.
- **Thu PM — 25 × 400 m, 30 s recovery.** Short reps keep it crisp — rhythm, not a 10K simulation. Cut reps if form fades.

**The #1 mistake is running the AM session too hard.** For a developing athlete, threshold sits at a **lower %MHR** than an elite's 82–92%, and drifts upward with fitness. The magic is repeatable controlled volume, not intensity. When in doubt, go easier.

Without a lactate meter, the proxies are: the HR caps above, the talk test (short sentences possible), and the "could do 2 more reps" rule at the end of every session.

## 5. Scaling — this is an elite template

The rep/km counts above are Ingebrigtsen's (~120–140 km/week professional). **Keep the structure identical** — 7 days, two double-threshold days, Saturday hills, Sunday long run, Friday/Sunday legs — but scale volume to current fitness.

Sensible starting point off a **49:50 10K** (the athlete's PB at handover; half marathon PB 1:53):

| Elite version | Scaled start |
|---------------|--------------|
| Easy runs 10 km | 6–8 km |
| Long run 20 km | 14–16 km |
| 10 × 1000 m | 6–8 × 1000 m |
| 25 × 400 m | 12–15 × 400 m |
| 20 × 200 m hills | 10–12 × 200 m |

Progression: add a little every few weeks, never everything at once. The stated goal was best possible 5K/10K by 2030 — a patient 4-year aerobic build. Consistency beats heroics.

Doubles can also be collapsed initially: a runner not ready for twice-a-day can run single threshold sessions on Tue/Thu and grow into doubles.

## 6. Race block protocol

The fixed week repeats year-round and IS the training. When racing:

1. **4–6 weeks out:** keep the skeleton, but shift PM threshold sessions toward goal race pace (5K/10K reps), add one sharpening/VO2 session, trim easy volume 10–20%.
2. **Final 7–10 days:** taper — cut volume 30–50%, keep a little intensity, rest the legs (drop or lighten Fri/Sun gym).
3. **After the race:** 3–5 genuinely easy/recovery days, then resume the exact base week. No re-planning needed.

## 7. Interaction with the gym plan (still live in the script)

If running comes back, the gym schedule already slots around it — that was the original design:

- **Leg days sit on Fri & Sun** so they never precede a threshold day directly (Tue/Thu quality is protected by Mon/Wed easy days). Friday lands before Saturday hills and Sunday lands after the long run — hence the "autoregulate load, 1–3 reps in reserve" rule.
- **Wednesday prevention work** (calves, tibialis, feet, hips, balance) is runner injury-prevention — it must stay light so it never competes with Thu threshold.
- **Upper body Mon/Wed/Sat** is neutral for running; keep 1–2 reps in reserve so it doesn't steal recovery.
- **Diet:** with running restored, carbs move to a run-driven periodization — HIGH (~4–6 g/kg) on Tue/Thu/Sat and long-run Sun, moderate-lower (~2–3 g/kg) on easy days, and **never below ~3 g/kg on a double-threshold day** (low-carb wrecks high-intensity running). Protein stays constant regardless.
- **Overtraining check** gains a running signal: threshold paces drifting slower at the same HR = back off.

## 8. Re-implementing in `training-plan.gs` — code notes

The current script keeps all the plumbing (`buildWeeklyPlan_`, `task_`, checkbox/colour rendering, `sectionTitle_`/`tableHeader_`/`noteRow_`/`writeMenu_` helpers). To restore running:

1. **Re-add the constant and HR helpers** at the top:

   ```javascript
   var MAX_HR = 188; // athlete's max HR — used to print bpm targets

   function pct_(p) {
     return Math.round(MAX_HR * p);
   }

   function hrRange_(lo, hi) {
     return pct_(lo) + '-' + pct_(hi) + ' bpm (' + Math.round(lo * 100) + '-' + Math.round(hi * 100) + '% MHR)';
   }

   // Live zone formulas in the sheet referenced an editable Max HR cell:
   function bpmFormula_(ref, lo, hi) {
     return '=ROUND(' + ref + '*' + lo + ')&"-"&ROUND(' + ref + '*' + hi + ')&" bpm"';
   }
   ```

2. **Re-add task types + colours** in `typeColor_`: `easy` `#eef3fb`, `threshold` `#fde9d9`, `hills` `#fce8b2`.

3. **Rebuild `weekStructure_()`** from the table in section 3. The running task entries were, verbatim:

   ```javascript
   var EASY = 'Z1 easy ' + hrRange_(0.65, 0.75) + ' — stay below the 82% threshold line';

   // Monday
   task_('easy', 'AM · Easy 10 km', EASY, 'Relaxed aerobic. ~70% of weekly km lives here. Conversational pace.'),
   task_('easy', 'PM · Easy 10 km + 6–8 strides', 'Z1 easy; strides at relaxed max-speed feel',
         'Strides = 15–20s smooth fast with full recovery. Technique + leg speed, not a workout.'),

   // Tuesday (double threshold)
   task_('threshold', 'AM · Threshold 5 × 6 min (1 min jog rec)',
         '~2.0–2.5 mmol · ' + hrRange_(0.80, 0.85) + ' · easy to finish',
         '15 min warm-up + drills, 10 min cool-down. Err on the EASY side — finishing with reps in the tank is correct.'),
   task_('threshold', 'PM · Threshold 10 × 1000 m (1 min rec)',
         '~3.0–3.5 mmol · ' + hrRange_(0.85, 0.89) + ' · a notch harder than AM',
         'Only slightly harder than AM. Still controlled — never racing.'),

   // Thursday (double threshold)
   task_('threshold', 'AM · Threshold 5 × 2 km (1 min rec)',
         '~2.0–2.5 mmol · ' + hrRange_(0.80, 0.85) + ' · easy to finish',
         'Longer reps, same controlled effort as Tue AM. Err on the easy side.'),
   task_('threshold', 'PM · Threshold 25 × 400 m (30 s rec)',
         '~3.0–3.5 mmol · ' + hrRange_(0.85, 0.89) + ' · a notch harder',
         'Short reps keep it crisp. Rhythm, not a 10K simulation. Cut reps if form fades.'),

   // Saturday
   task_('hills', 'AM · Hill run 20 × 200 m (70 s jog rec)',
         'Z3 ' + hrRange_(0.92, 0.97) + ' · hard, not sprint',
         'The only true high-intensity run. Strong, powerful, controlled form.'),
   task_('easy', 'PM · Easy 10 km', EASY, 'Flush the legs out after hills.'),

   // Sunday
   task_('easy', 'AM · Long run 20 km', EASY, 'Weekly long run. Fuel if over 90 min. Walk breaks fine.'),
   ```

   Wed/Fri also each had an `AM · Easy 10 km` task, and Tue/Thu rest-day handling in the current `buildWeeklyPlan_` (the "no tasks = rest row" branch) becomes unnecessary once every day has tasks again.

4. **Restore the leg-day run finisher** row in the leg protocol table: `['Finisher: 10 min easy run + 5 strides', '1 round', 'Converts strength/power into running coordination. Optional on Sunday after the long run.']`

5. **Rebuild the Guide's running sections** (either as a third tab `Guide & Zones` or inside the merged tab): the zone table (section 2, with live `bpmFormula_` bpm columns referencing an editable Max HR cell), the double-threshold target table (section 4), the scaling warning (section 5), and the race-block protocol (section 6). Note: `deleteOldGeneratedSheets_` currently deletes any tab named `Guide & Zones` — remove it from `oldNames` if you bring that tab back.

6. **Re-add the diet macro sections** (removed from the script entirely on 2026-07-02): daily protein 1.8–2.2 g/kg spread over ~4 meals and kept steady every day, plus a carb table using the run-driven periodization described in section 7.

## 9. Sources

- Norwegian Singles method: <https://norwegiansingles.run/>
- Marius Bakken — the Norwegian model: <https://www.mariusbakken.com/the-norwegian-model.html>
- Ingebrigtsen preparation-week structure and zone table: user-provided reference images (the two images the original plan was transcribed from).

## 10. Athlete context at handover (2026-07-02)

- Max HR 188 · body weight ~70 kg · 10K PB 49:50 · half marathon PB 1:53.
- Thrives on fixed, repeating routines; plan intentionally has zero week-to-week variation.
- Separate 10 km training work lives in the repo's `running/` folder (unrelated to this script).
