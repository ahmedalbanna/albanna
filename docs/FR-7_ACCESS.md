# FR-7 — Access and authority

**Status:** requirements review, closed out by the pass recorded in the
commits that follow this document.  Every claim below names the file and
the line that supports it, so a reader can check the claim rather than
trust it.

**Scope:** the seven functional requirements FR-7.1 … FR-7.7, which
describe who may use the chat, what they may be offered, and how the
authority layer refuses everybody else.

**The finding, before the details.** All seven were already met. Not one
was broken. Every gap was a rule that was correct in the code and
unheld by any test — and the difference between those two states is
invisible until somebody changes the code. See
[ADR-0055](adr/0055-a-requirement-that-is-met-is-not-a-requirement-that-is-held.md).

---

## FR-7.1 — Chat access shall be off by default for all users

**Requirement.** No account may chat until an operator says otherwise.

**Status: MET.**

**Evidence.** The gate is read permission on `Albanna Conversation`,
shipped as the `Albanna User` role and nothing else
(`albanna/albanna/doctype/albanna_conversation/albanna_conversation.json`
— one permission row, `if_owner=1`, permlevel 0). The installer creates
that role and grants it to no one (`albanna/install.py:46`,
`_ensure_role`). The one migration that grants it
(`albanna/patches/v0_1/migrate_chat_access_to_role.py`) grants only to
roles the operator previously named in the old `chat_roles` setting; a
site that named nothing is left with the shipped matrix. Production's
live `tabDocPerm` matches the shipped file exactly, and three accounts
hold the role — all deliberate grants.

**What was unheld.** The shipped matrix was asserted
(`tests/test_access_matrix.py`); the installer's half was not. An
`add_roles` anywhere in the install path would flip the default for
every account on the site, and every other test would still pass —
they each build their own user with explicit roles, so not one of them
reads what the installer handed out. `after_migrate` is in that path
too, and a grant there would re-open the chat on every migrate.

**Closed.** `test_the_installer_hands_the_chat_to_nobody` parses
`install.py`'s AST for a call to `add_roles`. Parsed rather than searched
as text, because a comment that mentions `add_roles` is not a grant.
See [ADR-0056](adr/0056-the-chats-gate-has-two-halves-and-the-installers-half-was-unheld.md).

---

## FR-7.2 — Only users holding the Albanna User role shall be able to use the chat

**Requirement.** The role is the door.

**Status: MET in substance. The letter deviates, deliberately.**

**Evidence.** All 23 whitelisted endpoints in `albanna/api/` sit behind
a door: 21 call `require_chat_access()`
(`albanna/permissions.py:138`), and the two that do not —
`provider.test_provider` and `usage.summary` — call
`require_system_manager()`, because they are the operator's and run no
turn and read no conversation. `Albanna User Policy`'s only permission
row is `System Manager`, so a reader cannot write themselves an `On`
override. Guest is refused (`albanna/permissions.py:116`). The widget
does not render for a reader who may not chat
(`albanna/api/widget.py:109`).

**The deviation.** The app's rule is not "holds the `Albanna User`
role". It is "holds read on `Albanna Conversation`", which an operator
may widen through the permission matrix, plus a per-user policy override
that may switch the chat on for one account the matrix would refuse.
Both are deliberate and documented in
[ADR-0008](adr/0008-frappe-decides-permissions.md) and
[ADR-0014](adr/0014-a-reader-who-may-not-chat-gets-no-widget.md) — and
ADR-0008 records the site owner's own words: *"we do not want to
increase complexity in the application or impose a restriction that
makes the chat and the artificial intelligence appear weak."*

**Recommendation.** Reconcile the requirement's wording to "read on
`Albanna Conversation`, shipped as the `Albanna User` role" rather than
change the code. The strict reading would mean re-adding a second list
of role names, which ADR-0008 removed on purpose.

**What was unheld.** `require_chat_access`'s docstring claimed every
endpoint calls it. Nothing counted them. An endpoint added tomorrow
without a door would be a road into the chat for every account on the
site, and nothing else would notice.

**Closed.** `test_every_endpoint_is_behind_a_door` parses every
whitelisted endpoint and asserts each calls one of the three doors. See
[ADR-0057](adr/0057-every-door-into-the-chat-is-counted-not-trusted.md).

---

## FR-7.3 — The Albanna User role shall grant read, write, create, and delete on Albanna Conversation, all scoped to owner

**Requirement.** The row's shape.

**Status: MET.**

**Evidence.** One row, `Albanna User`, read/write/create/delete all 1,
`if_owner=1`, permlevel 0. Production's live `tabDocPerm` matches flag
for flag.

