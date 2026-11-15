# ADR-0109: The compatibility facts are read and pinned

Date: 2026-11-15 · Status: accepted · The seventh NFR batch, after the
S-, R-, SEC- (ADR-0105), U- (ADR-0106), A- (ADR-0107) and M-series
(ADR-0108); answers the NFR-C1–C7 questions raised against the app's
compatibility surface.

## The requirement, and what "verified" means here

Seven compatibility requirements were named for the app.  Six held as
read — several by design decisions the code already carries — and one
was exposed: not in the code, but in what the code was *declared* to
need.

| # | Requirement | Verdict | Evidence |
|---|---|---|---|
| C1 | Frappe v15 + v16 (FC's stable line) | **the declaration was exposed, fixed** | the code is v15-clean — all 73 distinct `frappe.*` chains the app calls exist on the `version-15` branch, checked where drift was possible: `frappe.db.set_single_value`, `frappe.db.savepoint` (method and context manager), `frappe.db.rename_column`, `frappe.db.sql_ddl` in v15's `database.py`; `frappe.publish_realtime` in v15's `__init__.py`; `frappe.cache_manager.clear_user_cache`, `frappe.desk.form.assign_to.add`, `frappe.utils.file_manager.*` present; the hooks keys are long-stable; no Python 3.11+ syntax anywhere; `requires-python >=3.10` matches v15's floor.  But `[tool.bench.frappe-dependencies]` declared `frappe = ">=16.0.0-dev,<17.0.0"` — a v15 bench was told it could not install an app that would run on it.  Widened to `>=15.0.0,<17.0.0` for frappe and erpnext |
| C2 | ERPNext supported; ERPNext DocTypes where applicable | holds | `required_apps = ["erpnext"]`; escalation creates an ERPNext **Issue** with a ToDo fallback when Issue is not creatable (`api/widget.py:136`, `api/conversations.py:278-364`); the twelve tools are doctype-agnostic — every list/read/write takes the DocType from the model's arguments and is gated by the caller's own permissions, so ERPNext doctypes are first-class without special-casing; the site suite runs against ERPNext |
| C3 | any OpenAI-compatible endpoint, no code changes | holds | `base_url`, `model`, `api_key`, `max_tokens`, `timeout`, `temperature` and `extra_options` (the catch-all merged into the request payload) all come from `Albanna Settings` per request; the URL is `config.base_url + /chat/completions`; the alias kinds (openrouter, groq, vllm, lmstudio, together) are the same adapter |
| C4 | Ollama local or remote | holds | the Ollama adapter: default `http://127.0.0.1:11434`, any remote through `base_url`; URL is `config.base_url + /api/chat`; same settings surface as every other provider |
| C5 | Anthropic's API | holds | `config.base_url + /v1/messages` with the `anthropic-version` header; model, key, ceilings from Settings |
| C6 | Chrome, Firefox, Safari, Edge — latest two | holds | syntax is the build's problem and Frappe's esbuild targets `es2017`, so `?.`/`??` transpile down.  The panel's runtime APIs are Safari-lag-safe (`Intl.*` formatters, `matchMedia`, `flatMap`, `globalThis`, and `navigator.clipboard` explicitly feature-guarded).  CSS: no `@layer`, `@container`, `:has()` — the walker keeps it that way.  The modern things it *does* use — `color-mix()` tints (Chrome/Edge 111+, Firefox 113+, Safari 16.2+; all inside the latest-two budget), logical properties (`inset-inline`, 2021-era everywhere), `min()`/`clamp()` — degrade to a dropped declaration: the destructive card keeps its border and loses its tint.  The one modern *unit*, `100dvh`, is always declared after a `100vh` fallback in the same rule |
| C7 | mobile browsers, responsive (desktop optimised) | holds | three layers already in the bundle: ≤991px the docked column gives up its Desk margin and the panel becomes a fixed overlay; ≤640px it becomes a full-screen sheet sized by `100dvh` with no resize handle; `pointer: coarse` lifts both sides of every target to 44px at any width (U-series); hover-only affordances are wrapped in `@media (hover: hover)` so touch readers see them always; the composer is sticky, tables scroll instead of overflowing.  The Desk's own viewport meta governs |

## The exposure, and what was changed

The interesting thing about C1 is where it failed.  Not in the code —
every API call checked out against the version-15 branch — but in the
metadata: the app's own `pyproject.toml` told a v15 bench `>=16.0.0-dev`.
A compatibility claim is made at the package boundary, and the package
boundary was lying.

The fix is two halves.  The range now says `>=15.0.0,<17.0.0` — the
honest scope of what was verified.  And the verification is now
*enforced*, not remembered:

- `tests/test_compatibility_pins.py` walks every `frappe.*` chain in
  the app against a list read against the version-15 branch.  A new
  Frappe call fails the suite until someone answers "does v15 have
  this?" — the cheapest honest form of "we support v15" that an app on
  a v16 bench can carry.
- The range itself is pinned (`>=15`, `<17`), so a future edit cannot
  silently narrow the stable line out.
- The panel's JS is walked for the APIs Safari's stable releases lag
  (`structuredClone`, `findLast`, `Array.prototype.at`,
  `Object.groupBy`); the bundle CSS is walked for the features whose
  absence changes the meaning of a block rather than dropping one
  declaration (`@layer`, `@container`, `:has()`); and `dvh` is only
  allowed with a `vh` fallback in the same rule — the pattern the
  mobile sheet already uses.
- The responsive layers (991px overlay, 640px sheet, touch lift) are
  pinned to exist, and `required_apps = ["erpnext"]` is pinned for C2.

**What "supports v15" is not, said plainly.**  It is not a live v15
site run — the bench here is v16 and the suite runs live on v16 only.
It is: every symbol the app touches read against the version-15
branch, the hooks surface checked, the Python floor matched, and a
walker that keeps the surface from growing unverified.  The first
install on a real v15 bench is the test this record does not claim.

## Consequences

- A v15 Frappe Cloud site can install the app; `pip`-level claims and
  code agree for the first time.
- The price of the claim is one allowlist: adding a Frappe call means
  adding a line to `FIFTEEN_VERIFIED` after reading it against v15 —
  which is the review question that used to be skipped.
- C3/C4/C5 needed no change: the adapters have been settings-driven
  since the provider split, and the M4 batch made that structure the
  only structure.
- No runtime behaviour changed: metadata and walkers only.  The full
  site suite (388 tests) and the unit suite (449) passed on the
  changed tree.
