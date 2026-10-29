"""The base every test in this app stands on.

A test that *acts as* somebody — a sales user, an accounts user — leaves
the session as that person, and the framework does not put it back.  So
the next test starts as somebody it did not choose, and the order the
tests run in changes what they mean.

The leak bites in a way that is hard to see.  The framework makes the
*session's* own settings for a user it creates, so a test that creates
a user while the session is somebody else — a user another test made,
and one this transaction has already rolled back — fails the insert
with "Could not find User: …".  The failure names a user the test has
never heard of, and it appears only when the tests happen to run in a
different order.

So the session is put back here, after every test, and every test class
in this app stands on this base.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

#: A field on Customer that the form will not let a person change.
#:
#: The suite has a test for the app's refusal to write a read-only
#: field.  It needs one to refuse, and ERPNext's Customer happens to
#: lock five — but that is ERPNext's layout, and a test that depends
#: on it skips itself the day ERPNext moves them.  So the site's
#: preparation makes a field whose only job is to be read-only, and
#: this is its name.
#:
#: The script that makes it lives in ``scripts/prepare_test_site.py``
#: and reads the name from here, so the two cannot drift apart.
READ_ONLY_PROBE = "albanna_read_only_probe"


class AlbannaTestCase(FrappeTestCase):
    """A test case that leaves the session as it found it."""

    def tearDown(self):
        frappe.set_user("Administrator")
        # The role permissions are cached for the session; a fresh
        # identity needs a fresh cache or it reads the previous one's.
        frappe.local.role_permissions = {}
        frappe.local.perms = {}
        super().tearDown()
