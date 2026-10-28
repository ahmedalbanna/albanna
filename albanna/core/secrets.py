"""A secret, and how it is shown.

A secret has two lives: the value itself, and every place the value is
*not*.  The API key is the app's one secret, and it used to have a third
life it should never have had — the printed form of the configuration
that holds it.

A dataclass prints itself, and the configuration that holds the key is a
dataclass, so anything that printed it printed the key: a traceback, a
``bench execute``, a log line, a test failure.  A secret that is printed
by accident is a secret that has leaked by accident, and an accidental
leak is not a smaller leak — it is the same leak, in a place nobody was
looking.

So the representation is written by hand, and it says only *that* there
is a key.  Not how long it is, not its first few characters: a mask that
reveals the shape of the secret is a mask with holes in it.
"""

from __future__ import annotations

#: What a redacted secret reads as.
REDACTED = "[redacted]"


def mask_secret(value: str | None) -> str:
    """The secret, as something safe to print.

    An empty secret stays empty: "there is no key" and "there is a key
    and it is hidden" are different facts, and a reader of the output
    needs to tell them apart.

    @param value: the secret
    @returns: the mask, or an empty string
    """
    text = str(value or "").strip()
    if not text:
        return ""
    return REDACTED


def redact_secret(text: str | None, secret: str | None) -> str:
    """The text, with *secret* taken out of it.

    A provider's refusal often quotes the key it refused — "Incorrect API
    key provided: sk-…" — and the chat log is read by operators,
    exported, and copied off the host.  So a key that reached the log
    would be a key on a hundred laptops.

    An empty secret changes nothing: there is nothing to take out, and
    replacing every character of the text with the mask would be a
    different bug.

    @param text: the text to redact
    @param secret: the secret to take out of it
    @returns: the text, without the secret
    """
    body = str(text or "")
    value = str(secret or "").strip()
    if not value:
        return body
    return body.replace(value, REDACTED)
