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
from albanna.core.errors import (
    AllProvidersFailed,
    ProviderBudgetExceeded,
    ProviderError,
    reader_message,
)
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
from albanna.core.tools import TOOL_MANIFEST, ToolSpec, validate_arguments
from albanna.core.undo import is_undoable
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


def _reader_error(exc: BaseException) -> str:
    """The sentence the reader is shown when a turn fails.

    The sentence is chosen by the kind of failure and is then translated
    into the reader's language — the reader's language is the interface's
    language, and this is the layer that knows it.
    """
    message = reader_message(exc)
    try:
        import frappe

        return frappe._(message)
    except Exception:
        return message


def _without_secrets(text: str) -> str:
    """The text with the site's own keys taken out of it.

    A provider's refusal often quotes the key it refused — "Incorrect API
    key provided: sk-…" — and the chat log is read by operators,
    exported, and copied off the host.  So the log is written with the
    keys in it only if nobody thought of this, and the operator who
    reads the log is the last person who should have to.
    """
    from albanna.core.secrets import redact_secret

    body = str(text or "")
    try:
        from albanna.services.settings_service import get_settings

        settings = get_settings()
    except Exception:
        return body

    for config in (settings.provider, settings.fallback):
        if config is None:
            continue
        body = redact_secret(body, config.api_key)

    return body


@dataclass
class TurnRequest:
    """What the user asked for."""

    question: str
    conversation_id: str = ""
    page: str = ""
    page_context: str = ""
    stream: bool = False
    image: str = ""


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
    #: The cost of this turn in the site's currency, priced with the
    #: operator's price per million tokens.  Carried on the outcome so the
    #: browser can show it without a second request.
    cost: float = 0.0
    error: str = ""
    capped: bool = False
    #: True when the provider cut the answer off at the token ceiling.
    #:
    #: The answer is not wrong — it is unfinished, and the reader is told
    #: so, because an answer that looks complete and is not is worse
    #: than one that says it was cut.
    truncated: bool = False
    #: True when an image was sent but no provider could see it.
    image_dropped: bool = False
    diagnosis: dict[str, Any] = field(default_factory=dict)
    #: The rows this turn wrote, as ``(name, role)`` pairs.
    #:
    #: The browser is told what was written, because a row that can be
    #: named is a row that can be addressed later: the reader can remove
    #: this turn, and the browser has to know which row to ask for.  The
    #: names are the rows' own, so they do not shift when the
    #: conversation grows.
    written: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class TurnAudit:
    """What the audit row needs from a turn.

    A turn reaches :meth:`ChatService._log` at three endings — a clean
    answer, a failed provider chain, a round budget spent — and each
    passed eleven positional arguments before this existed.  Eleven
    positional arguments, spelled the same three ways, is an audit row
    waiting for its columns to swap.

    The record carries them by name instead.  Adding a column to the
    audit then touches exactly two places: this class and the writer —
    no call site changes, and none can silently misplace a field.
    """

    conversation: str
    user: str
    #: Which provider/model produced the turn's last word.  Empty when
    #: none of the chain answered, which is itself a fact worth logging.
    provider: str = ""
    model: str = ""
    rounds: int = 0
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: Usage | None = None
    #: When the turn began, by the clock :func:`time.monotonic` keeps —
    #: the duration is computed against this, not stored.
    started: float = 0.0
    status: str = "ok"
    error_class: str = ""
    error_message: str = ""
    price_per_million: float = 0.0
    had_image: bool = False
    #: Per-round durations in milliseconds, one per model call in the turn.
    #: Carried inside the audit row's ``tools`` field, not a column, so
    #: production avoids a DDL on ``tabAlbanna Chat Log``.
    round_ms: list[int] = field(default_factory=list)

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
        "image_dropped": outcome.image_dropped,
        "error": outcome.error,
        "dry_run": any(
            isinstance(tc, dict) and tc.get("dry_run") for tc in (outcome.tool_calls or [])
        ),
        # What the turn cost, so the reader can see it without a second
        # request.  Tokens and price both come from the turn; the browser
        # shows the cost in the site's currency.
        "input_tokens": (outcome.usage.input_tokens if outcome.usage else 0),
        "output_tokens": (outcome.usage.output_tokens if outcome.usage else 0),
        "cost": outcome.cost,
        # The rows the turn wrote, so that the browser can address this
        # turn later — a row that can be named is a row that can be
        # removed.
        "written": [{"name": name, "role": role} for name, role in outcome.written],
    }


