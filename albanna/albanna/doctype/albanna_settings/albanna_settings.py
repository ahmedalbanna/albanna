"""``Albanna Settings`` — the Single that holds the site's configuration.

The controller exists for one reason: the API key.  A ``Password`` field
stores its value in two halves — the ciphertext in the ``__Auth`` table and
a mask in the column — and Frappe v16 has no ``Document.set_password``.
Saving a document with a ``Password`` field through the ORM writes the
*plaintext* into the column, which is exactly the thing that must not
happen to a credential.

So the key is written after the save, through the encryption API, and the
column is left holding the mask.  The controller is the only place that
knows this, and the only place it needs to be known.
"""

import frappe
from frappe.model.document import Document


class AlbannaSettings(Document):
    """Site-wide settings for the Albanna side chat."""

    def validate(self):
        self._enforce_one_key()
        self._enforce_real_roles()
        self._enforce_valid_options()

    def on_update(self):
        self._store_secret("api_key", self.api_key)
        self._store_secret("fallback_api_key", self.fallback_api_key)

    # -- helpers ----------------------------------------------------------

    def _enforce_one_key(self):
        """Reject a document that carries a secret in a plain column.

        A ``Password`` field is masked in the column, so a value that is not
        a mask means the value was written in the clear — either by a script
        that used ``db_set`` or by a hand-edited row.  Refusing to save is
        the only response that does not leave the secret sitting in the
        table in plain text.
        """
        for fieldname in ("api_key", "fallback_api_key"):
            value = self.get(fieldname)
            if not value:
                continue
            if self.is_new() and not frappe.db.exists("__Auth", {"parent": self.name, "parenttype": self.doctype, "parentfield": fieldname}):
                # A new document legitimately has no stored secret yet.
                continue
            if not _is_mask(value):
                frappe.throw(
                    frappe._(
                        "The value in {0} is stored in plain text. "
                        "Clear the field, save, and enter the key again."
                    ).format(fieldname),
                    frappe.ValidationError,
                )

    def _enforce_real_roles(self):
        """Refuse a role name that is not a role.

        The two role fields are free text, and the operator types role
        names into them.  A name that is not exactly a role is *ignored*
        — silently — so a typo left an administrator wondering why the
        people they had chosen could not chat, with nothing anywhere
        saying that the name was wrong.

        So the save is where it is caught.  The names that do not exist
        are named, and the roles that do exist are offered, so the fix is
        a click rather than a guess.
        """
        from albanna.services.settings_service import split_names

        for fieldname, label in (
            ("chat_roles", "Chat Roles"),
            ("widget_roles", "Widget Roles"),
        ):
            names = split_names(self.get(fieldname))
            if not names:
                continue

            # Each name is checked on its own: a listing of the roles
            # would be paginated, and a role past the first page would be
            # reported as missing.
            missing = [name for name in names if not frappe.db.exists("Role", name)]
            if not missing:
                continue

            frappe.throw(
                frappe._("These are not roles: {0}").format(", ".join(missing)),
                frappe.ValidationError,
                title=frappe._(label),
            )

    def _enforce_valid_options(self):
        """Refuse options that are not a JSON object.

        The field is free text and the operator types JSON into it.  A
        typo — a missing comma, a trailing comma — would be ignored
        silently, and the option the operator wanted would simply not be
        there, with nothing anywhere saying why.

        So the save is where it is caught, and the error says what is
        wrong with the text rather than that the text is wrong.
        """
        import json

        raw = str(self.get("extra_options") or "").strip()
        if not raw:
            return

        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            frappe.throw(
                frappe._("These are not valid options: {0}").format(str(exc)),
                frappe.ValidationError,
                title=frappe._("Extra Options"),
            )
            return

        if not isinstance(parsed, dict):
            frappe.throw(
                frappe._('The options must be a JSON object, such as {"setCacheKey": "True"}.'),
                frappe.ValidationError,
                title=frappe._("Extra Options"),
            )

    def _store_secret(self, fieldname: str, value: str | None):
        """Write a secret into ``__Auth`` and leave a mask in the column."""
        if not value:
            return
        if _is_mask(value):
            return

        from frappe.utils.password import set_encrypted_password

        set_encrypted_password(self.doctype, self.name, value, fieldname)
        self.db_set(fieldname, "*" * 10)


def _is_mask(value: str) -> bool:
    """True when a stored password is a mask rather than a secret."""
    text = str(value or "")
    if not text:
        return False
    return set(text) == {"*"}