**What was unheld.** `test_the_chat_row_is_scoped_to_the_owner` held the
`if_owner` half. Nothing held the four rights, and nothing held the row
count. A row that lost its `delete` would still be `if_owner` and would
still pass every test in that file. And Frappe applies *every* matching
permission row, so a second row for the same role is a second shape —
the wider of the two governs.

**Closed.** `test_the_chat_row_grants_the_four_rights_and_is_one_row`
asserts the four against a named list, and asserts there is exactly one
row. See
[ADR-0058](adr/0058-the-shipped-matrix-is-asserted-against-the-requirement-not-against-memory.md).

**Found on the way.** The doctype's docstring claimed the matrix granted
read and write to *two* roles — "`System Manager` outright, and
`Albanna User` for the rows the account owns". The `System Manager` row
was removed on 2026-10-29. The comment described a matrix that had not
existed for eleven days. Corrected.

**Closed.** The row granted five rights beyond the four the requirement
names — `share`, `print`, `email`, `report`, `export` — all of them
Frappe's default permission row, never trimmed, and none of them
mentioned in any ADR. Four are harmless: `if_owner` scopes them to the
owner's own rows, so a reader may only print, email, report on or
export their own conversations.

`share` was not harmless. It let a reader hand their conversation to
another user through the Desk's Share dialog, crossing the owner-only
boundary the rest of the app enforces — `assert_owns` checks ownership
and ignores `DocShare` entirely, and `permission_query_conditions`
narrows list views to the owner. The app never creates or reads a share
itself, so the right was granted by accident and used by nobody. It is
dropped from `Albanna Conversation` and `Albanna Question`, and the
test now asserts it is absent.

---

## FR-7.4 — A System Manager shall not have chat access unless explicitly granted the Albanna User role

**Requirement.** Running the site is not holding the door open.

**Status: MET.**

**Evidence.** The shipped matrix names one role and no `System Manager`
row. `can_use_chat()` has no special case — its docstring says so and
the code agrees. A System Manager without the role is refused with
reason `"permission"` (`albanna/tests/test_chat_access.py`,
`test_a_system_manager_is_refused_the_chat`), and one who takes the role
may chat.

**What was unheld.** `can_use_chat()` was tested for a System Manager.
`require_chat_access()` — the function twenty-one endpoints call and
nothing else — was tested twice, both times about refusal wording, and
never once about a System Manager. A bypass at the top of that one
function would have opened every endpoint to every account that runs the
site, and all seventeen existing tests would have passed. It was proved,
not reasoned about: the bypass was added, the suite was run, and exactly
one test failed.

**Closed.** `test_the_door_refuses_a_system_manager` and its mirror. See
[ADR-0059](adr/0059-administrator-is-exempt-and-the-reason-was-invisible.md).

**Recorded, and invisible without this.** Administrator has chat access
without holding the role. Frappe's `has_permission` returns `True` for
Administrator *before it reads a single permission row*
(`frappe/permissions.py:103`) — verified on `test.localhost`, where
Administrator holds no `tabHas Role` row for `Albanna User` yet
`has_permission` returns `True`. And `frappe.get_roles()` reports
Administrator as holding every role on the site, so nothing an operator
can look at tells them which of the two is the reason. This is the one
account FR-7.4's letter does not cover; it is almost certainly correct
(the site owner can read everything anyway, and the app's own hooks
exempt Administrator deliberately), and it is now written down so that
nobody "fixes" it and takes the chat away from the site owner.

---

## FR-7.5 — The system shall filter available tools based on the user's capabilities

**Requirement.** A tool the user cannot use shall never be mentioned to
the model.

**Status: MET.**

**Evidence.** `albanna/services/toolset.py:29` (`tool_registry`) builds
a per-user registry; `without_writes_out_of_reach`
(`albanna/core/tools.py:147`) switches off any write tool whose right the
caller holds on no DocType; `Authority.visible()`
(`albanna/core/authority.py:211`) filters by `enabled` and
`required_roles`. Both the system prompt
(`albanna/services/chat_service.py:498`) and the provider payload
(`:551`) are built from that one filtered list.

**What was unheld.** Every test stopped at the registry — they assert
`visible_names()` excludes the tool. That is the rule *computed*. The
rule is *obeyed* in two separate places, by separate code, and nothing
asked either of them. Pointing the prompt at the whole manifest failed
one test; pointing the provider payload at it failed a different one.

