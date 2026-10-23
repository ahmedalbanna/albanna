"""``Albanna User Policy`` — per-user overrides for the safety rails.

A user who must not write anything gets "Never".  A user who must
confirm every write gets "Always".  Everyone else inherits the site
default, which is what a blank override means.
"""

from __future__ import annotations

import frappe
from frappe.model.document import Document


class AlbannaUserPolicy(Document):
    """Per-user overrides for the safety rails."""

    def validate(self):
        self._enforce_real_user()

    def _enforce_real_user(self):
        """The policy belongs to a real account."""
        if self.user and not frappe.db.exists("User", self.user):
            frappe.throw(
                frappe._("That is not a user."),
                frappe.ValidationError,
                title="User",
            )
