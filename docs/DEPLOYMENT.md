# Deploying the Albanna app

This is the runbook for putting a change to this app onto the production
site.  It was written after the 0.2.1 deployment, from what that deployment
actually needed — including the things that went wrong, or nearly went
wrong, on the way.

Read it once end to end before your first deploy.  After that, the order is
the part that matters.

## What is deployed where

| | |
|---|---|
| **The code** | `/home/frappe/frappe-bench/apps/albanna` — git, branch `main`, pushed to `origin/main`. |
| **The production site** | `albanna.localhost`. It is served by nginx on **:8086** with `Host: albanna.localhost`; the Desk is at `http://127.0.0.1:8086/app`. |
| **The test site** | `test.localhost` — the suite runs there, and it is where a change is proved before it is deployed. |
| **The assets** | Built into `sites/assets`, which is **shared by every site on the bench**. One build changes all of them. |

The site's database is `albanna.localhost`; its app is not installed on the
other sites except `test.localhost`.

## The order

Do not reorder these.  Each step exists because of something that went
wrong, or nearly went wrong, without it.

1. **Backup** — so there is a way back if the migrate breaks the site.
2. **Build** — so a broken build is discovered *before* the site goes down.
3. **Migrate** — in a maintenance window, because it locks the site.
4. **Restart every worker set** — systemd *and* supervisor.
5. **Verify** — the site, the assets, the workers, a live turn, the ledger.

---

### 1. Backup

```bash
cd /home/frappe/frappe-bench
bench --site albanna.localhost backup --with-files
```

This is safe to run against production: it is a dump and a file archive.  It
does **not** run a migrate and does **not** sync the schema — which is
exactly what `bench --site <site> execute` does, and must never be used as
a health check (see *Never use these* below).

The dump lands in `sites/albanna.localhost/private/backups/`.  Frappe cleans
that directory after `keep_backups_for_hours` (336 — a fortnight — on this
site), so the safety net survives the deploy it was taken for.

The scheduled backup (`albanna-site-backup.timer`, daily 03:47) is a second
line of defence, not a substitute: it runs at 03:47, and a deploy at 16:00
wants a dump taken at 15:55.  Check it anyway:

```bash
cat /home/frappe/backups/sites/last_ok
```

### 2. Build

```bash
cd /home/frappe/frappe-bench
bench build --app albanna
```

The assets are shared, so this also rebuilds what `test.localhost` serves.
That is fine and it is also why a build must not be left half-done: the
next site to ask for an asset gets whatever is on disk.

### 3. Migrate

**In a maintenance window.**  The migrate takes an exclusive lock on
`tabDocType`, and every request on the site reads that table — so while the
DDL runs, the whole site hangs and answers `500`.  That is not a fault; it
is the lock.

```bash
cd /home/frappe/frappe-bench
bench --site albanna.localhost set-maintenance-mode on
bench --site albanna.localhost migrate          # ~50 s
bench --site albanna.localhost set-maintenance-mode off
```

The migrate does three things this app depends on:

* it syncs the DocType schema, so a field added in a `.json` file becomes a
  column;
