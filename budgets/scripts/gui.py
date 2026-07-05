"""Budgets portal - every ringgit of net income mapped, surplus routed to goals.

Money model (locked 2026-07-05): exact recurring items + lump-sum monthly
estimates. No per-transaction entry. Single SQLite file at data/budgets.db,
created and seeded on first run.

    python scripts/gui.py   ->  http://127.0.0.1:5002
"""

import calendar
import csv
import hmac
import io
import json
import os
import re
import secrets
import sqlite3
import time
from datetime import date, datetime
from pathlib import Path

from flask import Flask, g, jsonify, redirect, request, send_from_directory, session

BASE_DIR = Path(__file__).resolve().parent.parent  # project root
DB_PATH = BASE_DIR / "data" / "budgets.db"

app = Flask(__name__, static_folder=str(BASE_DIR / "static"))

CADENCE_MONTHS = {"monthly": 1, "quarterly": 3, "half-yearly": 6, "yearly": 12}

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS income (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    gross_monthly REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS deduction (
    id INTEGER PRIMARY KEY,
    income_id INTEGER NOT NULL REFERENCES income(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    amount_monthly REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS category (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    sort INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS expense (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    category_id INTEGER NOT NULL REFERENCES category(id),
    amount REAL NOT NULL,
    cadence TEXT NOT NULL DEFAULT 'monthly',
    is_estimate INTEGER NOT NULL DEFAULT 0,
    renews_on TEXT,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS goal (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    target_amount REAL NOT NULL,
    deadline TEXT NOT NULL,
    yearly INTEGER NOT NULL DEFAULT 0,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS contribution (
    id INTEGER PRIMARY KEY,
    goal_id INTEGER NOT NULL REFERENCES goal(id) ON DELETE CASCADE,
    on_date TEXT NOT NULL,
    amount REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tracker (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    grp TEXT,
    interval_months INTEGER,
    expires_on TEXT,
    expected_cost REAL,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS entry (
    id INTEGER PRIMARY KEY,
    tracker_id INTEGER NOT NULL REFERENCES tracker(id) ON DELETE CASCADE,
    on_date TEXT NOT NULL,
    cost REAL,
    note TEXT
);
CREATE TABLE IF NOT EXISTS snapshot (
    id INTEGER PRIMARY KEY,
    month TEXT NOT NULL UNIQUE,
    taken_on TEXT NOT NULL,
    gross REAL, net REAL, mapped REAL, surplus REAL,
    categories TEXT
);
CREATE TABLE IF NOT EXISTS checkin (
    id INTEGER PRIMARY KEY,
    on_date TEXT NOT NULL,
    balance REAL NOT NULL,
    note TEXT
);
CREATE TABLE IF NOT EXISTS statement (
    id INTEGER PRIMARY KEY,
    uploaded_on TEXT NOT NULL,
    source TEXT NOT NULL,
    filename TEXT,
    txn_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS txn (
    id INTEGER PRIMARY KEY,
    statement_id INTEGER NOT NULL REFERENCES statement(id) ON DELETE CASCADE,
    on_date TEXT NOT NULL,
    description TEXT,
    amount REAL NOT NULL,
    category_id INTEGER REFERENCES category(id)
);
CREATE TABLE IF NOT EXISTS rule (
    id INTEGER PRIMARY KEY,
    keyword TEXT NOT NULL,
    category_id INTEGER NOT NULL REFERENCES category(id)
);
"""

DEFAULT_CATEGORIES = [
    "Housing", "Utilities & Bills", "Food", "Transport & Car", "Insurance",
    "Health", "Subscriptions", "Family", "Personal", "Misc",
]

# (name, interval in months or None, group or None) - fixed-expiry items (road tax,
# insurance, license, passport) get their expires_on date set by the user
DEFAULT_TRACKERS = [
    ("Haircut", None, None), ("Service", 6, "Car"), ("Battery", 24, "Car"),
    ("Road tax", None, "Car"), ("Insurance", None, "Car"),
    ("Driving license", None, "Car"), ("Running shoes", None, None),
    ("Passport", None, None),
]


def _migrate(con):
    """Bring pre-existing DBs up to the current schema (fresh ones skip through)."""
    for stmt in ("ALTER TABLE goal ADD COLUMN yearly INTEGER NOT NULL DEFAULT 0",
                 "ALTER TABLE tracker ADD COLUMN grp TEXT",
                 "ALTER TABLE tracker ADD COLUMN expires_on TEXT"):
        try:
            con.execute(stmt)
        except sqlite3.OperationalError:
            pass  # column already exists
    # one-time regroup of the seeded rows - exact names only, renames stay untouched
    if not con.execute("SELECT 1 FROM meta WHERE key = 'mig-car-group'").fetchone():
        con.execute("UPDATE goal SET yearly = 1 WHERE name = 'EPF self-contribution'")
        con.execute("UPDATE tracker SET name = 'Service', grp = 'Car'"
                    " WHERE name = 'Car service' AND grp IS NULL")
        con.execute("UPDATE tracker SET name = 'Battery', grp = 'Car'"
                    " WHERE name = 'Car battery' AND grp IS NULL")
        con.execute("UPDATE tracker SET grp = 'Car'"
                    " WHERE name = 'Driving license' AND grp IS NULL")
        con.execute("INSERT INTO meta (key, value) VALUES ('mig-car-group', ?)",
                    (date.today().isoformat(),))
    if not con.execute("SELECT 1 FROM meta WHERE key = 'mig-car-expiry'").fetchone():
        for name in ("Road tax", "Insurance"):
            if not con.execute("SELECT 1 FROM tracker WHERE name = ?", (name,)).fetchone():
                con.execute("INSERT INTO tracker (name, grp) VALUES (?, 'Car')", (name,))
        con.execute("INSERT INTO meta (key, value) VALUES ('mig-car-expiry', ?)",
                    (date.today().isoformat(),))


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)
    _migrate(con)
    if con.execute("SELECT COUNT(*) FROM category").fetchone()[0] == 0:
        con.executemany("INSERT INTO category (name, sort) VALUES (?, ?)",
                        [(n, i) for i, n in enumerate(DEFAULT_CATEGORIES)])
    if con.execute("SELECT COUNT(*) FROM goal").fetchone()[0] == 0:
        con.execute(
            "INSERT INTO goal (name, target_amount, deadline, yearly, notes) VALUES (?, ?, ?, 1, ?)",
            ("EPF self-contribution", 100000, f"{date.today().year}-12-31",
             "Voluntary top-up; cap RM100,000 per calendar year"))
    if con.execute("SELECT COUNT(*) FROM tracker").fetchone()[0] == 0:
        con.executemany("INSERT INTO tracker (name, interval_months, grp) VALUES (?, ?, ?)",
                        DEFAULT_TRACKERS)
    con.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('installed', ?)",
                (date.today().isoformat(),))
    con.commit()
    con.close()


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exc):
    con = g.pop("db", None)
    if con is not None:
        con.close()


# ------------------------------------------------------------------------ auth
# Set BUDGETS_PASSWORD to require login (hosted mode); unset = open (local use).

PASSWORD = os.getenv("BUDGETS_PASSWORD")
_fails = {}  # client ip -> (fail_count, locked_until_epoch)

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(PASSWORD),
    PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 90,
    MAX_CONTENT_LENGTH=10 * 1024 * 1024,  # uploads are one statement/payslip at a time
)

LOGIN_HTML = """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Budget · login</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Cdefs%3E%3ClinearGradient id='g' x1='0' y1='0' x2='32' y2='32'%3E%3Cstop stop-color='%233ecf8e'/%3E%3Cstop offset='1' stop-color='%234f7cf0'/%3E%3C/linearGradient%3E%3C/defs%3E%3Crect width='32' height='32' rx='9' fill='url(%23g)'/%3E%3Crect x='7' y='17' width='4.5' height='8' rx='2' fill='%23fff' opacity='.8'/%3E%3Crect x='13.75' y='12' width='4.5' height='13' rx='2' fill='%23fff' opacity='.9'/%3E%3Crect x='20.5' y='7' width='4.5' height='18' rx='2' fill='%23fff'/%3E%3C/svg%3E">
<style>:root{color-scheme:dark}*{box-sizing:border-box}
body{font-family:'Inter','Segoe UI Variable Text','Segoe UI',system-ui,sans-serif;margin:0;
min-height:100vh;display:flex;align-items:center;justify-content:center;color:#e7ecf3;
background:radial-gradient(900px 460px at 50% -160px,rgba(79,124,240,.14),transparent 60%),
radial-gradient(700px 380px at 82% -120px,rgba(62,207,142,.07),transparent 60%),#0a0d13}
form{background:linear-gradient(180deg,rgba(255,255,255,.025),transparent 40%),#11161f;
border:1px solid #232c3c;border-radius:16px;padding:26px;width:300px;
display:flex;flex-direction:column;gap:10px;
box-shadow:0 1px 2px rgba(0,0,0,.3),0 24px 48px -24px rgba(0,0,0,.6)}
.brand{display:flex;align-items:center;gap:10px;font-weight:650;font-size:15px;margin-bottom:6px}
input{background:#0d1119;border:1px solid #232c3c;border-radius:9px;color:#e7ecf3;
padding:9px 11px;font:inherit;font-size:14px;transition:border-color .15s,box-shadow .15s}
input::placeholder{color:#5d687c}
input:focus{outline:none;border-color:#3a558a;box-shadow:0 0 0 3px rgba(107,166,255,.15)}
button{background:linear-gradient(180deg,#4f7cf0,#3f63d4);border:1px solid rgba(255,255,255,.09);
box-shadow:inset 0 1px 0 rgba(255,255,255,.12);color:#fff;font:inherit;font-size:14px;
font-weight:600;border-radius:9px;padding:9px;cursor:pointer}
button:hover{filter:brightness(1.08)}button:active{transform:translateY(1px)}
.err{color:#f47174;font-size:12.5px;min-height:15px}</style></head>
<body><form method="post"><div class="brand"><svg width="20" height="20" viewBox="0 0 32 32" fill="none" aria-hidden="true"><defs><linearGradient id="lg" x1="0" y1="0" x2="32" y2="32"><stop stop-color="#3ecf8e"/><stop offset="1" stop-color="#4f7cf0"/></linearGradient></defs><rect width="32" height="32" rx="9" fill="url(#lg)"/><rect x="7" y="17" width="4.5" height="8" rx="2" fill="#fff" opacity=".8"/><rect x="13.75" y="12" width="4.5" height="13" rx="2" fill="#fff" opacity=".9"/><rect x="20.5" y="7" width="4.5" height="18" rx="2" fill="#fff"/></svg>Budget</div>
<input type="password" name="password" placeholder="password" autofocus required>
<div class="err">{err}</div><button>enter</button></form></body></html>"""


def _client_ip():
    return (request.headers.get("CF-Connecting-IP")
            or request.headers.get("X-Real-IP")
            or request.remote_addr or "?")


@app.before_request
def _guard():
    if not PASSWORD or session.get("ok") or request.path in ("/login", "/logout"):
        return
    if request.path.startswith("/api/"):
        return jsonify({"error": "login required"}), 401
    return redirect("/login")


@app.get("/login")
def login_page():
    return LOGIN_HTML.replace("{err}", "")


@app.post("/login")
def login_post():
    ip = _client_ip()
    count, until = _fails.get(ip, (0, 0))
    if time.time() < until:
        return LOGIN_HTML.replace("{err}", "locked out - try again later"), 429
    if PASSWORD and hmac.compare_digest(request.form.get("password", ""), PASSWORD):
        _fails.pop(ip, None)
        session.permanent = True
        session["ok"] = True
        return redirect("/")
    count += 1
    _fails[ip] = (count, time.time() + 900 if count >= 5 else 0)
    return LOGIN_HTML.replace("{err}", "wrong password"), 403


@app.get("/logout")
def logout():
    session.clear()
    return redirect("/login")


def _ensure_secret():
    """Stable Flask session secret, persisted in the DB so restarts keep logins."""
    con = sqlite3.connect(DB_PATH)
    row = con.execute("SELECT value FROM meta WHERE key = 'secret'").fetchone()
    if not row:
        con.execute("INSERT INTO meta (key, value) VALUES ('secret', ?)",
                    (secrets.token_hex(32),))
        con.commit()
        row = con.execute("SELECT value FROM meta WHERE key = 'secret'").fetchone()
    con.close()
    return row[0]


# ---------------------------------------------------------------- calculations

def monthly_eq(amount: float, cadence: str) -> float:
    return amount / CADENCE_MONTHS.get(cadence, 1)


def months_left(deadline: str) -> float:
    return max(0.0, (date.fromisoformat(deadline) - date.today()).days / 30.44)


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def next_roll(anchor: str, cadence: str) -> date:
    """Next occurrence of the anchor date at this cadence, today or later.

    Steps are always taken from the original anchor so a 31st-of-month
    subscription clamps per month (Feb 28) without drifting permanently.
    """
    a = date.fromisoformat(anchor)
    step = CADENCE_MONTHS.get(cadence, 1)
    today, k, d = date.today(), 0, a
    while d < today:
        k += 1
        d = add_months(a, k * step)
    return d


def money_state(con):
    incomes = [dict(r) for r in con.execute("SELECT * FROM income ORDER BY id")]
    deductions = [dict(r) for r in con.execute("SELECT * FROM deduction ORDER BY id")]
    gross = sum(i["gross_monthly"] for i in incomes)
    net = gross - sum(d["amount_monthly"] for d in deductions)

    categories, mapped = [], 0.0
    for c in con.execute("SELECT * FROM category ORDER BY sort, id"):
        items = []
        for e in con.execute("SELECT * FROM expense WHERE category_id = ? ORDER BY id", (c["id"],)):
            e = dict(e)
            e["monthly_eq"] = round(monthly_eq(e["amount"], e["cadence"]), 2)
            if e["renews_on"]:
                roll = next_roll(e["renews_on"], e["cadence"])
                e["next_roll"] = roll.isoformat()
                e["days_to_roll"] = (roll - date.today()).days
            items.append(e)
        total = sum(i["monthly_eq"] for i in items)
        mapped += total
        categories.append({
            "id": c["id"], "name": c["name"], "sort": c["sort"],
            "monthly": round(total, 2),
            "pct_of_net": round(100 * total / net, 1) if net > 0 else None,
            "items": items,
        })
    return incomes, deductions, gross, net, categories, mapped


def snap_month(con, month_key):
    """Store (or refresh) a snapshot of the current money map, labelled month_key."""
    _, _, gross, net, categories, mapped = money_state(con)
    if gross == 0 and mapped == 0:
        return False
    con.execute(
        "INSERT OR REPLACE INTO snapshot (month, taken_on, gross, net, mapped, surplus, categories)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (month_key, date.today().isoformat(), round(gross, 2), round(net, 2),
         round(mapped, 2), round(net - mapped, 2),
         json.dumps([{"name": c["name"], "monthly": c["monthly"]}
                     for c in categories if c["monthly"]])))
    con.commit()
    return True


def ensure_monthly_snapshot(con):
    """Lazily close last month the first time the app computes in a new month.

    Uses the live money map as the closing state - acceptable because spending
    is stable month to month (locked assumption). Months before install are
    never fabricated.
    """
    prev = add_months(date.today().replace(day=1), -1)
    key = f"{prev.year}-{prev.month:02d}"
    installed = con.execute("SELECT value FROM meta WHERE key = 'installed'").fetchone()
    if installed and key < installed[0][:7]:
        return
    if not con.execute("SELECT 1 FROM snapshot WHERE month = ?", (key,)).fetchone():
        snap_month(con, key)


@app.get("/api/summary")
def summary():
    con = db()
    ensure_monthly_snapshot(con)
    incomes, deductions, gross, net, categories, mapped = money_state(con)
    surplus = net - mapped

    trackers = []
    for t in con.execute("SELECT * FROM tracker ORDER BY name"):
        t = dict(t)
        t["entries"] = [dict(r) for r in con.execute(
            "SELECT * FROM entry WHERE tracker_id = ? ORDER BY on_date DESC, id DESC",
            (t["id"],))]
        t["last"] = t["entries"][0] if t["entries"] else None
        # fixed expiry (road tax, insurance, license, passport) beats interval;
        # renewing = updating expires_on, the entry log keeps cost history
        if t.get("expires_on"):
            due = date.fromisoformat(t["expires_on"])
            t["next_due"] = t["expires_on"]
            t["days_to_due"] = (due - date.today()).days
        elif t["last"] and t["interval_months"]:
            due = add_months(date.fromisoformat(t["last"]["on_date"]), t["interval_months"])
            t["next_due"] = due.isoformat()
            t["days_to_due"] = (due - date.today()).days
        trackers.append(t)

    # forward radar: non-monthly expense rolls in the next 90 days (monthly items
    # are already smooth in the mapping; only lumpy cadences surprise a month),
    # merged with tracker dues (expected money, not budgeted - marked as such;
    # negative days = overdue, deliberately kept visible)
    upcoming = sorted(
        [{"name": i["name"], "category": c["name"], "amount": i["amount"],
          "on": i["next_roll"], "days": i["days_to_roll"]}
         for c in categories for i in c["items"]
         if i.get("next_roll") and i["cadence"] != "monthly" and i["days_to_roll"] <= 90] +
        [{"name": (t["grp"] + " · " + t["name"]) if t.get("grp") else t["name"],
          "category": "due", "amount": t["expected_cost"],
          "on": t["next_due"], "days": t["days_to_due"], "expected": True}
         for t in trackers
         if t.get("next_due") and t["days_to_due"] <= 90],
        key=lambda u: u["on"])

    goals = []
    for gl in con.execute("SELECT * FROM goal ORDER BY id"):
        gl = dict(gl)
        # yearly goals never expire: the deadline rolls to Dec 31 of the current
        # year, so each January the target resets and last year's contributions
        # stay in history without counting
        if gl.get("yearly"):
            gl["deadline"] = f"{date.today().year}-12-31"
        # annual goals: only contributions in the deadline's calendar year count
        contributed = con.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM contribution"
            " WHERE goal_id = ? AND substr(on_date, 1, 4) = ?",
            (gl["id"], gl["deadline"][:4])).fetchone()[0]
        contribs = [dict(r) for r in con.execute(
            "SELECT * FROM contribution WHERE goal_id = ? ORDER BY on_date DESC", (gl["id"],))]
        remaining = gl["target_amount"] - contributed
        ml = months_left(gl["deadline"])
        projected = surplus * ml if surplus > 0 else 0.0
        goals.append({
            **gl, "contributed": round(contributed, 2), "remaining": round(remaining, 2),
            "months_left": round(ml, 1),
            "required_monthly": round(remaining / ml, 2) if ml > 0 and remaining > 0 else None,
            "surplus_monthly": round(surplus, 2),
            "projected_by_deadline": round(projected, 2),
            "coverage_pct": round(100 * min(projected / remaining, 1.0), 1) if remaining > 0 else 100.0,
            "contributions": contribs,
        })

    checkins = [dict(r) for r in con.execute(
        "SELECT * FROM checkin ORDER BY on_date DESC, id DESC")]
    # drift: how the bank actually moved between the last two check-ins vs what
    # the plan predicted (surplus x span, minus money moved into goals). Uses the
    # CURRENT surplus - fine while spending is stable month to month.
    drift = None
    if len(checkins) >= 2:
        latest, prev = checkins[0], checkins[1]
        span_days = (date.fromisoformat(latest["on_date"])
                     - date.fromisoformat(prev["on_date"])).days
        if span_days > 0:
            span_mo = span_days / 30.44
            contrib = con.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM contribution"
                " WHERE on_date > ? AND on_date <= ?",
                (prev["on_date"], latest["on_date"])).fetchone()[0]
            predicted = surplus * span_mo - contrib
            actual = latest["balance"] - prev["balance"]
            drift = {
                "from": prev["on_date"], "to": latest["on_date"],
                "span_months": round(span_mo, 1),
                "actual_delta": round(actual, 2),
                "predicted_delta": round(predicted, 2),
                "contributions": round(contrib, 2),
                "gap_total": round(actual - predicted, 2),
                "gap_monthly": round((actual - predicted) / span_mo, 2),
            }

    snapshots = []
    for r in con.execute("SELECT * FROM snapshot ORDER BY month DESC"):
        r = dict(r)
        r["categories"] = json.loads(r["categories"] or "[]")
        r["savings_pct"] = round(100 * r["surplus"] / r["net"], 1) if r["net"] else None
        snapshots.append(r)

    ps = con.execute("SELECT value FROM meta WHERE key = 'payslip_last'").fetchone()

    return jsonify({
        "as_of": date.today().isoformat(),
        "incomes": incomes, "deductions": deductions,
        "gross": round(gross, 2), "net": round(net, 2),
        "categories": categories,
        "mapped": round(mapped, 2),
        "mapped_pct": round(100 * mapped / net, 1) if net > 0 else None,
        "surplus": round(surplus, 2),
        "surplus_pct": round(100 * surplus / net, 1) if net > 0 else None,
        "upcoming": upcoming,
        "goals": goals,
        "trackers": trackers,
        "checkins": checkins,
        "drift": drift,
        "snapshots": snapshots,
        "payslip_last": json.loads(ps[0]) if ps else None,
    })


# ------------------------------------------------------------- statement parse

DATE_FORMATS = ["%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y", "%d %B %Y", "%d/%m/%y"]


def _amount(text):
    t = str(text).strip().replace("RM", "").replace(",", "").replace(" ", "")
    if not t:
        return 0.0
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()")
    if t.endswith("-"):  # trailing-minus convention some banks use
        neg, t = True, t[:-1]
    v = float(t)
    return -abs(v) if neg else v


def _detect(headers):
    """Classify a candidate header row into column roles; None if not a header."""
    low = [str(h).strip().lower() for h in headers]

    def find(pred):
        return [i for i, h in enumerate(low) if pred(h)]

    dates = find(lambda h: "date" in h or "tarikh" in h)
    if not dates:
        return None
    balance = set(find(lambda h: "balance" in h))
    debit = [i for i in find(lambda h: "debit" in h) if i not in balance]
    credit = [i for i in find(lambda h: "credit" in h) if i not in balance]
    drcr = find(lambda h: "dr" in h and "cr" in h)
    amount = [i for i in find(lambda h: "amount" in h or h in ("amaun", "jumlah"))
              if i not in balance and i not in debit and i not in credit and i not in drcr]
    if debit and credit:
        mode = "debit_credit"
    elif amount and drcr:
        mode = "drcr"
    elif amount:
        mode = "signed"
    else:
        return None
    used = set(dates) | balance | set(debit) | set(credit) | set(amount) | set(drcr)
    desc = [i for i in find(lambda h: any(k in h for k in
            ("descri", "detail", "particular", "merchant", "narrat", "reference", "transaction")))
            if i not in used]
    if not desc:
        desc = [i for i in range(len(low)) if i not in used][:1]
    return {"date": dates[0], "desc": desc, "mode": mode,
            "debit": debit[0] if debit else None, "credit": credit[0] if credit else None,
            "amount": amount[0] if amount else None, "drcr": drcr[0] if drcr else None}


def _dates(rows, col):
    """Parse the date column; picks the format that fits the most rows."""
    best = None
    for fmt in DATE_FORMATS:
        parsed = []
        for r in rows:
            try:
                parsed.append(datetime.strptime(r[col].strip(), fmt).date().isoformat())
            except (ValueError, IndexError):
                parsed.append(None)
        ok = sum(1 for p in parsed if p)
        if best is None or ok > best[0]:
            best = (ok, parsed)
        if ok == len(rows):
            break
    return best[1] if best and best[0] >= max(1, len(rows) // 2) else None


def parse_csv(raw):
    """bytes -> (rows [{on_date, description, amount}], skipped). Outflow = negative."""
    for enc in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("could not decode file as text")
    try:
        dialect = csv.Sniffer().sniff(text[:2000], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    lines = [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
    spec = header_at = None
    for i, row in enumerate(lines[:10]):
        spec = _detect(row)
        if spec:
            header_at = i
            break
    if not spec:
        raise ValueError("no header row found (need date + amount/debit/credit columns)")
    body = [r for r in lines[header_at + 1:] if len(r) > spec["date"]]
    iso = _dates(body, spec["date"])
    if iso is None:
        raise ValueError("unrecognised date format")
    out, skipped = [], 0
    for r, d in zip(body, iso):
        if d is None:
            skipped += 1
            continue
        try:
            if spec["mode"] == "debit_credit":
                amt = _amount(r[spec["credit"]]) - _amount(r[spec["debit"]])
            elif spec["mode"] == "drcr":
                amt = abs(_amount(r[spec["amount"]]))
                if "DR" in str(r[spec["drcr"]]).upper():
                    amt = -amt
            else:
                amt = _amount(r[spec["amount"]])
        except (ValueError, IndexError):
            skipped += 1
            continue
        desc = " ".join(r[i].strip() for i in spec["desc"] if i < len(r)).strip()
        if amt == 0 and not desc:
            skipped += 1
            continue
        out.append({"on_date": d, "description": desc, "amount": round(amt, 2)})
    return out, skipped


def apply_rules(con):
    """First matching rule (by id) categorises; only touches uncategorised txns."""
    matched = 0
    for r in con.execute("SELECT * FROM rule ORDER BY id"):
        cur = con.execute(
            "UPDATE txn SET category_id = ? WHERE category_id IS NULL"
            " AND instr(upper(description), upper(?)) > 0",
            (r["category_id"], r["keyword"]))
        matched += cur.rowcount
    return matched


@app.post("/api/statement/upload")
def statement_upload():
    f = request.files.get("file")
    source = (request.form.get("source") or "").strip() or "statement"
    if not f:
        return jsonify({"error": "no file"}), 400
    try:
        rows, skipped = parse_csv(f.read())
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if not rows:
        return jsonify({"error": "no transactions found in file"}), 400
    con = db()
    sid = con.execute(
        "INSERT INTO statement (uploaded_on, source, filename) VALUES (?, ?, ?)",
        (date.today().isoformat(), source, f.filename)).lastrowid
    imported = dupes = 0
    for r in rows:
        # dedup so overlapping statement periods never double-count
        if con.execute("SELECT 1 FROM txn WHERE on_date = ? AND description = ? AND amount = ?",
                       (r["on_date"], r["description"], r["amount"])).fetchone():
            dupes += 1
            continue
        con.execute("INSERT INTO txn (statement_id, on_date, description, amount) VALUES (?, ?, ?, ?)",
                    (sid, r["on_date"], r["description"], r["amount"]))
        imported += 1
    con.execute("UPDATE statement SET txn_count = ? WHERE id = ?", (imported, sid))
    matched = apply_rules(con)
    con.commit()
    unmatched = con.execute(
        "SELECT COUNT(*) FROM txn WHERE category_id IS NULL AND amount < 0").fetchone()[0]
    return jsonify({"ok": True, "imported": imported, "duplicates": dupes, "rows_skipped": skipped,
                    "auto_categorised": matched, "unmatched_spend": unmatched})


@app.post("/api/statement/<int:rid>/flip")
def statement_flip(rid):
    # for exports that list spending as positive numbers
    con = db()
    con.execute("UPDATE txn SET amount = -amount WHERE statement_id = ?", (rid,))
    con.commit()
    return jsonify({"ok": True})


@app.post("/api/rules/apply")
def rules_apply():
    con = db()
    matched = apply_rules(con)
    con.commit()
    return jsonify({"ok": True, "matched": matched})


@app.get("/api/reconcile")
def reconcile_data():
    con = db()
    months = [r[0] for r in con.execute(
        "SELECT DISTINCT substr(on_date, 1, 7) FROM txn ORDER BY 1 DESC")]
    month = request.args.get("month") or (months[0] if months else None)
    _, _, _, _, categories, _ = money_state(con)
    plan = {c["name"]: c["monthly"] for c in categories}
    out = {
        "months": months, "month": month,
        "categories": [{"id": c["id"], "name": c["name"]} for c in categories],
        "rules": [dict(r) for r in con.execute(
            "SELECT rule.*, category.name AS category FROM rule"
            " JOIN category ON category.id = rule.category_id ORDER BY rule.id")],
        "statements": [dict(r) for r in con.execute("SELECT * FROM statement ORDER BY id DESC")],
    }
    if month:
        like = month + "%"
        out["actuals"] = [
            {"category": r[0], "actual": round(r[1], 2), "plan": plan.get(r[0])}
            for r in con.execute(
                "SELECT category.name, SUM(-txn.amount) FROM txn"
                " JOIN category ON category.id = txn.category_id"
                " WHERE txn.amount < 0 AND txn.on_date LIKE ?"
                " GROUP BY category.name ORDER BY 2 DESC", (like,))]
        out["unmatched"] = [
            {"description": r[0], "count": r[1], "total": round(r[2], 2)}
            for r in con.execute(
                "SELECT description, COUNT(*), SUM(-amount) FROM txn"
                " WHERE category_id IS NULL AND amount < 0 AND on_date LIKE ?"
                " GROUP BY description ORDER BY 3 DESC LIMIT 50", (like,))]
        out["txns"] = [dict(r) for r in con.execute(
            "SELECT * FROM txn WHERE on_date LIKE ? ORDER BY on_date DESC, id DESC LIMIT 500", (like,))]
        flow = con.execute(
            "SELECT COALESCE(SUM(CASE WHEN amount < 0 THEN -amount END), 0),"
            "       COALESCE(SUM(CASE WHEN amount > 0 THEN amount END), 0)"
            " FROM txn WHERE on_date LIKE ?", (like,)).fetchone()
        out["outflow"], out["inflow"] = round(flow[0], 2), round(flow[1], 2)
    return jsonify(out)


# --------------------------------------------------------------- payslip parse
# The reader trusts a payslip only when its own arithmetic reconciles: parsed
# deduction items must sum to the printed Total Deduction, and gross minus
# deductions must equal Nett Pay. Items are scanned as label+number runs, which
# survives two-column layouts, merged rows and the YTD summary table (whose
# employee-current figures dedup against the deduction items).

PAY_MONEY = re.compile(r"-?[\d,]*\d\.\d{2}")
PAY_ITEM = re.compile(r"([A-Za-z][A-Za-z .()/&%'-]*?)\s+((?:-?[\d,]*\d\.\d{2}(?:\s+|$))+)")

PAY_TOTALS = {
    "gross": ("gross earning", "gross pay", "gross salary", "total earning",
              "jumlah pendapatan"),
    "total_deductions": ("total deduction", "jumlah potongan"),
    "net": ("nett pay", "net pay", "nett salary", "net salary", "nett income",
            "net income", "take home", "gaji bersih"),
}
PAY_STOP = ("gross", "total", "nett", "earning", "deduction", "employer", "current",
            "ytd", "working", "absent", "lateness", "upl", "qty", "amount", "period",
            "company", "bank", "payslip", "signature", "page")
PAY_DEDUCT = ("epf", "kwsp", "socso", "perkeso", "eis", "employment insurance", "tax",
              "pcb", "mtd", "cukai", "zakat", "cp38", "loan", "advance", "potongan",
              "unpaid", "deduct")
PAY_EARN = ("salary", "gaji", "basic", "allowance", "elaun", "overtime", "bonus",
            "commission", "incentive", "claim", "arrear", "shift", "wage")
PAY_CANON = (
    (("epf", "kwsp"), "EPF"),
    (("socso", "perkeso"), "SOCSO"),
    (("eis", "employment insurance"), "EIS"),
    (("zakat",), "Zakat"),
    (("income tax", "pcb", "mtd", "cukai", "tax"), "Income Tax (PCB)"),
)
PAY_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
PAY_MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})


def _pay_close(a, b):
    return a is not None and b is not None and abs(a - b) <= 0.02


def _pay_labelled(lines, labels):
    """First amount printed right after any of the labels."""
    for line in lines:
        low = line.lower()
        for lab in labels:
            i = low.find(lab)
            if i >= 0:
                m = PAY_MONEY.search(line, i + len(lab))
                if m:
                    return _amount(m.group())
    return None


def _pay_candidates(lines):
    """Every label+numbers run -> {name, source, amount, kind}, deduped."""
    out, seen = [], set()
    for line in lines:
        for m in PAY_ITEM.finditer(line):
            name = " ".join(m.group(1).split()).strip(" .:-")
            low = name.lower()
            if len(low) < 3 or any(w in low for w in PAY_STOP):
                continue
            toks = m.group(2).split()
            vals = [_amount(t) for t in toks]
            if len(vals) == 2:
                # "name qty amount" (qty = days/units/rate, small, no thousands
                # separator) vs a "name current ytd" summary pair, where the
                # current month is first. A wrong pick here still gets caught
                # and repaired by the reconciliation pass below.
                qty_like = "," not in toks[0] and 0 <= vals[0] <= 400
                amt = vals[1] if qty_like else vals[0]
            else:
                amt = vals[0]  # single amount, or employee-current column of the YTD table
            if amt <= 0:
                continue
            if any(w in low for w in PAY_DEDUCT):
                kind = "deduction"
            elif any(w in low for w in PAY_EARN):
                kind = "earning"
            else:
                kind = "unknown"
            disp = name
            for keys, canon in PAY_CANON:
                if any(k in low for k in keys):
                    disp = canon
                    break
            key = (disp.lower(), round(amt * 100))
            if key in seen:
                continue
            seen.add(key)
            out.append({"name": disp, "source": name, "amount": round(amt, 2), "kind": kind})
    return out


def _pay_rescue(cands, target):
    """Subset of candidates summing exactly to the printed total (indices).

    Keyword-classified deductions are offered to the DP first so they end up
    in the answer whenever an exact match containing them exists.
    """
    cents = round(target * 100)
    if cents <= 0 or len(cands) > 40:
        return None
    order = sorted(range(len(cands)),
                   key=lambda i: 0 if cands[i]["kind"] == "deduction" else 1)
    dp = {0: ()}
    for i in order:
        c = round(cands[i]["amount"] * 100)
        if c <= 0 or c > cents:
            continue
        add = {}
        for s, path in dp.items():
            t = s + c
            if t <= cents and t not in dp and t not in add:
                add[t] = path + (i,)
        dp.update(add)
        if cents in dp:
            break
    hit = dp.get(cents)
    return sorted(hit) if hit is not None else None


def _pay_period(text):
    for m in re.finditer(r"\b([A-Za-z]{3,9})\s*[/ ,-]\s*(20\d{2})\b", text):
        mon = PAY_MONTHS.get(m.group(1).lower())
        if mon:
            return f"{m.group(2)}-{mon:02d}", f"{calendar.month_name[mon]} {m.group(2)}"
    m = re.search(r"(?:period|month|bulan|gaji)\D{0,10}\b(0?[1-9]|1[0-2])\s*/\s*(20\d{2})\b",
                  text, re.I)
    if m:
        mon = int(m.group(1))
        return f"{m.group(2)}-{mon:02d}", f"{calendar.month_name[mon]} {m.group(2)}"
    return None, None


def _pay_employer(lines):
    for line in lines:
        m = re.match(r"company\b[:\s]+(.+)", line, re.I)
        if m:
            # cut at the duplicated "X / X" form and at the next field label
            name = re.split(r"\s+/\s+|\s{2,}|\b(?:location|address|branch)\b",
                            m.group(1), 1, re.I)[0]
            name = " ".join(name.split()).strip(" .,-:/")
            if name:
                return name
    return None


def parse_payslip(lines):
    text = "\n".join(lines)
    gross = _pay_labelled(lines, PAY_TOTALS["gross"])
    total = _pay_labelled(lines, PAY_TOTALS["total_deductions"])
    net = _pay_labelled(lines, PAY_TOTALS["net"])
    printed = sum(v is not None for v in (gross, total, net))
    if printed < 2:
        raise ValueError("could not find the payslip totals"
                         " (need two of: gross / total deduction / nett pay)")
    if gross is None:
        gross = round(net + total, 2)
    if total is None:
        total = round(gross - net, 2)
    if net is None:
        net = round(gross - total, 2)

    cands = _pay_candidates(lines)
    deds = [c for c in cands if c["kind"] == "deduction"]
    warnings = []
    if not _pay_close(sum(c["amount"] for c in deds), total):
        pool = [c for c in cands if c["kind"] != "earning"]
        hit = _pay_rescue(pool, total)
        if hit is not None:
            deds = [pool[i] for i in hit]
            extras = [c["source"] for c in deds if c["kind"] != "deduction"]
            if extras:
                warnings.append("included by arithmetic: " + ", ".join(extras))
        else:
            gap = round(total - sum(c["amount"] for c in deds), 2)
            warnings.append(f"parsed deductions miss the printed total by RM {gap:,.2f}"
                            " — edit below before saving")

    earns = [c for c in cands if c["kind"] == "earning"]
    earn_sum = round(sum(c["amount"] for c in earns), 2)
    checks = {
        "deductions_reconcile": _pay_close(sum(c["amount"] for c in deds), total),
        "identity": _pay_close(round(gross - total, 2), net) if printed == 3 else None,
        "earnings_reconcile": _pay_close(earn_sum, gross) if earns else None,
    }
    if checks["identity"] is False:
        warnings.append("gross − total deductions ≠ nett pay on the slip itself")
    if checks["earnings_reconcile"] is False:
        warnings.append(f"earning items sum to RM {earn_sum:,.2f},"
                        f" slip gross is RM {gross:,.2f}")

    period, period_label = _pay_period(text)
    employer = _pay_employer(lines)
    short = employer and re.sub(
        r"\b(sdn\.?|bhd\.?|berhad|sendirian|plt|enterprise|holdings?|co\.?|ltd\.?)\b",
        "", employer, flags=re.I)
    short = short and " ".join(short.split()).strip(" .,&-")
    return {
        "gross": round(gross, 2), "net": round(net, 2),
        "total_deductions": round(total, 2),
        "deductions": [{"name": c["name"], "source": c["source"], "amount": c["amount"]}
                       for c in deds],
        "earnings": [{"name": c["name"], "amount": c["amount"]} for c in earns],
        "checks": checks, "warnings": warnings,
        "period": period, "period_label": period_label,
        "employer": employer,
        "suggested_name": f"Salary — {short}" if short else "Salary",
    }


@app.post("/api/payslip/parse")
def payslip_parse():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "no file"}), 400
    try:
        import pdfplumber
    except ImportError:
        return jsonify({"error": "PDF reading not available on the server"
                                 " - pip install pdfplumber"}), 400
    try:
        with pdfplumber.open(io.BytesIO(f.read())) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    except Exception:
        return jsonify({"error": "could not open this PDF (corrupt or password-protected?)"}), 400
    lines = [" ".join(l.split()) for l in text.splitlines() if l.strip()]
    if not lines:
        return jsonify({"error": "no text in this PDF - scanned image?"
                                 " export the digital payslip instead"}), 400
    try:
        out = parse_payslip(lines)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    out["filename"] = f.filename
    out["incomes"] = [dict(r) for r in db().execute(
        "SELECT id, name, gross_monthly FROM income ORDER BY id")]
    return jsonify(out)


@app.post("/api/payslip/save")
def payslip_save():
    d = request.get_json(force=True)
    try:
        name = (d.get("name") or "").strip()
        if not name:
            raise ValueError("income name required")
        gross = float(d.get("gross_monthly"))
        if gross < 0:
            raise ValueError("gross must be >= 0")
        deds = []
        for r in d.get("deductions") or []:
            n = (r.get("name") or "").strip()
            a = float(r.get("amount_monthly"))
            if not n:
                raise ValueError("every deduction needs a name")
            if a < 0:
                raise ValueError("deduction amounts must be >= 0")
            deds.append((n, a))
    except (TypeError, ValueError) as e:
        return jsonify({"error": str(e) or "bad values"}), 400
    con = db()
    income_id = d.get("income_id")
    try:
        if income_id:
            income_id = int(income_id)
            if not con.execute("SELECT 1 FROM income WHERE id = ?", (income_id,)).fetchone():
                return jsonify({"error": "income not found"}), 404
            con.execute("UPDATE income SET name = ?, gross_monthly = ? WHERE id = ?",
                        (name, gross, income_id))
            con.execute("DELETE FROM deduction WHERE income_id = ?", (income_id,))
        else:
            income_id = con.execute(
                "INSERT INTO income (name, gross_monthly) VALUES (?, ?)",
                (name, gross)).lastrowid
        con.executemany(
            "INSERT INTO deduction (income_id, name, amount_monthly) VALUES (?, ?, ?)",
            [(income_id, n, a) for n, a in deds])
        net = gross - sum(a for _, a in deds)
        con.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('payslip_last', ?)",
                    (json.dumps({
                        "period": d.get("period"), "period_label": d.get("period_label"),
                        "employer": d.get("employer"), "filename": d.get("filename"),
                        "income_id": income_id, "gross": round(gross, 2),
                        "net": round(net, 2), "saved_on": date.today().isoformat(),
                    }),))
        con.commit()
    except Exception:
        con.rollback()
        raise
    return jsonify({"ok": True, "income_id": income_id, "net": round(net, 2)})


# ------------------------------------------------------------------------ crud

# entity -> (columns the API may write, columns required on create)
ENTITIES = {
    "income":       (["name", "gross_monthly"], ["name", "gross_monthly"]),
    "deduction":    (["income_id", "name", "amount_monthly"], ["income_id", "name", "amount_monthly"]),
    "category":     (["name", "sort"], ["name"]),
    "expense":      (["name", "category_id", "amount", "cadence", "is_estimate", "renews_on", "notes"],
                     ["name", "category_id", "amount"]),
    "goal":         (["name", "target_amount", "deadline", "yearly", "notes"], ["name", "target_amount", "deadline"]),
    "contribution": (["goal_id", "on_date", "amount"], ["goal_id", "on_date", "amount"]),
    "tracker":      (["name", "grp", "interval_months", "expires_on", "expected_cost", "notes"], ["name"]),
    "entry":        (["tracker_id", "on_date", "cost", "note"], ["tracker_id", "on_date"]),
    "checkin":      (["on_date", "balance", "note"], ["on_date", "balance"]),
    "rule":         (["keyword", "category_id"], ["keyword", "category_id"]),
    "txn":          (["category_id"], ["category_id"]),   # manual category override
    "statement":    ([], []),                              # delete-only via API
}

NUMERIC = {"gross_monthly", "amount_monthly", "amount", "target_amount", "expected_cost", "cost", "balance"}
INTEGER = {"income_id", "category_id", "goal_id", "sort", "is_estimate", "tracker_id", "interval_months", "yearly"}
DATES = {"renews_on", "deadline", "on_date", "expires_on"}


def clean(entity, data, creating):
    cols, required = ENTITIES[entity]
    if creating:
        missing = [c for c in required if data.get(c) in (None, "")]
        if missing:
            raise ValueError("missing: " + ", ".join(missing))
    out = {}
    for c in cols:
        if c not in data:
            continue
        v = data[c]
        if v == "":
            v = None
        if v is not None:
            if c in NUMERIC:
                v = float(v)
                # balance may be negative (overdraft); income can only be zeroed
                if c not in ("gross_monthly", "balance") and v < 0:
                    raise ValueError(f"{c} must be >= 0")
            elif c in INTEGER:
                v = int(v)
            elif c in DATES:
                date.fromisoformat(v)  # raises ValueError on junk
        out[c] = v
    if out.get("cadence") is not None and out["cadence"] not in CADENCE_MONTHS:
        raise ValueError("cadence must be one of: " + ", ".join(CADENCE_MONTHS))
    return out


def _tag_to_category(data):
    """The plan page sends a category NAME (the inline tag); resolve or create it."""
    name = (data.pop("category", None) or "").strip()
    if name and not data.get("category_id"):
        con = db()
        row = con.execute("SELECT id FROM category WHERE name = ? COLLATE NOCASE",
                          (name,)).fetchone()
        data["category_id"] = row["id"] if row else con.execute(
            "INSERT INTO category (name, sort)"
            " VALUES (?, (SELECT COALESCE(MAX(sort), 0) + 1 FROM category))",
            (name,)).lastrowid
    return data


@app.post("/api/<entity>")
def create(entity):
    if entity not in ENTITIES:
        return jsonify({"error": "unknown entity"}), 404
    try:
        data = request.get_json(force=True)
        if entity == "expense":
            data = _tag_to_category(data)
        row = clean(entity, data, creating=True)
        cols = list(row)
        cur = db().execute(
            f"INSERT INTO {entity} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
            [row[c] for c in cols])
        db().commit()
        return jsonify({"id": cur.lastrowid})
    except (ValueError, TypeError, sqlite3.IntegrityError) as e:
        return jsonify({"error": str(e)}), 400


@app.put("/api/<entity>/<int:rid>")
def update(entity, rid):
    if entity not in ENTITIES:
        return jsonify({"error": "unknown entity"}), 404
    try:
        data = request.get_json(force=True)
        if entity == "expense":
            data = _tag_to_category(data)
        row = clean(entity, data, creating=False)
        if not row:
            return jsonify({"error": "nothing to update"}), 400
        cols = list(row)
        db().execute(
            f"UPDATE {entity} SET {', '.join(c + ' = ?' for c in cols)} WHERE id = ?",
            [row[c] for c in cols] + [rid])
        db().commit()
        return jsonify({"ok": True})
    except (ValueError, TypeError, sqlite3.IntegrityError) as e:
        return jsonify({"error": str(e)}), 400


@app.delete("/api/<entity>/<int:rid>")
def delete(entity, rid):
    if entity not in ENTITIES:
        return jsonify({"error": "unknown entity"}), 404
    try:
        db().execute(f"DELETE FROM {entity} WHERE id = ?", (rid,))
        db().commit()
        return jsonify({"ok": True})
    except sqlite3.IntegrityError:
        return jsonify({"error": f"{entity} is still referenced by other rows"}), 400


# ---------------------------------------------------------------------- static

@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/plan")
def plan():
    return send_from_directory(app.static_folder, "plan.html")


@app.get("/radar")
def radar():
    return send_from_directory(app.static_folder, "radar.html")


@app.get("/month")
def month():
    return send_from_directory(app.static_folder, "month.html")


# pre-restructure tab urls (bookmarks, muscle memory) keep landing somewhere sane
for _old, _new in (("/manage", "/plan"), ("/subs", "/radar"), ("/life", "/radar"),
                   ("/history", "/month"), ("/reconcile", "/month")):
    app.add_url_rule(_old, "legacy_" + _old.strip("/"),
                     (lambda target: lambda: redirect(target))(_new))


@app.post("/api/snapshot/now")
def snapshot_now():
    key = f"{date.today().year}-{date.today().month:02d}"
    if snap_month(db(), key):
        return jsonify({"ok": True, "month": key})
    return jsonify({"error": "nothing to snapshot yet"}), 400


@app.delete("/api/snapshot/<int:rid>")
def snapshot_delete(rid):
    db().execute("DELETE FROM snapshot WHERE id = ?", (rid,))
    db().commit()
    return jsonify({"ok": True})


if __name__ == "__main__":
    init_db()
    app.secret_key = _ensure_secret()
    port = int(os.getenv("PORT", "5002"))
    print(f"Budgets GUI: http://127.0.0.1:{port}" + (" (login required)" if PASSWORD else ""))
    app.run(host=os.getenv("HOST", "127.0.0.1"), port=port,
            debug=False, threaded=True)
