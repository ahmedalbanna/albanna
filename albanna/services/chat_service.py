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
from albanna.core.tools import TOOL_MANIFEST, ToolRegistry, ToolSpec, validate_arguments
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
    diagnosis: dict[str, Any] = field(default_factory=dict)


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

        registry = self._tool_registry(settings)
        authority = Authority(registry, principal, FrappePermissionChecker())
        visible = authority.visible()

        conversation = self._resolve_conversation(request, principal.user, question)

        history = load_messages(conversation, settings.history_limit)
        company = default_company()
        context = PromptContext(
            site=site,
            company=company,
            currency=default_currency(company),
            user=principal.user,
            creatable=tuple(creatable_doctypes(principal.user)),
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
                    reply = "I could not produce an answer to that."
                append_messages(
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
                    "ok",
                    "",
                    "",
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
                    "error": result.error,
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
        reply = self._answer_from_findings(llm_config, messages, visible, diagnosis)

        append_messages(
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
            "capped",
            "round_limit",
            f"reached {settings.max_tool_rounds} rounds",
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
            diagnosis=diagnosis,
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
        from albanna.services.conversation_service import assert_owns, ensure_conversation

        if not request.conversation_id:
            return ensure_conversation(user, request.page, title=question[:120])

        assert_owns(request.conversation_id, user)
        return request.conversation_id

    def _tool_registry(self, settings) -> ToolRegistry:
        """The tool set this turn may use.

        Two switches, applied in order: the operator's list of disabled
        tools, and the site's write switch.  A write tool that is off is not
        in the *visible* set, so the model is never told it exists — there
        is nothing for it to ask for, and a call to it by name is refused.
        """
        registry = TOOL_MANIFEST.without(settings.disabled_tools)
        if not settings.allow_writes:
            registry = registry.without_mutating()
        return registry

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
            emit({"event": "tool_done", "name": call.name, "ok": False, "error": decision.reason})
            return ToolResult.refusal(decision.reason, decision.code)

        invalid = validate_arguments(spec, call.arguments)
        if invalid:
            emit({"event": "tool_done", "name": call.name, "ok": False, "error": invalid})
            return ToolResult.failure(invalid, invalid)

        emit({"event": "tool_start", "name": call.name, "arguments": call.arguments})

        context = ToolContext(principal=principal, site=site)
        try:
            result = self._backend.call(spec, call.arguments, context)
            result = self._explain_failure(spec, call.arguments, result, authority)
        except Exception as exc:  # noqa: BLE001 - a tool must not kill the turn
            logger.exception("Tool '%s' could not be run", call.name)
            message = f"The tool '{call.name}' could not be run: {type(exc).__name__}: {exc}"
            emit({"event": "tool_done", "name": call.name, "ok": False, "error": message})
            return ToolResult.failure(message, message)

        emit(
            {
                "event": "tool_done",
                "name": call.name,
                "ok": result.ok,
                "error": result.error,
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
    ) -> str:
        """Close a turn that ran out of steps, with the model's own words.

        The step budget is a fact about one question, not a failure of the
        assistant, and the answer says so by *reporting what was found*:
        the question's data, and which part of it is still open.
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
                return answer
        except Exception:
            logger.exception("Could not close a capped turn with a summary")

        return self._capped_reply(diagnosis)

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
                doc.cost = usage.cost
                doc.estimated = 1 if usage.estimated else 0
            if error_class:
                doc.error_class = error_class
            if error_message:
                doc.error_message = error_message[:500]
            doc.insert(ignore_permissions=True)
        except Exception:
            logger.exception("Could not write the chat log row")


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
