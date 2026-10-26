"""``Albanna Settings`` — the Single that holds the site's configuration.

The controller exists for one reason: the API key.  A ``Password`` field
stores its value in two halves — the ciphertext in ``tabAuth`` and a mask
in the column — and Frappe v16 has no ``Document.set_password``.
Saving a document with a ``Password`` field through the ORM writes the
*plaintext* into the column, which is exactly the thing that must not
happen to a credential.

So the key is written during ``validate``, through the encryption API,
and the column is left holding the mask.  ``validate`` runs after
``set_new_name`` and before ``db_insert``, so the plain text never
reaches the table at all — not even briefly.  The same pass repairs a
key that was already stored in the clear.  The controller is the only
place that knows this, and the only place it needs to be known.
"""

import frappe
from frappe.model.document import Document


class AlbannaSettings(Document):
    """Site-wide settings for the Albanna side chat."""

    def validate(self):
        self._secure_secrets()
        self._enforce_valid_options()
        self._clamp_approval_wait()

    def on_update(self):
        # ``validate`` has already moved the secrets, so this is a no-op
        # for an ordinary save.  It stays because a save made with
        # ``ignore_validate`` skips ``validate`` — and a key that skipped
        # the one place that knows how to store it must still be stored.
        self._store_secret("api_key", self.api_key)
        self._store_secret("fallback_api_key", self.fallback_api_key)

    # -- helpers ----------------------------------------------------------

    def _secure_secrets(self):
        """Leave no secret in the plain column, whatever the operator typed.

        A ``Password`` field stores its value in two halves: the ciphertext
        in ``tabAuth`` and a mask in the column.  Saving through the ORM
        writes the *plaintext* into the column, which is the one thing that
        must not happen to a credential.

        So the value is encrypted *here*, during ``validate``, and the
        column is replaced with the mask.  ``validate`` runs after
        ``set_new_name`` and before ``db_insert``, so the plain text is
        never written to the table at all — not even briefly.

        The same pass repairs a document that is already wrong.  When the
        column holds a secret in the clear — a script that used
        ``db_set``, a hand-edited row, or a save that failed before the
        key could be moved — the value is moved now, and the operator is
        told.  Refusing to save instead would leave them with a document
        they cannot save *and* the secret still sitting in the table,
        which is the worst of both.
        """
        for fieldname in ("api_key", "fallback_api_key"):
            value = self.get(fieldname)
            if not value or _is_mask(value):
                continue

            stored = self._stored_value(fieldname)
            if stored is not None and not _is_mask(stored):
                frappe.msgprint(
                    frappe._(
                        "The {0} was stored in plain text and has been encrypted."
                    ).format(fieldname),
                    indicator="green",
                    alert=True,
                )

            self._encrypt(fieldname, value)

    def _stored_value(self, fieldname: str):
        """What the table holds right now, mask or secret, or None."""
        try:
            return frappe.db.get_single_value(self.doctype, fieldname, cache=False)
        except Exception:
            # A settings document that has never been saved, or a column
            # that does not exist yet: either way there is nothing stored
            # in the clear to repair.
            return None

    def _encrypt(self, fieldname: str, value: str):
        """Write a secret into ``tabAuth`` and leave a mask in the column."""
        from frappe.utils.password import set_encrypted_password

        set_encrypted_password(self.doctype, self.name, value, fieldname)
        self.set(fieldname, "*" * 10)

    def _clamp_approval_wait(self):
        """Keep the approval wait inside the bounds the wait itself honours.

        The wait is read with a clamp as well — :func:`wait_seconds` — so
        a value outside the bounds is not a crash, it is a clamp.  But a
        clamp the operator cannot see is a setting that does not do what
        the box says, so the value is corrected *here*, where the
        operator typed it, and the box then shows what will happen.

        The bounds are the ones in :mod:`albanna.services.approval`: a
        floor, because a wait shorter than a reader's pause refuses
        writes nobody was given the chance to approve; a ceiling, because
        the worker holds its slot for as long as the wait lasts.
        """
        from albanna.services.approval import MAX_TIMEOUT, MIN_TIMEOUT

        try:
            seconds = int(self.get("confirm_timeout") or 0)
        except (TypeError, ValueError):
            seconds = 0

        if seconds <= 0:
            return

        clamped = min(max(seconds, int(MIN_TIMEOUT)), int(MAX_TIMEOUT))
        if clamped != seconds:
            self.confirm_timeout = clamped
            frappe.msgprint(
                frappe._("The approval wait is kept between {0} and {1} seconds; {2} was used.").format(
                    int(MIN_TIMEOUT), int(MAX_TIMEOUT), clamped
                ),
                indicator="orange",
                alert=True,
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
        """Write a secret into ``tabAuth`` and leave a mask in the column.

        The fallback for a save made with ``ignore_validate``, which
        skips :meth:`_secure_secrets`.  An ordinary save has already been
        through that, so the value is a mask here and this returns.

        The document is already written by the time this runs, so the mask
        has to reach the table with its own write rather than with the
        in-memory change :meth:`_encrypt` makes.
        """
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
