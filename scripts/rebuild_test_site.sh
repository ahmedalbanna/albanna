#!/usr/bin/env bash
#
# Rebuild a site from scratch, so the site suite can be run against a
# site that anybody can rebuild.
#
# The site suite used to run against a clone of production: a database
# dump taken by hand, on a day, and then left to drift.  It worked, and
# it was the only gate that spoke for the framework this site actually
# runs on — the CI runs the released line, which is a different thing.
# But a clone nobody can rebuild is a clone that quietly stops being
# what it was: it accumulates the site's own test records, it drifts
# away from the app's schema, and when it breaks, nobody can say why.
#
# So this makes the site instead: a new site, ERPNext, the app, the
# smallest set of data the suite reads (the app's own preparation
# script), and then the suite itself.  The result is a site that any
# body can rebuild, on any host, and get the same gate.
#
#     scripts/rebuild_test_site.sh --site test.localhost --replace
#
# What it will not do without being told twice:
#
#   * drop an existing site.  `--replace` is required, and it is the
#     only thing that lets the script touch a site that already exists.
#     A site is somebody's work.
#   * guess the database root password.  It is read from
#     `$DB_ROOT_PASSWORD`, or from `--db-root-password`, or from the
#     credentials file at `~/.mariadb-root.credentials` when that
#     exists.  It is never written into this script and never printed.
#
# Options:
#   --site NAME             the site to build (default: test.localhost)
#   --replace               drop the site first, if it exists
#   --with-demo-data        also load ERPNext's demo data (slow, and
#                            not needed by the suite)
#   --db-root-password PW   the database root password
#   --admin-password PW     the site's administrator password
#   --skip-tests            build the site but do not run the suite
#
# What the suite reads, and what the preparation script makes:
#
#   * a company with a chart of accounts, the fiscal year it is in,
#     the price lists and the defaults that name it;
#   * one item (a service, because the suite's documents name an item
#     and nothing else) and one customer;
#   * one submitted sales invoice, because two tests read one;
#   * one read-only field on Customer, because one test refuses to
#     write a read-only field;
#   * a provider key that is not a real key, because one test checks
#     that a key the provider quotes never reaches the chat log.

set -euo pipefail

SITE="test.localhost"
REPLACE="no"
DEMO_DATA="no"
SKIP_TESTS="no"
DB_ROOT_PASSWORD="${DB_ROOT_PASSWORD:-}"
DB_ROOT_USERNAME="${DB_ROOT_USERNAME:-root}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-admin}"

usage() {
	sed -n '3,60p' "$0" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
	case "$1" in
	--site)
		SITE="$2"
		shift 2
		;;
	--replace)
		REPLACE="yes"
		shift
		;;
	--with-demo-data)
		DEMO_DATA="yes"
		shift
		;;
	--db-root-password)
		DB_ROOT_PASSWORD="$2"
		shift 2
		;;
	--admin-password)
		ADMIN_PASSWORD="$2"
		shift 2
		;;
	--skip-tests)
		SKIP_TESTS="yes"
		shift
		;;
	-h | --help)
		usage
		exit 0
		;;
	*)
		echo "rebuild_test_site: unknown argument: $1" >&2
		usage >&2
		exit 2
		;;
	esac
done

# The bench this script runs in: the directory above the app's, found by
# walking up until the bench's own configuration is there.  The app lives
# in ``apps/<app>``, so the bench root is two levels up — but a bench
# that puts its apps somewhere else still works, because what is looked
# for is the bench's own configuration and not a path.
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENCH_DIR="$APP_DIR"
while [ "$BENCH_DIR" != "/" ]; do
	if [ -f "$BENCH_DIR/sites/common_site_config.json" ]; then
		break
	fi
	BENCH_DIR="$(dirname "$BENCH_DIR")"
done

if [ ! -f "$BENCH_DIR/sites/common_site_config.json" ]; then
	echo "rebuild_test_site: no bench found above $APP_DIR." >&2
	exit 5
fi

cd "$BENCH_DIR"

if [ ! -f "sites/$SITE/site_config.json" ]; then
	SITE_EXISTS="no"
else
	SITE_EXISTS="yes"
fi

if [ "$SITE_EXISTS" = "yes" ] && [ "$REPLACE" != "yes" ]; then
	echo "rebuild_test_site: the site $SITE already exists." >&2
	echo "  A site is somebody's work, so this script will not drop one" >&2
	echo "  without being told to: pass --replace if that is what you want." >&2
	exit 3
fi

if [ -z "$DB_ROOT_PASSWORD" ]; then
	CREDENTIALS_FILE="${HOME}/.mariadb-root.credentials"
	if [ -f "$CREDENTIALS_FILE" ]; then
		DB_ROOT_PASSWORD="$(sed -n 's/^password=//p' "$CREDENTIALS_FILE" | head -1)"
		DB_ROOT_USERNAME="$(sed -n 's/^user=//p' "$CREDENTIALS_FILE" | head -1)"
		DB_ROOT_USERNAME="${DB_ROOT_USERNAME:-root}"
	fi
fi

if [ -z "$DB_ROOT_PASSWORD" ]; then
	echo "rebuild_test_site: no database root password." >&2
	echo "  Set DB_ROOT_PASSWORD, pass --db-root-password, or put one in" >&2
	echo "  $HOME/.mariadb-root.credentials." >&2
	exit 4
fi

say() {
	echo "rebuild_test_site: $*"
}

if [ "$SITE_EXISTS" = "yes" ]; then
	say "dropping the site $SITE"
	bench drop-site "$SITE" --root-login "$DB_ROOT_USERNAME" --root-password "$DB_ROOT_PASSWORD" --no-backup
fi

say "making the site $SITE"
bench new-site "$SITE" --db-root-password "$DB_ROOT_PASSWORD" --admin-password "$ADMIN_PASSWORD"

say "installing ERPNext"
bench --site "$SITE" install-app erpnext

say "installing the app"
bench --site "$SITE" install-app albanna

if [ "$DEMO_DATA" = "yes" ]; then
	say "loading ERPNext's demo data"
	# The demo setup clones the first company it finds, so the site has
	# to have one before this can work.
	./env/bin/python apps/albanna/scripts/prepare_test_site.py --site "$SITE"
	bench --site "$SITE" setup_demo_data
fi

say "giving the site the data the suite reads"
./env/bin/python apps/albanna/scripts/prepare_test_site.py --site "$SITE"

say "letting the site run tests"
bench --site "$SITE" set-config allow_tests true

if [ "$SKIP_TESTS" = "yes" ]; then
	say "the site is ready; the suite was not run"
	exit 0
fi

say "running the site suite"
bench --site "$SITE" run-tests --app albanna
say "the site $SITE is rebuilt, and the suite passed on it"
