# Site database backup — what it covers, and how to restore

This file is the operator's copy.  The source of truth is
[`docs/BACKUP.md`](../docs/BACKUP.md) in the app's repository; the backup
script copies it here after every successful run, so the runbook is next to
the artifacts rather than in a repository somebody has to find first.

## What is covered

| | |
|---|---|
| **What** | The MariaDB database of every site in the list, the site's private and public files, and its `site_config.json`. |
| **Which sites** | `albanna.localhost` (production for this app) and `frappe.localhost` (the live Albanna business data). |
| **Which are not** | `test.localhost` — a disposable clone that the test suite overwrites. Backing it up would fill the disk to protect nothing. |
| **Where** | `/home/frappe/backups/sites/<site>/{daily,weekly,monthly}/<date>/` |
| **When** | Daily at 03:47, by `albanna-site-backup.timer`. A missed run fires on the next boot. |
| **How long** | 14 daily, 8 weekly, 6 monthly, per site. |

The MCP control-plane backup (`/home/frappe/backups/mcp/`) covers
PostgreSQL, Redis and the file-based secrets.  It does **not** cover these
databases, and it says so in its own header.

## What a run checks before it is declared good

A file that exists is not a backup.  Before a run is marked good, each
dump must pass all of these:

1. the gzip stream is intact (`gzip -t`);
2. mysqldump's completion footer is present — a truncated dump is still a
   valid gzip stream, so this is the check that catches a cut-short dump;
3. it holds a plausible number of tables (at least ten);
4. it holds the site's own tables — `tabAlbanna Chat Log`,
   `tabAlbanna Conversation` and `tabAlbanna Message` for
   `albanna.localhost`;
5. it holds **no fewer** tables than the last good dump — the schema only
   grows, so a drop means the dump came from the wrong place;
6. the file archives list, and the site config is valid JSON.

If any of these fails, the run exits non-zero, the artifacts are kept for
inspection, and `last_ok` is **not** updated.

## How to tell whether it is working

There is no mail on this host, so the alert is the staleness of the
marker file:

```bash
cat /home/frappe/backups/sites/last_ok          # the last fully good run
cat /home/frappe/backups/sites/<site>/last_ok    # the last good run for one site
tail -50 /var/log/site-backup.log
systemctl list-timers albanna-site-backup.timer
```

If `last_ok` is more than a day old, the last run did not pass.  The log
says why.

## How to restore

A restore is a decision, not a cron job.  Read this before you start.

**What a restore costs.**  Restoring the database replaces everything in
it: the documents, the chat history, the users, the settings.  Anything
written since the dump was taken is gone.  Take a fresh dump of the current
state first, so the way back is still open.

**Which dump.**  Every generation has a `MANIFEST.txt` with the sha256 and
size of each artifact, and the table count and insert count of the dump.
Check the manifest before trusting a file:

```bash
cd /home/frappe/backups/sites/albanna.localhost/daily/2026-10-29
sha256sum -c <(awk '/^[0-9a-f]{64}/ {print $1"  "$3}' MANIFEST.txt)
```

**The steps.**

1. Put the site in maintenance mode, so nobody writes to a database that
   is about to be replaced:

   ```bash
   bench --site albanna.localhost set-maintenance-mode on
   ```

2. Take a dump of the state you are about to discard, so the way back is
   still open:

   ```bash
   bench --site albanna.localhost backup --with-files
   ```

3. Restore the database.  `bench restore` drops the site's database and
   rebuilds it from the dump, and re-applies the framework's patches so the
   schema matches the apps that are on disk.  It needs **MariaDB root
   credentials** — `--db-root-username` and `--db-root-password` — and on
   this host the root password is not in a usable state; ask the operator
   for it rather than guessing.  The file archives are passed by path:

   ```bash
   cd /home/frappe/backups/sites/albanna.localhost/daily/2026-10-29
   bench --site albanna.localhost restore \
      20261029_034700-albanna_localhost-database.sql.gz \
      --with-public-files  20261029_034700-albanna_localhost-files.tar.gz \
      --with-private-files 20261029_034700-albanna_localhost-private-files.tar.gz \
      --db-root-username root --db-root-password '<from the operator>'
   ```

   The restore is interactive and asks before it overwrites the database.
   That prompt is the last checkpoint — read it.

   `bench restore` leaves the site's `site_config.json` alone ✓, so the
   database password and the encryption key stay as they are.

4. Put the site's private files back, if the restore did not already do
   it.  The archive holds the site's `private/files` tree:

   ```bash
   tar -xzf <dump>-private-files.tar.gz -C /home/frappe/frappe-bench/sites/albanna.localhost
   ```

5. Clear the cache and restart, so the workers do not serve a document from
   a cache that predates the restore:

   ```bash
   bench --site albanna.localhost clear-cache
   sudo systemctl restart frappe-bench-frappe-web
   sudo supervisorctl restart 'frappe-bench-frappe-short-worker:*'
   sudo supervisorctl restart 'frappe-bench-frappe-long-worker:*'
   ```

6. Turn maintenance mode off, and check the site answers:

   ```bash
   bench --site albanna.localhost set-maintenance-mode off
   curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: albanna.localhost' http://127.0.0.1:8086/login
   ```

**What is not restored by the database dump.**  The shared `sites/assets`
directory (the built front-end assets and the uploaded files that live
there) is not in the site's dump — it is shared by every site on the bench.
Rebuild it if it is missing:

```bash
cd /home/frappe/frappe-bench && bench build
```

The bench's own configuration — `site_config.json`, the encryption key, the
database password — is not in the dump either.  The `site_config_backup.json`
in the generation holds a copy of the site's config as it was at dump time,
but restoring it over the live config would overwrite the current database
password.  Use it as a reference, not as a file to copy back.

## The known gap

These artifacts live on the same disk as the databases they protect.  They
protect against a bad edit, a bad migration, and a mistake — not against the
disk.  Copying them off this host is the missing step, and it is not done
here.  The MCP backup has the same gap, and says so in the same words.

## One thing to know about the site's own backup directory

Frappe cleans `sites/<site>/private/backups/` itself: `bench backup` deletes
the files there that are older than `keep_backups_for_hours`, which defaults
to 24.  Left alone, that would delete the safety net taken before a
migration one day later — and a *newer* scheduled dump is not the same
thing as the dump taken before that particular migration.

So both covered sites have `keep_backups_for_hours` set to 336 (fourteen
days).  The site's own directory keeps a fortnight of manual dumps, and the
scheduled generations live in `/home/frappe/backups/sites/` on their own
rotation.
