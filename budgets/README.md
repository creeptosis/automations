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

Pages:

- `/` — decision screen: gross -> deductions -> net -> categories (RM + % of net) -> surplus,
  goal pacing ("surplus gives RM X/mo -> RM Y by deadline"), and upcoming non-monthly
  rolls in the next 90 days.
- `/subs` — every expense with a roll date: exact cost, cadence, next renewal (computed
  forward from the anchor date, so past dates never go stale), monthly equivalent.
- `/life` — life-admin trackers (haircut, car service, battery, road tax docs, passport):
  last done, cost then, next due (last entry + interval). Click a row to see history and
  log a new entry. Dues within 90 days (and overdue) join the decision screen's UPCOMING
  list marked `~` — expected money, not part of the budget map (no double-counting).
- `/history` — the honesty loop: log your total bank balance once a month; drift shows
  how the bank actually moved vs what the plan predicted (net of goal contributions),
  e.g. "bank +RM 2,400, plan said +RM 3,100 -> ~RM 700/mo unmapped". Months auto-close
  into snapshots (net, mapped, surplus, savings rate, per-category) the first time the
  app runs in a new month, building the multi-year record.
- `/reconcile` — optional honesty upgrade for the lumps: upload a bank/e-wallet CSV,
  keyword rules categorise every spend (teach once, applies forever), and each month
  shows actual vs plan per category ("Food actually ran RM 1,712 vs the RM 1,500 lump").
  Duplicate rows across overlapping statements are skipped. Never required - skip it
  and the app works exactly as before. PDF statements: drop one sample in `samples/`
  (gitignored) and the exact parser gets built against it.
- `/manage` — edit income, deductions, expenses, goals, contributions, categories,
  and tracker definitions.

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

## Open items

- PDF statement parsers: waiting on real samples dropped into `samples/`
  (TNG app export, bank PDF) - each gets an exact tested parser.
- Optional hardening: Cloudflare "Full (strict)" + free Origin CA cert for `*.tubby.asia`.
- The droplet has a pending kernel upgrade - reboot it sometime (brief avery downtime).
- The hosted DB still needs real data: income, deductions, expenses, tracker history.
