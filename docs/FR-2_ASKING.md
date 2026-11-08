# FR-2 — Asking

**Status:** requirements review, closed out by the pass recorded in the
commits that follow this document.  Every claim below names the file and
the line that supports it, so a reader can check the claim rather than
trust it.

**Scope:** the eleven functional requirements FR-2.1 … FR-2.11, which
describe the act of asking — the composer, the panel's keyboard and drag
behaviour, voice, attachments, the model's honesty about what it could
read, the truncation indication, stopping a turn, the sources a refused
read must not produce, and copying a table out of an answer.

---

## FR-2.1 — The composer

**Requirement.** The question box is the one place a reader types.  It
must be usable while a turn is running, must not lose what the reader
typed, and must tell a screen reader how to submit.

**Status.** Shipped, with the exclusions in §Blocked.

**Evidence.**
- `albanna/public/js/side-chat/Composer.vue:185-191` — `onKeydown` now
  calls `onAction()`, so Enter sends when idle and stops when busy, the
  same thing the button beside the field does.
- `albanna/public/js/side-chat/Composer.vue:192-210` — `submit()` delegates
  the rules (trim, refuse empty unless a file is attached, refuse while
  busy) to `submit.mjs`, so they are testable.
- `albanna/public/js/side-chat/submit.mjs` — the pure module, with
  `submit.test.mjs` beside it.
- `albanna/public/js/side-chat/Composer.vue:508-518` — the textarea
  carries `aria-describedby="albanna-chat__hint"`.
- `albanna/public/js/side-chat/Composer.vue:642-644` — the hint carries
  `id="albanna-chat__hint"`.

**Gaps found.**
- **G1 (fixed this pass).** Enter was a dead key while a turn ran: the
  newline was cancelled and then nothing happened, while the send button
  in that exact state became a stop square and did something.  Fixed by
  routing Enter through `onAction()`.
- **G2 (closed).** No length cap on the question.  The two neighbouring
  fields are capped (conversation title at 120, `recent_questions` at
  300); the question itself was not.  It is now: 4000 characters,
  enforced at both doors, with the length named in the refusal.  See
  ADR-0043.
- **G3 (fixed this pass).** The hint was a bare `<p>` with no
  `aria-describedby`, so a screen reader heard "Your question" and was
  never told how to submit it.
- **G4 (fixed this pass).** The submit rules lived inside `Composer.vue`
  untested.  Extracted to `submit.mjs` with `submit.test.mjs`.

**Deliberate exclusions.** None.

**Accepted trade-offs.** None.

---

## FR-2.2 — Drag and drop

**Requirement.** A file may be attached by pasting, dropping or picking,
and a drop that misses the composer must not navigate the Desk away.

**Status.** Shipped, with the exclusions in §Blocked.

**Evidence.**
- `albanna/public/js/albanna-side-chat.bundle.js` — the panel's
  `dragover` and `drop` listeners call `preventDefault()`, so a drop
  anywhere inside the panel (transcript, empty state, header, nudge) no
  longer replaces the whole Desk.  The composer's own handler is a
  descendant and runs first, so its work stands.
- `albanna/public/js/side-chat/Composer.vue:258-280` — `onDrop`,
  `onDragEnter`, `onDragLeave`, `onDragOver`.
- `albanna/public/js/side-chat/Composer.vue:507-516` — the field carries
  `albanna-chat__field--dragover` while a file is over it.
- `albanna/public/css/albanna-side-chat.bundle.css` — the drag-over
  affordance, written with logical properties.
- `tests/test_front_end_rules.py` — `test_the_three_attach_paths_route_through_attachFiles`,
  a tripwire that paste, drop and the picker all call `attachFiles`.

**Gaps found.**
- **G1 (fixed this pass).** The only drop handling in the app was on the
  ~44 px composer strip; a drop over the rest of the panel navigated the
  Desk to the file.  Fixed in the launcher, which owns the panel element,
  so the guard holds even when the Vue bundle fails to load.
- **G2 (fixed this pass).** `onDragOver` called `preventDefault()` and
  nothing else, so the reader had no way to know where to aim.  Fixed
  with a drag-over class on the field.
- **G3 (fixed this pass).** The three attach paths converged only by
  convention.  A static assertion now checks that they all route through
  `attachFiles`.

