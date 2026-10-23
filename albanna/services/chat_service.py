"""One turn of the chat.

This is the orchestrator.  It owns the loop that the connector called
``_run_chat`` and the backend's clients call a "tool loop":

    ask the model  ->  the model asks for a tool  ->  run the tool
                   ->  feed the result back        ->  ask again

and it ends when the model answers without asking for a tool, or when the
round budget runs out.

The rules it keeps
------------------

*   **The model only ever sees tools the user may reach.**  The manifest is
    filtered by the authority layer *before* the schemas are sent, so a tool
    the user cannot use is never mentioned and never called.

*   **A tool failure is not a turn failure.**  A tool that errors returns
    its error to the model as the tool's result, because the model can
    often fix it — add the filter the report asked for, use a different
    fieldname.  The turn only fails when the *model* fails.

*   **The turn is bounded.**  ``max_tool_rounds`` is a hard ceiling, and
    hitting it produces a diagnosis rather than a silence: which tool was
    called most, what the last failure was, how many rounds were spent
    looking for a tool.  "I could not answer that" with the reason attached
    is a usable answer; a turn that stops without saying why is not.

*   **A tool's write survives the turn.**  The tool functions commit their
    own transaction, so a document that was created is created even if the
    model fails afterwards.  That is deliberate: the user asked for the
    document, and the assistant's ability to describe it is a separate
    concern.
"""

from __future__ import annotations

import contextlib
import json
import logging
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

import frappe
from frappe import _

from albanna.core.authority import Authority
from albanna.core.cost import cost_of_turn
from albanna.core.errors import AllProvidersFailed, ProviderBudgetExceeded, ProviderError
from albanna.core.messages import (
    Message,
    ToolCall,
    as_plain_history,
    sanitize,
    system,
    tool_result,
    user,
)
from albanna.core.prompt import PromptContext, build_system_prompt
from albanna.core.tools import ToolSpec, validate_arguments
from albanna.providers.base import (
    Completion,
    LLMConfig,
    ProviderConfig,
    StreamDone,
    Usage,
    build_provider,
)
from albanna.tools.backend import ErpnextBackend
from albanna.tools.base import ToolContext, ToolResult

logger = logging.getLogger(__name__)

#: Called with each progress event as it happens.
Emit = Callable[[dict[str, Any]], None]


def _noop_emit(event: dict[str, Any]) -> None:
    return None


@dataclass
class TurnRequest:
    """What the user asked for."""

    question: str
    conversation_id: str = ""
    page: str = ""
    page_context: str = ""
    stream: bool = False


@dataclass
class TurnOutcome:
    """What happened."""

    ok: bool
    reply: str = ""
    conversation_id: str = ""
    provider: str = ""
    model: str = ""
    rounds: int = 0
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: Usage | None = None
    error: str = ""
    capped: bool = False
    #: True when the provider cut the answer off at the token ceiling.
    #:
    #: The answer is not wrong — it is unfinished, and the reader is told
    #: so, because an answer that looks complete and is not is worse
    #: than one that says it was cut.
    truncated: bool = False
    diagnosis: dict[str, Any] = field(default_factory=dict)
    #: The rows this turn wrote, as ``(name, role)`` pairs.
    #:
    #: The browser is told what was written, because a row that can be
    #: named is a row that can be addressed later: the reader can remove
    #: this turn, and the browser has to know which row to ask for.  The
    #: names are the rows' own, so they do not shift when the
    #: conversation grows.
    written: list[tuple[str, str]] = field(default_factory=list)
