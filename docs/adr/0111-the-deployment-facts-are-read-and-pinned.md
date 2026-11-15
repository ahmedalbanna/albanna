# ADR-0111: The deployment facts are read and pinned

Date: 2026-11-15 · Status: accepted · The ninth NFR batch, after the
S-, R-, SEC- (ADR-0105), U- (ADR-0106), A- (ADR-0107), M- (ADR-0108),
C- (ADR-0109) and I-series (ADR-0110); answers the NFR-D1–D7 questions
raised against the app's deployment surface.

## What the reading found

Six of the seven held, one of them measured rather than assumed.  One
was exposed, and the exposure was the kind only a deployment question
finds: the code was correct on this bench and silently dead anywhere
else.

| # | Requirement | Verdict | Evidence |
|---|---|---|---|
| D1 | installs via standard Frappe commands | **held, with the freshest evidence narrowed by the host** | the standard surface is complete: `[project]` metadata (flit_core), `requires-python >=3.10`, two runtime deps (`requests`, `jsonschema` — the ERPNext tools are implemented in-app rather than pulled from a package, so the app installs anywhere), the C1 version range, one module in `modules.txt`, six idempotent patches in `patches.txt`, idempotent `after_install`/`after_migrate` (settings row + role), `required_apps = ["erpnext"]`.  A fresh-site install was attempted live and is **blocked by the host's MariaDB root-credential drift** (AGENTS.md, 2026-10-05): `bench new-site` died at the root-password prompt mid-provision and the site had to be removed; the live migrate-path evidence comes from `test.localhost` (migrated this batch, new field synced) plus four sites that already carry the app from standard commands |
| D2 | no external services beyond Frappe/Redis/MariaDB/model provider | holds | the only outbound HTTP in the app is the four provider adapters — the model provider, the declared exception; every `base_url` is operator-configured.  No email, webhooks, telemetry or phone-home anywhere |
| D3 | no license server or gateway | holds | no license/entitlement/portal code; `app_license = "mit"` is the standard SPDX metadata field, not a check.  The MCP stack's license portal belongs to a different codebase |
| D4 | migrations via Frappe's system | holds | six patches in `patches.txt` — the migration system's own extension point; DDL only through the framework's helpers (`rename_column`, `add_index`, `sql_ddl`) and only inside patches; zero DDL at runtime; the `tabSingles` raw SQL is a documented ORM-cannot-express exception, parameterised, inside a patch |
| D5 | deployable on Frappe Cloud without special configuration | **exposed: the chat queue — fixed** | everything else was clean (no hard-coded paths, site names, or conf reads a fresh site lacks).  But `api/chat.py` enqueued every turn to `queue="chat"` — a custom queue no stock worker listens on.  On this bench it works because a dedicated chat-worker was configured; on Frappe Cloud the job would sit in Redis forever and the turn would never start.  The queue is now the `background_queue` setting |
| D6 | asset builds within 2 minutes | holds (measured) | `time bench build --app albanna --force` = **6.5s** wall (build + translation compile), against the 120s budget |
| D7 | no changes to Frappe core or other apps | holds | hooks use only the framework's extension points (`permission_query_conditions`, `has_permission`, `scheduler_events`, `after_install`/`after_migrate`, `app_include_*`); no `override_doctype_class`, no `override_whitelisted_methods`, no monkey-patching (`setattr(frappe.local, ...)` is the per-request memo idiom — request-scoped state, not a core edit), no writes outside the app's own paths |

## The exposure, and what was changed

**The turn's job runs on a stock queue.**  The custom `chat` queue
existed for a real reason — a turn of many rounds once held the
`short` queue for its whole length, and everything else the site drops
there waited behind it.  But a custom queue is a queue only a worker
someone configured serves, and "someone configured a worker" is
exactly the special configuration D5 forbids.  The queue is now the
`background_queue` setting: a Select over the three names every bench
ships workers for (`short`, `default`, `long`), defaulting to `short`,
with an out-of-list value reading as `short` — a typo must not park
every turn in Redis forever, which is why the field honours only the
three stock names instead of accepting anything.

**The known loss.**  On a stock install a long turn now holds the
`short` queue for its budget (up to turn + approval + slack, minutes
at the defaults).  That is the price of "works without special
configuration", and it is bounded: the job's `timeout` is the same
budget it always had.  A site that wants isolation can pick `long` —
semantically the right class for a multi-minute job — or run its own
worker topology; what it can no longer do is name a queue nobody
serves.  This host's dedicated `chat` workers remain as
infrastructure; the app no longer requires them.

## What is pinned

`tests/test_deployment_pins.py`, eight walkers, five red-checked live
(a stray `import requests` in services; a DDL string in tools; a
hard-coded `queue="chat"`; `STANDARD_QUEUES` widened with `"chat"`;
an `override_doctype_class` in hooks — each FAILED then reverted):

- D2: no HTTP client outside `providers/`.
- D3: no license machinery tokens.
- D4: no DDL outside `patches/`; every patch named in `patches.txt`
  exists on disk.
- D5: the enqueue's queue is never a string literal; the settings
  honour only `short`/`default`/`long`.
- D7: the hooks override no core behaviour; no `setattr` through
  frappe outside the per-request memo.

## Follow-ups for the operator

- The half-provisioned site left `_3e0b02e071dafd8f` (database and/or
  user) behind the failed `bench new-site`; it is not enumerable with
  the credentials this host allows.  Clean it up with a working root
  credential when one is available.
- This host's sites now run turns on `short` by default.  If the
  chat-worker isolation is wanted back, set `background_queue` — the
  field's three options are what the app honours; a dedicated `short`
  worker is the topology that restores isolation without leaving the
  standard surface.
