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
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from albanna.api.chat import _prepare_image
from albanna.services.chat_job import _json_list
from albanna.services.chat_service import ATTACHABLE, ChatService

# "hi" in base64.
HELLO = "aGVsbG8="


def _settings(image_support=True, max_image_size_kb=2048):
    return SimpleNamespace(image_support=image_support, max_image_size_kb=max_image_size_kb)


def _data_url(mime="image/png", payload=HELLO):
    return f"data:{mime};base64,{payload}"


# -- _prepare_image ------------------------------------------------------


def test_no_attachment_passes_through():
    images, error = _prepare_image("", _settings())
    assert images == []
    assert error == ""


def test_off_site_says_so_instead_of_dropping_it():
    """When the operator has turned image support off, the reader is told.

    The attachment used to be dropped silently, and the model — which
    received no image — answered "you have not provided one".  That is a
    lie the reader could not see through, so the refusal is explicit now.
    """
    images, error = _prepare_image(_data_url(), _settings(image_support=False))
    assert images == []
    assert "not enabled" in error


def test_a_good_image_passes():
    images, error = _prepare_image(_data_url(), _settings())
    assert images == [_data_url()]
    assert error == ""


def test_undecodable_payload_is_an_error():
    images, error = _prepare_image("data:image/png;base64,!!!!", _settings())
    assert images == []
    assert error != ""


def test_oversize_is_an_error_naming_the_ceiling():
    settings = _settings(max_image_size_kb=1)  # 1 KB
    big = "data:image/png;base64," + "A" * 4096
    images, error = _prepare_image(big, settings)
    assert images == []
    assert "1 KB" in error


def test_image_within_the_ceiling_passes():
    settings = _settings(max_image_size_kb=2048)
    images, error = _prepare_image(_data_url(), settings)
    assert error == ""
    assert images


def test_zero_ceiling_means_no_ceiling():
    settings = _settings(max_image_size_kb=0)
    images, error = _prepare_image(_data_url(), settings)
    assert error == ""


# -- several attachments -------------------------------------------------


def test_several_attachments_are_carried_whole():
    """A reader may attach more than one file, and each is kept."""
    first = _data_url("image/png")
    second = _data_url("application/pdf")
    images, error = _prepare_image(json.dumps([first, second]), _settings())
    assert images == [first, second]
    assert error == ""


def test_a_single_attachment_still_arrives_as_one():
    """The turn carries a list, but a reader who attached one file did
    not attach a list of one by any choice of theirs."""
    images, error = _prepare_image(json.dumps([_data_url()]), _settings())
    assert len(images) == 1
    assert error == ""


def test_one_bad_attachment_stops_the_whole_turn():
    """A turn that carries two files and cannot read one of them must not
    go to the model as a turn with one file: the reader believes the
    model saw both."""
    images, error = _prepare_image(
        json.dumps([_data_url(), "data:image/png;base64,!!!!"]), _settings()
    )
    assert images == []
    assert error != ""


def test_an_entry_that_is_not_a_string_is_refused():
    images, error = _prepare_image(json.dumps([_data_url(), 7]), _settings())
    assert images == []
    assert error != ""


# -- the parked marker ---------------------------------------------------


def test_the_marker_reads_a_list_back():
    assert _json_list(json.dumps(["a", "b"])) == ["a", "b"]


def test_the_marker_reads_a_bare_attachment_back():
    """A turn queued before the marker held a list parks one bare data
    URL, and it must still run."""
    assert _json_list("data:image/png;base64,AAAA") == ["data:image/png;base64,AAAA"]


def test_the_marker_reads_nothing_as_nothing():
    assert _json_list("") == []
    assert _json_list(None) == []
    assert _json_list(7) == []
    assert _json_list("[not json") == []


# -- the storage allow-list ---------------------------------------------


def test_allowed_types_spell_their_own_extensions():
    assert ATTACHABLE["image/png"] == ".png"
    assert ATTACHABLE["image/jpeg"] == ".jpg"
    assert ATTACHABLE["image/webp"] == ".webp"
    assert ATTACHABLE["image/gif"] == ".gif"
    assert ATTACHABLE["application/pdf"] == ".pdf"


def test_unknown_types_are_not_on_the_list():
    """An svg executes scripts; html fakes the desk. Neither rides along."""
    assert "image/svg+xml" not in ATTACHABLE
    assert "text/html" not in ATTACHABLE


def test_storage_rejects_an_unlisted_type():
    """The rejection happens before the database is touched, so an empty
    return proves the file was refused, not that the write failed."""
    svg = _data_url("image/svg+xml", "PHN2Zz48L3N2Zz4=")  # <svg></svg>
    assert ChatService()._store_image(svg, "someone") == ""


def test_storage_rejects_a_bare_payload_with_no_type():
    assert ChatService()._store_image(HELLO, "someone") == ""
