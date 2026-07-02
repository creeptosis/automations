/**
 * Fixed Weekly Gym & Diet Tracker
 * Version: g1 — one fixed, repeating week. No week-by-week progression.
 *
 * Philosophy: you thrive on routine, so this is the SAME week every week, year-round.
 *   - Leg day on Fri & Sun — one fixed protocol: strength + plyo contrast
 *   - Upper body 3x/week (Mon/Wed/Sat) — 3 fixed days, antagonist supersets, V-taper focus
 *   - Abs 4x/week (Mon/Wed/Fri/Sun) — one fixed 3-move protocol + finisher
 *   - Light durability / prevention work on Wed
 *   - Tue & Thu are full rest days
 *
 * Creates 2 tabs:
 *   - Weekly Plan : the checklist you tick off each week
 *   - Guide & Diet : leg/upper/abs protocols, simple meals & shopping list, recovery notes
 *
 * How to use:
 *   1) Open a blank Google Sheet.
 *   2) Extensions > Apps Script. Paste this whole file into Code.gs.
 *   3) Save, then run buildWeeklyTracker().
 *   4) Each new week, use menu > "Reset week (uncheck all)".
 *
 * The running / double-threshold version of this plan was removed. Everything
 * needed to re-implement it is documented in README.md next to this file.
 */

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Training Plan')
    .addItem('Build / Reset Weekly Tracker', 'buildWeeklyTracker')
    .addItem('Reset week (uncheck all)', 'resetWeeklyChecks')
    .addToUi();
}

function buildWeeklyTracker() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  ss.setSpreadsheetTimeZone('Asia/Kuala_Lumpur');

  var weekSheet = getOrCreateSheet_(ss, 'Weekly Plan');
  var guideSheet = getOrCreateSheet_(ss, 'Guide & Diet');

  deleteOldGeneratedSheets_(ss);
  deleteBlankDefaultSheets_(ss);

  buildWeeklyPlan_(weekSheet);
  buildGuideDiet_(guideSheet);

  ss.setActiveSheet(weekSheet);
}

/* ------------------------------------------------------------------ *
 * The fixed week
 * ------------------------------------------------------------------ */

function task_(type, title, target, note) {
  return { type: type, title: title, target: target, note: note };
}

function weekStructure_() {
  var ABS = task_('abs', 'Abs · fixed protocol', 'See Guide — same every time', 'Hanging leg raise (PPT) · decline weighted crunch · ab wheel · hollow-hold/plank finisher.');
  var LEG = task_('leg', 'Leg day — strength + plyo contrast', 'See Guide', 'Heavy set → 5–8 explosive jumps (contrast). 1–3 reps in reserve.');
  var UPPER_A = task_('upper', 'Upper body A (supersets)', 'See Guide', 'SS1 pull-up + incline press · SS2 DB row + lateral raise. ~40 min.');
  var UPPER_B = task_('upper', 'Upper body B (supersets)', 'See Guide', 'SS1 DB row + standing DB press · SS2 incline press + lateral raise. ~40 min.');
  var UPPER_C = task_('upper', 'Upper body C (supersets)', 'See Guide', 'SS1 pull-up + overhead triceps · SS2 gladiator deadlift/row + lateral raise. ~40 min.');

  return [
    {
      day: 'Monday',
      focus: 'Upper body A + Abs',
      tasks: [UPPER_A, ABS]
    },
    {
      day: 'Tuesday',
      focus: 'Rest',
      tasks: []
    },
    {
      day: 'Wednesday',
      focus: 'Upper body B + prevention + Abs',
      tasks: [
        UPPER_B,
        task_('strength', 'Durability · calves, feet, hips (light)', 'See Guide', 'Light & preventative — calves, tibialis, feet, hips, balance. NOT a leg day.'),
        ABS
      ]
    },
    {
      day: 'Thursday',
      focus: 'Rest',
      tasks: []
    },
    {
      day: 'Friday',
      focus: 'LEG DAY (strength + plyo) + Abs',
      tasks: [LEG, ABS]
    },
    {
      day: 'Saturday',
      focus: 'Upper body C',
      tasks: [UPPER_C]
    },
    {
      day: 'Sunday',
      focus: 'LEG DAY (strength + plyo) + Abs',
      tasks: [
        task_('leg', 'Leg day — strength + plyo contrast', 'See Guide', 'Same as Friday. If Friday left you sore, autoregulate the load — lighter is fine, skipping is not.'),
        ABS
      ]
    }
  ];
}

