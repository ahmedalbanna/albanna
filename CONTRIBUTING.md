# Contributing

## Getting set up

```bash
bench get-app https://github.com/ahmedalbanna/albanna --branch main
bench --site <your-site> install-app albanna
bench --site <your-site> migrate
bench build --app albanna
```

## The two suites

```bash
cd apps/albanna

# The domain suite: no bench, no site, no network.  Under a second.
../../env/bin/python -m pytest

# The site suite: needs a site with ERPNext installed.
bench --site <your-site> run-tests --app albanna
```

The split is deliberate.  `core/` may not import Frappe, and everything
that can be tested without a site is tested without one — so the suite that
runs on every save stays fast, and the suite that needs a database holds
only the things that genuinely do.

## The rules that matter

- **`core/` imports no Frappe.** A test asserts it, so a stray import fails
  the suite rather than quietly making the domain slow.
- **The manifest and the implementations must agree.**  A schema that
  promises an argument the implementation does not accept fails on every
  call, in the middle of a turn, where it costs the most.  `tests/test_tool_manifest.py`
  checks the two against each other.
- **The assistant never apologises for a limit that is not its own.**  If you
  add a refusal, a hint or a message the model reads, it must read as a
  fact about the organisation.
- **A tool's permissions are the framework's.**  Do not add
  `ignore_permissions=True` to anything.
- **A failure the caller cannot act on is a failure the caller will retry
  identically.**  Say what to do about it.

## Style

- Ruff, with the configuration in `pyproject.toml`.  `ruff check .` and
  `ruff format .`.
- A module docstring on every file, explaining what it is for and — where
  it is not obvious — why it is shaped that way.
- `from __future__ import annotations` at the top of every module.
- Commit messages: a conventional-commit subject, then a body that says
  what changed and **why**.  "what" is in the diff; "why" is not.

## Adding a tool

1. Add the `ToolSpec` to `core/tools.py` — the name, the description
   (written for a model, not for a developer), and the JSON Schema.  A
   write tool also says which right it is authorised against:
   `write_permission="create"` makes a document, `"write"` changes one.
2. Implement it in `tools/erpnext.py`, with the same parameter names the
   schema declares.  A write takes a savepoint before it writes, so that a
   failure undoes that write and nothing else.
3. Map it in `tools/backend.py`.
4. Add a test that the schema and the implementation agree.

The manifest and the implementation are checked against each other, so a
half-finished tool fails the suite rather than the first user who reaches
for it.