class ChatService:
    """Runs one turn of the chat."""

    def __init__(self, backend=None) -> None:
        self._backend = backend or ErpnextBackend()
        # The audit row written at turn start, if any.  Read with getattr
        # everywhere, so a _log call that arrives without a run (the tests
        # call it directly) still works.
        self._audit_name: str | None = None

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

        image_dropped = bool(request.image) and not (
            getattr(settings.provider, "supports_vision", False)
            or (settings.fallback is not None and getattr(settings.fallback, "supports_vision", False))
        )

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

        # An image attached to the question is stored as a Frappe File so
        # that the assistant can reference it by URL — for example, to set
        # it as a document's image field.  The bytes travel with the turn
        # only; what is stored is the file, not the chat.
        image_url = ""
        if request.image:
            image_url = self._store_image(request.image, principal.user)
            is_image = str(request.image).startswith("data:image/")
            kind = "image" if is_image else "file"
            if image_url:
                extra = (
                    f"\n\nA {kind} was attached to this question and stored as a "
                    f"Frappe File. Its URL is: {image_url}. If the user asks to "
                    f"set it as a document's field, use this URL as the value."
                )
            else:
                extra = (
                    f"\n\nA {kind} was attached to this question but could not be "
                    "stored as a file. Do not attempt to use it."
                )
            request = TurnRequest(
                question=request.question,
                conversation_id=request.conversation_id,
                page=request.page,
                page_context=(request.page_context or "") + extra,
                stream=request.stream,
                image=request.image,
            )

        history = load_messages(conversation, settings.history_limit)

        # The audit row is written *before* the turn can die, so that a
        # turn that never finishes still leaves a record.  It starts as
        # 'running' and is updated in place at the turn's end.  If the
        # worker dies between, it stays 'running' and the reaper marks it
        # 'interrupted' later — a ghost row is truth, not a leak.
        try:
            running = frappe.new_doc("Albanna Chat Log")
            running.user = principal.user
            running.conversation = conversation
            running.status = "running"
            running.rounds = 0
            running.tool_calls = 0
            running.had_image = 1 if bool(request.image) else 0
            running.insert(ignore_permissions=True)
            self._audit_name = running.name
            frappe.db.commit()
        except Exception:
            logger.exception("Could not write the running audit row")

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
        messages.append(user(question, image=request.image or None))

        tool_calls_made: list[dict[str, Any]] = []
        rounds = 0
        # Per-round durations, one per model call, for the audit row.
        round_durations: list[int] = []
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
            round_start = time.monotonic()
            # A code, not a sentence.  The turn runs in a worker, and a
            # worker has no user's language to render a label in — the
            # interface's language is the *reader's*, and only the reader
            # has it.  So the server says what is happening and the client
            # says it in the reader's language.
            emit({"event": "status", "round": rounds, "code": "thinking"})

            try:
                completion = self._complete(llm_config, messages, visible, emit, request.stream)
            except AllProvidersFailed as exc:
                round_durations.append(int((time.monotonic() - round_start) * 1000))
                self._log(
                    TurnAudit(
                        conversation=conversation,
                        user=principal.user,
                        provider=provider_name,
                        model=model_name,
                        rounds=rounds,
                        tool_calls=tool_calls_made,
                        usage=usage,
                        started=started,
                        status="error",
                        error_class="provider_error",
                        error_message=str(exc),
                        price_per_million=settings.price_per_million,
                        had_image=bool(request.image),
                        round_ms=round_durations,
                    )
                )
                return TurnOutcome(
                    ok=False,
                    error=_reader_error(exc),
                    conversation_id=conversation,
                    rounds=rounds,
                    tool_calls=tool_calls_made,
                    image_dropped=image_dropped,
                )

            round_durations.append(int((time.monotonic() - round_start) * 1000))

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
                        {"role": "user", "content": question, "round_no": 0, "image_url": image_url},
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
                    TurnAudit(
                        conversation=conversation,
                        user=principal.user,
                        provider=completion.provider,
                        model=completion.model,
                        rounds=rounds,
                        tool_calls=tool_calls_made,
                        usage=usage,
                        started=started,
                        status="truncated" if completion.truncated else "ok",
                        price_per_million=settings.price_per_million,
                        had_image=bool(request.image),
                        round_ms=round_durations,
                    )
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
                    image_dropped=image_dropped,
                    written=written,
                    cost=(
                        cost_of_turn(
                            usage.input_tokens,
                            usage.output_tokens,
                            settings.price_per_million,
                        )
                        if usage is not None
                        else 0.0
                    ),
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
                tool_calls_made.append(tool_entry(call, result))
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
                {"role": "user", "content": question, "round_no": 0, "image_url": image_url},
                {"role": "assistant", "content": reply, "round_no": rounds},
            ],
        )
        self._log(
            TurnAudit(
                conversation=conversation,
                user=principal.user,
                provider=provider_name,
                model=model_name,
                rounds=rounds,
                tool_calls=tool_calls_made,
                usage=usage,
                started=started,
                status="truncated" if truncated else "capped",
                error_class="round_limit",
                error_message=f"reached {settings.max_tool_rounds} rounds",
                price_per_million=settings.price_per_million,
                round_ms=round_durations,
            )
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
            image_dropped=image_dropped,
            diagnosis=diagnosis,
            written=written,
            cost=(
                cost_of_turn(
                    usage.input_tokens,
                    usage.output_tokens,
                    settings.price_per_million,
                )
                if usage is not None
                else 0.0
            ),
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

    def _ensure_albanna_folder(self) -> str:
        """Ensure the 'Home/Albanna' folder exists and return its name."""
        folder_name = "Home/Albanna"
        if frappe.db.exists("File", folder_name):
            return folder_name
        try:
            folder = frappe.new_doc("File")
            folder.file_name = "Albanna"
            folder.is_folder = 1
            folder.folder = "Home"
            folder.insert(ignore_permissions=True)
            return folder.name
        except Exception:
            if frappe.db.exists("File", "Home/Attachments"):
                return "Home/Attachments"
            return "Home"

    #: The file types an attachment may carry.  Anything else is rejected
    #: rather than stored with a guessed extension — a broad accept would
    #: happily file away ``image/svg+xml`` (which executes as HTML) or
    #: ``text/html`` under a ``.bin`` name the chromium postfix would not.
    ATTACHABLE = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "application/pdf": ".pdf",
    }

    def _store_image(self, image: str, user: str) -> str:
        """Store an attached file as a Frappe File and return its URL."""
        if not image:
            return ""
        try:
            import base64

            header, payload = (image.split(",", 1) + [""])[:2]
            raw = base64.b64decode(payload, validate=True)
            mime = (
                header.split(";")[0].split(":")[-1].strip()
                if header.startswith("data:")
                else ""
            )
            ext = self.ATTACHABLE.get(mime)
            if ext is None:
                logger.warning(
                    "Rejected an attached file of unsupported type %r", mime or "(none)"
                )
                return ""
            filename = f"albanna-{frappe.generate_hash(length=8)}{ext}"
            folder = self._ensure_albanna_folder()
            saved = frappe.utils.file_manager.save_file(
                filename, raw, "User", user, is_private=1, folder=folder
            )
            return str(getattr(saved, "file_url", "") or "")
        except Exception:
            logger.exception("Could not store an attached file")
            return ""

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
            emit_tool_done(emit, call, ok=False, error=decision.reason, summary=decision.reason)
            return ToolResult.refusal(decision.reason, decision.code)

        invalid = validate_arguments(spec, call.arguments)
        if invalid:
            emit_tool_done(emit, call, ok=False, error=invalid, summary=invalid)
            return ToolResult.failure(invalid, invalid)

        # Hard confirmation gate: when the operator has asked for it, a
        # write does not run until the reader has approved it.  The turn
        # pauses here and waits for the browser's answer; a refusal or a
        # timeout is reported to the model as a denial, so it can say so.
        from albanna.services.settings_service import get_settings
        from albanna.user_policy import confirm_writes_for

        # Memoised per request, so this is the same object `run` read:
        # the wait the operator configured, not a second reading of it.
        settings = get_settings()
        gated = spec.mutating and confirm_writes_for(principal.user)

        if gated:
            request_id, refusal = self._ask_for_approval(call, principal, emit, settings)
            if refusal is not None:
                return refusal
        else:
            request_id = ""

        emit({"event": "tool_start", "name": call.name, "arguments": call.arguments})

        context = ToolContext(principal=principal, site=site)
        try:
            result = self._backend.call(spec, call.arguments, context)
            result = self._explain_failure(spec, call.arguments, result, authority)
            if gated:
                # The result is frozen, so the flag arrives as a copy, not
                # an assignment — a write that was approved after the wait
                # is recorded as approved.
                result = replace(result, approved=True)

            if settings.dry_run and spec.mutating and result.ok:
                # Nothing is saved: the write ran its validation and
                # reported what it would do, then the transaction was
                # rolled back.  The reader is told, so a preview is never
                # mistaken for a change.
                try:
                    frappe.db.rollback()
                except Exception:
                    pass
                result = replace(result, dry_run=True, content=result.content + "\n(dry run — not saved)")
            elif spec.mutating and result.ok:
                # The audit row records the write in the same transaction
                # as the change it made, so the two cannot disagree: a
                # row that says a change was approved and a database
                # that says it was never written are not both possible.
                #
                # A write that ran is committed now, not at the end of the
                # turn: the turn's own writes survive a turn that dies
                # afterwards, and the audit row is not the only thing that
                # does.  The user asked for the document; the assistant's
                # ability to describe it is a separate concern.
                self._record_write(call, result, request_id)
                try:
                    frappe.db.commit()
                except Exception:
                    logger.exception("Could not commit a successful write")
        except Exception as exc:  # noqa: BLE001 - a tool must not kill the turn
            logger.exception("Tool '%s' could not be run", call.name)
            message = f"The tool '{call.name}' could not be run: {type(exc).__name__}: {exc}"
            emit_tool_done(emit, call, ok=False, error=message, summary=message)
            return ToolResult.failure(message, message)

        emit_tool_done(
            emit,
            call,
            ok=result.ok,
            error=result.error,
            # What the call found, in the tool's own words.  It goes
            # behind the tool's name in the panel: the reader can see
            # what was looked up without reading the answer.
            summary=result.summary or result.error,
            # The documents it looked at, so that the answer can link
            # to them.
            documents=touched_documents(call, result),
            # Whether the turn can be taken back.  The rule is the undo's
            # own rule, so the panel and the transcript cannot disagree
            # about a turn that is offered and then does nothing.
            undoable=_is_undoable_call(call, result),
        )
        return result

    def _ask_for_approval(
        self,
        call: ToolCall,
        principal,
        emit: Emit,
        settings,
    ) -> tuple[str, ToolResult | None]:
        """Ask the reader to approve a write, and say whether it may run.

        Returns the request id and the refusal to report.  The refusal
        is ``None`` when the write may run.
        """
        import uuid

        from albanna.services.approval import (
            CHANGED_MESSAGE,
            await_decision,
            denial_message,
            record_pending,
            still_unchanged,
            wait_seconds,
            write_diff,
            write_preview,
            write_target,
        )

        request_id = uuid.uuid4().hex
        # One deadline, told to both sides.  The worker waits this long;
        # the browser counts down from the same number, sent with the
        # event.  A countdown computed on the browser's own clock against
        # a different constant is a countdown that lies — and the reader
        # decides how long to take by it.
        seconds = wait_seconds(settings.confirm_timeout)

        # The approval is recorded in the turn's own audit row before the
        # reader is asked, and committed there.  The row outlives the
        # turn; the cache record does not.  So the row is what can still
        # answer *did the change I confirmed happen?* when the worker
        # dies between the approval and the write — which is exactly
        # when the reader cannot be told anything else.
        self._record_approval(request_id, call)

        # The pending write is recorded before the reader is asked,
        # because it is what the answer is recorded against: the endpoint
        # that takes the decision refuses one that names no write, and
        # the second decision on the same write is refused.  The record
        # outlives the wait it answers.
        record_pending(
            request_id,
            principal.user,
            call.name,
            call.arguments,
            ttl=seconds + 60,
            row=getattr(self, "_audit_name", "") or "",
        )

        # The document the write is about, and the stamp it had when the
        # reader was asked.  It is checked again once they have answered:
        # a document that has moved in the meantime is not the document
        # they were asked about.
        target = write_target(call.name, call.arguments)

        emit(
            {
                "event": "confirm",
                "request_id": request_id,
                "name": call.name,
                "arguments": call.arguments,
                "preview": write_preview(call.name, call.arguments),
                "diff": write_diff(call.name, call.arguments),
                "window_seconds": seconds,
            }
        )

        decision = await_decision(request_id, principal.user, timeout=seconds)

        if decision != "approve":
            message = denial_message(decision)
            emit_tool_done(emit, call, ok=False, error=message, summary=message)
            return request_id, ToolResult(
                ok=False, content=message, error=message, denied=True, approved=False
            )

        if not still_unchanged(target):
            emit_tool_done(emit, call, ok=False, error=CHANGED_MESSAGE, summary=CHANGED_MESSAGE)
            return request_id, ToolResult(
                ok=False,
                content=CHANGED_MESSAGE,
                error=CHANGED_MESSAGE,
                denied=True,
                approved=False,
            )

        return request_id, None

    def _record_approval(self, request_id: str, call: ToolCall) -> None:
        """Write the approval into the turn's audit row, and commit it.

        The row is the record that outlives the turn, so it is where the
        approval belongs: a reader's *yes* that lives only in the cache
        is a yes that disappears when the worker is killed, and the panel
        then says the turn did not finish without saying that a change
        was confirmed and never made.

        Only the document's identity goes in — its type and, when the
        reader may read it, its name.  The values the model wanted to
        write are not recorded: the ledger is read by operators, and a
        value the reader alone may see has no business there.
        """
        row = getattr(self, "_audit_name", "") or ""
        if not row:
            return

        from albanna.services.approval import write_target
        from albanna.services.audit_rows import merge_payload

        arguments = call.arguments or {}
        doctype = str(arguments.get("doctype") or "").strip()

        # The card names a document the reader may read and does not
        # name one they may not, and the panel's message about an
        # approval must not name it either.
        target = write_target(call.name, arguments)
        name = str(target.get("name") or "").strip()
        if not name and call.name != "update_doc":
            # The tools that change a document carry its name in their
            # arguments, and the ledger already records the names they
            # touched.
            name = str(arguments.get("name") or "").strip()

        merge_payload(
            row,
            {
                "approvals": [
                    {
                        "request_id": request_id,
                        "tool": call.name,
                        "doctype": doctype,
                        "name": name,
                    }
                ]
            },
        )

        try:
            frappe.db.commit()
        except Exception:
            logger.exception("Could not commit the approval to the chat log row")

    def _record_write(self, call: ToolCall, result: ToolResult, request_id: str) -> None:
        """Write the call into the turn's audit row, and mark its approval.

        The record is written **before** the transaction that carries the
        change is committed, so the two commit together: a row that says
        "approved" and a database that says "written" can never disagree.
        A turn that dies between the write and the end of its answer
        still says what it changed, and an approval that the write
        answered is marked as answered.
        """
        row = getattr(self, "_audit_name", "") or ""
        if not row:
            return

        from albanna.services.audit_rows import merge_payload

        changes: dict[str, Any] = {"calls": [tool_entry(call, result)]}
        if request_id:
            changes["approvals"] = [{"request_id": request_id, "ran": True}]

        merge_payload(row, changes)

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

    def _log(self, audit: TurnAudit) -> None:
        """Write or update the turn's audit row.

        The row may already exist as a 'running' row written at turn start;
        in that case it is updated in place rather than duplicated.  A
        direct caller (the tests call this method on its own) finds no
        stored name and gets a fresh row, so the behaviour they relied on
        is unchanged.

        The per-round timings travel inside the existing ``tools`` field,
        as ``{"calls": [...], "round_ms": [...]}``, so no new column is
        needed and production avoids a DDL on ``tabAlbanna Chat Log``.
        """
        try:
            name = getattr(self, "_audit_name", None)
            if name and frappe.db.exists("Albanna Chat Log", name):
                doc = frappe.get_doc("Albanna Chat Log", name)
                is_update = True
            else:
                doc = frappe.new_doc("Albanna Chat Log")
                is_update = False

            doc.user = audit.user
            doc.conversation = audit.conversation
            doc.provider = audit.provider
            doc.model = audit.model
            doc.status = audit.status
            doc.rounds = audit.rounds
            doc.tool_calls = len(audit.tool_calls)
            payload: dict[str, Any] = {"calls": audit.tool_calls or []}
            if getattr(audit, "round_ms", None):
                payload["round_ms"] = list(audit.round_ms)
            # The approvals were written while the turn ran — the reader
            # was asked, and answered — and the turn's own payload must
            # not drop them.  They are the record of what was confirmed,
            # and a row that loses them is a row that cannot say whether
            # the change happened.
            from albanna.services.audit_rows import approvals_of

            approvals = approvals_of({"tools": doc.tools})
            if approvals:
                payload["approvals"] = approvals
            if payload.get("calls") or payload.get("round_ms") or payload.get("approvals"):
                doc.tools = json.dumps(payload, default=str)
            doc.duration_ms = int((time.monotonic() - audit.started) * 1000) if audit.started else 0
            if audit.usage is not None:
                usage = audit.usage
                doc.input_tokens = usage.input_tokens
                doc.output_tokens = usage.output_tokens
                doc.cost = cost_of_turn(
                    usage.input_tokens,
                    usage.output_tokens,
                    audit.price_per_million,
                )
                doc.provider_cost = usage.cost
                doc.estimated = 1 if usage.estimated else 0
            if audit.error_class:
                doc.error_class = audit.error_class
            if audit.error_message:
                doc.error_message = _without_secrets(audit.error_message)[:500]
            doc.had_image = 1 if audit.had_image else 0

            if is_update:
                doc.save(ignore_permissions=True)
            else:
                doc.insert(ignore_permissions=True)
                self._audit_name = doc.name

            try:
                frappe.db.commit()
            except Exception:
                logger.exception("Could not commit the chat log row")
        except Exception:
            logger.exception("Could not write the chat log row")


