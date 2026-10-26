"""The attachment path: validation before a turn, storage before a send.

The rules under test:

- an attachment the site has not enabled is not carried at all;
- bytes that cannot be decoded are an error the caller sees, never a
  silent text-only turn;
- the site's size ceiling is honoured;
- storage accepts only the types on the allow-list, and names them with
  the extension the type actually means.
"""

from __future__ import annotations

from types import SimpleNamespace

from albanna.api.chat import _prepare_image
from albanna.services.chat_service import ChatService

# "hi" in base64.
HELLO = "aGVsbG8="


def _settings(image_support=True, max_image_size_kb=2048):
    return SimpleNamespace(
        image_support=image_support, max_image_size_kb=max_image_size_kb
    )


def _data_url(mime="image/png", payload=HELLO):
    return f"data:{mime};base64,{payload}"


# -- _prepare_image ------------------------------------------------------


def test_empty_image_passes_through():
    image, error = _prepare_image("", _settings())
    assert image == ""
    assert error == ""


def test_off_site_strips_the_image():
    """When the operator has turned image support off, the attachment is
    dropped before anything else — the size ceiling never gets a vote."""
    image, error = _prepare_image(_data_url(), _settings(image_support=False))
    assert image == ""
    assert error == ""


def test_a_good_image_passes():
    image, error = _prepare_image(_data_url(), _settings())
    assert image == _data_url()
    assert error == ""


def test_undecodable_payload_is_an_error():
    image, error = _prepare_image("data:image/png;base64,!!!!", _settings())
    assert image == ""
    assert error != ""


def test_oversize_is_an_error_naming_the_ceiling():
    settings = _settings(max_image_size_kb=1)  # 1 KB
    big = "data:image/png;base64," + "A" * 4096
    image, error = _prepare_image(big, settings)
    assert image == ""
    assert "1 KB" in error


def test_image_within_the_ceiling_passes():
    settings = _settings(max_image_size_kb=2048)
    image, error = _prepare_image(_data_url(), settings)
    assert error == ""
    assert image


def test_zero_ceiling_means_no_ceiling():
    settings = _settings(max_image_size_kb=0)
    image, error = _prepare_image(_data_url(), settings)
    assert error == ""


# -- the storage allow-list ---------------------------------------------


def test_allowed_types_spell_their_own_extensions():
    assert ChatService.ATTACHABLE["image/png"] == ".png"
    assert ChatService.ATTACHABLE["image/jpeg"] == ".jpg"
    assert ChatService.ATTACHABLE["image/webp"] == ".webp"
    assert ChatService.ATTACHABLE["image/gif"] == ".gif"
    assert ChatService.ATTACHABLE["application/pdf"] == ".pdf"


def test_unknown_types_are_not_on_the_list():
    """An svg executes scripts; html fakes the desk. Neither rides along."""
    assert "image/svg+xml" not in ChatService.ATTACHABLE
    assert "text/html" not in ChatService.ATTACHABLE


def test_storage_rejects_an_unlisted_type():
    """The rejection happens before the database is touched, so an empty
    return proves the file was refused, not that the write failed."""
    svg = _data_url("image/svg+xml", "PHN2Zz48L3N2Zz4=")  # <svg></svg>
    assert ChatService()._store_image(svg, "someone") == ""


def test_storage_rejects_a_bare_payload_with_no_type():
    assert ChatService()._store_image(HELLO, "someone") == ""
