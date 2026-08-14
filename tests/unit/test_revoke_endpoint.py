"""
Unit tests for POST /revoke endpoint via FastAPI TestClient.

Same strategy as test_attest_endpoint.py:
  - patch `captre.payment_middleware` to a passthrough (stays live in `with`)
  - patch `captre.api.attest._extract_payer` to return (payer, tx_id) directly

No chain, no USDC.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from captre.models import AttestationStatus
from tests.conftest import (
    FAKE_ATTESTATION_ID,
    FAKE_AUTHOR,
    FAKE_CONTENT_HASH,
    FAKE_TX_ID,
    make_payment_payload,
)

DIFFERENT_ADDRESS = "ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ"


@contextmanager
def _test_client(payer: str = FAKE_AUTHOR):
    payload = make_payment_payload(payer)

    async def passthrough(request, call_next):
        request.state.payment_payload = payload
        return await call_next(request)

    with patch("captre.payment_middleware", return_value=passthrough), \
         patch("captre.x402_config.build_x402_server", return_value=MagicMock()), \
         patch("captre.api.attest._extract_payer", return_value=(payer, FAKE_TX_ID)), \
         patch("captre.api.revoke._extract_payer", return_value=(payer, FAKE_TX_ID)):
        from captre import create_app
        app = create_app()
        yield TestClient(app, raise_server_exceptions=False), payer


@contextmanager
def _blocking_client():
    async def blocking(request, call_next):
        return await call_next(request)

    with patch("captre.payment_middleware", return_value=blocking), \
         patch("captre.x402_config.build_x402_server", return_value=MagicMock()):
        from captre import create_app
        app = create_app()
        yield TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_revoke_no_payment_returns_402():
    with _blocking_client() as client:
        resp = client.post("/revoke", json={"attestation_id": FAKE_ATTESTATION_ID})
    assert resp.status_code == 402


def test_revoke_not_found_returns_404():
    with _test_client() as (client, _):  # noqa: SIM117
        with patch("captre.api.revoke.read_attestation_from_box", return_value=None), \
             patch("captre.api.revoke.resolve_id_from_chain", return_value=None):
            resp = client.post("/revoke", json={"attestation_id": "no-such-id"})
    assert resp.status_code == 404


def test_revoke_wrong_author_returns_403(fake_attestation):
    with _test_client(payer=DIFFERENT_ADDRESS) as (client, _):  # noqa: SIM117
        with patch("captre.api.revoke.read_attestation_from_box", return_value=fake_attestation), \
             patch("captre.api.revoke.revoke_attestation", side_effect=PermissionError("not the original author")):
            resp = client.post("/revoke", json={"attestation_id": FAKE_ATTESTATION_ID})
    assert resp.status_code == 403
    assert "not the original author" in resp.json()["detail"]


def test_revoke_success(fake_attestation):
    revoked = fake_attestation.model_copy(update={"status": AttestationStatus.revoked})
    with _test_client() as (client, _):  # noqa: SIM117
        with patch("captre.api.revoke.read_attestation_from_box", return_value=fake_attestation), \
             patch("captre.api.revoke.revoke_attestation", return_value=revoked):
            resp = client.post("/revoke", json={"attestation_id": FAKE_ATTESTATION_ID})
    assert resp.status_code == 200
    body = resp.json()
    assert body["attestation"]["status"] == "revoked"
    assert body["message"] == "Attestation revoked successfully"


def test_revoke_resolves_uuid_via_chain(fake_attestation):
    """UUID in request → resolve_id_from_chain → read box."""
    revoked = fake_attestation.model_copy(update={"status": AttestationStatus.revoked})
    with _test_client() as (client, _):  # noqa: SIM117
        with patch("captre.api.revoke.read_attestation_from_box", side_effect=[None, fake_attestation]), \
             patch("captre.api.revoke.resolve_id_from_chain", return_value=FAKE_CONTENT_HASH), \
             patch("captre.api.revoke.revoke_attestation", return_value=revoked):
            resp = client.post("/revoke", json={"attestation_id": FAKE_ATTESTATION_ID})
    assert resp.status_code == 200
    assert resp.json()["attestation"]["status"] == "revoked"