def tool_done_event(
    name: str,
    ok: bool,
    error: str = "",
    summary: str = "",
    documents=None,
    undoable: bool = False,
) -> dict[str, Any]:
    """The panel's record of one tool call's end.

    **One place**, because the shape is read in three kinds of place — a
    refusal, a failure, a finish — and every one of them sent a slightly
    different set of keys before this existed.  A key added here reaches
    all of them; a key forgotten elsewhere is silently absent.

    Args:
        name: the tool's name, as the model called it.
        ok: whether it ran to a result (a refusal never did).
        error: what went wrong, empty when nothing did.
        summary: what the call found, in the tool's own words.
        documents: the documents the call touched, when known.
        undoable: whether this call may be taken back, when it may.
    """
    event: dict[str, Any] = {"event": "tool_done", "name": name, "ok": ok}
    if error:
        event["error"] = error
    if summary:
        event["summary"] = summary
    if documents is not None:
        event["documents"] = documents
    if undoable:
        event["undoable"] = True
    return event


def emit_tool_done(
    emit: Emit,
    call: ToolCall,
    ok: bool,
    error: str = "",
    summary: str = "",
    documents=None,
    undoable: bool = False,
) -> None:
    """Say a tool call is over, through whatever ``emit`` carries events."""
    emit(
        tool_done_event(
            call.name,
            ok,
            error=error,
            summary=summary,
            documents=documents,
            undoable=undoable,
        )
    )