def turn_payload(outcome: TurnOutcome) -> dict[str, Any]:
    """The wire shape of a turn.

    **One place**, because there are two ways a turn reaches the browser:
    the endpoint that runs it here and now, and the worker that runs it
    there and now.  Both send the same shape, so both build it here —
    a field that is added to one of them and forgotten in the other is a
    field the reader never sees, and the bug is invisible until someone
    waits for the answer that was never announced.
    """
    return {
        "status": "ok" if outcome.ok else "error",
        "reply": outcome.reply,
        "conversation_id": outcome.conversation_id,
        "provider": outcome.provider,
        "model": outcome.model,
        "rounds": outcome.rounds,
        "tool_calls": outcome.tool_calls,
        "capped": outcome.capped,
        # The answer was cut off at the token ceiling.  The reader is
        # told, because an answer that looks complete and is not is
        # worse than one that says it was cut.
        "truncated": outcome.truncated,
        "error": outcome.error,
        # The rows the turn wrote, so that the browser can address this
        # turn later — a row that can be named is a row that can be
        # removed.
        "written": [{"name": name, "role": role} for name, role in outcome.written],
    }


class ChatService:
    """Runs one turn of the chat."""

    def __init__(self, backend=None) -> None:
        self._backend = backend or ErpnextBackend()

    # -- the turn ---------------------------------------------------------

    def run(self, request: TurnRequest, emit: Emit = _noop_emit) -> TurnOutcome:
        """Run one turn and return what happened."""
        from albanna.permissions import (
            FrappePermissionChecker,
            creatable_doctypes,
            current_principal,
            writable_doctypes,
        )
        from albanna.services.conversation_service import (
            append_messages,
            assert_owns,
            ensure_conversation,
            load_messages,
            trim_conversation,
        )
        from albanna.services.settings_service import get_settings
        from albanna.site_context import current_site, default_company, default_currency

        started = time.monotonic()
        settings = get_settings()

        if not settings.enabled:
            return TurnOutcome(ok=False, error=_("The chat is switched off on this site."))

        question = (request.question or "").strip()
        if not question:
            return TurnOutcome(ok=False, error=_("Ask a question."))
        principal = current_principal()
        site = current_site()

        registry = self._tool_registry(principal.user)
        authority = Authority(registry, principal, FrappePermissionChecker())
        visible = authority.visible()

        conversation = self._resolve_conversation(request, principal.user, question)

        history = load_messages(conversation, settings.history_limit)
        company = default_company()
        from albanna.user_policy import confirm_writes_for

        context = PromptContext(
            site=site,
            company=company,
            currency=default_currency(company),
            user=principal.user,
            creatable=tuple(creatable_doctypes(principal.user)),
            writable=tuple(writable_doctypes(principal.user)),
            writes_require_approval=confirm_writes_for(principal.user),
            page_context=request.page_context,
        )

        messages: list[Message] = [
            system(build_system_prompt(visible, context, settings.system_prompt))
        ]
        messages.extend(sanitize(as_plain_history(history)))
        messages.append(user(question))

        tool_calls_made: list[dict[str, Any]] = []
        rounds = 0
        usage: Usage | None = None
        provider_name = ""
        model_name = ""

        llm_config = LLMConfig(
            primary=settings.provider,
            fallback=settings.fallback,
            retries=1,
        )

        for round_no in range(settings.max_tool_rounds):
            rounds = round_no + 1
            # A code, not a sentence.  The turn runs in a worker, and a
            # worker has no user's language to render a label in — the
            # interface's language is the *reader's*, and only the reader
            # has it.  So the server says what is happening and the client
            # says it in the reader's language.
            emit({"event": "status", "round": rounds, "code": "thinking"})

            try:
                completion = self._complete(llm_config, messages, visible, emit, request.stream)
            except AllProvidersFailed as exc:
                self._log(
                    conversation,
                    principal.user,
                    provider_name,
                    model_name,
                    rounds,
                    tool_calls_made,
                    usage,
                    started,
                    "error",
                    "provider_error",
                    str(exc),
                    price_per_million=settings.price_per_million,
                )
                return TurnOutcome(
                    ok=False,
                    error=str(exc),
                    conversation_id=conversation,
                    rounds=rounds,
                    tool_calls=tool_calls_made,
                )

            provider_name = completion.provider
            model_name = completion.model
            if completion.usage is not None:
                usage = completion.usage

            answer = completion.message

            if not answer.tool_calls:
                reply = (answer.content or "").strip()
                if not reply:
                    reply = _("I could not produce an answer to that.")
                written = append_messages(
                    conversation,
                    [
                        {"role": "user", "content": question, "round_no": 0},
                        {
                            "role": "assistant",
                            "content": reply,
                            "round_no": rounds,
                            # The *executed* tool calls, not the ones the
                            # model asked for: the transcript shows what
                            # happened, and the audit log records the same
                            # shape.  One shape, two readers.
                            "tool_calls": json.dumps(tool_calls_made, default=str),
                        },
                    ],
                )
                trim_conversation(conversation)
                frappe.db.set_value(
                    "Albanna Conversation",
                    conversation,
                    {"model": completion.model},
                    update_modified=False,
                )
                self._log(
                    conversation,
                    principal.user,
                    completion.provider,
                    completion.model,
                    rounds,
                    tool_calls_made,
                    usage,
                    started,
                    "truncated" if completion.truncated else "ok",
                    "",
                    "",
                    price_per_million=settings.price_per_million,
                )
                return TurnOutcome(
                    ok=True,
                    reply=reply,
                    conversation_id=conversation,
                    provider=completion.provider,
                    model=completion.model,
                    rounds=rounds,
                    tool_calls=tool_calls_made,
                    usage=usage,
                    truncated=completion.truncated,
                    written=written,
                )

            # The model asked for tools.  Record the request, run them, and
            # feed the results back.
            messages.append(
                Message(
                    role="assistant",
                    content=answer.content or "",
                    tool_calls=answer.tool_calls,
                )
            )

            for call in answer.tool_calls:
                result = self._run_tool(call, authority, principal, site, visible, emit)
                entry = {
                    "name": call.name,
                    "ok": result.ok,
                    "denied": result.denied,
                    "approved": result.approved,
                    "error": result.error,
                    # What the call found, kept with the call so that a
                    # conversation reopened tomorrow still says what was
                    # looked up, and not only which function was called.
                    "summary": result.summary or result.error,
                    # The documents it looked at, kept for the same
                    # reason: a reopened answer links to them too.
                    "documents": touched_documents(call, result),
                }
                created = _created_name(result)
                if created:
                    entry["created"] = created
                tool_calls_made.append(entry)
                messages.append(tool_result(call.id, result.content))

        # The step budget ran out.  Rather than have the *app* compose a
        # sentence about it, the model is asked to answer with what it has
        # already found.  Two things follow: the answer is in the reader's
        # language rather than the app's, and it reports findings instead
        # of apologising for a limit that is not the assistant's own.
        diagnosis = self._diagnose(tool_calls_made, rounds)
        reply, truncated = self._answer_from_findings(llm_config, messages, visible, diagnosis)

        written = append_messages(
            conversation,
            [
                {"role": "user", "content": question, "round_no": 0},
                {"role": "assistant", "content": reply, "round_no": rounds},
            ],
        )
        self._log(
            conversation,
            principal.user,
            provider_name,
            model_name,
            rounds,
            tool_calls_made,
            usage,
            started,
            "truncated" if truncated else "capped",
            "round_limit",
            f"reached {settings.max_tool_rounds} rounds",
            price_per_million=settings.price_per_million,
        )
        return TurnOutcome(
            ok=True,
            reply=reply,
            conversation_id=conversation,
            provider=provider_name,
            model=model_name,
            rounds=rounds,
            tool_calls=tool_calls_made,
            usage=usage,
            capped=True,
            truncated=truncated,
            diagnosis=diagnosis,
            written=written,
        )

    # -- the model --------------------------------------------------------

    def _complete(
        self,
        config: LLMConfig,
        messages: list[Message],
        tools: list[ToolSpec],
        emit: Emit,
        stream: bool,
    ) -> Completion:
        """Call the model, trying the chain and retrying what is worth retrying."""
        failures: list[str] = []

        for provider_config in config.chain():
            provider = build_provider(provider_config.kind)
            attempt = 0
            reduced = False

            while True:
                try:
                    if stream:
                        return self._stream(provider, provider_config, messages, tools, emit)
                    return provider.complete(provider_config, messages, tools)
                except ProviderBudgetExceeded as exc:
                    affordable = exc.affordable_tokens or 0
                    if affordable and not reduced and affordable < provider_config.max_tokens:
                        # The provider said what it could pay for.  Asking
                        # again with that ceiling is not a retry of a
                        # failure — it is the same request with a limit the
                        # provider has already told us is acceptable.
                        provider_config = replace(provider_config, max_tokens=affordable)
                        reduced = True
                        logger.info(
                            "Provider %s can afford %d tokens; asking again with that ceiling",
                            provider_config.label,
                            affordable,
                        )
                        continue
                    failures.append(f"{provider_config.label}: {exc}")
                    break
                except ProviderError as exc:
                    failures.append(f"{provider_config.label}: {exc}")
                    if exc.transient and attempt < config.retries:
                        attempt += 1
                        time.sleep(min(2.0 * (2 ** (attempt - 1)), 8.0))
                        continue
                    break
                except Exception as exc:  # noqa: BLE001 - a provider may raise anything
                    failures.append(f"{provider_config.label}: {type(exc).__name__}: {exc}")
                    break

        raise AllProvidersFailed("; ".join(failures) or "No model provider is configured.")

    def _stream(
        self,
        provider,
        provider_config: ProviderConfig,
        messages: list[Message],
        tools: list[ToolSpec],
        emit: Emit,
    ) -> Completion:
        """Consume a provider's stream and emit its deltas."""
        completion: Completion | None = None
        for event in provider.stream(provider_config, messages, tools):
            if isinstance(event, StreamDone):
                completion = event.completion
            else:
                emit({"event": "token", "text": event.text})

        if completion is None:
            raise ProviderError(
                f"{provider_config.label} ended its stream without an answer.",
                provider=provider_config.label,
            )
        return completion

    # -- the tools --------------------------------------------------------

    def _resolve_conversation(self, request: TurnRequest, user: str, question: str) -> str:
        """The conversation this turn belongs to.

        A conversation id arrives from the browser, so it is checked against
        the caller's own: the rows are read with direct SQL, which does not
        consult the permission hooks.
        """
        from albanna.services.conversation_service import (
            assert_owns,
            ensure_conversation,
            name_after_question,
        )

        if not request.conversation_id:
            return ensure_conversation(user, request.page, title=question[:120])

        assert_owns(request.conversation_id, user)

        # A conversation the panel's "New" button created has no title yet:
        # the button is pressed before there is a question to name it
        # after.  This is that question, so it names it.
        name_after_question(request.conversation_id, question)

        return request.conversation_id

    def _tool_registry(self, user: str):
        """The tool set this turn may use.

        The set is the caller's, not the site's: a write tool is in it
        when the caller holds the right it needs, and not otherwise.  The
        alternative -- one switch for the whole site -- made the assistant
        weaker than the person in front of it.
        """
        from albanna.services.toolset import tool_registry

        return tool_registry(user)

    def _run_tool(
        self,
        call: ToolCall,
        authority: Authority,
        principal,
        site: str,
        visible: list[ToolSpec],
        emit: Emit,
    ) -> ToolResult:
        """Run one tool call, or explain why it was not run."""
        spec = authority.spec_for(call.name)
        if spec is None:
            names = ", ".join(tool.name for tool in visible) or "none"
            return ToolResult.refusal(
                f"There is no tool named '{call.name}'. The available tools are: {names}.",
                "unknown_tool",
            )

        decision = authority.authorize(call.name, call.arguments)
        if not decision.allowed:
            emit(
                {
                    "event": "tool_done",
                    "name": call.name,
                    "ok": False,
                    "error": decision.reason,
                    "summary": decision.reason,
                }
            )
            return ToolResult.refusal(decision.reason, decision.code)

        invalid = validate_arguments(spec, call.arguments)
        if invalid:
            emit(
                {
                    "event": "tool_done",
                    "name": call.name,
                    "ok": False,
                    "error": invalid,
                    "summary": invalid,
                }
            )
            return ToolResult.failure(invalid, invalid)

        # Hard confirmation gate: when the operator has asked for it, a
        # write does not run until the reader has approved it.  The turn
        # pauses here and waits for the browser's answer; a refusal or a
        # timeout is reported to the model as a denial, so it can say so.
        from albanna.user_policy import confirm_writes_for

        gated = spec.mutating and confirm_writes_for(principal.user)

        if gated:
            import time
            import uuid

            request_id = uuid.uuid4().hex
            emit(
                {
                    "event": "confirm",
                    "request_id": request_id,
                    "name": call.name,
                    "arguments": call.arguments,
                    "preview": _write_preview(call.name, call.arguments),
                }
            )

            key = f"albanna:confirm:{request_id}"
            decision = "timeout"
            deadline = time.monotonic() + 120.0
            while time.monotonic() < deadline:
                value = frappe.cache().get_value(key, user=principal.user)
                if value is not None:
                    decision = str(value)
                    with contextlib.suppress(Exception):
                        frappe.cache().delete_value(key, user=principal.user)
                    break
                time.sleep(0.5)

            if decision != "approve":
                message = (
                    "The reader did not approve this change, so it was not made."
                    if decision == "reject"
                    else "The reader did not respond in time, so the change was not made."
                )
                emit(
                    {
                        "event": "tool_done",
                        "name": call.name,
                        "ok": False,
                        "error": message,
                        "summary": message,
                    }
                )
                return ToolResult(ok=False, content=message, error=message, denied=True, approved=False)

        emit({"event": "tool_start", "name": call.name, "arguments": call.arguments})

        context = ToolContext(principal=principal, site=site)
        try:
            result = self._backend.call(spec, call.arguments, context)
            result = self._explain_failure(spec, call.arguments, result, authority)
            if gated:
                result.approved = True
        except Exception as exc:  # noqa: BLE001 - a tool must not kill the turn
            logger.exception("Tool '%s' could not be run", call.name)
            message = f"The tool '{call.name}' could not be run: {type(exc).__name__}: {exc}"
            emit(
                {
                    "event": "tool_done",
                    "name": call.name,
                    "ok": False,
                    "error": message,
                    "summary": message,
                }
            )
            return ToolResult.failure(message, message)

        emit(
            {
                "event": "tool_done",
                "name": call.name,
                "ok": result.ok,
                "error": result.error,
                # What the call found, in the tool's own words.  It goes
                # behind the tool's name in the panel: the reader can see
                # what was looked up without reading the answer.
                "summary": result.summary or result.error,
                # The documents it looked at, so that the answer can link
                # to them.
                "documents": touched_documents(call, result),
            }
        )
        return result

    def _explain_failure(
        self,
        spec: ToolSpec,
        arguments: dict[str, Any],
        result: ToolResult,
        authority: Authority,
    ) -> ToolResult:
        """Turn a failure with no reason into a fact the model can act on.

        This is the single most valuable thing the app does for the
        assistant's competence.  The tools report a failure with the reason
        when they have one — "Unknown field(s) for DocType 'Item Price'" —
        and *without* one when the framework's own permission engine refused
        the read.  An empty reason is the most confusing thing an assistant
        can be handed: it cannot tell "you may not read this" from "this
        does not exist", so it tries the call again, and again, and burns
        its steps on a question that was never going to work.

        So the reason is supplied here, from the same permission data the
        framework used: who *can* read this, and therefore what the reader
        needs to know.  The tool is unchanged; the assistant is simply told
        the truth.
        """
        reason = (result.error or "").strip()
        if not reason:
            return result

        # The tools end their message with the reason, after a colon.  An
        # empty tail means there was no reason to give.
        head, separator, tail = reason.rpartition(":")
        if not separator or tail.strip():
            return result

        doctype = arguments.get("doctype")
        if not isinstance(doctype, str) or not doctype.strip():
            return result

        roles = authority.roles_for(doctype.strip(), "read")
        if not roles:
            return result

        listed = ", ".join(roles)
        explanation = (
            f"{head.strip()}: this account may not read '{doctype.strip()}'. "
            f"Reading that DocType is done by these roles: {listed}. "
            f"Do not try this call again; say what is needed instead."
        )

        return ToolResult(
            ok=result.ok,
            content=explanation,
            data=result.data,
            error=explanation,
            denied=result.denied,
        )

    # -- when the budget runs out ----------------------------------------

    def _diagnose(self, tool_calls: list[dict[str, Any]], rounds: int) -> dict[str, Any]:
        """Describe what the turn was doing when it ran out of rounds."""
        names = [call["name"] for call in tool_calls]
        counter = Counter(names)
        most_repeated = counter.most_common(1)[0] if counter else ("", 0)
        last_error = ""
        for call in reversed(tool_calls):
            if call.get("error"):
                last_error = str(call["error"])[:300]
                break
        return {
            "rounds": rounds,
            "tool_calls": len(tool_calls),
            "most_repeated_tool": most_repeated[0],
            "most_repeated_count": most_repeated[1],
            "last_error": last_error,
        }

    def _answer_from_findings(
        self,
        config: LLMConfig,
        messages: list[Message],
        tools: list[ToolSpec],
        diagnosis: dict[str, Any],
    ) -> tuple[str, bool]:
        """Close a turn that ran out of steps, with the model's own words.

        The step budget is a fact about one question, not a failure of the
        assistant, and the answer says so by *reporting what was found*:
        the question's data, and which part of it is still open.

        The second value says whether the closing answer was itself cut
        off at the token ceiling — it was written under the same ceiling
        as every other answer, and a closing that stops mid-sentence is
        a closing that says nothing useful.
        """
        instruction = (
            "You have used every step one question is allowed to take, so you must "
            "answer now. Answer with what you have already found. If part of the "
            "question is still open, say which part and what you would need in "
            "order to answer it. State the step limit as a fact about the question, "
            "not as a limitation of your own, and do not apologise."
        )
        closing = [*messages, Message(role="user", content=instruction)]

        try:
            completion = self._complete(config, closing, tools, _noop_emit, False)
            answer = (completion.message.content or "").strip()
            if answer:
                return answer, completion.truncated
        except Exception:
            logger.exception("Could not close a capped turn with a summary")

        return self._capped_reply(diagnosis), False

    def _capped_reply(self, diagnosis: dict[str, Any]) -> str:
        """The answer for a turn that ran out of steps *and* could not be summarised.

        Facts, not an apology: what the turn was doing, what failed last, and
        that the steps are the number one question is allowed to take.
        """
        parts = []
        if diagnosis.get("most_repeated_tool"):
            parts.append(
                f"The tool used most was '{diagnosis['most_repeated_tool']}' "
                f"({diagnosis['most_repeated_count']} times)."
            )
        if diagnosis.get("last_error"):
            parts.append(f"The last step that failed was: {diagnosis['last_error']}")
        parts.append(
            "One question is allowed this many steps, and this one used them all."
        )
        return " ".join(parts)

    # -- the audit row ----------------------------------------------------

    def _log(
        self,
        conversation: str,
        user: str,
        provider: str,
        model: str,
        rounds: int,
        tool_calls: list[dict[str, Any]],
        usage: Usage | None,
        started: float,
        status: str,
        error_class: str,
        error_message: str,
        price_per_million: float = 0.0,
    ) -> None:
        """Write the turn's audit row.

        It records what was *done* — which tools ran, whether they worked,
        and what a write created — and the counts, timings and error classes.

        It does not record the question or the answer.  The audit trail
        answers "what did the assistant do and what did it cost"; the
        conversation answers "what was said".  Keeping the two apart is what
        makes it safe to show the log to a manager.

        The one exception is the *name* of a document a write created, which
        is an identifier rather than a statement, and is what a manager
        needs in order to find out what the assistant did.
        """
        try:
            doc = frappe.new_doc("Albanna Chat Log")
            doc.user = user
            doc.conversation = conversation
            doc.provider = provider
            doc.model = model
            doc.status = status
            doc.rounds = rounds
            doc.tool_calls = len(tool_calls)
            if tool_calls:
                doc.tools = json.dumps(tool_calls, default=str)
            doc.duration_ms = int((time.monotonic() - started) * 1000)
            if usage is not None:
                doc.input_tokens = usage.input_tokens
                doc.output_tokens = usage.output_tokens
                # The cost in the *site's* currency: the tokens the turn
                # used, priced with the price the operator set.  The
                # provider's own number is in the provider's own currency
                # — a dollar in a riyals ledger — so it is recorded
                # beside it, in its own column, and never mixed with it.
                doc.cost = cost_of_turn(
                    usage.input_tokens,
                    usage.output_tokens,
                    price_per_million,
                )
                doc.provider_cost = usage.cost
                doc.estimated = 1 if usage.estimated else 0
            if error_class:
                doc.error_class = error_class
            if error_message:
                doc.error_message = error_message[:500]
            doc.insert(ignore_permissions=True)
        except Exception:
            logger.exception("Could not write the chat log row")


