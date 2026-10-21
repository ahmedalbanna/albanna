"""The operator's extra options for the provider.

Some providers take options the app knows nothing about — a cache key, a
vendor's own flag, a parameter that only that provider has.  The operator
writes them as JSON, and they are added to the request the app sends.

Two rules, and both of them are about not surprising the operator.

**A value that spells a boolean is a boolean.**  A provider's own
configuration for an OpenAI-compatible endpoint writes ``"True"`` — a
string — where it means the boolean, and the SDK that reads it parses it
into one.  So the app parses it too: ``"true"`` and ``"false"``, in any
case, become the boolean they mean.  A number in the JSON is already a
number, and nothing else is touched.

**The app's own keys win.**  The extra options are *extra*: they fill the
gaps the app has no field for.  What the app has a field for — the
model, the temperature, the token ceiling — is the operator's too, and
was written with a purpose, so it is not overwritten by a line of JSON
typed later.
"""

from __future__ import annotations

import json
from typing import Any

#: The strings that mean a boolean.
TRUE_WORDS = frozenset({"true"})
FALSE_WORDS = frozenset({"false"})


def parse_options(raw: str) -> dict[str, Any]:
    """The operator's extra options, as a dictionary.

    An empty string is no options, and so is a string that is not JSON
    or is not a JSON *object*: the settings are refused at save time
    (see the settings controller), so this function is the second line
    of defence rather than the first, and it returns nothing rather
    than raising.

    @param raw: the JSON the operator wrote
    @returns: the options
    """
    text = str(raw or "").strip()
    if not text:
        return {}

    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return {}

    if not isinstance(parsed, dict):
        return {}

    return {str(key): _typed(value) for key, value in parsed.items()}


def merge_options(payload: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
    """The request body, with the operator's extra options in it.

    The app's own keys win: the options are extra, and a setting the
    app has a field for was written on purpose.

    @param payload: the body the app built
    @param options: the operator's extra options
    @returns: the body to send
    """
    if not options:
        return payload

    merged = dict(options)
    merged.update(payload)
    return merged


def _typed(value: Any) -> Any:
    """A value, with a string that spells a boolean turned into one.

    @param value: the value from the JSON
    @returns: the value
    """
    if not isinstance(value, str):
        return value

    word = value.strip().lower()
    if word in TRUE_WORDS:
        return True
    if word in FALSE_WORDS:
        return False
    return value
