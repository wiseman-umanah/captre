"""
Unit tests for POST /evaluate endpoint via FastAPI TestClient.

Strategy:
  - patch ``captre.payment_middleware`` to a passthrough that injects
    payment_payload — patch stays live inside ``with`` block.
  - patch ``captre.api.evaluate._extract_payer`` to return
    (FAKE_AUTHOR, FAKE_TX_ID) — avoids real AVM bytes.
  - patch ``captre.api.evaluate.write_evaluation`` at the using module.

AGENTS.md note: _extract_payer is defined in captre.api.attest and imported
into captre.api.evaluate — only captre.api.evaluate._extract_payer needs to be
patched here (the using namespace).

No chain, no USDC needed.
"""

from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from captre.models import EvaluationRecord, EvaluationResult
from tests.conftest import (
    FAKE_ATTESTATION_ID,
    FAKE_AUTHOR,
    FAKE_CONTENT_HASH,
    FAKE_TX_ID,
    make_payment_payload,
)

FAKE_EVALUATION_ID = "cccccccc-dddd-eeee-ffff-aaaaaaaaaaaa"
FAKE_POLICY_HASH = "sha256:" + "a" * 64
FAKE_EVAL_BODY = {
    "output_attestation_id": FAKE_ATTESTATION_ID,
    "content_hash": FAKE_CONTENT_HASH,
    "policy_hash": FAKE_POLICY_HASH,
    "evaluation_result": "pass",
}


def _make_fake_evaluation() -> EvaluationRecord:
    """
    Return a stable ``EvaluationRecord`` fixture for evaluate tests.

    Returns
    -------
    EvaluationRecord
        A deterministic evaluation record using ``FAKE_*`` constants.
    """
    return EvaluationRecord(
        evaluation_id=FAKE_EVALUATION_ID,
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
        tx_id=FAKE_TX_ID,
        output_attestation_id=FAKE_ATTESTATION_ID,
        content_hash=FAKE_CONTENT_HASH,
        evaluator=FAKE_AUTHOR,
        policy_hash=FAKE_POLICY_HASH,
        evaluation_result=EvaluationResult.pass_,
    )


@contextmanager
def _test_client(payer: str = FAKE_AUTHOR):
    """
    Context manager that yields a TestClient with payment_middleware bypassed.

    Parameters
    ----------
    payer : str
        Algorand address injected as the payment payer.
    """
    payload = make_payment_payload(payer)

    async def passthrough(request, call_next):
        request.state.payment_payload = payload
        return await call_next(request)

    with patch("captre.payment_middleware", return_value=passthrough), \
         patch("captre.x402_config.build_x402_server", return_value=MagicMock()), \
         patch("captre.api.evaluate._extract_payer", return_value=(payer, FAKE_TX_ID)):
        from captre import create_app
        app = create_app()
        yield TestClient(app, raise_server_exceptions=False), payer


@contextmanager
def _blocking_client():
    """Context manager that yields a TestClient with no payment payload injected."""
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

def test_evaluate_no_payment_returns_402():
    with _blocking_client() as client:
        resp = client.post("/evaluate", json=FAKE_EVAL_BODY)
    assert resp.status_code == 402


def test_evaluate_success_returns_200():
    fake_eval = _make_fake_evaluation()
    with _test_client() as (client, _payer):  # noqa: SIM117
        with patch("captre.api.evaluate.write_evaluation", return_value=fake_eval):
            resp = client.post("/evaluate", json=FAKE_EVAL_BODY)
    assert resp.status_code == 200
    body = resp.json()
    assert body["evaluation"]["evaluation_id"] == FAKE_EVALUATION_ID
    assert body["evaluation"]["evaluator"] == FAKE_AUTHOR
    assert body["evaluation"]["evaluation_result"] == "pass"
    assert body["message"] == "Evaluation recorded successfully"


def test_evaluate_not_found_returns_404():
    with _test_client() as (client, _):  # noqa: SIM117
        with patch(
            "captre.api.evaluate.write_evaluation",
            side_effect=ValueError("attestation not found"),
        ):
            resp = client.post("/evaluate", json=FAKE_EVAL_BODY)
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"]


def test_evaluate_duplicate_returns_409():
    with _test_client() as (client, _):  # noqa: SIM117
        with patch(
            "captre.api.evaluate.write_evaluation",
            side_effect=ValueError("already exists"),
        ):
            resp = client.post("/evaluate", json=FAKE_EVAL_BODY)
    assert resp.status_code == 409


def test_evaluate_runtime_error_returns_500():
    with _test_client() as (client, _):  # noqa: SIM117
        with patch("captre.api.evaluate.write_evaluation", side_effect=RuntimeError("boom")):
            resp = client.post("/evaluate", json=FAKE_EVAL_BODY)
    assert resp.status_code == 500


def test_evaluate_invalid_policy_hash_returns_422():
    bad_body = {**FAKE_EVAL_BODY, "policy_hash": "not-a-sha256"}
    with _test_client() as (client, _):
        resp = client.post("/evaluate", json=bad_body)
    assert resp.status_code == 422
