# Budgets

Every ringgit of net income mapped -> surplus -> wealth goals. Flask + SQLite, port 5002.

    budget          ->  opens https://budget.tubby.asia (the hosted portal - daily driver)
    budget local    ->  starts the local dev server and opens http://127.0.0.1:5002
    budget stop     ->  stops the local dev server
    budget deploy   ->  ships scripts/static to the droplet and restarts the service
    portals         ->  starts every local portal (replay-gui 5000, running 5001, budgets 5002)
    portals stop    ->  stops all local python portals (never touches Docker)

Commands live in `..\bin` and are on PATH via forwarders in `C:\Users\etern\bin`.
Manual fallback: `python scripts/gui.py`.

Five tabs, one per question (restructured 2026-07-05; the old /manage, /subs, /life,
/radar, /history, /reconcile and /month URLs redirect to their new homes). Nav labels:
Budget · Plan · Upcoming · Savings · Strategy.

- `/` (home) — decide: gross -> deductions -> net -> categories (RM + % of net) -> surplus,
  goal pacing ("surplus gives RM X/mo -> RM Y by deadline"), and upcoming non-monthly
  rolls in the next 90 days. Goals marked "resets yearly" (EPF self-contribution:
  the RM100k cap is per calendar year) roll their deadline to Dec 31 every year and
  count only that year's contributions - the goal never goes stale.
- `/plan` — enter/edit everything, top to bottom in setup order.
  ① income: gross with deductions indented beneath (per-income net line); forms stay
  hidden until "+ income" (heading) or + on an income row (inline deduction under
  that income) is pressed. Or skip typing entirely: upload a payslip PDF and the reader pulls gross, EPF/SOCSO/EIS/PCB,
  period and employer off it, refuses to trust itself unless the slip's own arithmetic
  reconciles, then previews a one-line diff vs the current base before replacing it.
  ② spending: ONE list for everything money goes to - rent, Netflix, road tax, car
  service, the daily ≈ lump. Every row is name + tag + RM + one repeat rule:
  monthly/quarterly/half-yearly/yearly (counted in the map, optional renews-on date)
  or every-N-months / fixed-expiry / log-only (radar only - expected money the lumps
  already cover, so no double-counting). Mapped rows take an optional ends date: a
  cancelled sub keeps counting until it lapses, then drops out of the map and the
  radar automatically ("ended" pill, row stays for history) - past months keep their
  snapshots either way. The tag is typed inline (datalist of existing
  categories + groups); new category names are created on the fly - no categories card.
  Notes show dim after the name. A mapped row expands (click) into its breakdown:
  named fixed pieces inside the lump (TIME internet 145.20, Cuckoo 60 "2nd of month")
  plus the unaccounted rest - informational only, the map still counts the lump.
  ③ goals: click a goal to see and log its contributions inline.
  ④ investments: allocation-only earmarks as % of net (or gross) income -> RM/mo,
  e.g. "S&P 500 · 12% of net". Home's waterfall splits the surplus into earmarks and
  "free for goals"; goal pacing draws on the free part; click a row to log actual
  transfers (which drift nets out, same as goal contributions). No returns/price
  tracking - conservative estimates only, later, per the locked scope.
  Plus a "tags" section at the bottom: rename or delete any tag (expense category
  or tracker group) with usage counts; deletes are refused while items still use it.
- `/upcoming` (was /radar) — everything dated on one timeline, soonest first: expense renewals and
  tracker dues/expiries together. Tracker rows expand in place to log a renewal
  (expiry items offer "new expiry" in the same form - road tax renewals are one row);
  logging a past date backfills "last changed". Below it, the log-only list answers
  "when did I last ..." (haircut, running shoes). Definitions are edited in /plan.
- `/savings` — the projection, front and centre: net − plan = surplus/mo, carried
  forward ("by Dec 31" / "in 12 months"), anchored in real ringgit once a monthly
  balance check-in is logged (money moved to goals/investments stays counted as
  savings). Below it: check-ins with the drift verdict (bank moved vs plan
  predicted, net of transfers), statement CSV upload with keyword rules (teach
  once, applies forever), actual vs plan per category, and auto-closed month
  snapshots. Never required beyond the one check-in - skip the rest and the app
  works exactly as before. PDF statements: drop one sample in `samples/`
  (gitignored) and the exact parser gets built against it.

- `/strategy` — the standing playbook, static reference (no data entry): float rule
  (RM15-20k liquid always), the stack (S&P DCA -> house fund -> EPF), EPF dividend
  mechanics (contributions earn from the last day of their month - drip beats a
  December lump), broker comparison (IBKR CSPX quarterly vs moomoo VOO monthly),
  cash-parking rates (dated - rates move), and house affordability numbers.
  Update it when the strategy changes; it is advice-as-of-a-date, not live data.

Money model (locked 2026-07-05): exact recurring items (subscriptions, rent, insurance,
with real renewal dates) + lump-sum monthly estimates (food, personal). No per-transaction
entry, ever. Goal contributions are logged only when money actually moves.

Data is a single file: `data/budgets.db` (gitignored). Back it up by copying the file.

## Hosted (the real instance)

**https://budget.tubby.asia** - password login (any browser, any device, PC off is fine).
The password lives locally in `data/hosted-password.txt`; to rotate it, edit
`/opt/budgets/.env` on the droplet and `systemctl restart budgets`.

Architecture on the avery droplet (167.99.65.102):
- systemd service `budgets` running as its own unix user, `/opt/budgets`, venv + Flask,
  memory-capped (MemoryMax=250M) so it can never starve the neighbouring MySQL.
- Port 5002 is ufw-allowed only from the docker subnet (172.19.0.0/16) - invisible publicly.
- nginx vhost `budget.tubby.asia` lives in the avery compose stack
  (`/home/deploy/avery-psychology/nginx/conf.d/budget.conf`), reloaded via SIGHUP.
- Cloudflare-proxied, zone SSL mode "Full" (optional hardening: Origin CA cert for
  `*.tubby.asia` + "Full (strict)").
- Nightly DB backup via `/etc/cron.daily/budgets-backup` -> 7 rotating weekday copies
  in `/opt/budgets/data/`.

**The hosted DB is the source of truth.** The local copy under `data/` is a dev
sandbox - it diverges from production and deploys never touch either DB.
Deploy code changes with `budget deploy` (ships scripts/static, restarts the service).
Deploys ship code only - a new python dependency needs a one-time
`ssh avery "/opt/budgets/venv/bin/pip install -r /opt/budgets/requirements.txt"`
(pdfplumber added 2026-07-05 for the payslip reader).

## Open items

- PDF statement parsers: waiting on real samples dropped into `samples/`
  (TNG app export, bank PDF) - each gets an exact tested parser.
- Optional hardening: Cloudflare "Full (strict)" + free Origin CA cert for `*.tubby.asia`.
- The droplet has a pending kernel upgrade - reboot it sometime (brief avery downtime).
- The hosted DB still needs real data: income + deductions now come from a payslip
  upload on /plan; expenses and tracker history are still hand-entered.