def touched_documents(call, result: ToolResult) -> list[dict[str, str]]:
    """The documents a tool call looked at.

    They are what the panel turns into links, so that an answer is a
    doorway into the Desk and not only a description of it.

    The names are the ones the tool was *given* — the document it read,
    the documents a listing returned, the document it created — so there
    is no guessing about which words in the answer are document names.
    A name the assistant never opened is not a link, and a name that is
    not a document is never mistaken for one.
    """
    doctype = str(call.arguments.get("doctype") or "").strip()
    if not doctype:
        return []

    documents: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(name) -> None:
        name = str(name or "").strip()
        if name and name not in seen:
            seen.add(name)
            documents.append({"doctype": doctype, "name": name})

    if call.name == "get_doc":
        add(call.arguments.get("name"))
    elif call.name == "list_docs":
        for row in result.data or []:
            if isinstance(row, dict):
                add(row.get("name"))
    elif call.name == "create_doc":
        add(_created_name(result))

    return documents


def _created_name(result: ToolResult) -> str:
    """The name of the document a tool created, if it created one.

    The write tools return the created document's name in their envelope.
    Recording it is what turns the audit row from "the assistant called a
    tool" into "the assistant created ACC-SINV-2026-00008".
    """
    data = result.data
    if not isinstance(data, dict):
        return ""
    name = data.get("name")
    return str(name) if name else ""