**Deliberate exclusions.** None.

**Accepted trade-offs.** The static assertion proves that each of the
three named handlers calls `attachFiles`; it does not prove that a fourth
entry point added later will remember to, nor that the rules themselves
are right.

---

## FR-2.3 — Voice

**Requirement.** The reader may dictate a question instead of typing it.

**Status.** Shipped as *dictation* (speech transcribed into the question
text), with the scope question recorded as blocked.

**Evidence.**
- `albanna/public/js/side-chat/Composer.vue:95-140` — `toggleVoice`,
  `onresult`, `onend`.
- `albanna/public/js/side-chat/voice.mjs` — `mergeTranscript`, `readResults`.
- `albanna/public/js/side-chat/voice.test.mjs` — the tested half.

**Gaps found.**
- **D1 (fixed this pass).** `onend` emitted `finalText.trim()` — the
  spoken words only — discarding anything the reader typed while the
  microphone was open, even though `onresult` had merged it correctly on
  every result event.  Fixed to emit `lastEmitted`.
- **D2 (accepted).** `PRIVACY.md` now names the third-party flow: while
  the microphone is open, the reader's audio is sent to Google's servers
  for transcription.

**Deliberate exclusions.** None.

**Accepted trade-offs.** None.

**Blocked.** Whether FR-2.3 means dictation (shipped) or a *voice note*
(an audio attachment) is the owner's call.  No audio type exists in
`ATTACHABLE_TYPES`, there is no `MediaRecorder` anywhere, and no provider
handles audio.  Stage 1.7 and 3.4 fix the dictation that exists
regardless.

---

## FR-2.4 — Attachments

**Requirement.** A reader may attach a file to a question.

**Status.** Shipped, with the honesty gap fixed this pass and the scope
question recorded as blocked.

**Evidence.**
- `albanna/core/attachments.py` — `ATTACHABLE_TYPES`, including PDF.
- `albanna/core/messages.py:52-80` — `attachment_note`.
- `albanna/services/chat_service.py:383-388` — `image_dropped`.
- `albanna/providers/openai.py:229-260` — `_payload`, the drop path.

**Gaps found.**
- **G2 (fixed this pass).** `attachment_note` gave the model the address
  of a stored file and said nothing about readability, so a model that
  received a PDF it could not parse had every reason to answer as though
  it had seen the document.  The note now says a PDF's contents could not
  be read.  The reader side already uses the `image_dropped` channel for
  the provider-drop case.

**Deliberate exclusions.** None.

**Accepted trade-offs.** None.

**Blocked.**
- **Scope.** "A file" may mean a document (PDF is the answer) or any
  file.  Blocked on the same kind of owner decision.

**Closed in the pass that followed.**
- **G1 — a PDF's text reaches the model, and its bytes do not.**  A PDF
  was sent to the provider as an `image_url` part that nothing parses,
  and the app worked around it with a caveat sentence — so the model was
  honest and the reader attached a document and got an answer that could
  not see it.  The cost was not only honesty: the site's ceiling is
  2048 KB, and a two-megabyte PDF is the better part of a million tokens
  of base64.  The text is extracted with `pypdf` — a dependency of Frappe
  itself, so nothing new is installed — and travels with the turn; the
  bytes are dropped from the provider payload.  A scanned PDF is
  described as unreadable, in the turn that attached it and nowhere
  else.  See ADR-0050.

---

## FR-2.5 — Streaming and retries

**Requirement.** An answer streams token by token, and a retry or fallback
after tokens have been emitted must not concatenate two answers.

**Status.** Shipped, with the retry-after-tokens interaction fixed this
pass.

**Evidence.**
- `albanna/services/chat_service.py:711-760` — `_complete`, now emitting a
  `reset` event when a stream restarts after tokens were emitted.
- `albanna/services/chat_service.py:762-790` — `_stream`, now setting the
  `emitted` flag the caller owns.
- `albanna/public/js/side-chat/SideChatApp.vue` — the `status` handler
  records the round's starting length, and the `reset` handler truncates
  back to it.

**Gaps found.**
- **D1 (fixed this pass).** `_stream` emitted a `token` per delta and the
  client accumulated with no reset, so a retry or fallback appended a
  second answer to the tail of the first.  Fixed with a server-emitted
  `reset` and a one-line client handler.
