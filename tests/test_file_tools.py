"""The read_file tool: the model's way back to a stored file's text.

The rules under test:

- a file is found by its URL or by its File record's name, and by
  nothing else — a guessed path finds nothing;
- a file the account may not read is refused, and the refusal says so
  as a fact about the account;
- a picture is refused as a picture: its pixels cannot be read as text;
- a PDF's text comes out, and a file with no text in it says so rather
  than coming back empty;
- a long file comes back in parts, and the part's envelope names the
  offset the next read continues from;
- an offset that is not a whole number, or one past the end, is an
  error the model can act on.

The permission check and the URL resolution are ``erpnext``'s own
helpers, reused rather than copied — the File rules are one rules and
not two.
"""

from __future__ import annotations

import json

import pytest

files = pytest.importorskip("albanna.tools.files")
from albanna.core.tools import MAX_RESULT_CHARS, TOOL_MANIFEST  # noqa: E402
from tests.test_attach import _pdf_bytes  # noqa: E402


class FakeFile:
    """A File document, as far as read_file reads one."""

    def __init__(self, content=b"", mime_type="text/plain", file_url="/files/notes.txt",
                 is_private=0, name="FILE-001", file_name="notes.txt", file_size=None):
        self.content = content
        self.mime_type = mime_type
        self.file_url = file_url
        self.is_private = is_private
        self.name = name
        self.file_name = file_name
        self.file_size = file_size if file_size is not None else len(content)

    def get_content(self):
        return self.content


@pytest.fixture(autouse=True)
def permitted(monkeypatch):
    """Every file resolves and every read is allowed, unless a test says otherwise."""
    monkeypatch.setattr(files, "_file_for_url", lambda url: None)
    monkeypatch.setattr(files, "_may_read_file", lambda source: True)


class _FakeDB:
    """A db proxy, as far as _resolve reads one.

    The real ``frappe.db`` is a request-scoped proxy and is unbound in a
    unit test, so the module's ``frappe`` is replaced wholesale.
    """

    def __init__(self, source):
        self._source = source

    def exists(self, doctype, name):
        return name == "FILE-001"


class _FakeFrappe:
    def __init__(self, source):
        self.db = _FakeDB(source)
        self._source = source

    def get_doc(self, doctype, name):
        return self._source


def _found(monkeypatch, source):
    monkeypatch.setattr(files, "_file_for_url", lambda url: source)


def _named(monkeypatch, source):
    monkeypatch.setattr(files, "frappe", _FakeFrappe(source))


def _payload(raw: str) -> dict:
    return json.loads(raw)


# -- resolution ---------------------------------------------------------------


def test_a_file_is_read_by_its_url(monkeypatch):
    source = FakeFile(content=b"hello world")
    _found(monkeypatch, source)
    result = _payload(files.read_file("/files/notes.txt"))
    assert result["status"] == "ok"
    assert "hello world" in result["data"]["text"]


def test_a_file_is_read_by_its_record_name(monkeypatch):
    source = FakeFile(content=b"from the record")
    _named(monkeypatch, source)
    result = _payload(files.read_file("FILE-001"))
    assert result["status"] == "ok"
    assert "from the record" in result["data"]["text"]


def test_a_guessed_path_finds_nothing():
    result = _payload(files.read_file("/files/does-not-exist.txt"))
    assert result["status"] == "error"
    assert "No file" in result["message"]


def test_an_empty_argument_is_an_error():
    assert _payload(files.read_file(""))["status"] == "error"
    assert _payload(files.read_file("   "))["status"] == "error"
    assert _payload(files.read_file(None))["status"] == "error"


# -- permission ---------------------------------------------------------------


def test_a_file_the_account_may_not_read_is_refused(monkeypatch):
    _found(monkeypatch, FakeFile(content=b"secret"))
    monkeypatch.setattr(files, "_may_read_file", lambda source: False)
    result = _payload(files.read_file("/private/files/secret.txt"))
    assert result["status"] == "error"
    assert result.get("denied") is True
    assert "may not read" in result["message"]