/* ------------------------------------------------------------------ *
 * Weekly Plan (the checklist)
 * ------------------------------------------------------------------ */

function buildWeeklyPlan_(sheet) {
  sheet.clear();
  sheet.clearConditionalFormatRules();
  sheet.setHiddenGridlines(true);

  var week = weekStructure_();

  // Title
  sheet.getRange(1, 1, 1, 4).merge();
  sheet.getRange(1, 1)
    .setValue('Weekly Gym Plan — fixed repeating week')
    .setFontWeight('bold').setFontSize(13)
    .setBackground('#1c2b4a').setFontColor('#ffffff')
    .setHorizontalAlignment('center');

  // Column headers
  sheet.getRange(2, 1, 1, 4).setValues([['Done', 'Workout', 'Target', 'Notes']])
    .setFontWeight('bold').setBackground('#dce3f0');

  var dayHeaderRows = [];
  var taskRows = [];      // { row: n, type: t }
  var r = 3;

  for (var d = 0; d < week.length; d++) {
    var day = week[d];

    sheet.getRange(r, 1, 1, 4).merge();
    sheet.getRange(r, 1).setValue(day.day.toUpperCase() + '  —  ' + day.focus);
    dayHeaderRows.push(r);
    r++;

    if (day.tasks.length === 0) {
      sheet.getRange(r, 1, 1, 4).merge();
      sheet.getRange(r, 1)
        .setValue('Rest — full recovery day. Sleep, food, an easy walk. Nothing to tick.')
        .setFontStyle('italic').setBackground('#f5f5f5');
      r++;
      continue;
    }

    for (var t = 0; t < day.tasks.length; t++) {
      var task = day.tasks[t];
      sheet.getRange(r, 1, 1, 4).setValues([['', task.title, task.target, task.note]]);
      taskRows.push({ row: r, type: task.type });
      r++;
    }
  }

  var lastRow = r - 1;

  // Checkboxes on task rows, colour by type
  for (var i = 0; i < taskRows.length; i++) {
    var tr = taskRows[i];
    sheet.getRange(tr.row, 1).insertCheckboxes();
    sheet.getRange(tr.row, 1, 1, 4).setBackground(typeColor_(tr.type));
  }

  // Style day headers
  for (var j = 0; j < dayHeaderRows.length; j++) {
    sheet.getRange(dayHeaderRows[j], 1, 1, 4)
      .setFontWeight('bold').setFontSize(11)
      .setBackground('#384b6e').setFontColor('#ffffff');
  }

  sheet.setFrozenRows(2);
  sheet.getRange(1, 1, lastRow, 4).setVerticalAlignment('middle');
  sheet.getRange(3, 2, lastRow - 2, 3).setWrap(true).setVerticalAlignment('top');

  sheet.setColumnWidth(1, 55);
  sheet.setColumnWidth(2, 330);
  sheet.setColumnWidth(3, 250);
  sheet.setColumnWidth(4, 380);
}

function typeColor_(type) {
  switch (type) {
    case 'leg':       return '#e6d9f2'; // purple
    case 'abs':       return '#d9ead3'; // green
    case 'upper':     return '#cce8e6'; // teal
    case 'strength':  return '#ededed'; // grey
    default:          return '#ffffff';
  }
}