def undo_entry(call: ToolCall, result: ToolResult) -> dict[str, Any] | None:
    """The undo this call carries, if it carries one.

    **One place**, because two readers have to agree: the transcript,
    which stores the entry and later spends it, and the live panel, which
    has to say whether the turn can be taken back *before* the turn is
    stored.  Two builders would drift, and the drift would show as a
    button that is offered and then does nothing.

    The entry says what it wants; :func:`albanna.core.undo.is_undoable`
    says whether the tool that made the call may have it.
    """
    created = _created_name(call, result)
    if created:
        return {
            "action": "delete",
            "doctype": str(call.arguments.get("doctype") or "").strip(),
            "name": created,
        }

    data = getattr(result, "data", None) or {}
    if isinstance(data, dict) and data.get("before"):
        return {
            "action": "update",
            "doctype": str(data.get("doctype") or call.arguments.get("doctype") or "").strip(),
            "name": str(data.get("name") or call.arguments.get("name") or "").strip(),
            "data": data.get("before"),
        }

    # A submitted document is taken back by cancelling it.
    if call.name == "submit_doc" and result.ok:
        doctype = str(call.arguments.get("doctype") or "").strip()
        docname = str(call.arguments.get("name") or "").strip()
        if doctype and docname:
            return {"action": "cancel", "doctype": doctype, "name": docname}

    return None


