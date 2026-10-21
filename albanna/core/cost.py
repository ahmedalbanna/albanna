"""What a turn cost.

The provider reports **tokens** — exactly, when it reports them at all —
and money only when its API happens to carry a price.  A price in the
provider's own currency is not a price in the site's currency, and a
ledger that mixes the two is a ledger nobody can read.

So the site prices the turn itself: the operator says what a million
tokens cost *them*, in *their* currency, and the cost in the ledger is
computed from the tokens and that price.  It is an estimate — the
operator's price is an estimate too, and prices move — and it is the
site's own currency, which is what the ledger is for.

The provider's own number is not thrown away: it is recorded beside the
site's, in its own currency, for whoever reconciles the two.
"""

from __future__ import annotations

#: How many tokens a price is quoted for.
TOKENS_PER_PRICE_UNIT = 1_000_000


def cost_of_turn(
    input_tokens: int,
    output_tokens: int,
    price_per_million: float,
) -> float:
    """What a turn cost, in the site's currency.

    Zero when the operator has set no price: a turn with no price is a
    turn whose cost is unknown, and a zero that says "free" is a lie the
    ledger would tell.

    @param input_tokens: the tokens the request cost
    @param output_tokens: the tokens the answer cost
    @param price_per_million: what a million tokens cost, in the site's
        currency
    @returns: the cost, in the site's currency
    """
    try:
        price = float(price_per_million or 0)
    except (TypeError, ValueError):
        return 0.0
    if price <= 0:
        return 0.0

    tokens = max(0, int(input_tokens or 0)) + max(0, int(output_tokens or 0))
    if not tokens:
        return 0.0

    return round(tokens / TOKENS_PER_PRICE_UNIT * price, 6)