function resetWeeklyChecks() {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Weekly Plan');
  if (!sheet) return;
  var last = sheet.getLastRow();
  if (last < 3) return;
  var range = sheet.getRange(3, 1, last - 2, 1);
  var vals = range.getValues();
  for (var i = 0; i < vals.length; i++) {
    if (vals[i][0] === true || vals[i][0] === false) vals[i][0] = false;
  }
  range.setValues(vals);
}

/* ------------------------------------------------------------------ *
 * Guide & Diet
 * ------------------------------------------------------------------ */

function buildGuideDiet_(sheet) {
  sheet.clear();
  sheet.setHiddenGridlines(true);

  var r = 1;

  // Title
  sheet.getRange(r, 1, 1, 7).merge();
  sheet.getRange(r, 1).setValue('Guide & Diet')
    .setFontWeight('bold').setFontSize(14)
    .setBackground('#1c2b4a').setFontColor('#ffffff')
    .setHorizontalAlignment('center');
  r += 2;

  // Goal
  r = sectionTitle_(sheet, r, 'Goal');
  r = noteRow_(sheet, r, 'Lean, athletic V-taper physique — patient, repeatable weeks.', null);
  r += 1;

  // Leg day (Friday & Sunday) — one fixed protocol
  r = sectionTitle_(sheet, r, 'Leg day (Friday & Sunday) — strength + plyo contrast', '#e6d9f2', '#000000');
  r = tableHeader_(sheet, r, ['Exercise', 'Sets × Reps', 'Notes', '', '', '', '']);
  var leg = [
    ['Back / front squat + jump (CONTRAST)', '3 × 4-6  +  5-8 jumps', 'Heavy squat, 4–5 min rest. Right after each set do 5–8 explosive reps (depth jumps / hurdle hops / bounds). This IS the plyo — no separate day.'],
    ['Romanian deadlift',          '3 × 5-8',         'Hamstrings / glutes. No back rounding.'],
    ['Bulgarian split squat',      '2-3 × 6-8 / leg', 'Single-leg strength & balance.'],
    ['Standing calf raise',        '3 × 8-12',        'Pair with pogo hops if you want extra reactive work.'],
    ['Seated soleus raise',        '3 × 12-15',       'Shin / calf / ankle durability.']
  ];
  r = writeMenu_(sheet, r, leg);
  r = noteRow_(sheet, r,
    'Same protocol both days = maximally repeatable. Contrast sets (heavy squat → explosive jump) use post-activation ' +
    'potentiation: the heavy set primes the nervous system so the jump is more powerful. Keep 1–3 reps in reserve on the ' +
    'lifts — you hit legs twice a week, so you never need to grind to failure. If Friday left you sore, autoregulate Sunday’s load.', '#f4f0fa');
  r += 1;

  // Upper body — 3x/week, antagonist supersets (teal header matches the Weekly Plan)
  r = sectionTitle_(sheet, r, 'Upper body (Mon / Wed / Sat) — 3 fixed days, antagonist supersets', '#cce8e6', '#000000');
  r = tableHeader_(sheet, r, ['Day', 'Superset (pair A1+A2)', 'Sets × Reps', 'Notes', '', '', '']);
  var upper = [
    ['A', 'Pull-up  +  Incline DB press',               '3 × 6-10',          'Antagonist (back + chest) — they rest each other.'],
    ['A', 'DB row  +  Lateral raise',                    '3 × 8-12 / 12-15',  'Back thickness + side delt — non-competing.'],
    ['B', 'DB row  +  Standing DB press',                '3 × 8-12 / 6-10',   'Back + shoulders — different prime movers.'],
    ['B', 'Incline DB press  +  Lateral raise',          '3 × 6-10 / 12-15',  'Chest + side delt — different muscles, lateral is light, fine to pair.'],
    ['C', 'Pull-up  +  Overhead triceps extension',      '3 × 6-10 / 8-12',   'Back/biceps + triceps — antagonist arms.'],
    ['C', 'Gladiator deadlift / row  +  Lateral raise',  '3 × 6-10 / 12-15',  'Back + side delt.']
  ];
  r = writeMenu_(sheet, r, upper);
  r = noteRow_(sheet, r,
    'Weekly total: back 5 · lateral raise 3 · chest 2 · overhead press 1 · triceps 1. SUPERSET RULE: only pair muscles that ' +
    'do NOT overlap (push+pull, or limb+core) — never two shoulder/delt-press moves together. That is exactly why lateral ' +
    'raise is paired with a back row or chest here, never with the overhead press (both hit the delts). Pairing an upper set ' +
    'with abs also works. Chest stays minimal (it grows fastest for you); lateral delts + back get the volume to build the ' +
    'shoulder-to-waist V-taper. Progressive overload on these fixed lifts is the whole game — log the numbers and beat them. ' +
    'Skip biceps/rear-delt isolation: pull-ups and rows cover them for the lean-athletic look. Keep 1–2 reps in reserve.', '#eaf6f5');
  r += 1;

  // Wednesday durability menu
  r = sectionTitle_(sheet, r, 'Wednesday — durability / injury prevention (light)');
  r = tableHeader_(sheet, r, ['Exercise', 'Sets × Reps', 'Notes', '', '', '', '']);
  var wed = [
    ['Single-leg calf raise',      '3 × 12-15',      'Calf / ankle durability.'],
    ['Tibialis raise',             '2-3 × 15-25',    'Shin protection. Controlled burn, not pain.'],
    ['Foot / arch (towel scrunch, short-foot)', '2-3 sets', 'Intrinsic foot strength.'],
    ['Hip (clamshell, monster walk, glute bridge)', '2 sets', 'Pelvis & knee stability.'],
    ['Single-leg balance',         '2 sets',             'Proprioception.']
  ];
  r = writeMenu_(sheet, r, wed);
  r = noteRow_(sheet, r, 'Preventative accessory work, not a leg day — keep it light so it never competes with Friday.', '#f1f1f1');
  r += 1;

  // Abs — fixed protocol (green header matches the Weekly Plan)
  r = sectionTitle_(sheet, r, 'Abs — fixed protocol (Mon / Wed / Fri / Sun), same every time', '#d9ead3', '#000000');
  r = tableHeader_(sheet, r, ['Exercise', 'Sets × Reps', 'Notes', '', '', '', '']);
  var abs = [
    ['Hanging leg raise (posterior pelvic tilt)', '3 × 8-12', 'The PPT is everything — curl the pelvis up, don’t just lift the legs. Add weight (dumbbell between feet) when 12 is easy.'],
    ['Decline weighted crunch',    '3 × 10-15',      'Plate BEHIND the head = longest lever = most ab tension (neck neutral, no yanking). On the chest = easier/safer. Never press it in front — that loads shoulders, not abs.'],
    ['Ab wheel rollout',           '3 × 6-10',       'Loaded anti-extension + eccentric. From knees; go as far as you can control.'],
    ['Finisher: hollow hold OR plank', '2 × 30-60s', 'Pick ONE and stick with it. Whole-trunk tension to end.']
  ];
  r = writeMenu_(sheet, r, abs);
  r = noteRow_(sheet, r,
    'For aesthetics, abs are a muscle: progressive overload (add weight/reps over time) + enough protein + low enough body fat ' +
    'to see them. These 3 cover the whole rectus — lower (leg raise), upper (crunch), anti-extension (wheel). Frequency beats ' +
    'cramming: 4 short identical sessions/week beat 1–2 marathons. Leave 1–2 reps in reserve; if abs stay sore, drop to 3×/week.', '#e6f0e0');
  r += 1;

  // Super-simple meals
  r = sectionTitle_(sheet, r, 'Super-simple meals — air fryer / microwave (no rice cooker to wash)');
  r = tableHeader_(sheet, r, ['Meal', 'How', 'Why it works', '', '', '', '']);
  var meals = [
    ['Kunyit chicken thigh', 'Rub turmeric + salt + pepper + a little oil. Air fryer ~18–20 min @ 200°C.', 'Tastes like ayam goreng kunyit at home. ~25–30 g protein/thigh. Batch 4–6.'],
    ['Crispy tempeh + sambal', 'Slice, air fry 12–15 min till golden. Top with bottled sambal.', 'Cheap complete protein made delicious by sambal. No skill needed.'],
    ['Crispy tofu + sambal', 'Press, cube, air fry ~15 min. Sambal or kicap + garlic.', 'Same idea, even cheaper. Sambal is the flavour cheat-code.'],
    ['Microwave potato', 'Fork-poke, microwave ~3 min/side. Olive oil + salt.', 'Your favourite already — perfect training-day carb, dirt cheap.'],
    ['Microwave sweet potato', 'Poke holes, microwave 4–6 min.', 'Slower carb, great post-workout.'],
    ['Air-fryer eggs', 'Whole eggs in air fryer 9–11 min = boiled, no pot to wash. Peel and go.', '~6 g protein/egg. Snack or meal base.'],
    ['Canned tuna + chapathi', 'Microwave chapathi 20s; tuna + a little mayo or sambal.', 'Zero cooking, ~30 g protein in 2 minutes.'],
    ['Protein shake', 'Powder + water.', 'Cheapest protein per gram and your only "drinkable" calories.'],
    ['Greek / plain yoghurt + fruit', 'No cooking.', 'Protein + carbs + gut health. A solid night treat.'],
    ['Dhal (lentils)', 'Batch-cook once a week in one pot; reheat in microwave.', 'Very cheap protein + carbs. One wash, lasts days.']
  ];
  r = writeMenu_(sheet, r, meals);
  r = noteRow_(sheet, r,
    'The flavour cheat-code: a jar of bottled sambal (sambal tumis / sambal ikan bilis — Adabi, Life, kampung-style, etc.) ' +
    'turns cheap tofu, tempeh, eggs and rice into something you actually want to eat, with zero cooking. Buy one jar and ' +
    'cheap protein stops being a chore.', '#eef3fb');
  r += 1;

  // Cheap Malaysian groceries
  r = sectionTitle_(sheet, r, 'Cheapest good groceries in Malaysia');
  r = tableHeader_(sheet, r, ['Protein (cheap)', 'Carbs (cheap)', '', '', '', '', '']);
  var groceries = [
    ['Eggs', 'White rice (cheap, easy bulk carb)'],
    ['Chicken thigh / whole chicken', 'Potato: kentang Holland (cheapest, versatile)'],
    ['Canned tuna / sardines / ikan kembung', 'Sweet potato'],
    ['Tempeh & tofu', 'Oats'],
    ['Dhal / lentils', 'Chapathi'],
    ['Whey protein powder', 'Banana & local fruit'],
    ['Milk / plain yoghurt', 'Corn']
  ];
  r = writeMenu_(sheet, r, groceries);
  r = noteRow_(sheet, r,
    'White potato to buy: kentang Holland is the cheapest, most versatile and microwaves well. If you want that extra-fluffy ' +
    'baked-potato texture, larger Australian potatoes are better but cost a bit more.', null);
  r += 1;

  // Recovery
  r = sectionTitle_(sheet, r, 'Recovery — the discipline that unlocks progress');
  var recovery = [
    '• Fixed schedule beats raw hours, and a fixed WAKE time anchors your body clock even more than bedtime. A consistent 12–1am bed is fine if your wake time is consistent. Aim 7.5–9 h.',
    '• Post-work nap: keep it 20–30 min (power nap) OR a full ~90 min cycle. Avoid 45–60 min — you wake groggy. Not after ~5pm or it eats your night sleep.',
    '• Sleep is your biggest legal performance enhancer — muscle is built in recovery, not in the session.',
    '• Overtraining check: lifts stalling or going backwards, rising resting HR, flat mood = back off a few days. First thing to cut is Sunday’s leg session.'
  ];
  for (var j = 0; j < recovery.length; j++) r = noteRow_(sheet, r, recovery[j], null);
  r += 1;

  // Results timeline
  r = sectionTitle_(sheet, r, 'When will you see serious results?');
  var results = [
    '• Muscle: you were jacked & lean in college, so you have muscle memory (retained myonuclei) — regain is FAST. Visible upper-body change in 4–8 weeks; most of your old physique back in ~3–4 months.',
    '• Leanness / abs: with consistent training and the simple meals on rotation, abs sharpen in 4–8 weeks and "shredded" is realistic in ~3–4 months.'
  ];
  for (var k = 0; k < results.length; k++) r = noteRow_(sheet, r, results[k], null);
  r += 1;

  // Sources
  r = sectionTitle_(sheet, r, 'Sources');
  sheet.getRange(r, 1, 1, 2).setValues([
    ['Hypertrophy frequency vs volume', 'Schoenfeld et al. meta-analyses (frequency matters mainly via total weekly volume)']
  ]);
  r += 1;

  // Formatting
  sheet.getRange(1, 1, r + 2, 7).setVerticalAlignment('top').setWrap(true);
  sheet.setColumnWidth(1, 300);
  sheet.setColumnWidth(2, 320);
  sheet.setColumnWidth(3, 360);
  for (var c = 4; c <= 7; c++) sheet.setColumnWidth(c, 90);
  sheet.setFrozenRows(1);
}

