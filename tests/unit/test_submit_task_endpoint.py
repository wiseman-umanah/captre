"""
Unit tests for POST /submit-task endpoint via FastAPI TestClient.

Strategy:
  - patch ``captre.payment_middleware`` to a passthrough that injects
    payment_payload — patch stays live inside ``with`` block.
  - patch ``captre.api.submit_task._extract_payer`` to return
    (FAKE_AUTHOR, FAKE_TX_ID) directly — avoids real AVM transaction bytes.
  - patch ``captre.api.submit_task.write_task`` / ``read_task_from_box``
    at the using module, not the defining module.

No chain, no USDC needed.
"""

from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from captre.models import TaskRecord
from tests.conftest import (
    FAKE_AUTHOR,
    FAKE_TX_ID,
    make_payment_payload,
)

FAKE_TASK_ID = "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"
FAKE_TASK_HASH = "sha256:cafebabe00000001"
FAKE_TASK_CONTENT = "Summarise paper X"


def _make_fake_task() -> TaskRecord:
    """
    Return a stable ``TaskRecord`` fixture for submit-task tests.

    Returns
    -------
    TaskRecord
        A deterministic task record using ``FAKE_*`` constants.
    """
    return TaskRecord(
        task_id=FAKE_TASK_ID,
        author=FAKE_AUTHOR,
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
        tx_id=FAKE_TX_ID,
        task_hash=FAKE_TASK_HASH,
        description="unit test task",
        tags=["test"],
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
         patch("captre.api.submit_task._extract_payer", return_value=(payer, FAKE_TX_ID)):
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

def test_submit_task_no_payment_returns_402():
    with _blocking_client() as client:
        resp = client.post("/submit-task", json={"content": FAKE_TASK_CONTENT})
    assert resp.status_code == 402


def test_submit_task_success_returns_200():
    fake_task = _make_fake_task()
    with _test_client() as (client, _payer):  # noqa: SIM117
        with patch("captre.api.submit_task.write_task", return_value=fake_task):
            resp = client.post("/submit-task", json={"content": FAKE_TASK_CONTENT})
    assert resp.status_code == 200
    body = resp.json()
    assert body["task"]["task_id"] == FAKE_TASK_ID
    assert body["task"]["author"] == FAKE_AUTHOR
    assert body["message"] == "Task submitted successfully"


def test_submit_task_duplicate_returns_409():
    fake_task = _make_fake_task()
    with _test_client() as (client, _):  # noqa: SIM117
        with patch("captre.api.submit_task.write_task", side_effect=ValueError("already")), \
             patch("captre.api.submit_task.read_task_from_box", return_value=fake_task):
            resp = client.post("/submit-task", json={"content": FAKE_TASK_CONTENT})
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert "already claimed" in detail["error"]


def test_submit_task_runtime_error_returns_500():
    with _test_client() as (client, _):  # noqa: SIM117
        with patch("captre.api.submit_task.write_task", side_effect=RuntimeError("boom")):
            resp = client.post("/submit-task", json={"content": FAKE_TASK_CONTENT})
    assert resp.status_code == 500
