"""The file writes' approval cards.

A file write waits for the reader like every other write, and the card
that asks is the reader's whole view of the change.  The rules under
test:

- the preview says what will happen in the reader's words — "Create
  file notes.csv", "Change file /files/notes.txt" — and quotes the
  content only when it is short enough to be read;
- the diff of an edit is the file's text before and after, capped, and
  carries no diff for a file the reader may not read;
- the target is the File record and the stamp it had when the reader
  was asked, so a file that moved since is refused at the write.
"""

from __future__ import annotations

import pytest

approval = pytest.importorskip("albanna.services.approval")
files = pytest.importorskip("albanna.tools.files")


class FakeFile:
    """A File document, as far as the card reads one."""

    def __init__(self, content=b"old text", file_url="/files/notes.txt", name="FILE-001",
                 modified="2026-11-12 10:00:00.000000"):
        self.content = content
        self.mime_type = "text/plain"
        self.file_url = file_url
        self.name = name
        self.modified = modified

    def get_content(self):
        return self.content


@pytest.fixture(autouse=True)
def readable(monkeypatch):
    """Every file resolves and may be read, unless a test says otherwise."""
    monkeypatch.setattr(files, "_resolve", lambda file: None)
    import albanna.tools.erpnext as erpnext

    monkeypatch.setattr(erpnext, "_may_read_file", lambda source: True)


def _found(monkeypatch, source):
    monkeypatch.setattr(files, "_resolve", lambda file: source)


# -- the preview --------------------------------------------------------------


def test_a_new_file_is_described_by_its_name():
    preview = approval.write_preview("write_file", {"file_name": "notes.csv", "content": "a,b"})
    assert preview == "Create file notes.csv: a,b"


def test_a_long_new_file_is_described_by_its_size():
    preview = approval.write_preview(
        "write_file", {"file_name": "notes.csv", "content": "x" * 2000}
    )
    assert preview == "Create file notes.csv (2000 characters)"


def test_a_new_file_without_a_name_is_described_barely():
    assert approval.write_preview("write_file", {}) == "Create a file"


def test_an_edit_is_described_by_the_file_it_changes():
    preview = approval.write_preview("edit_file", {"file": "/files/notes.txt"})
    assert preview == "Change file /files/notes.txt"
    assert approval.write_preview("edit_file", {}) == "Change a file"


# -- the diff -----------------------------------------------------------------


def test_an_edit_carries_the_text_before_and_after(monkeypatch):
    _found(monkeypatch, FakeFile(content=b"old text"))
    diff = approval.write_diff("edit_file", {"file": "/files/notes.txt", "content": "new text"})
    assert diff == {"content": {"before": "old text", "after": "new text"}}


def test_a_long_edit_is_capped_on_the_card(monkeypatch):
    _found(monkeypatch, FakeFile(content=b"o" * 3000))
    diff = approval.write_diff("edit_file", {"file": "/files/notes.txt", "content": "n" * 3000})
    before = diff["content"]["before"]
    after = diff["content"]["after"]
    assert len(before) < 3000 and "more characters" in before
    assert len(after) < 3000 and "more characters" in after


def test_a_file_the_reader_may_not_read_carries_no_diff(monkeypatch):
    _found(monkeypatch, FakeFile())
    import albanna.tools.erpnext as erpnext

    monkeypatch.setattr(erpnext, "_may_read_file", lambda source: False)
    assert approval.write_diff("edit_file", {"file": "/files/notes.txt", "content": "x"}) is None


def test_a_missing_file_carries_no_diff():
    assert approval.write_diff("edit_file", {"file": "/files/nope.txt", "content": "x"}) is None


def test_a_document_write_still_carries_its_own_diff():
    """The file branch did not take the document branch's place."""
    assert approval.write_diff("create_doc", {"doctype": "Item", "data": {}}) is None


# -- the target ---------------------------------------------------------------


def test_an_edit_targets_the_file_and_its_stamp(monkeypatch):
    source = FakeFile(modified="2026-11-12 10:00:00.000000")
    _found(monkeypatch, source)
    target = approval.write_target("edit_file", {"file": "/files/notes.txt", "content": "x"})
    assert target == {
        "doctype": "File",
        "name": "FILE-001",
        "modified": "2026-11-12 10:00:00.000000",
    }


def test_an_edit_of_a_file_the_reader_may_not_read_has_no_target(monkeypatch):
    _found(monkeypatch, FakeFile())
    import albanna.tools.erpnext as erpnext

    monkeypatch.setattr(erpnext, "_may_read_file", lambda source: False)
    assert approval.write_target("edit_file", {"file": "/files/notes.txt"}) == {}


def test_a_creation_has_no_target():
    assert approval.write_target("write_file", {"file_name": "a.csv", "content": "x"}) == {}
