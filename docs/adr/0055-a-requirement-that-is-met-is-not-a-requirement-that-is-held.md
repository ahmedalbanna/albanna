# ADR-0055: A requirement that is met is not a requirement that is held

Status: **Accepted**
Date: 2026-11-09

## Context

FR-7 arrived as seven statements about who may use the chat and what
they may be offered. All seven were already true. Not one of them was
broken.

That is the finding, and it is worth recording before the individual
ADRs, because it inverts what a requirements review is usually for. The
expectation going in was that some of the seven would be unmet and would
need building. What the review found instead was seven rules that were
correct in the code and unheld by any test — and the difference between
those two states is invisible until somebody changes the code.

The shape recurred every time, in four variants:

* **A rule held on one side only.** FR-7.1's "off by default" was
  asserted for the shipped matrix and not for the installer that grants
  the role. FR-7.3's row shape was asserted for `if_owner` and not for
  the four rights.
* **A rule claimed by a comment.** `require_chat_access`'s docstring
  said every endpoint calls it. Nothing counted them.
* **A rule tested where it is computed, not where it is obeyed.**
  `visible_names()` excluded the tool; the prompt and the provider
  payload were never asked.
* **A rule whose unreachable branch had never run.**
  `unbound_write_tool` refuses a manifest mistake the shipped manifest
  cannot make.

## Decision

**Record the distinction, and treat "met" as a claim to be checked
rather than a conclusion.**

Each of the seven is now held by a test that fails when the rule is
broken, and each was proved by reintroducing the defect. That last part
is the decision that matters: a test that has never been seen to fail is
a test that has never been run against the thing it claims to guard.

## Alternatives considered

**Report FR-7 as passing and move on.** Rejected: it would have been
true and useless. The seven rules would have stayed correct for exactly
as long as nobody edited the files they live in, and the next change to
any of them would have been made in the dark.

**Rewrite the seven requirements to match the code.** Rejected: the
code was right. The requirements were the fixed point; what was missing
was the evidence.

**Add one test per requirement and stop there.** Rejected: it would
have produced seven tests that each pass, which is the state the review
started from. The negative test is what turns a passing test into a
guard.

## Consequences

* Seven requirements, seven guards, and seven reintroduced defects
  caught.
* The general lesson, which the rest of this ADR set applies: the
  question to ask of a met requirement is not "is it true?" but "what
  would fail if it stopped being true?"
* Two of the seven turned out to need a decision rather than a test,
  and both are recorded rather than taken — FR-7.2's letter deviates
  from the implementation deliberately (ADR-0008), and FR-7.3's row
  grants five rights beyond the four named.
* One thing this pass got wrong on its own, caught by the suite: a test
  helper read `user or frappe.session.user`, which turned the empty
  string into the session user, so the case under test never reached
  the gate. The test passed for the wrong reason — which is the failure
  mode this whole ADR is about, occurring inside the fix for it.

## See also

* [ADR-0040](0040-a-guard-that-only-runs-past-a-threshold-fails-in-whatever-crossed-it.md)
  — the other bound in this app that was wrong at its edge, found the
  same way.
* ADR-0056 through ADR-0060 — the seven requirements, grouped into the
  six decisions they produced.
* `docs/FR-7_ACCESS.md` — the record of the seven against the code.
