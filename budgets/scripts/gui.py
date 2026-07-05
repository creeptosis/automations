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
    interval_months INTEGER,
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

# (name, interval in months or None for log-only)
DEFAULT_TRACKERS = [
    ("Haircut", None), ("Car service", 6), ("Car battery", 24),
    ("Running shoes", None), ("Driving license", None), ("Passport", 60),
]


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)
    if con.execute("SELECT COUNT(*) FROM category").fetchone()[0] == 0:
        con.executemany("INSERT INTO category (name, sort) VALUES (?, ?)",
                        [(n, i) for i, n in enumerate(DEFAULT_CATEGORIES)])
    if con.execute("SELECT COUNT(*) FROM goal").fetchone()[0] == 0:
        con.execute(
            "INSERT INTO goal (name, target_amount, deadline, notes) VALUES (?, ?, ?, ?)",
            ("EPF self-contribution", 100000, f"{date.today().year}-12-31",
             "Voluntary top-up; cap RM100,000 per calendar year"))
    if con.execute("SELECT COUNT(*) FROM tracker").fetchone()[0] == 0:
        con.executemany("INSERT INTO tracker (name, interval_months) VALUES (?, ?)",
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
)

LOGIN_HTML = """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Budget · login</title>
<style>body{font-family:'Segoe UI',system-ui,sans-serif;background:#111418;color:#e6e6e6;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
form{background:#1a1f26;border:1px solid #2c333d;border-radius:10px;padding:24px;
display:flex;gap:8px;flex-direction:column;width:250px}h1{font-size:1.1em;margin:0 0 4px}
input,button{background:#1e242c;color:#e6e6e6;border:1px solid #2c333d;border-radius:6px;padding:8px}
button{background:#2b3a4d;border-color:#3d5878;cursor:pointer}
.err{color:#f87171;font-size:.85em;min-height:1em}</style></head>
<body><form method="post"><h1>Budget</h1>
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
        if t["last"] and t["interval_months"]:
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
        [{"name": t["name"], "category": "due", "amount": t["expected_cost"],
          "on": t["next_due"], "days": t["days_to_due"], "expected": True}
         for t in trackers
         if t.get("next_due") and t["days_to_due"] <= 90],
        key=lambda u: u["on"])

    goals = []
    for gl in con.execute("SELECT * FROM goal ORDER BY id"):
        gl = dict(gl)
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


# ------------------------------------------------------------------------ crud

# entity -> (columns the API may write, columns required on create)
ENTITIES = {
    "income":       (["name", "gross_monthly"], ["name", "gross_monthly"]),
    "deduction":    (["income_id", "name", "amount_monthly"], ["income_id", "name", "amount_monthly"]),
    "category":     (["name", "sort"], ["name"]),
    "expense":      (["name", "category_id", "amount", "cadence", "is_estimate", "renews_on", "notes"],
                     ["name", "category_id", "amount"]),
    "goal":         (["name", "target_amount", "deadline", "notes"], ["name", "target_amount", "deadline"]),
    "contribution": (["goal_id", "on_date", "amount"], ["goal_id", "on_date", "amount"]),
    "tracker":      (["name", "interval_months", "expected_cost", "notes"], ["name"]),
    "entry":        (["tracker_id", "on_date", "cost", "note"], ["tracker_id", "on_date"]),
    "checkin":      (["on_date", "balance", "note"], ["on_date", "balance"]),
    "rule":         (["keyword", "category_id"], ["keyword", "category_id"]),
    "txn":          (["category_id"], ["category_id"]),   # manual category override
    "statement":    ([], []),                              # delete-only via API
}

NUMERIC = {"gross_monthly", "amount_monthly", "amount", "target_amount", "expected_cost", "cost", "balance"}
INTEGER = {"income_id", "category_id", "goal_id", "sort", "is_estimate", "tracker_id", "interval_months"}
DATES = {"renews_on", "deadline", "on_date"}


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


@app.post("/api/<entity>")
def create(entity):
    if entity not in ENTITIES:
        return jsonify({"error": "unknown entity"}), 404
    try:
        row = clean(entity, request.get_json(force=True), creating=True)
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
        row = clean(entity, request.get_json(force=True), creating=False)
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


@app.get("/manage")
def manage():
    return send_from_directory(app.static_folder, "manage.html")


@app.get("/subs")
def subs():
    return send_from_directory(app.static_folder, "subs.html")


@app.get("/life")
def life():
    return send_from_directory(app.static_folder, "life.html")


@app.get("/history")
def history():
    return send_from_directory(app.static_folder, "history.html")


@app.get("/reconcile")
def reconcile():
    return send_from_directory(app.static_folder, "reconcile.html")


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