**Closed.** `TestAToolTheUserCannotUse` runs a real turn as a reader who
holds no submit right anywhere on the site, and asks both the prompt and
the payload. The reader's rights were verified against the role's actual
rows rather than assumed: `Albanna User` grants rights on two DocTypes,
neither submittable, and the `Desk User` role Frappe adds alongside it
grants none either. A Sales User is the mirror, so the filter is proved
to drop what the reader cannot use and nothing else. See
[ADR-0060](adr/0060-a-rule-is-tested-where-it-is-obeyed-not-only-where-it-is-computed.md).

**Found on the way, and not a defect.** `creatable_doctypes` reported
seventeen DocTypes for a bare `Albanna User`. That is `Desk User`, which
Frappe attaches automatically and which grants create on fifteen
unrelated ones. It is the kind of number that reads like a bug.

---

## FR-7.6 — Write tools shall be offered only when the user has permission to perform that write on at least one DocType

**Requirement.** The offering condition.

**Status: MET.**

**Evidence.** `without_writes_out_of_reach` switches a write tool off
when its right is held on no DocType, and `tool_registry` feeds it the
six lists from `albanna/permissions.py`.

**What was unheld.** The existing tests named `create_doc` and
`update_doc`. The other five — `bulk_update_doc`, `submit_doc`,
`cancel_doc`, `amend_doc`, `delete_doc` — are switched by the same dict
literal, and a literal that named the wrong key would leave a tool
offered against a list that has nothing to do with it. The six lists
also reach the function as six *positional* arguments, and a swap would
offer `submit_doc` to a caller who may only cancel.

**Closed.** All seven write tools are asserted in both directions, with
the exactness proved — holding one right must switch on the tools that
right governs and nothing else. And the wiring is asked, by giving each
of the six lists a name of its own, one at a time, and asking the tools
which one they followed. Both defects were reintroduced and both were
caught. See
[ADR-0060](adr/0060-a-rule-is-tested-where-it-is-obeyed-not-only-where-it-is-computed.md).

---

## FR-7.7 — The authority check shall be fail-closed

**Requirement.** Unknown tools, disabled tools, missing roles, absent
DocTypes, site mismatches, and permission errors shall all result in
denial.

**Status: MET.**

**Evidence.** All six are refused: `unknown_tool`, `tool_disabled`,
`missing_role`, `missing_doctype`, the site mismatch in
`albanna/tools/backend.py:133` (`_assert_site`), and
`permission_check_failed` (`albanna/core/authority.py:289`). Five are
tested in `tests/test_authority.py`, purely; the site mismatch is tested
twice in the site suite.

**What was unheld.** The *unresolved* half of two of them, and a third
branch the shipped manifest cannot reach. A mismatch is a call bound to
the wrong site; an unresolved call is bound to no site at all, and
`_assert_site` keeps a separate branch for it — as does `_assert_actor`
for the actor. Neither had a test. And `unbound_write_tool` refuses a
mutating tool that names no target DocType, which the manifest cannot
currently produce.

**Closed.** All three branches are asked, and all three fail with their
branch made permissive. See
[ADR-0060](adr/0060-a-rule-is-tested-where-it-is-obeyed-not-only-where-it-is-computed.md).

**One thing this got wrong on its own, caught by the suite.** The test
helper read `user or frappe.session.user`, which turns an empty string
into the session user — so the empty-actor case never reached the gate
and the test passed for the wrong reason. `None` now means "whoever is
signed in" and an empty string is a value of its own. It is the failure
mode ADR-0055 is about, occurring inside the fix for it.

---

## Deliberate exclusions

* **FR-7.2's strict reading.** Not implemented, and recorded above
  rather than taken. It would re-add a second list of role names.
* **The five extra rights on the chat row.** Not removed, and recorded
  above as needing the owner's decision.
* **A decorator that makes the gate unforgetable.** Recorded in
  ADR-0057 as the real fix and not built; the test holds the property in
  the meantime.

## Accepted trade-offs

* **The Administrator exemption is inherited from Frappe, not chosen.**
  The app could refuse Administrator and does not, because the site
  owner can read everything anyway. It is now written down.
* **`share` on the chat row is granted and unused.** The app never
  creates or reads a share, so the right is inert inside the app and
  live in the Desk. That asymmetry is the reason it is flagged rather
  than ignored.

## Pointer

`docs/ROADMAP.md` §0 lists the access features among the shipped ones.
This document is the access-specific record, and
[ADR-0055](adr/0055-a-requirement-that-is-met-is-not-a-requirement-that-is-held.md)
through
[ADR-0060](adr/0060-a-rule-is-tested-where-it-is-obeyed-not-only-where-it-is-computed.md)
are the six decisions the pass made.
