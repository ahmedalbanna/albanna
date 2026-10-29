#!/usr/bin/env bash
# site-backup — a rotating, verified backup of the bench's site databases.
#
# Why this exists.  The MCP control-plane backup covers PostgreSQL, Redis
# and the file-based secrets, and it says so plainly: the MariaDB site
# databases are NOT covered.  Until this script existed, the only copy of
# production's Albanna data was a manual `bench backup` sitting on the same
# disk as the database it protects — which protects against a bad edit and
# not against the disk.
#
# Three properties this script exists to guarantee, in order:
#
#   1. The dump is *verified* before the run is declared good.  A file that
#      exists is not a backup.  The gzip stream is checked, mysqldump's
#      completion footer must be there, the site's own tables must be in
#      it, and the table count must not have gone *down* since the last
#      good run.
#   2. A failure is loud and unmissable: non-zero exit, a line in
#      /var/log/site-backup.log, and no `last_ok` update.  There is no mail
#      on this host (no Email Account is configured), so the staleness of
#      `last_ok` is the alert.
#   3. Retention is bounded and cheap.  Grandfather-father-son per site, and
#      every generation records its own sha256 so a corrupted artifact is
#      detectable later without re-reading the live database.
#
# What it does *not* do, on purpose:
#
#   * It does not take a backup of the sites it is not told about.
#     `test.localhost` is a disposable clone that the test suite overwrites;
#     backing it up would fill the disk to protect nothing.
#   * It does not restore.  A restore is a decision, not a cron job.  The
#     runbook next to the artifacts says how, and says what is lost.
#   * It does not copy anything off this disk.  The artifacts are local, and
#     that is a known gap, not a hidden one: see docs/BACKUP.md.
#
# The dump is taken with `bench --site <site> backup`, which is the same
# path the application uses to reach the database and which takes a
# `--single-transaction` snapshot — consistent, and without locking the
# tables the site is using.
#
# Environment overrides (all optional):
#
#   SITE_BACKUP_ROOT     where the artifacts live   (default /home/frappe/backups/sites)
#   SITE_BACKUP_SITES    the sites to back up        (default "albanna.localhost frappe.localhost")
#   SITE_BACKUP_LOG      the log file                (default /var/log/site-backup.log)
#   SITE_BACKUP_KEEP_*   retention counts            (defaults below)

set -euo pipefail

BENCH=/home/frappe/frappe-bench
ROOT=${SITE_BACKUP_ROOT:-/home/frappe/backups/sites}
LOG=${SITE_BACKUP_LOG:-/var/log/site-backup.log}
SITES=${SITE_BACKUP_SITES:-"albanna.localhost frappe.localhost"}

KEEP_DAILY=${SITE_BACKUP_KEEP_DAILY:-14}
KEEP_WEEKLY=${SITE_BACKUP_KEEP_WEEKLY:-8}
KEEP_MONTHLY=${SITE_BACKUP_KEEP_MONTHLY:-6}

#: The tables a dump must contain, per site.  These are the site's own
#: tables — the ones that would be missing from a dump of the wrong
#: database, or from a dump taken before the app was installed.  They are
#: separated by `|`, because a table name may contain a space.
declare -A SENTINELS=(
  [albanna.localhost]="tabAlbanna Chat Log|tabAlbanna Conversation|tabAlbanna Message"
  [frappe.localhost]="tabToDo|tabUser|tabDocType"
)

TODAY=$(date +%F)
STAMP=$(date +%Y%m%d_%H%M%S)

log() {
  local line
  line="$(printf '%s %s\n' "$(date -Is)" "$*")"
  if ! printf '%s\n' "$line" | tee -a "$LOG" 2>/dev/null; then
    # The log is the alert on this host, so a run that cannot write it says
    # so rather than failing silently — and still says it somewhere.
    printf '%s\n' "$line" >&2
  fi
}
warn() { log "WARN  $*"; }
die()  { log "FATAL $*"; exit 1; }

# --- one run at a time -----------------------------------------------------
# A slow dump must not overlap the next tick: timer + Persistent=true means
# a missed run fires on boot, so overlap is the normal failure to prevent.
mkdir -p "$ROOT"
exec 9>"$ROOT/.lock"
if ! flock -n 9; then
  log "SKIP  another site-backup run holds the lock"
  exit 0
