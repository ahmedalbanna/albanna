"""The provider's "you asked for too much" refusal."""

from albanna.core.errors import ProviderBudgetExceeded, ProviderRejected
from albanna.providers.base import ProviderConfig
from albanna.providers.openai import _affordable_tokens


class FakeResponse:
    def __init__(self, payload=None, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


CONFIG = ProviderConfig(kind="openai", base_url="https://example.test", model="m", max_tokens=4096)


def test_the_affordable_number_is_read_out_of_the_refusal():
    detail = (
        "This request requires more credits, or fewer max_tokens. "
        "You requested up to 4096 tokens, but can only afford 3543."
    )
    assert _affordable_tokens(detail) == 3543


def test_a_refusal_without_a_number_reads_as_nothing():
    assert _affordable_tokens("Payment required") is None
    assert _affordable_tokens("can only afford zero tokens") is None
    assert _affordable_tokens("") is None


def test_a_402_naming_a_budget_is_a_budget_error(monkeypatch):
    from albanna.providers.openai import OpenAIProvider

    def fake_post(*args, **kwargs):
        return FakeResponse(
            payload={
                "error": {
                    "message": "You requested up to 4096 tokens, but can only afford 2048."
                }
            },
            status_code=402,
        )

    monkeypatch.setattr("albanna.providers.openai.post", fake_post)

    import pytest

    with pytest.raises(ProviderBudgetExceeded) as caught:
        OpenAIProvider().complete(CONFIG, [], [])

    assert caught.value.affordable_tokens == 2048
    assert caught.value.transient is False


def test_a_402_without_a_number_is_an_ordinary_refusal(monkeypatch):
    from albanna.providers.openai import OpenAIProvider

    def fake_post(*args, **kwargs):
        return FakeResponse(payload={"error": {"message": "Payment required"}}, status_code=402)

    monkeypatch.setattr("albanna.providers.openai.post", fake_post)

    import pytest

    with pytest.raises(ProviderRejected) as caught:
        OpenAIProvider().complete(CONFIG, [], [])

    assert not isinstance(caught.value, ProviderBudgetExceeded)
