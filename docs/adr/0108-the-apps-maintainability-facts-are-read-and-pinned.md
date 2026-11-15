# ADR-0108: The app's maintainability facts are read and pinned

Date: 2026-11-15 · Status: accepted · The sixth NFR batch, after the
S-, R-, SEC- (ADR-0105), U- (ADR-0106) and A-series (ADR-0107); answers
the NFR-M1–M8 questions raised against the app's structure.

## The requirement, and what "verified" means here

Eight maintainability requirements were named for the app.  Each was
read against the source before it was believed; two did not hold and
are what this ADR changes.  The others held — some because they were
designed in and written down, one because the numbers were measured
rather than assumed.

| # | Requirement | Verdict | Evidence |
|---|---|---|---|
| M1 | `core/` has zero Frappe/app dependencies | holds, **now pinned** | `albanna/core/` imports only the standard library and other `core/` modules (`authority→tools`, `messages→tools`, `prompt→tools`).  Zero `frappe`, zero `services`/`tools`/`api`/`providers`.  The rule was even written in `core/__init__.py` — but nothing enforced it; `tests/test_maintainability_pins.py` now does (AST walk, red-checked) |
| M2 | domain tests run without bench, site, or network | holds, **now pinned** | no test file imports Frappe unguarded; a bare `pytest tests/` passes in ~9 s with no site, no network.  The one frappe import in the suite (`test_scheduler.py`) is try/except-guarded by design and the pin allows guarded imports.  Pinned by the same walker |
| M3 | a new tool is exactly two places | **was three, fixed** | see below |
| M4 | a new provider is one file implementing the interface | **was four+, fixed** | see below |
| M5 | ≥80% coverage on the domain layer | holds, **now gated** | `pytest --cov=albanna.core`: **92%** (759 statements, 64 missed); lowest module 62% (`secrets.py`, 13 statements).  The gate is in `pyproject.toml` (`[tool.coverage.report] fail_under = 80`) — a coverage run on the domain fails below the floor |
| M6 | every public endpoint documented | holds, **now pinned** | all 23 whitelisted endpoints in `albanna/api/` carry docstrings (four are one-sentence but real).  Pinned by the AST walker |
| M7 | configuration changes need no code change or redeploy | holds | 39 `Albanna Settings` fields cover every operational knob — provider kind/model/key, fallback chain, timeouts, token ceiling, tool-round limit, history limit, rate limit, monthly budget, attachment ceiling, and the system prompt itself.  `get_settings` reads per request with cache invalidation on save: a change is live on the next request |
| M8 | standard Frappe app structure | holds | `hooks.py`, `pyproject.toml` (the flit layout current Frappe scaffolds; `setup.py` is not required), `modules.txt` ("Albanna"), doctypes under `albanna/albanna/doctype`, `patches.txt`, `config/`, `public/`, `templates/` |

## The two exposures, and what was changed

**M3 — the third place.**  A new tool touched **three** server places:
one `ToolSpec` in `core/tools.py`, one handler function in
`albanna/tools/`, and one line in `_BOUND_TOOLS` in
`albanna/tools/backend.py` — plus two parallel dicts in
`tests/test_tool_manifest.py` that duplicated the name→module mapping a
third time over.  A table no one needs is a table someone forgets: the
manifest test caught a missing *handler*, but nothing forced the
*binding*, and a tool bound under the wrong name would have been a
silent misroute.

The fix is the same shape the providers got: the handler marks itself
with `@tool_handler` (in `tools/base.py`, the port's own module), and
the backend builds its name→function bindings by scanning the handler
modules for marked functions.  The manifest test derives its pairings
from the same marker, so both parallel dicts are gone.  A new tool is
now one `ToolSpec` and one marked function — the manifest's contract
and the implementation's signature were already the same words; now
nothing else has to say so.

**M4 — the dispatch that was four places.**  A new provider needed the
new file, *and* edits to `providers/base.py`: a kind constant, a line
in `PROVIDER_KINDS`, a branch in `build_provider`, a branch in
`default_base_url` — plus the Select options in the Settings doctype.
The OpenAI adapter's alias kinds (`openrouter`, `groq`, `vllm`,
`lmstudio`, `together`) were listed by hand in a dispatch tuple too.

The fix: a provider adapter class declares its `kind` (its canonical
name) and optional `kinds` (its aliases) beside itself, and
`providers/base.py` discovers the registry by scanning the package for
classes that carry a string `kind` and a `complete` method.  `build_provider`,
`default_base_url` and the kind list all derive from that one registry,
and `base.py` no longer names any adapter class.  A new provider is one
file under `providers/`; the one registration left outside the file is
the Settings dropdown's options line, which is declarative metadata a
user reads, not a dispatch a developer maintains.

**The security pin this touched.**  The SEC11 walker banned
`importlib` outright in shipped Python.  Both discovery mechanisms
(tool handlers, provider adapters) need `importlib.import_module`, so
the ban is narrowed to what the threat actually is — `eval`, `exec`,
`compile`, `__import__`, the doors through which model text could
become code.  `import_module` can only load modules already importable
on the app's path: it is module *discovery*, never the execution of
content the model produced.  The reasoning is written in the pin's
docstring so the next reader does not widen it back.

## The pins

`tests/test_maintainability_pins.py` (six walkers, red-checked):

- M1 — `core/` imports no Frappe and no outer layer (`api`, `services`,
  `tools`, `providers`, `permissions`, `install`, `privacy`).
- M2 — no test imports Frappe unguarded.
- M3 — `tools/backend.py` declares no binding table; the marker is the
  only pairing (the manifest-agreement tests in
  `test_tool_manifest.py` do the rest).
- M4 — `providers/base.py` names no adapter class; every registered
  kind builds.
- M6 — every whitelisted endpoint has a docstring.

M5's gate lives in `pyproject.toml`, not in a test, because coverage is
a measurement, not a fact about the source text.

## Consequences

- A new tool is two places (manifest + marked handler); a new provider
  is one file.  Both are enforced by tests that fail loudly on the
  pattern that would add the third place back.
- The M1/M2 rules the codebase already followed are now facts a test
  defends, not prose a reviewer must remember.
- The domain coverage floor (80%, measured 92%) fails a coverage run
  that lets the domain rot.
- Nothing changed at runtime: the registry and the bindings are built
  from the same functions the old tables named, and the full site suite
  (388 tests) and unit suite (442) passed on the changed code.
