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
    from_wire,
    sanitize,
    system,
    to_wire,
    tool_result,
    user,
)


def test_message_round_trip():
    original = assistant("hello", (ToolCall(id="call_1", name="list_docs", arguments={"doctype": "Item"}),))
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


def test_to_wire_emits_vision_shape_when_image_set():
    image = "data:image/png;base64,AAAA"
    message = user("describe this", image=image)
    wire = message.to_wire()
    assert isinstance(wire["content"], list)
    assert wire["content"][0] == {"type": "text", "text": "describe this"}
    assert wire["content"][1] == {"type": "image_url", "image_url": {"url": image}}


def test_to_wire_emits_plain_string_when_no_image():
    message = user("hello")
    wire = message.to_wire()
    assert wire["content"] == "hello"
    assert isinstance(wire["content"], str)


def test_from_wire_round_trips_a_vision_message():
    image = "data:image/png;base64,AAAA"
    original = user("describe this", image=image)
    parsed = from_wire([original.to_wire()])[0]
    assert parsed.content == "describe this"
    assert parsed.image == image


def test_from_wire_handles_text_only_content_in_a_list():
    wire = {"role": "user", "content": [{"type": "text", "text": "hi"}]}
    parsed = Message.from_wire(wire)
    assert parsed.content == "hi"
    assert parsed.image is None


def test_as_plain_history_carries_the_image():
    image = "data:image/png;base64,AAAA"
    messages = [user("q", image=image), assistant("a")]
    plain = as_plain_history(messages)
    assert plain[0].image == image
