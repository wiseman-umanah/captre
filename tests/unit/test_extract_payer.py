"""
Unit tests for _extract_payer() — the function that reads the real author
address from an x402 payment payload.

We mock decode_payment_group so no real AVM transaction bytes are needed.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from captre.api.attest import _extract_payer
from tests.conftest import FAKE_AUTHOR, FAKE_TX_ID


def _make_payload(payer: str, group_id: str | None = FAKE_TX_ID) -> SimpleNamespace:
    """
    Build the minimal object ``_extract_payer()`` consumes.

    Parameters
    ----------
    payer : str
        Algorand address that the mocked ``decode_payment_group`` will return
        as the transaction sender at index 1 (``paymentIndex=1``).
    group_id : str or None
        Group ID to set on the fake ``group_info`` object. Pass ``None`` to
        test the fallback ``"group-idx-<index>"`` behaviour.

    Returns
    -------
    SimpleNamespace
        A minimal payload object with ``.payload["paymentGroup"]`` and
        ``.payload["paymentIndex"]`` set.
    """
    return SimpleNamespace(payload={"paymentGroup": "BASE64==", "paymentIndex": 1})


def _make_group_info(payer: str, group_id: str | None) -> SimpleNamespace:
    """
    Build a fake ``decode_payment_group`` return value.

    Parameters
    ----------
    payer : str
        Algorand address placed at ``transactions[1]`` (paymentIndex=1).
    group_id : str or None
        Group ID attached to the returned namespace.

    Returns
    -------
    SimpleNamespace
        A fake group info object with ``.transactions`` and ``.group_id``.
    """
    tx = SimpleNamespace(sender=payer)
    return SimpleNamespace(transactions=[None, tx], group_id=group_id)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_extract_payer_returns_sender_and_group_id() -> None:
    payload = _make_payload(FAKE_AUTHOR)
    with patch(
        "captre.api.attest.decode_payment_group",
        return_value=_make_group_info(FAKE_AUTHOR, FAKE_TX_ID),
    ):
        address, tx_id = _extract_payer(payload)

    assert address == FAKE_AUTHOR
    assert tx_id == FAKE_TX_ID


def test_extract_payer_fallback_when_no_group_id() -> None:
    """When group_id is None, tx_id falls back to 'group-idx-<index>'."""
    payload = _make_payload(FAKE_AUTHOR)
    with patch(
        "captre.api.attest.decode_payment_group",
        return_value=_make_group_info(FAKE_AUTHOR, None),
    ):
        address, tx_id = _extract_payer(payload)

    assert address == FAKE_AUTHOR
    assert tx_id == "group-idx-1"


def test_extract_payer_uses_payment_index_for_sender() -> None:
    """sender is looked up at transactions[paymentIndex], not transactions[0]."""
    payload = _make_payload(FAKE_AUTHOR)
    wrong_sender = "WRONGWRONGWRONGWRONGWRONGWRONGWRONGWRONGWRONGWRONGWRONG"
    # transactions[0] has wrong_sender, transactions[1] (paymentIndex) has FAKE_AUTHOR
    tx0 = SimpleNamespace(sender=wrong_sender)
    tx1 = SimpleNamespace(sender=FAKE_AUTHOR)
    group_info = SimpleNamespace(transactions=[tx0, tx1], group_id=FAKE_TX_ID)

    with patch("captre.api.attest.decode_payment_group", return_value=group_info):
        address, _ = _extract_payer(payload)

    assert address == FAKE_AUTHOR