# -- kinds of file ------------------------------------------------------------


def test_a_picture_is_refused_as_a_picture(monkeypatch):
    _found(monkeypatch, FakeFile(content=b"pixels", mime_type="image/png",
                                 file_url="/files/picture.png"))
    result = _payload(files.read_file("/files/picture.png"))
    assert result["status"] == "error"
    assert "picture" in result["message"]
    assert "read_file" in result["hints"][0]


def test_a_pdf_comes_back_as_text(monkeypatch):
    pdf = _pdf_bytes(b"Quarterly revenue rose")
    _found(monkeypatch, FakeFile(content=pdf, mime_type="application/pdf",
                                 file_url="/files/report.pdf"))
    result = _payload(files.read_file("/files/report.pdf"))
    assert result["status"] == "ok"
    assert "Quarterly revenue rose" in result["data"]["text"]


def test_a_file_with_no_text_in_it_says_so(monkeypatch):
    _found(monkeypatch, FakeFile(content=b"\x00\x01\x02", mime_type="application/octet-stream",
                                 file_url="/files/blob.bin"))
    result = _payload(files.read_file("/files/blob.bin"))
    assert result["status"] == "error"
    assert "no text" in result["message"]


def test_bytes_that_arrive_as_a_string_are_read(monkeypatch):
    _found(monkeypatch, FakeFile(content="text as a string"))
    result = _payload(files.read_file("/files/notes.txt"))
    assert result["status"] == "ok"
    assert "text as a string" in result["data"]["text"]


# -- long files ---------------------------------------------------------------


def test_a_long_file_comes_back_in_parts(monkeypatch):
    body = ("abcdefghij" * 2000).encode()  # 20 000 characters
    _found(monkeypatch, FakeFile(content=body))
    first = _payload(files.read_file("/files/long.txt"))
    assert first["status"] == "ok"
    assert first["data"]["more_remain"] is True
    assert first["data"]["returned_characters"] == files.READ_CHUNK_CHARS
    assert first["data"]["next_offset"] == files.READ_CHUNK_CHARS

    second = _payload(files.read_file("/files/long.txt", offset=first["data"]["next_offset"]))
    assert second["data"]["offset"] == files.READ_CHUNK_CHARS
    # The second part continues where the first stopped — the same read,
    # not the same text.
    assert second["data"]["text"] == body.decode()[
        files.READ_CHUNK_CHARS : 2 * files.READ_CHUNK_CHARS
    ]


def test_the_last_part_says_nothing_remains(monkeypatch):
    body = ("abcdefghij" * 2000).encode()
    _found(monkeypatch, FakeFile(content=body))
    last = _payload(files.read_file("/files/long.txt", offset=19000))
    assert last["data"]["more_remain"] is False
    assert last["data"]["next_offset"] is None


def test_an_offset_past_the_end_is_an_error(monkeypatch):
    _found(monkeypatch, FakeFile(content=b"short"))
    result = _payload(files.read_file("/files/short.txt", offset=100))
    assert result["status"] == "error"
    assert "past the end" in result["message"]


def test_an_offset_that_is_not_a_number_is_an_error(monkeypatch):
    _found(monkeypatch, FakeFile(content=b"short"))
    result = _payload(files.read_file("/files/short.txt", offset="beginning"))
    assert result["status"] == "error"
    assert "not a character offset" in result["message"]


def test_a_negative_offset_reads_from_the_beginning(monkeypatch):
    _found(monkeypatch, FakeFile(content=b"short"))
    result = _payload(files.read_file("/files/short.txt", offset=-5))
    assert result["status"] == "ok"
    assert result["data"]["offset"] == 0


# -- the envelope survives its own ceiling ------------------------------------


def test_the_spec_ceiling_leaves_room_for_the_envelope():
    spec = TOOL_MANIFEST._specs["read_file"]
    assert spec.max_result_chars >= files.READ_CHUNK_CHARS + 2000
    assert MAX_RESULT_CHARS == files.READ_CHUNK_CHARS