def _write_preview(name: str, arguments: dict) -> str:
    """A compact, human-readable summary of a pending write.

    The reader approves a *change*, not a JSON blob, so the confirmation
    dialog says what will happen in the reader's words: "Create Customer:
    Acme (type Company)" rather than the raw arguments.
    """
    arguments = arguments or {}
    doctype = str(arguments.get("doctype") or "").strip()
    data = arguments.get("data") or {}
    if not isinstance(data, dict):
        data = {}

    if name == "create_doc":
        title = _preview_title(doctype, data)
        if title:
            return f"Create {doctype}: {title}"
        return f"Create a {doctype}"

    if name == "update_doc":
        docname = str(arguments.get("name") or "").strip()
        fields = ", ".join(f"{key} = {value}" for key, value in list(data.items())[:6])
        if docname and fields:
            return f"Change {doctype} {docname}: {fields}"
        if docname:
            return f"Change {doctype} {docname}"
        return f"Change a {doctype}"

    return f"{name}({doctype})"


def _preview_title(doctype: str, data: dict) -> str:
    """The most identifying value in a new document's data."""
    for key in ("customer_name", "supplier_name", "full_name", "item_name", "subject", "title", "name"):
        value = data.get(key)
        if value:
            return str(value)
    # Fall back to the first non-empty value.
    for value in data.values():
        if isinstance(value, (str, int, float)) and str(value).strip():
            return str(value)
    return ""
