"""Who may call what.

This module is the reason Albanna can run the ERPNext tools in-process.

The backend it borrows the tools from enforced a role gate at the edge: a
tool was reachable or not depending on the caller's Frappe roles, checked by
the registration layer before the tool body ran.  Calling the same functions
directly — which is what "in-process" means — removes that gate, and
removing it silently would turn every tool into an Administrator action.
So Albanna owns the decision itself, here, in one place.

Two questions, two kinds of answer
-----------------------------------

*Reachability* is static.  It asks whether this person may reach this tool
at all: is it switched on, does the principal hold the roles it requires.
The answer does not depend on what the model asked for, so it is computed
once per turn and used to decide what the model is even told about.

*Authorisation* is dynamic.  It asks whether this person may make *this*
call.  A write tool names its target in the arguments — ``create_doc`` and
``update_doc`` both carry a ``doctype`` — and whether the person may create
a Sales Invoice is a different question from whether they may create a
Customer.  The answer depends on the arguments, so it is computed per call,
against the DocType the arguments selected.

The two kinds of write are authorised against different rights.
``create_doc`` is checked against ``create`` and ``update_doc`` against
``write``, because a role model that grants one does not necessarily grant
the other.

The rule that falls out of this, and that the chat service obeys: a tool the
principal may not reach is never mentioned to the model.  Not "mentioned and
then refused" — never mentioned.  A model that can see a tool it cannot use
spends a turn discovering that, and a model that cannot see a tool cannot
waste one.

Fail-closed
-----------
Every path that is not an explicit "yes" is a "no".  An unknown tool name, a
tool that is switched off, a missing role, a write call whose target
DocType is missing from the arguments, a permission checker that raises —
all of them deny.  The only way to widen the surface is to change the
manifest or the settings, both of which are reviewed code or reviewed
configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from albanna.core.tools import ToolRegistry, ToolSpec


@dataclass(frozen=True)
class Principal:
    """The person on whose behalf a call is made."""

    user: str
    roles: frozenset[str] = frozenset()
    is_system_manager: bool = False

    def has_role(self, role: str) -> bool:
        return role in self.roles or self.is_system_manager


@dataclass(frozen=True)
class PermissionChecker(Protocol):
    """The document-level questions the authority layer needs answered.

    Implemented in the Frappe layer (:mod:`albanna.permissions`).  It is a
    protocol rather than an import so that this module stays free of Frappe
    and can be tested with a stub.
    """

    def can_create(self, doctype: str) -> bool:
        """True when the principal may create a document of *doctype*."""
        ...

    def can_write(self, doctype: str) -> bool:
        """True when the principal may change documents of *doctype*.

        The same question as :meth:`can_create`, asked about a different
        right.  Creating a Sales Invoice and changing one are different
        permissions, and a role model that grants the first does not
        necessarily grant the second.
        """
        ...

    def can_submit(self, doctype: str) -> bool:
        """True when the principal may submit documents of *doctype*."""
        ...

    def can_cancel(self, doctype: str) -> bool:
        """True when the principal may cancel documents of *doctype*."""
        ...

    def can_amend(self, doctype: str) -> bool:
        """True when the principal may amend documents of *doctype*."""
        ...

    def can_delete(self, doctype: str) -> bool:
        """True when the principal may delete documents of *doctype*."""
        ...

    def can_read(self, doctype: str) -> bool:
        """True when the principal may read documents of *doctype*."""
        ...

    def roles_for(self, doctype: str, ptype: str) -> list[str]:
        """The roles that hold *ptype* on *doctype*.

        Used to turn a refusal into a fact the reader can act on.  "You
        cannot create a Sales Invoice" is a dead end; "a Sales Invoice is
        created by an Accounts User" is a fact about the organisation that
        the assistant can state plainly, without apologising for anything.
        """
        ...


#: How each kind of write is named when it is refused.
#:
#: A refusal is handed to the *model*, which then tells the reader, so the
#: wording has to be a fact about the organisation rather than a failure of
#: the assistant.  "Creating a 'Sales Invoice' is done by these roles" is a
#: fact; "you may not create this" is a wall.
WRITE_VERBS = {
    "create": {"infinitive": "create", "verb": "Creating", "participle": "created"},
    "write": {"infinitive": "edit", "verb": "Editing", "participle": "changed"},
    "submit": {"infinitive": "submit", "verb": "Submitting", "participle": "submitted"},
    "cancel": {"infinitive": "cancel", "verb": "Cancelling", "participle": "cancelled"},
    "amend": {"infinitive": "amend", "verb": "Amending", "participle": "amended"},
    "delete": {"infinitive": "delete", "verb": "Deleting", "participle": "deleted"},
}


def write_verb(ptype: str) -> dict[str, str]:
    """The vocabulary for a write authorised against *ptype*."""
    return WRITE_VERBS.get(ptype, WRITE_VERBS["create"])


@dataclass(frozen=True)
class Denial:
    """A refused call, and why."""

    code: str
    reason: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.reason


@dataclass(frozen=True)
class Decision:
    """The outcome of one authorisation check."""

    allowed: bool
    reason: str = ""
    code: str = ""

    @classmethod
    def allow(cls) -> Decision:
        return cls(allowed=True)

    @classmethod
    def deny(cls, code: str, reason: str) -> Decision:
        return cls(allowed=False, code=code, reason=reason)

    def as_denial(self) -> Denial | None:
        return None if self.allowed else Denial(code=self.code, reason=self.reason)


class Authority:
    """Answers reachability and authorisation for one principal."""

    def __init__(
        self,
        registry: ToolRegistry,
        principal: Principal,
        checker: PermissionChecker | None = None,
    ) -> None:
        self._registry = registry
        self._principal = principal
        self._checker = checker

    @property
    def principal(self) -> Principal:
        return self._principal

    # -- reachability ----------------------------------------------------

    def get(self, name: str) -> ToolSpec | None:
        return self._registry.get(name)

    def spec_for(self, name: str) -> ToolSpec | None:
        """The specification of a tool, whether or not it is reachable.

        The chat service needs this to validate arguments before a call and
        to describe the tool back to the model; the *reachability* of that
        tool is a separate question, answered by :meth:`authorize`.
        """
        return self._registry.get(name)

    def is_reachable(self, spec: ToolSpec) -> bool:
        """True when the principal may reach this tool at all."""
        if not spec.enabled:
            return False
        return all(self._principal.has_role(role) for role in spec.required_roles)

    def visible(self) -> list[ToolSpec]:
        """The tools this principal may reach.

        This list is what the model is told about.  It is also the list the
        chat service will accept a call for — a call to a tool outside it is
        refused, not merely ignored.
        """
        return [spec for spec in self._registry.all() if self.is_reachable(spec)]

    def visible_names(self) -> tuple[str, ...]:
        return tuple(spec.name for spec in self.visible())

    # -- authorisation ---------------------------------------------------

    def authorize(self, name: str, arguments: dict[str, Any] | None = None) -> Decision:
        """Decide whether this principal may make this call."""
        arguments = arguments or {}

        spec = self._registry.get(name)
        if spec is None:
            return Decision.deny(
                "unknown_tool",
                f"There is no tool named '{name}'. Available tools: "
                f"{', '.join(self.visible_names()) or 'none'}.",
            )

        if not spec.enabled:
            return Decision.deny("tool_disabled", f"The tool '{name}' is not available.")

        missing_roles = [role for role in spec.required_roles if not self._principal.has_role(role)]
        if missing_roles:
            return Decision.deny(
                "missing_role",
                f"The tool '{name}' requires the role(s): {', '.join(missing_roles)}.",
            )

        if spec.mutating:
            return self._authorize_write(spec, arguments)

        return Decision.allow()

    def _authorize_write(self, spec: ToolSpec, arguments: dict[str, Any]) -> Decision:
        """Check a write call against the document it would create.

        The target DocType is chosen by the model, so the check happens here,
        at call time, against the argument the model actually supplied.
        """
        if not spec.doctype_arg:
            # A write tool with no document target has no document-level
            # permission to check.  That is a manifest mistake, and the
            # safe reading of it is to refuse the call.
            return Decision.deny(
                "unbound_write_tool",
                f"The tool '{spec.name}' writes but names no target DocType, "
                f"so its permission cannot be established.",
            )

        doctype = arguments.get(spec.doctype_arg)
        if not isinstance(doctype, str) or not doctype.strip():
            return Decision.deny(
                "missing_doctype",
                f"The tool '{spec.name}' needs a '{spec.doctype_arg}' naming the DocType to write.",
            )

        doctype = doctype.strip()
        verb = write_verb(spec.write_permission)

        if self._checker is None:
            return Decision.deny(
                "no_permission_checker",
                f"Cannot establish whether '{doctype}' may be {verb['infinitive']}ed.",
            )

        try:
            checker = getattr(self._checker, f"can_{spec.write_permission}", None)
            if checker is None:
                raise AttributeError(f"no can_{spec.write_permission}")
            allowed = bool(checker(doctype))
        except Exception:
            # A checker that fails is a checker that says no.  Letting the
            # exception through would turn a broken permission query into an
            # open door.
            return Decision.deny(
                "permission_check_failed",
                f"Could not establish permission to {verb['infinitive']} '{doctype}'.",
            )

        if not allowed:
            return Decision.deny(
                "not_permitted",
                self._refusal(spec.name, doctype, spec.write_permission),
            )

        return Decision.allow()

    def _refusal(self, tool: str, doctype: str, ptype: str = "create") -> str:
        """Why the write was refused, stated as a fact.

        The wording matters more here than anywhere else in the app.  This
        string is handed to the *model*, which then tells the reader.  If it
        reads like the assistant's own failure, the assistant apologises for
        it, and the reader concludes the tool is broken.  It is not: it is a
        fact about who may change this kind of document, and the reader is
        told it as one — with the roles that could, so the answer is
        actionable.

        The wording follows the kind of write: a refused *edit* is not a
        refused *creation*, and telling the reader they may not create a
        document when the assistant tried to change one is its own small
        kind of wrong.
        """
        verb = write_verb(ptype)
        roles = self.roles_for(doctype, ptype)

        if roles:
            listed = ", ".join(roles)
            return (
                f"{verb['verb']} a '{doctype}' is done by these roles: {listed}. "
                f"This account does not hold one of them, so the document was "
                f"not {verb['participle']}. Say who can {verb['infinitive']} it, "
                f"and do not apologise for it."
            )

        return (
            f"This account is not permitted to {verb['infinitive']} a "
            f"'{doctype}', so the document was not {verb['participle']}. State "
            f"that as a fact about the account, and do not apologise for it."
        )

    def roles_for(self, doctype: str, ptype: str) -> list[str]:
        """The roles that hold *ptype* on *doctype*, as the framework sees them."""
        if self._checker is None or not doctype:
            return []
        try:
            return list(self._checker.roles_for(doctype, ptype))
        except Exception:
            return []
