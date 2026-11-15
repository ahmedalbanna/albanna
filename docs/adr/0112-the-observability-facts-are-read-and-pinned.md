# ADR-0112: The observability facts are read and pinned

Date: 2026-11-15 · Status: accepted · The tenth NFR batch, after the
S-, R-, SEC- (ADR-0105), U- (ADR-0106), A- (ADR-0107), M- (ADR-0108),
C- (ADR-0109), I- (ADR-0110) and D-series (ADR-0111); answers the
NFR-O1–O5 questions raised against the app's observability surface.

## What the reading found

The ledger turned out to be the strongest part: it was designed as an
audit row from the start and it carries everything the first four
requirements ask for.  What was missing was the part *around* the
ledger — the log lines a grep can join against it, and a door a
monitor can knock on.

| # | Requirement | Verdict | Evidence |
|---|---|---|---|
| O1 | errors logged with user, site, turn ID, provider | **the log lines were exposed, fixed** | the *durable* record was already complete: every turn writes a `Albanna Chat Log` row with user, conversation, provider, model, status, `error_class` and a secret-stripped `error_message`; provider errors, round caps, truncations and the reaper each write their status.  **Exposed:** the turn-failure line was `logger.exception("Chat turn failed")` — no stream, no user, no conversation — and the O1 walker found five more just like it (the turn commit, the running-audit row, the approval commit, the two write commits, the capped-turn close).  Every error line in the turn paths now names its audit row, stream, user or conversation |
| O2 | provider request/response metadata logged, content never | **exposed, fixed** | the adapters logged nothing at all.  Fixed with one INFO line per turn at the audit close — provider, model, status, rounds, input/output tokens, duration, cost — the same numbers the ledger row carries, and only numbers and names.  The walkers forbid any log call in the providers or the turn paths from passing a content-bearing variable (payload/message/reply/question/answer/prompt/body/transcript) |
| O3 | health-check endpoints | **exposed, fixed** | the app had none.  `albanna.api.health.check` is the one guest door: database probe (`select 1`), cache probe (redis `ping`), a chat-configured boolean, `ok`/`degraded` and the app version.  A failing check reads `degraded`, not a 500 — a monitor wants a body it can parse either way.  The SEC3 no-guest pin and the api-surface door test both carry it as a named, reasoned exemption |
| O4 | the ledger is the primary usage/cost tool | holds | every turn writes the row; `usage_service.usage_summary()` aggregates month-to-date **in the database** (group by provider/model/user/status, one row per group — a large ledger costs no more than a small one of the same month shape), counts the *uncosted* turns apart so a zero is never read as "free", and separates the site's cost from the provider's own.  `albanna.api.usage.summary` is System-Manager-only.  Strengthened: `status` is now standard-filterable in the ledger's list view |
| O5 | failed turns distinguishable by status | holds | the `status` Select carries the whole vocabulary — running / ok / error / capped / denied / truncated / interrupted — and every path writes it: provider errors → `error` with `error_class=provider_error`, the step budget → `capped`, the token ceiling → `truncated`, the reaper → `interrupted`; the usage summary counts the errors per month |

## The decision worth keeping

**One guest door, named.**  The SEC series pinned "no endpoint admits
a guest", and a health check a monitor can read needs exactly that
door.  The resolution is not an exception in the code but an exception
in the *pin*: the allowlist names `health.py` in two tests, the
response is held to `ALLOWED_KEYS` by a walker, and the behavioural
test asserts the degrade-not-raise shape with both probes broken.  A
monitor gets booleans and a version; a guest who finds the door gets
the same.

## What is pinned

`tests/test_observability_pins.py`, nine walkers, five red-checked
live (a bare `Chat turn failed` line; a content variable in a provider
log; the summary line removed; the guest door closed; the filter
dropped — each FAILED then reverted):

- O1: every `logger.exception`/`logger.error` in the turn paths
  (chat_job, chat_service) carries at least one format argument.
- O2: the turn-summary line exists; no log call in the providers or
  the turn paths passes a content-bearing variable.
- O3: the health endpoint is whitelisted with `allow_guest`; the
  response keys are the allowlisted four; the logic degrades rather
  than raising (tested with the probes mocked, so the suite runs
  bench-free).
- O5: the ledger's status field is standard-filterable with the full
  vocabulary; the usage summary counts `status = 'error'`.

## The trade-offs, named

- The turn-summary line is one INFO line per turn — a busy site writes
  a line per turn into the worker log.  It is deliberately at INFO:
  the requirement is that the metadata *shall* be logged, and a line
  only a debug level would surface does not satisfy it.
- The guest health door is a new anonymous surface.  It is held to
  four keys and two cheap probes; an endpoint that ever wants to carry
  more must leave the allowlist and the door first.
