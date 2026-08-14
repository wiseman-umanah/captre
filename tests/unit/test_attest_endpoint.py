"""
Unit tests for POST /attest endpoint via FastAPI TestClient.

Strategy:
  - patch `captre.payment_middleware` (the name in captre's namespace) to a
    passthrough that injects payment_payload — patch stays live inside `with`
  - patch `captre.api.attest._extract_payer` to return (FAKE_AUTHOR, FAKE_TX_ID)
    directly — avoids needing real AVM transaction bytes or decode_payment_group

No chain, no USDC needed.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from tests.conftest import (
    FAKE_ATTESTATION_ID,
    FAKE_AUTHOR,
    FAKE_CONTENT_HASH,
    FAKE_TX_ID,
    make_payment_payload,
)


@contextmanager
def _test_client(payer: str = FAKE_AUTHOR):
    """
    All patches stay active for the full duration of the `with` block,
    including while the TestClient sends requests.
    """
    payload = make_payment_payload(payer)

    async def passthrough(request, call_next):
        request.state.payment_payload = payload
        return await call_next(request)

    with patch("captre.payment_middleware", return_value=passthrough), \
         patch("captre.x402_config.build_x402_server", return_value=MagicMock()), \
         patch("captre.api.attest._extract_payer", return_value=(payer, FAKE_TX_ID)):
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

def test_attest_no_payment_returns_402():
    with _blocking_client() as client:
        resp = client.post("/attest", json={"content_hash": FAKE_CONTENT_HASH})
    assert resp.status_code == 402


def test_attest_success_returns_200(fake_attestation):
    with _test_client() as (client, _payer):  # noqa: SIM117
        with patch("captre.api.attest.write_attestation", return_value=fake_attestation):
            resp = client.post("/attest", json={"content_hash": FAKE_CONTENT_HASH})
    assert resp.status_code == 200
    body = resp.json()
    assert body["attestation"]["attestation_id"] == FAKE_ATTESTATION_ID
    assert body["attestation"]["author"] == FAKE_AUTHOR
    assert body["message"] == "Attestation created successfully"


def test_attest_duplicate_returns_409(fake_attestation):
    with _test_client() as (client, _):  # noqa: SIM117
        with patch("captre.api.attest.write_attestation", side_effect=ValueError("already")), \
             patch("captre.api.attest.read_attestation_from_box", return_value=fake_attestation):
            resp = client.post("/attest", json={"content_hash": FAKE_CONTENT_HASH})
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["error"] == "content_hash already claimed"
    assert detail["existing_attestation"]["attestation_id"] == FAKE_ATTESTATION_ID


def test_attest_runtime_error_returns_500():
    with _test_client() as (client, _):  # noqa: SIM117
        with patch("captre.api.attest.write_attestation", side_effect=RuntimeError("boom")):
            resp = client.post("/attest", json={"content_hash": FAKE_CONTENT_HASH})
    assert resp.status_code == 500
