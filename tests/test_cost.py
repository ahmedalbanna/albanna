"""What a turn cost.

The provider reports tokens and money only when its API happens to
carry a price, and a price in the provider's own currency is not a price
in the site's currency.  So the site prices the turn itself, from the
tokens and the price the operator set, and the ledger is in the site's
currency.

These cases pin the rule: a turn with no price costs nothing *known*,
not nothing at all, and a negative or broken price never becomes a
negative cost.
"""

from __future__ import annotations

from albanna.core.cost import TOKENS_PER_PRICE_UNIT, cost_of_turn


def test_a_turn_costs_the_price_of_its_tokens():
    # A million tokens at 3 riyals, and the turn used 4000 of them.
    cost = cost_of_turn(2000, 2000, 3.0)
    assert cost == 0.012


def test_the_price_is_per_million():
    assert cost_of_turn(TOKENS_PER_PRICE_UNIT, 0, 2.5) == 2.5
    assert cost_of_turn(TOKENS_PER_PRICE_UNIT // 2, 0, 2.5) == 1.25


def test_a_turn_with_no_price_costs_nothing_known():
    assert cost_of_turn(1000, 1000, 0) == 0
    assert cost_of_turn(1000, 1000, 0.0) == 0


def test_a_price_that_is_not_a_number_is_no_price():
    assert cost_of_turn(1000, 1000, "not a number") == 0
    assert cost_of_turn(1000, 1000, None) == 0


def test_a_negative_price_does_not_make_a_negative_cost():
    assert cost_of_turn(1000, 1000, -3.0) == 0


def test_a_turn_with_no_tokens_costs_nothing():
    assert cost_of_turn(0, 0, 3.0) == 0


def test_a_negative_token_count_is_no_token_count():
    assert cost_of_turn(-100, 2000, 3.0) == 0.006