# -- write_file ---------------------------------------------------------------


class FakeInserted:
    """A File document as insert() leaves it."""

    def __init__(self, spec):
        self._spec = spec
        self.name = "FILE-NEW"
        self.file_url = "/files/" + spec["file_name"]
        self.file_name = spec["file_name"]
        self.is_private = spec["is_private"]
        self.file_size = len(spec["content"])

    def insert(self):
        return self


def test_a_file_is_created_private_by_default(monkeypatch):
    seen = {}

    def get_doc(spec):
        seen.update(spec)
        return FakeInserted(spec)

    monkeypatch.setattr(files.frappe, "get_doc", get_doc)
    result = _payload(files.write_file("notes.csv", "a,b\n1,2"))
    assert result["status"] == "ok"
    assert seen["is_private"] == 1
    assert seen["folder"] == "Home"
    assert result["data"]["file_url"] == "/files/notes.csv"


def test_a_file_is_public_only_when_asked(monkeypatch):
    seen = {}

    def get_doc(spec):
        seen.update(spec)
        return FakeInserted(spec)

    monkeypatch.setattr(files.frappe, "get_doc", get_doc)
    result = _payload(files.write_file("notes.csv", "a,b", is_private=False))
    assert result["status"] == "ok"
    assert seen["is_private"] == 0


def test_a_write_without_content_is_refused():
    assert _payload(files.write_file("notes.csv", ""))["status"] == "error"
    assert _payload(files.write_file("", "content"))["status"] == "error"
    assert _payload(files.write_file(None, "content"))["status"] == "error"


def test_a_failed_insert_is_an_error_not_an_exception(monkeypatch):
    class Broken:
        def insert(self):
            raise RuntimeError("disk full")

    monkeypatch.setattr(files.frappe, "get_doc", lambda spec: Broken())
    result = _payload(files.write_file("notes.csv", "a,b"))
    assert result["status"] == "error"
    assert "could not be created" in result["message"]


# -- edit_file ----------------------------------------------------------------


def test_an_edit_replaces_the_content_through_frappe(monkeypatch):
    calls = {}
    source = FakeFile(content=b"old text", file_url="/files/notes.txt")

    def save_file(content, overwrite=False):
        calls["content"] = content
        calls["overwrite"] = overwrite

    source.save_file = save_file
    source.save = lambda: calls.setdefault("saved", True)
    _found(monkeypatch, source)
    monkeypatch.setattr(files.frappe, "has_permission", lambda *a, **k: True)

    result = _payload(files.edit_file("/files/notes.txt", "new text"))
    assert result["status"] == "ok"
    assert calls["overwrite"] is True
    assert calls["content"] == "new text"
    assert calls["saved"] is True


def test_an_edit_needs_the_write_right(monkeypatch):
    source = FakeFile(content=b"old text")
    _found(monkeypatch, source)
    monkeypatch.setattr(files.frappe, "has_permission", lambda *a, **k: False)
    result = _payload(files.edit_file("/files/notes.txt", "new text"))
    assert result["status"] == "error"
    assert result.get("denied") is True


def test_an_edit_of_a_picture_is_refused(monkeypatch):
    source = FakeFile(content=b"pixels", mime_type="image/png", file_url="/files/picture.png")
    _found(monkeypatch, source)
    monkeypatch.setattr(files.frappe, "has_permission", lambda *a, **k: True)
    result = _payload(files.edit_file("/files/picture.png", "new text"))
    assert result["status"] == "error"
    assert "picture" in result["message"]


def test_an_edit_without_content_is_refused():
    assert _payload(files.edit_file("/files/notes.txt", ""))["status"] == "error"


def test_an_edit_of_a_missing_file_is_refused():
    result = _payload(files.edit_file("/files/nope.txt", "new text"))
    assert result["status"] == "error"
    assert "No file" in result["message"]