/* ------------------------------------------------------------------ *
 * Guide layout helpers
 * ------------------------------------------------------------------ */

function sectionTitle_(sheet, r, text, bg, fontColor) {
  bg = bg || '#384b6e';
  fontColor = fontColor || '#ffffff';
  sheet.getRange(r, 1, 1, 7).merge();
  sheet.getRange(r, 1).setValue(text)
    .setFontWeight('bold').setFontSize(11)
    .setBackground(bg).setFontColor(fontColor);
  return r + 1;
}

function tableHeader_(sheet, r, arr) {
  sheet.getRange(r, 1, 1, arr.length).setValues([arr])
    .setFontWeight('bold').setBackground('#dce3f0');
  return r + 1;
}

function noteRow_(sheet, r, text, bg) {
  sheet.getRange(r, 1, 1, 7).merge();
  var cell = sheet.getRange(r, 1).setValue(text).setWrap(true).setVerticalAlignment('top');
  if (bg) cell.setBackground(bg);
  return r + 1;
}

function writeMenu_(sheet, r, rows) {
  for (var i = 0; i < rows.length; i++) {
    sheet.getRange(r + i, 1, 1, rows[i].length).setValues([rows[i]]);
  }
  return r + rows.length;
}

/* ------------------------------------------------------------------ *
 * Sheet plumbing
 * ------------------------------------------------------------------ */

function getOrCreateSheet_(ss, name) {
  var sheet = ss.getSheetByName(name);
  if (!sheet) sheet = ss.insertSheet(name);
  sheet.clear();
  return sheet;
}

function deleteOldGeneratedSheets_(ss) {
  // Tabs from the old running versions and any earlier experiments.
  var oldNames = ['Plan Tracker', 'Setup & Guide', 'TT Log', 'Dashboard', 'Config', 'Effort Guide', 'Guide & Zones', 'Diet & Recovery'];
  oldNames.forEach(function(name) {
    var sheet = ss.getSheetByName(name);
    if (sheet && ss.getSheets().length > 1) ss.deleteSheet(sheet);
  });
}

function deleteBlankDefaultSheets_(ss) {
  ['Sheet1', 'Sheet 1'].forEach(function(name) {
    var sheet = ss.getSheetByName(name);
    if (sheet && ss.getSheets().length > 1 && isSheetBlank_(sheet)) ss.deleteSheet(sheet);
  });
}

function isSheetBlank_(sheet) {
  var range = sheet.getDataRange();
  return range.getNumRows() === 1 && range.getNumColumns() === 1 && range.getCell(1, 1).isBlank();
}