fi

# The log is the alert on this host — there is no mail — so a run that
# cannot write it says so loudly and carries on with the output going to
# the journal instead.
if ! touch "$LOG" 2>/dev/null; then
  printf '%s WARN  cannot write the log at %s — the output goes to the journal\n' \
    "$(date -Is)" "$LOG" >&2
  LOG=/dev/stderr
fi

umask 077

log "START site backup run $TODAY ($STAMP)"

failed=0

for site in $SITES; do
  slug=${site//./_}
  run="$ROOT/$site/daily/$TODAY"
  mkdir -p "$run"

  db="$run/$STAMP-$slug-database.sql.gz"
  public="$run/$STAMP-$slug-files.tar.gz"
  private="$run/$STAMP-$slug-private-files.tar.gz"
  conf="$run/$STAMP-$slug-site_config_backup.json"

  log "---- $site"

  if ! (cd "$BENCH" && bench --site "$site" backup \
        --with-files \
        --backup-path-db "$db" \
        --backup-path-files "$public" \
        --backup-path-private-files "$private" \
        --backup-path-conf "$conf" \
        --compress) >>"$LOG" 2>&1; then
    rm -f "$db" "$public" "$private" "$conf"
    warn "$site: bench backup failed — see the log above"
    failed=1
    continue
  fi

  # --- verification: before this run is declared good --------------------
  ok=1

  # The dump is read once, into a list of its tables.  Two reasons: the
  # sentinel check and the table count then cost one pass instead of one
  # pass each, and the checks read a plain file rather than a pipeline.
  #
  # The pipeline is not an innocent detail.  `zcat dump | grep -q pattern`
  # under `set -o pipefail` reports a *missing* pattern when the pattern is
  # there: grep exits as soon as it matches, zcat dies of SIGPIPE, and the
  # pipeline's status is the failure.  `zgrep` does not have the problem —
  # it does not set pipefail — and a temporary file does not have it either.
  table_list=$(mktemp)

  if [ ! -s "$db" ]; then
    warn "$site: the database dump is missing or empty"
    ok=0
  else
    if ! gzip -t "$db" 2>>"$LOG"; then
      warn "$site: the database dump is not a valid gzip stream"
      ok=0
    fi

    # mysqldump writes this footer only when it finished.  A truncated dump
    # is still a valid gzip stream, so the footer is the check that matters.
    if ! zgrep -q "Dump completed on" "$db"; then
      warn "$site: the dump has no completion footer — it was cut short"
      ok=0
    fi

    zcat "$db" | grep "^CREATE TABLE" >"$table_list" 2>/dev/null || true
    tables=$(wc -l <"$table_list" | tr -d ' ')

    if [ "${tables:-0}" -lt 10 ]; then
      warn "$site: the dump holds only ${tables:-0} tables — that is not a site"
      ok=0
    fi

    IFS='|' read -ra sentinels <<<"${SENTINELS[$site]:-}"
    for sentinel in "${sentinels[@]:-}"; do
      [ -n "$sentinel" ] || continue
      if ! grep -q "^CREATE TABLE \`$sentinel\`" "$table_list"; then
        warn "$site: the dump is missing \`$sentinel\` — wrong database?"
        ok=0
      fi
    done

    # The schema only grows.  A dump with fewer tables than the last good
    # one means something took the dump from the wrong place, or the last
    # good one was itself wrong and the error is now visible.
    previous=$(ls -1d "$ROOT/$site/daily/"*/ 2>/dev/null \
               | grep -v "/$TODAY/$" | sort -r | head -1 || true)
    if [ -n "$previous" ]; then
      prev_db=$(ls -1 "$previous"*"$slug-database.sql.gz" 2>/dev/null | head -1 || true)
      if [ -n "$prev_db" ]; then
        prev_tables=$(zcat "$prev_db" | grep -c "^CREATE TABLE" || true)
        if [ "${tables:-0}" -lt "${prev_tables:-0}" ]; then
          warn "$site: the dump holds $tables tables, the last good one held $prev_tables"
          ok=0
        fi
      fi
    fi

    if [ "$ok" -eq 1 ]; then
      log "OK    $site: dump verified ($tables tables, $(stat -c%s "$db") bytes)"
    else
      warn "$site: the dump did not pass verification — the artifacts are kept for inspection"
    fi
  fi
  rm -f "$table_list"

  if [ -s "$private" ]; then
    if tar -tzf "$private" >/dev/null 2>&1; then
      log "OK    $site: private files verified ($(tar -tzf "$private" | wc -l) entries)"
    else
      warn "$site: the private-files archive does not list"
      ok=0
    fi
  fi

  if [ -s "$public" ]; then
    if tar -tzf "$public" >/dev/null 2>&1; then
      log "OK    $site: public files verified"
    else
      warn "$site: the public-files archive does not list"
      ok=0
    fi
  fi

  if [ -s "$conf" ]; then
    if python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$conf" 2>/dev/null; then
      log "OK    $site: site config verified"
    else
      warn "$site: the site config backup is not valid JSON"
      ok=0
    fi
  fi

  if [ "$ok" -ne 1 ]; then
    warn "$site: the run is NOT good — the artifacts are kept for inspection, and $site/last_ok is not updated"
    failed=1
    continue
  fi

  # --- manifest: what this run contains, provably ------------------------
  manifest="$run/MANIFEST.txt"
  {
    echo "site-backup $site $TODAY $STAMP"
    echo "host $(hostname)"
    echo "database $(basename "$db")"
    for f in "$db" "$public" "$private" "$conf"; do
      [ -f "$f" ] || continue
      printf '%s  %s bytes  %s\n' "$(sha256sum "$f" | cut -d' ' -f1)" \
        "$(stat -c%s "$f")" "$(basename "$f")"
    done
    echo "tables $tables"
    echo "insert statements $(zcat "$db" | grep -c '^INSERT INTO' || true)"
  } >"$manifest"
  chmod 600 "$manifest"
  log "OK    $site: manifest written"

  date -Is >"$ROOT/$site/last_ok"

  # --- weekly and monthly copies -----------------------------------------
  # `cp -a` rather than a hardlink: these files are never rewritten in
  # place, but a plain copy fails loudly if that ever changes instead of
  # silently sharing an inode.
  mkdir -p "$ROOT/$site/weekly" "$ROOT/$site/monthly"
  if [ "$(date +%u)" = "7" ]; then
    cp -a "$run" "$ROOT/$site/weekly/$TODAY" 2>/dev/null \
      && log "OK    $site: weekly copy kept" \
      || warn "$site: the weekly copy failed"
  fi
  if [ "$(date +%d)" = "01" ]; then
    cp -a "$run" "$ROOT/$site/monthly/$TODAY" 2>/dev/null \
      && log "OK    $site: monthly copy kept" \
      || warn "$site: the monthly copy failed"
  fi

  # --- retention ----------------------------------------------------------
  prune() {
    local dir="$1" keep="$2"
    [ -d "$dir" ] || return 0
    ls -1 "$dir" 2>/dev/null | sort -r | tail -n +"$((keep + 1))" \
      | while read -r d; do rm -rf "$dir/$d"; done
  }
  prune "$ROOT/$site/daily" "$KEEP_DAILY"
  prune "$ROOT/$site/weekly" "$KEEP_WEEKLY"
  prune "$ROOT/$site/monthly" "$KEEP_MONTHLY"
done

# --- the restore runbook, next to the artifacts ---------------------------
# The operator in a crisis reads what is next to the data, not what is in
# a git repository.  The source of truth stays in the repository; this is
# a copy of it.
if [ -f "$BENCH/apps/albanna/docs/BACKUP.md" ]; then
  cp "$BENCH/apps/albanna/docs/BACKUP.md" "$ROOT/RESTORE.md" 2>/dev/null \
    || warn "could not refresh $ROOT/RESTORE.md"
fi

if [ "$failed" -ne 0 ]; then
  log "FATAL the run did not verify — last_ok was not updated"
  exit 1
fi

date -Is >"$ROOT/last_ok"
log "OK    run complete — every site's artifacts verified"
