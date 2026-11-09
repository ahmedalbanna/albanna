"""The canonical message format.

Pure logic, no Frappe and no network: the format is the contract every
provider adapter depends on, and a bug here is a bug in all three of them
at once.
"""

from __future__ import annotations

import json

from albanna.core.messages import (
    Message,
    ToolCall,
    as_plain_history,
    assistant,
    attachment_note,
    from_wire,
    sanitize,
    system,
    to_wire,
    tool_result,
    unstored_note,
    user,
)


def test_message_round_trip():
    original = assistant(
        "hello", (ToolCall(id="call_1", name="list_docs", arguments={"doctype": "Item"}),)
    )
    parsed = Message.from_wire(original.to_wire())
    assert parsed.role == "assistant"
    assert parsed.content == "hello"
    assert len(parsed.tool_calls) == 1
    assert parsed.tool_calls[0].name == "list_docs"
    assert parsed.tool_calls[0].arguments == {"doctype": "Item"}


def test_tool_arguments_survive_the_wire_as_a_string():
    call = ToolCall(id="call_1", name="create_doc", arguments={"doctype": "Item", "data": {"x": 1}})
    wire = call.to_wire()
    # OpenAI wants the arguments as a JSON *string*.
    assert isinstance(wire["function"]["arguments"], str)
    assert json.loads(wire["function"]["arguments"]) == {"doctype": "Item", "data": {"x": 1}}
    # And the canonical form holds the parsed mapping.
    assert ToolCall.from_wire(wire).arguments == {"doctype": "Item", "data": {"x": 1}}


def test_unparseable_arguments_become_empty_rather_than_raising():
    wire = {"id": "call_1", "function": {"name": "list_docs", "arguments": "{not json"}}
    call = ToolCall.from_wire(wire)
    assert call.arguments == {}
    assert call.name == "list_docs"


def test_a_tool_call_without_a_name_is_still_usable():
    call = ToolCall.from_wire({"function": {"arguments": "{}"}})
    assert call.name == ""
    assert call.id  # an id is always minted, so a result can be paired with it


def test_tool_result_carries_its_call_id():
    message = tool_result("call_9", "the answer")
    assert message.role == "tool"
    assert message.to_wire()["tool_call_id"] == "call_9"


def test_sanitize_drops_empty_turns():
    messages = [user(""), assistant(""), system(""), user("real")]
    assert [m.content for m in sanitize(messages)] == ["real"]


def test_sanitize_merges_consecutive_user_turns():
    messages = [user("first"), user("second"), assistant("answer")]
    cleaned = sanitize(messages)
    assert len(cleaned) == 2
    assert "first" in cleaned[0].content
    assert "second" in cleaned[0].content


def test_sanitize_drops_a_tool_result_with_no_matching_call():
    messages = [
        assistant("working", (ToolCall(id="call_1", name="list_docs", arguments={}),)),
        tool_result("call_1", "result"),
        tool_result("call_missing", "orphan"),
    ]
    cleaned = sanitize(messages)
    assert len(cleaned) == 2
    assert cleaned[1].content == "result"


def test_plain_history_drops_tool_calls():
    messages = [
        user("q"),
        assistant("a", (ToolCall(id="call_1", name="list_docs", arguments={}),)),
        tool_result("call_1", "result"),
    ]
    plain = as_plain_history(messages)
    assert plain[1].tool_calls == ()
    assert plain[1].content == "a"
    # A tool result is not a user or assistant turn; it survives as it is.
    assert plain[2].role == "tool"


def test_to_wire_and_from_wire_agree():
    messages = [system("s"), user("u"), assistant("a"), tool_result("call_1", "r")]
    assert len(from_wire(to_wire(messages))) == len(messages)


def test_to_wire_emits_vision_shape_when_an_image_is_set():
    attachments = "data:image/png;base64,AAAA"
    message = user("describe this", attachments=[attachments])
    wire = message.to_wire()
    assert isinstance(wire["content"], list)
    assert wire["content"][0] == {"type": "text", "text": "describe this"}
    assert wire["content"][1] == {"type": "image_url", "image_url": {"url": attachments}}


def test_to_wire_carries_several_images():
    first = "data:image/png;base64,AAAA"
    second = "data:image/jpeg;base64,BBBB"
    wire = user("these two", attachments=[first, second]).to_wire()
    assert [
        part["image_url"]["url"] for part in wire["content"] if part["type"] == "image_url"
    ] == [
        first,
        second,
    ]


def test_to_wire_emits_plain_string_when_no_image():
    message = user("hello")
    wire = message.to_wire()
    assert wire["content"] == "hello"
    assert isinstance(wire["content"], str)


def test_from_wire_round_trips_a_vision_message():
    attachments = "data:image/png;base64,AAAA"
    original = user("describe this", attachments=[attachments])
    parsed = from_wire([original.to_wire()])[0]
    assert parsed.content == "describe this"
    assert parsed.attachments == [attachments]


def test_from_wire_round_trips_several_images():
    first = "data:image/png;base64,AAAA"
    second = "data:image/jpeg;base64,BBBB"
    original = user("these two", attachments=[first, second])
    parsed = from_wire([original.to_wire()])[0]
    assert parsed.attachments == [first, second]


def test_from_wire_handles_text_only_content_in_a_list():
    wire = {"role": "user", "content": [{"type": "text", "text": "hi"}]}
    parsed = Message.from_wire(wire)
    assert parsed.content == "hi"
    assert parsed.attachments == []


