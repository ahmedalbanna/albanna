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