- **D2 (accepted).** A client whose socket dies sees no streaming at all;
  tokens are deliberately not mirrored into the cache marker (only the
  approval card is).  The poll is the delivery guarantee, not the
  transport.  A reasonable degradation, documented in `turn.mjs`'s header.
- **D3 (covered).** The retry-after-tokens interaction is covered by the
  server-side change and the client handler above.

**Deliberate exclusions.** None.

**Accepted trade-offs.** None.

---

## FR-2.6 — Re-attached turns

**Requirement.** A turn that is re-attached to the panel shows its state.

**Status.** Shipped with no defects.

**Evidence.**
- `albanna/public/js/side-chat/SideChatApp.vue` — `resumeInflight`,
  `attachRunningTurns`.

**Gaps found.** None.

**Deliberate exclusions.** None.

**Accepted trade-offs.** Two observations were found and deliberately not
acted on: a re-attached turn shows the generic "Thinking" until its next
event, and there is no elapsed-time or round counter.  Both are polish on
a feature that works, and ROADMAP §6's rule is "a feature that is not
used is clutter".

---

## FR-2.7 — Stopping a turn

**Requirement.** Pressing Stop stops the turn.

**Status.** Shipped, with the approval-pending case fixed this pass.

**Evidence.**
- `albanna/public/js/side-chat/SideChatApp.vue` — `stop()`, now using
  `stopPlan`.
- `albanna/public/js/side-chat/stop.mjs` — the pure decision, with
  `stop.test.mjs` beside it.

**Gaps found.**
- **D1 (fixed this pass).** When a write was waiting for approval, Stop
  rejected every visible approval and returned without aborting anything,
  so the worker carried on to its next round and the turn kept running.
  Fixed to reject and then fall through and abort.
- **D2 (fixed this pass).** `stop()`'s two branches were untested.  The
  decision is now extracted to `stop.mjs` and covered by `stop.test.mjs`.

**Deliberate exclusions.** None.

**Accepted trade-offs.** None.

---

## FR-2.8 — Truncation indication

**Requirement.** When an answer is cut off at the token ceiling, the
reader is told.

**Status.** Shipped in the live view, with persistence recorded as
blocked.

**Evidence.**
- `albanna/public/js/side-chat/SideChatApp.vue` — `makeMessage` now
  carries a `truncated` field; `applyTurnResult` sets `answer.truncated`.
- `albanna/public/js/side-chat/SideChatApp.vue` — the footer renders the
  indication beside the answer it describes.

**Gaps found.**
- **G1 (fixed this pass).** `applyTurnResult` wrote the truncation
  indication into `state.notice`, the panel's single slot, so asking a
  follow-up erased the previous answer's indication while that answer was
  still visible, and any other notice overwrote it.  It now lives on the
  answer message and renders beside it.
- **G2 (closed).** Persisting the flag needed a column on
  `tabAlbanna Message`, so a migrate (backup → build → maintenance mode
  → migrate → every worker set restarted, per `docs/DEPLOYMENT.md`).  It
  was a deploy decision, and it is now made: the column exists, both
  paths that store an answer write it, and the transcript reads it back.
  See ADR-0042.

**Deliberate exclusions.** None.

**Accepted trade-offs.** None.

---

## FR-2.9 — Sources and refused reads

**Requirement.** A refused read must not produce a document link, and the
reader must not learn that the document exists from the panel.

**Status.** Shipped, with the gate fixed this pass.

**Evidence.**
- `albanna/services/chat_service.py:1588-1640` — `touched_documents`,
  now gating the argument-derived adds on `result.ok` and `not result.denied`.
- `albanna/core/prompt.py:71` — the model is instructed to say what it
  could not read.

**Gaps found.**
- **D1 (fixed this pass).** `touched_documents` took the name from the
  arguments for `get_doc` and the write tools and never looked at the
  outcome, so a refused read still linkified the name in the answer and
  listed it in the Sources line.  Fixed to add a document only when the
  call actually succeeded.
- **D2 (accepted).** `openSource`'s fallback navigates the whole page out
  of the SPA, and its try/catch swallows failures so a reader whose click
  does nothing gets no feedback.  Minor; best-effort navigation.