def test_as_plain_history_carries_the_image():
    attachments = "data:image/png;base64,AAAA"
    messages = [user("q", attachments=[attachments]), assistant("a")]
    plain = as_plain_history(messages)
    assert plain[0].attachments == [attachments]


def test_merging_two_questions_keeps_both_attachments():
    """Two questions in a row become one message, and a picture attached
    to either of them is still attached to the message that is sent."""
    first = "data:image/png;base64,AAAA"
    second = "data:image/jpeg;base64,BBBB"
    merged = sanitize([user("q", attachments=[first]), user("r", attachments=[second])])
    assert len(merged) == 1
    assert merged[0].attachments == [first, second]


# -- the note about where the attachments went ----------------------------


def test_the_note_names_every_stored_file():
    note = attachment_note(["/private/files/a.png", "/private/files/b.pdf"])
    assert "/private/files/a.png" in note
    assert "/private/files/b.pdf" in note
    assert "2 attachments were stored" in note


def test_no_note_without_a_stored_file():
    assert attachment_note([]) == ""


def test_one_attachment_is_said_in_the_singular():
    """ "1 attachment(s) is not a sentence, and a model reads it."""
    note = attachment_note(["/private/files/a.png"])
    assert "1 attachment was stored" in note
    assert "attachment(s)" not in note


def test_a_pdfs_text_travels_with_the_note():
    """A PDF's bytes are not a picture, so its text is the only thing
    about it the model can use.

    It used to be thrown away: the note said the contents could not be
    read and the model answered as though it had not seen the document.
    The text is read now, and it travels here rather than being dropped.
    """
    note = attachment_note(["/private/files/a.pdf"], ["Invoice 42\nTotal 100.00"])

    assert "/private/files/a.pdf" in note
    assert "Invoice 42" in note
    assert "Total 100.00" in note
    assert "could not be read" not in note


def test_an_attachment_with_no_text_says_so_rather_than_going_quiet():
    """A scanned PDF is pictures of words, and bytes that are not text are
    not text.

    The model is told, because a reader who attached a document and got
    an answer that ignored it has been answered about a document nobody
    read — the same "say what it could not read" property the app ships
    for refused reads.
    """
    note = attachment_note(["/private/files/a.pdf"], [""])

    assert "/private/files/a.pdf" in note
    assert "could not be read as text" in note
    assert "Do not describe what it says." in note


def test_a_csv_with_no_text_says_so_too():
    """The sentence is the attachment's, not the PDF's: a file that was
    looked at and yielded nothing is the same fact whatever its type."""
    note = attachment_note(["/private/files/a.csv"], [""])

    assert "/private/files/a.csv" in note
    assert "could not be read as text" in note


def test_a_picture_carries_no_text_of_its_own():
    """The provider is already looking at the picture; there is nothing
    to say about it that the picture does not say."""
    note = attachment_note(["/private/files/a.png"], [""])

    assert "/private/files/a.png" in note
    assert "could not be read" not in note
    assert "The text of" not in note


def test_a_csv_among_pictures_is_described_on_its_own():
    """One attachment's text does not become every attachment's, and the
    rule is the attachment's type rather than its position."""
    note = attachment_note(
        ["/private/files/a.png", "/private/files/b.csv"],
        ["", "order,customer\nSAL-1,Acme"],
    )

    assert "order,customer" in note
    assert "The text of /private/files/b.csv" in note
    assert "The text of /private/files/a.png" not in note


def test_a_pdf_among_pictures_is_described_on_its_own():
    """One attachment's text does not become every attachment's."""
    note = attachment_note(
        ["/private/files/a.png", "/private/files/b.pdf"],
        ["", "Page one of the contract"],
    )

    assert "Page one of the contract" in note
    assert "The text of /private/files/b.pdf" in note
    assert "The text of /private/files/a.png" not in note


def test_the_note_about_what_was_not_kept_says_how_many():
    """The model is told how many of the attachments it was given are
    unusable, so it does not try to use them."""
    note = unstored_note(2, 3)
    assert "2 of the attachments" in note
    assert "Do not attempt to use them." in note


def test_one_attachment_that_was_not_kept_is_said_in_the_singular():
    note = unstored_note(1, 3)
    assert "1 of the attachments" in note
    assert "Do not attempt to use it." in note


def test_none_of_the_attachments_kept_is_said_without_a_count():
    """When nothing was kept, the model is told that all of them are
    unusable — it knows how many it was given."""
    note = unstored_note(3, 3)
    assert "None of the attachments" in note
    assert "attachment(s)" not in note


def test_the_note_is_text_and_not_an_image_part():
    """The URL is a path on this site.  A vision provider cannot read a
    path it has no way to fetch, so the URL travels as words."""
    note = attachment_note(["/private/files/a.png"])
    assert "image_url" not in note
    assert "/private/files/a.png" in note


def test_the_history_claims_nothing_about_a_pdf_it_never_looked_at():
    """``None`` and an empty entry mean different things.

    The history is rebuilt from stored URLs alone, and it does not know
    whether a PDF's text was readable.  Saying "could not be read" there
    would be a claim with nothing behind it — and a claim the model
    repeats in the next turn's answer.
    """
    note = attachment_note(["/private/files/a.pdf"])

    assert "/private/files/a.pdf" in note
    assert "could not be read" not in note
    assert "The text of" not in note
