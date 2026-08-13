"""
Unit tests for revoke_attestation() business logic.

Specifically the PermissionError auth check — no chain call needed because
the check fires before the app_client.send.call().
"""

import pytest

from captre.models import AttestationStatus
from captre.settlement.write_attestation import revoke_attestation
from tests.conftest import FAKE_AUTHOR, FAKE_CONTENT_HASH, FAKE_TX_ID

DIFFERENT_ADDRESS = "ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ"


def test_revoke_wrong_author_raises_permission_error(fake_attestation):
    """A payer who is NOT the original author must be rejected before touching the chain."""
    with pytest.raises(PermissionError, match="not the original author"):
        revoke_attestation(
            content_hash=FAKE_CONTENT_HASH,
            payer_address=DIFFERENT_ADDRESS,
            existing=fake_attestation,
            payment_tx_id=FAKE_TX_ID,
        )


def test_revoke_correct_author_does_not_raise_permission_error(fake_attestation, monkeypatch):
    """Correct author passes the auth check (chain call mocked out)."""
    from unittest.mock import MagicMock, patch

    mock_result = MagicMock()
    with patch(
        "captre.settlement.write_attestation._get_app_client"
    ) as mock_client_fn:
        mock_app = MagicMock()
        mock_app.send.call.return_value = mock_result
        mock_client_fn.return_value = mock_app

        updated = revoke_attestation(
            content_hash=FAKE_CONTENT_HASH,
            payer_address=FAKE_AUTHOR,   # matches fake_attestation.author
            existing=fake_attestation,
            payment_tx_id=FAKE_TX_ID,
        )

    assert updated.status == AttestationStatus.revoked
    assert updated.author == FAKE_AUTHOR


def test_revoke_preserves_all_other_fields(fake_attestation, monkeypatch):
    """Revocation must only change status — all other fields must be unchanged."""
    from unittest.mock import MagicMock, patch

    with patch("captre.settlement.write_attestation._get_app_client") as mock_client_fn:
        mock_app = MagicMock()
        mock_app.send.call.return_value = MagicMock()
        mock_client_fn.return_value = mock_app

        updated = revoke_attestation(
            content_hash=FAKE_CONTENT_HASH,
            payer_address=FAKE_AUTHOR,
            existing=fake_attestation,
            payment_tx_id=FAKE_TX_ID,
        )

    assert updated.attestation_id == fake_attestation.attestation_id
    assert updated.content_hash == fake_attestation.content_hash
    assert updated.author == fake_attestation.author
    assert updated.created_at == fake_attestation.created_at
    assert updated.tags == fake_attestation.tags