**Deliberate exclusions.** None.

**Accepted trade-offs.** None.

**Finding on the answer text.** The prompt already instructs the model to
say what it could not read (ROADMAP §2 item 7), and a refused `get_doc`
returns an error the model can relay, so in practice the answer does say
the read was refused.  Dropping the link therefore does not leave the
reader with a name in the text and no way to reach it; the name is
mentioned and explained, not linked.

---

## FR-2.10 — Copying a table

**Requirement.** A table in an answer may be copied out as data.

**Status.** Shipped, with the production failure fixed this pass.

**Evidence.**
- `albanna/public/js/side-chat/SideChatApp.vue` — `copyTable`, now
  guarding `navigator.clipboard` and falling back to `fallbackCopy`.
- `albanna/public/js/side-chat/SideChatApp.vue` — `fallbackCopy`, the
  single hidden-textarea implementation both copy paths use.

**Gaps found.**
- **G2 (fixed this pass).** `copyTable` called `navigator.clipboard.writeText`
  directly, which throws a `TypeError` where the Clipboard API is absent
  — which is every real reader, because the site is served over plain
  HTTP.  `copyAnswer` beside it already guarded the same call.  Fixed to
  share the guard and the fallback.
- **G1 (closed).** Only the first table was copied.
  `markdown.test.mjs` asserted it with the comment "Only the first table
  is taken." — a statement with no reason, which is how a bug survives in
  a test.  The renderer now numbers the tables and puts a copy and a
  download button beside each one.  See ADR-0044.

**Deliberate exclusions.** None.

**Accepted trade-offs.** None.

---

## FR-2.11 — Opening with a question

**Requirement.** A question passed to the launcher opens the panel with
that question.

**Status.** Shipped, with the cold-panel case fixed this pass.

**Evidence.**
- `albanna/public/js/albanna-side-chat.bundle.js` — `ask`, now holding
  the question and flushing it from `loadBundle`'s `onload`.

**Gaps found.**
- **D1 (fixed this pass).** On a cold panel the event was dispatched in
  the next macrotask, long before the Vue bundle was fetched, parsed and
  mounted, so it reached `document` with nobody listening and the panel
  opened empty.  The launcher now holds the question and flushes it once
  `mount()` has run.

**Deliberate exclusions.** None.

**Accepted trade-offs.** None.

---

## Blocked — recorded, not fixed

- **FR-2.3 scope.** Dictation versus a voice note.  See FR-2.3.
- **FR-2.4 scope.** "A file" versus a document.  See FR-2.4.

## Closed in the pass that followed

- **FR-2.1 G2 — the question has a ceiling.**  4000 characters, enforced
  at both doors, with the length named in the refusal.  The first
  suggestion was 2000 and it was changed on checking what the question
  actually carries: a pasted stack trace runs 1,500–3,000, so 2000 would
  refuse a legitimate paste.  See ADR-0043.
- **FR-2.8 G2 — the truncation flag is stored.**  A `truncated` Check
  field on `tabAlbanna Message`, written by both paths that store an
  answer and read back by the transcript, so a reader who reloads the
  thread sees the indication the live view showed.  Stored rather than
  inferred from the answer's length: a short answer is not an unfinished
  one.  See ADR-0042.
- **FR-2.10 G1 — every table can be copied.**  The renderer numbers the
  tables and puts a copy and a download button beside each one, so a
  reader with two tables has two of each.  See ADR-0044.
- **FR-2.4 G1 — a PDF's text reaches the model.**  It was sent as an
  `image_url` part nothing parses, and the app worked around it with a
  caveat sentence.  The text is extracted with `pypdf` and travels with
  the turn; the bytes are dropped from the provider payload.  See
  ADR-0050.

## Accepted — recorded, not acted on

- **FR-2.5 D2.** A client whose socket dies sees no streaming at all.
- **FR-2.6.** Re-attached turn shows generic "Thinking"; no elapsed-time
  or round counter.
- **FR-2.9 D2.** `openSource`'s fallback navigates out of the SPA and
  swallows failures.

---

## Pointer

`docs/ROADMAP.md` §0 lists asking as shipped; this document is the
evidence behind that line.