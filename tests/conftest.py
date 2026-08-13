"""
Shared pytest fixtures used across unit and integration tests.
"""

from datetime import datetime, timezone
from types import SimpleNamespace

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
    """
    A fully-populated ``Attestation`` instance used as a stable test fixture.

    Returns
    -------
    Attestation
        An active attestation with deterministic field values matching the
        ``FAKE_*`` module-level constants.
    """
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

def make_payment_payload(
    payer_address: str = FAKE_AUTHOR,
    tx_id: str = FAKE_TX_ID,
) -> SimpleNamespace:
    """
    Build a minimal payment_payload object that ``_extract_payer()`` can decode.

    ``_extract_payer`` reads::

        payload.payload["paymentGroup"]
        payload.payload["paymentIndex"]

    then calls ``decode_payment_group(group, index).transactions[index].sender``.

    We mock ``decode_payment_group`` at the call site instead of constructing
    real AVM transaction bytes, so this object only needs the outer shape.

    Parameters
    ----------
    payer_address : str
        Algorand address to be returned by the mocked ``decode_payment_group``.
        Defaults to ``FAKE_AUTHOR``. Only used by tests that do not override
        the ``_extract_payer`` patch entirely.
    tx_id : str
        Unused by the object itself — present for API symmetry with fixtures
        that need a matching ``FAKE_TX_ID``.

    Returns
    -------
    SimpleNamespace
        A minimal object with a ``.payload`` dict containing ``"paymentGroup"``
        and ``"paymentIndex"`` keys.
    """
    inner = {
        "paymentGroup": "FAKEGROUP==",
        "paymentIndex": 0,
    }
    return SimpleNamespace(payload=inner)


@pytest.fixture
def fake_payment_payload() -> SimpleNamespace:
    """
    Pytest fixture wrapping :func:`make_payment_payload` with default arguments.

    Returns
    -------
    SimpleNamespace
        A minimal payment payload for ``FAKE_AUTHOR``.
    """
    return make_payment_payload()


@pytest.fixture
def fake_payment_payload_wrong_author() -> SimpleNamespace:
    """
    A payload whose decoded sender is a different address — used for 403 tests.

    Returns
    -------
    SimpleNamespace
        A minimal payment payload whose ``payer_address`` is distinct from
        ``FAKE_AUTHOR``, triggering authorization failures in revoke tests.
    """
    return make_payment_payload(payer_address="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
