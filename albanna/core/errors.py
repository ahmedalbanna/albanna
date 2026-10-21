"""The error taxonomy.

Two families, and the difference between them is the difference between
"retry this" and "tell the user":

*   A **provider** error is the model's side — the API was unreachable, the
    key was refused, the request was too large.  The chat service retries
    transient ones and falls back to the secondary provider on the rest.

*   A **tool** error is the site's side — the DocType does not exist, the
    filter names no such field, the user may not create that document.  These
    are not retried; they are handed back to the model as the tool's result,
    because the model can often fix them by calling the tool again with
    different arguments.

The taxonomy lives in the domain layer because the chat service needs to
classify failures, and it needs to do so without importing the provider
adapters or Frappe.
"""

from __future__ import annotations


class AlbannaError(Exception):
    """Base class for every error this app raises on purpose."""


class ProviderError(AlbannaError):
    """A model provider failed."""

    #: Whether retrying the same call could plausibly succeed.  An instance
    #: may override it — a 429 is the same class of failure as a 401 but the
    #: opposite answer to "retry?".
    transient = False

    def __init__(
        self,
        message: str,
        *,
        provider: str = "",
        status: int | None = None,
        transient: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status = status
        if transient is not None:
            self.transient = transient


class ProviderTimeout(ProviderError):
    """The provider did not answer in time."""

    transient = True


class ProviderUnreachable(ProviderError):
    """The provider could not be reached at all."""

    transient = True


class ProviderRejected(ProviderError):
    """The provider refused the request (a key, a limit, a bad request)."""

    transient = False


class ProviderBudgetExceeded(ProviderError):
    """The request asked for more than the key could pay for.

    Some providers check the *worst case* cost of a request — the maximum
    number of tokens the answer might use — against the key's balance, and
    refuse the request when the worst case is too expensive, even though
    the answer would in fact have been cheap.

    The refusal usually names the number that *would* have been affordable.
    That number is an instruction, not just a complaint: the request can be
    made again with a smaller ceiling, and the answer will usually be
    shorter than the ceiling anyway.
    """

    #: The number of tokens the provider says it could pay for, when it says.
    affordable_tokens: int | None = None

    def __init__(
        self,
        message: str,
        *,
        provider: str = "",
        status: int | None = None,
        affordable_tokens: int | None = None,
    ) -> None:
        super().__init__(message, provider=provider, status=status)
        self.affordable_tokens = affordable_tokens


class AllProvidersFailed(ProviderError):
    """Every configured provider failed."""


class ToolError(AlbannaError):
    """A tool call could not be completed."""


class ToolDenied(ToolError):
    """The principal was not allowed to make this call."""


class ToolInvalidArguments(ToolError):
    """The arguments did not match the tool's schema."""


class TurnLimitReached(AlbannaError):
    """The turn used its whole tool-round budget without an answer."""
