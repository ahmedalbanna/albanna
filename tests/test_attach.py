"""The attachment path: validation before a turn, storage before a send.

The rules under test:

- an attachment the site has not enabled is not carried at all;
- bytes that cannot be decoded are an error the caller sees, never a
  silent text-only turn;
- the site's size ceiling is honoured;
- a turn may carry several attachments, and each is carried whole;
- the marker a parked turn leaves behind can be read back;
- storage accepts only the types on the allow-list, and names them with
  the extension the type actually means.

The rules live in ``albanna.core.attachments``, which imports no Frappe:
a rule that cannot be reached without the framework is a rule that is
only ever tested where the framework already is.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from albanna.api.chat import _prepare_image, _read_attachments
from albanna.core.attachments import (
    ATTACHABLE_TYPES,
    DISABLED,
    TOO_LARGE,
    UNREADABLE,
    check_attachments,
    decode_data_url,
    read_attachment_list,
)
from albanna.services.chat_service import ChatService

# "hello" in base64.
HELLO = "aGVsbG8="


def _settings(image_support=True, max_image_size_kb=2048):
    return SimpleNamespace(image_support=image_support, max_image_size_kb=max_image_size_kb)


def _data_url(mime="image/png", payload=HELLO):
    return f"data:{mime};base64,{payload}"


# -- _prepare_image ------------------------------------------------------


def test_no_attachment_passes_through():
    images, reason = _prepare_image("", _settings())
    assert images == []
    assert reason == ""


def test_off_site_says_so_instead_of_dropping_it():
    """When the operator has turned image support off, the reader is told.

    The attachment used to be dropped silently, and the model — which
    received no image — answered "you have not provided one".  That is a
    lie the reader could not see through, so the refusal is explicit now.
    """
    images, reason = _prepare_image(_data_url(), _settings(image_support=False))
    assert images == []
    assert reason == DISABLED


def test_a_good_image_passes():
    images, reason = _prepare_image(_data_url(), _settings())
    assert images == [_data_url()]
    assert reason == ""


def test_undecodable_payload_is_an_error():
    images, reason = _prepare_image("data:image/png;base64,!!!!", _settings())
    assert images == []
    assert reason == UNREADABLE


def test_oversize_is_an_error_naming_the_ceiling():
    settings = _settings(max_image_size_kb=1)  # 1 KB
    big = "data:image/png;base64," + "A" * 4096
    images, reason = _prepare_image(big, settings)
    assert images == []
    assert reason == TOO_LARGE


def test_image_within_the_ceiling_passes():
    settings = _settings(max_image_size_kb=2048)
    images, reason = _prepare_image(_data_url(), settings)
    assert reason == ""
    assert images


def test_zero_ceiling_means_no_ceiling():
    settings = _settings(max_image_size_kb=0)
    images, reason = _prepare_image(_data_url(), settings)
    assert reason == ""


# -- several attachments -------------------------------------------------


def test_several_attachments_are_carried_whole():
    """A reader may attach more than one file, and each is kept."""
    first = _data_url("image/png")
    second = _data_url("application/pdf")
    images, reason = _prepare_image(json.dumps([first, second]), _settings())
    assert images == [first, second]
    assert reason == ""


def test_a_single_attachment_still_arrives_as_one():
    """The turn carries a list, but a reader who attached one file did
    not attach a list of one by any choice of theirs."""
    images, reason = _prepare_image(json.dumps([_data_url()]), _settings())
    assert len(images) == 1
    assert reason == ""


def test_one_bad_attachment_stops_the_whole_turn():
    """A turn that carries two files and cannot read one of them must not
    go to the model as a turn with one file: the reader believes the
    model saw both."""
    images, reason = _prepare_image(
        json.dumps([_data_url(), "data:image/png;base64,!!!!"]), _settings()
    )
    assert images == []
    assert reason == UNREADABLE


def test_an_entry_that_is_not_a_string_is_refused():
    images, reason = _prepare_image(json.dumps([_data_url(), 7]), _settings())
    assert images == []
    assert reason == UNREADABLE


def test_a_payload_with_no_type_is_refused():
    """Base64 on its own is not an attachment.

    The header is what says what the bytes are, and the file rules are a
    list of types.  A payload with no type is on no list, and a turn that
    carried one would put a broken image in front of the model.
    """
    images, reason = _prepare_image(HELLO, _settings())
    assert images == []
    assert reason == UNREADABLE


# -- the turn's two entry points ----------------------------------------


def test_both_entry_points_read_the_fields_the_same_way():
    """The turn that answers now and the turn that answers in a worker
    read the same fields, or they disagree about the same question."""
    images, stored, error = _read_attachments(
        _data_url(), json.dumps(["/private/files/a.png"]), _settings()
    )
    assert images == [_data_url()]
    assert stored == ["/private/files/a.png"]
    assert error == ""


def test_addresses_that_cannot_be_read_are_read_as_no_addresses():
    """The turn then stores the bytes itself, which is the safe answer
    to a field it does not understand."""
    images, stored, error = _read_attachments(_data_url(), "[not json", _settings())
    assert images == [_data_url()]
    assert stored == []
    assert error == ""


# -- one reader for the wire ---------------------------------------------


def test_a_list_is_read_as_a_list():
    assert read_attachment_list(["a", "b"]) == (["a", "b"], True)


def test_a_json_list_is_read_as_a_list():
    assert read_attachment_list(json.dumps(["a", "b"])) == (["a", "b"], True)


def test_a_bare_string_is_read_as_a_list_of_one():
    """A turn queued before the field held a list parks one bare value,
    and it must still run."""
    assert read_attachment_list("data:image/png;base64,AAAA") == (
        ["data:image/png;base64,AAAA"],
        True,
    )


def test_nothing_is_read_as_nothing():
    assert read_attachment_list("") == ([], True)
    assert read_attachment_list(None) == ([], True)


def test_rubbish_is_not_read_as_an_attachment():
    """A string that tries to be JSON and is not is a broken field.

    Reading it as a file name would put a broken path into a turn.
    """
    assert read_attachment_list("[not json") == ([], False)
    assert read_attachment_list(7) == ([], False)


def test_an_empty_entry_carries_nothing():
    """An empty entry is dropped rather than refused: it is not a
    malformed field, it is nothing in it."""
    items, readable = read_attachment_list(["", "a"])
    assert items == ["a"]
    assert readable is True


def test_the_readers_agree_about_every_shape():
    """One reader, one meaning.

    The same field used to be read four ways, and the ways disagreed:
    a bare URL was kept by one reader and dropped by another.  A turn
    that runs here and now and a turn that runs in a worker must not
    come to disagree about the same payload.
    """
    for value in (["a"], json.dumps(["a"]), "a"):
        assert read_attachment_list(value) == (["a"], True)


# -- the decoder ---------------------------------------------------------


def test_a_data_url_yields_its_bytes_and_its_type():
    raw, mime = decode_data_url(_data_url("image/png"))
    assert raw == b"hello"
    assert mime == "image/png"


def test_a_data_url_without_a_type_is_not_read():
    assert decode_data_url(HELLO) == (b"", "")


def test_a_data_url_with_bad_bytes_is_not_read():
    assert decode_data_url("data:image/png;base64,!!!!") == (b"", "")


def test_the_type_is_read_in_lower_case():
    raw, mime = decode_data_url(_data_url("IMAGE/PNG"))
    assert raw == b"hello"
    assert mime == "image/png"


# -- the rule ------------------------------------------------------------


def test_the_rule_names_the_reason_it_refused():
    assert check_attachments(_data_url(), 0) == ([_data_url()], "")
    assert check_attachments("[not json", 0) == ([], UNREADABLE)
    assert check_attachments(_data_url(), 1) == ([], TOO_LARGE)


# -- the parked marker ---------------------------------------------------


def test_the_marker_reads_a_list_back():
    assert read_attachment_list(json.dumps(["a", "b"]))[0] == ["a", "b"]


def test_the_marker_reads_a_bare_attachment_back():
    """A turn queued before the marker held a list parks one bare data
    URL, and it must still run."""
    value = "data:image/png;base64,AAAA"
    assert read_attachment_list(value)[0] == [value]


def test_the_marker_reads_nothing_as_nothing():
    assert read_attachment_list("")[0] == []
    assert read_attachment_list(None)[0] == []
    assert read_attachment_list(7)[0] == []
    assert read_attachment_list("[not json")[0] == []


# -- the storage allow-list ---------------------------------------------


def test_allowed_types_spell_their_own_extensions():
    assert ATTACHABLE_TYPES["image/png"] == ".png"
    assert ATTACHABLE_TYPES["image/jpeg"] == ".jpg"
    assert ATTACHABLE_TYPES["image/webp"] == ".webp"
    assert ATTACHABLE_TYPES["image/gif"] == ".gif"
    assert ATTACHABLE_TYPES["application/pdf"] == ".pdf"


def test_unknown_types_are_not_on_the_list():
    """An svg executes scripts; html fakes the desk. Neither rides along."""
    assert "image/svg+xml" not in ATTACHABLE_TYPES
    assert "text/html" not in ATTACHABLE_TYPES


def test_storage_rejects_an_unlisted_type():
    """The rejection happens before the database is touched, so an empty
    return proves the file was refused, not that the write failed."""
    svg = _data_url("image/svg+xml", "PHN2Zz48L3N2Zz4=")  # <svg></svg>
    assert ChatService()._store_image(svg, "someone") == ""


def test_storage_rejects_a_bare_payload_with_no_type():
    assert ChatService()._store_image(HELLO, "someone") == ""