* it syncs the **scheduler's job types** — a change to `scheduler_events`
  (the reaper's cadence, for instance) does nothing at all until a migrate
  has created the new `Scheduled Job Type` row and removed the old one;
* it syncs the fixtures.

If the migrate fails, the site stays in maintenance mode and the dump from
step 1 is the way back.

### 4. Restart every worker set

There are **two** sets of workers on this host, and they share the same
Redis queues — so a stale set silently takes half the jobs, and the jobs it
takes run the *old* code.  Both sets must be restarted.

```bash
# systemd: the web server and the three workers
sudo systemctl restart frappe-bench-frappe-web
sudo systemctl restart 'frappe-bench-frappe-default-worker@1'
sudo systemctl restart 'frappe-bench-frappe-long-worker@1'
sudo systemctl restart 'frappe-bench-frappe-short-worker@1'

# supervisor: the two workers and the scheduler
sudo supervisorctl restart 'frappe-bench-frappe-short-worker:*'
sudo supervisorctl restart 'frappe-bench-frappe-long-worker:*'
sudo supervisorctl restart frappe-bench-frappe-schedule
```

`bench restart` **does not work on this host** — it shells out to a
`supervisorctl` group that does not exist here, and it does not touch the
systemd units.  Use the commands above.

Why the workers and not just the web server: each job runs in a worker
process, and that process imported the app's modules when it started.  A
worker that predates the deploy is running the old code, and a worker that
predates the app's *installation* cannot import it at all — its jobs fail
with `ModuleNotFoundError`, which looks, from the user's side, like the app
hanging.

The scheduler (`frappe-bench-frappe-schedule`, under supervisor) is what
enqueues the app's scheduled jobs.  It reads the `Scheduled Job Type` rows
from the database — which the migrate has already written — so it does not
need a restart to pick up a new schedule; it is restarted here anyway, so
that one process on the host is not the one that was running before the
deploy.

### 5. Verify

**The site answers.**

```bash
curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: albanna.localhost' http://127.0.0.1:8086/login
# 200
```

**The assets are served.**  nginx serves `/assets` from disk; gunicorn on
:8000 does not, and answers `404` with an HTML page.  So check the assets
through nginx, and use the *hashed* file name — an unhashed name is a 404
even when everything is fine:

```bash
ls /home/frappe/frappe-bench/sites/assets/albanna/dist/js/ | head
curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: albanna.localhost' \
  http://127.0.0.1:8086/assets/albanna/dist/js/albanna-side-chat.bundle.<HASH>.js
# 200
```

**The workers are up.**

```bash
systemctl status 'frappe-bench-frappe-{default,long,short}-worker@1' --no-pager
sudo supervisorctl status | grep frappe-bench
```

**A live turn.**  Open the panel on a document, ask something that reads
one, and check the answer.  This is the step that catches a provider that
is slow or a prompt that broke — neither shows up in a status code.

**The ledger says what happened.**  The `Albanna Chat Log` list view in the
Desk, or the API.  A finished turn has a terminal `status` (`ok`, `error`,
`capped`, `truncated`), a `rounds` count, a `duration_ms`, and a `tools`
column holding `{"calls": [...], "round_ms": [...]}`.  A write turns shows
`"write": true` on the entry.  A turn that is still `running` long after it
ended is the reaper's business — it relabels rows older than fifteen
minutes every five minutes.

**Nothing new in the Error Log.**  In the Desk: *Error Log*, filtered to
today.

**The scheduler's job types** (only after a change to `scheduler_events`):

```bash
curl -s -H 'Host: albanna.localhost' -b cookies.txt \
  'http://127.0.0.1:8086/api/resource/Scheduled%20Job%20Type?filters=%5B%5B%22method%22%2C%22like%22%2C%22albanna.tasks.%25%22%5D%5D&fields=%5B%22name%22%2C%22method%22%2C%22frequency%22%2C%22cron_format%22%5D'
```

The row must exist with the frequency and the cron expression the hooks
declare — for the reaper, `frequency: Cron` and `cron_format: */5 * * * *`.
A row still reading `Daily` means the migrate did not sync the jobs, and
the change is not live.

The cookie file is a normal login:

```bash
curl -s -c cookies.txt -X POST -H 'Host: albanna.localhost' \
  -H 'Content-Type: application/json' \
  -d '{"usr":"Administrator","pwd":"<the administrator password>"}' \
  http://127.0.0.1:8086/api/method/login
```

## Never use these

| | |
|---|---|
| `bench --site <site> execute …` | It runs as Administrator **and triggers a schema sync**. An `ALTER TABLE` takes an exclusive metadata lock on `tabDocType`, which every request reads — so the site hangs and answers `500` until the DDL finishes. Use `curl` on the login page, or the MCP `/healthz`, to ask whether the site is up. |
| `bench restart` | Does nothing on this host (see step 4). |
| `nginx :80` to check the site | The vhost on `:80` has an empty `server_name` and never matches; it falls through to another site's vhost. Use `:8086` with the `Host:` header. |
| gunicorn `:8000` to check the assets | It does not serve `/assets`; nginx does. Use `:8086`. |

## The language trap

A server-side `_()` follows the **user's** language: `User.language`, then
the site's default language, then `frappe.local.lang`.  The `lang` request
parameter is **not** honoured on API calls.  So a sentence composed on the
server comes back in Arabic only when the *user* is an Arabic user —
switching the browser's language does nothing to it.

To verify an Arabic sentence, use an Arabic user.  To change the site's
language, change `User.language` (or the site default), not the request.

## Rolling back

**The code:** revert the release commit and redeploy.

```bash
cd /home/frappe/frappe-bench/apps/albanna
git revert <release-commit>
cd /home/frappe/frappe-bench && bench build --app albanna
bench --site albanna.localhost migrate
# then restart every worker set, as in step 4
```

**The data:** if the migrate damaged the site, restore the dump taken in
step 1.  The runbook is `docs/BACKUP.md` (a copy of it sits next to the
artifacts as `/home/frappe/backups/sites/RESTORE.md`).  Two things to know
before you start: a restore needs **MariaDB root credentials**, which do not
authenticate on this host — ask the operator — and it replaces everything
written since the dump was taken.

## The release checklist

Before the deploy, on the branch:

- [ ] `cd apps/albanna && ../../env/bin/python -m pytest` — the domain tests
- [ ] `bench --site test.localhost run-tests --app albanna` — the site suite
- [ ] `node albanna/public/js/side-chat/*.test.mjs` — the JS module tests
- [ ] `python scripts/check_translations.py` — every new `_()` string is in
      `albanna/locale/ar.po`
- [ ] `bench build --app albanna` — the build succeeds
- [ ] `__version__` and `CHANGELOG.md` updated; the tag pushed
- [ ] `ROADMAP.md` and `CONTEXT.md` say what this release does — one
      `CONTEXT` entry per design decision

Then on the server: backup → build → migrate → restart every worker set →
verify.