def _is_undoable_call(call: ToolCall, result: ToolResult) -> bool:
    """Whether this call may be taken back.

    The undo's own rule, asked about the call as it is running — so the
    live panel and the stored transcript cannot disagree about whether a
    turn can be undone.
    """
    undo = undo_entry(call, result)
    if not undo:
        return False
    return is_undoable({"name": call.name, "undo": undo})


def _is_write(call: ToolCall) -> bool:
    """Whether this call could change the site.

    The manifest is the answer: a tool is a write tool because it is in
    the WRITE tier, and the tier is what the authority layer enforces
    the approval on.  So the two cannot disagree about a call that
    changed something.
    """
    spec = TOOL_MANIFEST.get(call.name)
    return bool(spec and spec.mutating)


def tool_entry(call: ToolCall, result: ToolResult) -> dict[str, Any]:
    """What the transcript and the audit row both keep about one call.

    **One place**, because the *executed* calls are recorded in two
    shapes — the row under the answer in the transcript, and the audit
    row in the log — and the two must never disagree about what
    happened.  A field added here is recorded in both; renamed here, it
    is renamed in both.
    """
    entry: dict[str, Any] = {
        "name": call.name,
        "ok": result.ok,
        "denied": result.denied,
        "approved": result.approved,
        "error": result.error,
        # Whether the call could change the site.  The manifest says so,
        # and the manifest is the one place that knows: a tool writes
        # because it is in the WRITE tier.  Asking the name to guess
        # would be a second answer to the same question, and the two
        # answers would drift — a tool renamed on one side and not on
        # the other would be recorded as a read when it was a write.
        "write": bool(_is_write(call)),
        # What the call found, kept with the call so that a
        # conversation reopened tomorrow still says what was
        # looked up, and not only which function was called.
        "summary": result.summary or result.error,
        # The documents it looked at, kept for the same
        # reason: a reopened answer links to them too.
        "documents": touched_documents(call, result),
    }
    created = _created_name(call, result)
    if created:
        entry["created"] = created
    entry["dry_run"] = bool(getattr(result, "dry_run", False))
    undo = undo_entry(call, result)
    if undo:
        entry["undo"] = undo
    return entry


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
        add(_created_name(call, result))
    elif call.name in ("update_doc", "submit_doc", "cancel_doc", "delete_doc"):
        # The document a write touched is a document the answer is about,
        # and the Sources line is where the reader looks for it.
        add(call.arguments.get("name"))
    elif call.name == "bulk_update_doc":
        # A bulk change names no document in its arguments — it names a
        # condition — so the documents it touched are the ones the tool
        # found.  A write that changed fifty tickets changed fifty
        # tickets, and the reader is entitled to know which.
        data = result.data if isinstance(result.data, dict) else {}
        for name in data.get("names") or []:
            add(name)
    elif call.name == "amend_doc":
        # An amendment creates a new document and supersedes the old one;
        # both are worth naming.
        add((result.data or {}).get("amended") if isinstance(result.data, dict) else "")
        add(call.arguments.get("name"))

    return documents


def _created_name(call, result: ToolResult) -> str:
    """The name of the document a tool created, if it created one.

    Only ``create_doc`` creates a document.  The other tools name a
    document as well — the one they read, the one they changed — and
    taking the name out of the envelope alone would have every tool that
    mentions a document claiming to have created it.

    That claim is not harmless.  The claim is what the undo reads, and an
    undo that believed a *read* had created a document would delete it:
    the turn read the ticket, the turn changed the ticket, the reader
    pressed undo, and the ticket was gone — because a read had been
    recorded as a creation.

    So the tool decides, not the envelope.
    """
    if str(getattr(call, "name", "") or "").strip() != "create_doc":
        return ""

    data = result.data
    if not isinstance(data, dict):
        return ""
    name = data.get("name")
    return str(name) if name else ""



