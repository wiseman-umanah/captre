"""
Shared pytest fixtures used across unit and integration tests.
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from captre.models import Attestation, AttestationStatus, OutputType


# ---------------------------------------------------------------------------
# Canonical fake attestation — reuse everywhere
# ---------------------------------------------------------------------------

FAKE_CONTENT_HASH = "sha256:deadbeefcafe0001"
FAKE_ATTESTATION_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
FAKE_AUTHOR = "GFYF3KDNCMINZCDJ6KIQDV24WU2PPFMLNST4J5FBW2Z2YQFT54BOEEGJYY"
FAKE_TX_ID = "FAKETXID0000000000000000000000000000000000000000000000"


@pytest.fixture
def fake_attestation() -> Attestation:
    return Attestation(
        attestation_id=FAKE_ATTESTATION_ID,
        author=FAKE_AUTHOR,
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        tx_id=FAKE_TX_ID,
        status=AttestationStatus.active,
        content_hash=FAKE_CONTENT_HASH,
        agent_id="test-agent",
        output_type=OutputType.file,
        description="unit test attestation",
        tags=["test"],
    )


# ---------------------------------------------------------------------------
# Fake x402 payment_payload — bypasses middleware entirely
# ---------------------------------------------------------------------------

def make_payment_payload(payer_address: str = FAKE_AUTHOR, tx_id: str = FAKE_TX_ID):
    """
    Build a minimal payment_payload object that _extract_payer() can decode.

    _extract_payer reads:
        payload.payload["paymentGroup"]
        payload.payload["paymentIndex"]
    then calls decode_payment_group(group, index).transactions[index].sender

    We mock decode_payment_group at the call site instead of constructing real
    AVM transaction bytes, so this object only needs the outer shape.
    """
    inner = {
        "paymentGroup": "FAKEGROUP==",
        "paymentIndex": 0,
    }
    payload = SimpleNamespace(payload=inner)
    return payload


@pytest.fixture
def fake_payment_payload():
    return make_payment_payload()


@pytest.fixture
def fake_payment_payload_wrong_author():
    """A payload whose decoded sender is a *different* address — for 403 tests."""
    return make_payment_payload(payer_address="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
