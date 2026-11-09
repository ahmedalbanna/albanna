# ADR-0059: Administrator is exempt, and the reason was invisible

Status: **Accepted**
Date: 2026-11-09

## Context

FR-7.4: a System Manager shall not have chat access unless explicitly
granted the `Albanna User` role.

That was enforced and was not tested where it is enforced.
`can_use_chat()` was tested for a System Manager and refused correctly.
`require_chat_access()` — the function twenty-one endpoints call and
nothing else — was tested twice, both times about the wording of a
refusal, and never once about a System Manager.

So a bypass at the top of that one function would have opened every
endpoint on the site to every account that runs it, and all seventeen
existing tests would have passed. It was not reasoned about; it was
proved. The bypass was added, the suite was run, and exactly one test
failed — the new one.

## Decision

**Ask the door itself about a System Manager, and record the
Administrator exemption beside it.**

Two tests: the door refuses a System Manager who does not hold the
role, and the door opens for one who does. And a third that records the
one account FR-7.4's letter does not cover.

Frappe's `has_permission` returns `True` for Administrator *before it
reads a single permission row* — unconditional, in
`frappe/permissions.py`. The app's gate inherits that, and the app's own
hooks exempt Administrator deliberately: for the site owner, the list of
conversations is a fact about their own site.

It is recorded because it is invisible. Administrator holds no
`Albanna User` row in `tabHas Role`, and `frappe.get_roles()` reports
them as holding every role on the site — so nothing an operator can look
at tells them which of the two is the reason. A reader who concludes the
gate must cover Administrator and "fixes" it takes the chat away from
the site owner, for a reason that was never written down.

The test reads the role *rows* rather than `get_roles()`, because
`get_roles()` is the mask.

## Alternatives considered

**Refuse Administrator too.** Rejected: it would take the chat away
from the site owner, and the site owner can read everything anyway. The
exemption is not a hole; it is the framework's, and the app's own hooks
agree with it on purpose.

**Leave the exemption undocumented, since it is Frappe's behaviour and
not the app's.** Rejected: that is exactly why it needs writing down.
The next reader has no way to know it is the framework's rather than a
bug, and the obvious fix is the wrong one.

**Test only `can_use_chat()` and not the door.** Rejected: that is the
state the review found. The two are different functions, and a bypass
written into one is invisible to the other.

## Consequences

* The door is asked about a System Manager, and the test fails with the
  bypass reintroduced.
* The Administrator exemption is written down, and the test fails if
  somebody removes it — which would break the site owner's access for a
  reason nobody had recorded.
* The general lesson is ADR-0055's second variant, in its sharpest
  form: the function that enforces a rule and the function that answers
  the same question are not the same function, and testing one is not
  testing the other.

## See also

* [ADR-0008](0008-frappe-decides-permissions.md) — the `System Manager`
  row was removed from the matrix on 2026-10-29, which is what makes
  FR-7.4 a real requirement rather than a restatement of the framework.
* `albanna/tests/test_chat_access.py` — the gate read three ways: the
  matrix, the policy, and the door.
* `albanna/services/conversation_service.py` — `has_permission` and
  `get_permission_query_conditions`, which exempt Administrator
  deliberately and say why.
