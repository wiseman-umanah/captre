"""
Sequential write flow for evaluation records.

Payment settles first (via x402-avm middleware), then this module
submits the box-write application call to LedgerApp using the backend
service account.

CRITICAL:
  - ``evaluator`` is ALWAYS sourced from the x402 payment payer — never from the request body.
  - Two Python-layer guards run before the AVM call:
      1. read_attestation_from_box() — the referenced attestation must exist in CaptreApp.
      2. read_task_from_box() — the referenced task must exist in TaskApp (when task_hash set).
  - The AVM layer ALSO cross-calls both contracts — double enforcement.
  - Box key: SHA-256(evaluation_uuid) — 32 bytes, stored under b"e:" prefix (34 bytes total).
  - Both APP_ID (CaptreApp) and TASK_APP_ID (TaskApp) must be in foreignApps on the transaction.
  - Singleton getters are IMPORTED from write_attestation — never re-declared here.
"""

import asyncio
import hashlib
import json
import logging
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from algokit_utils import BoxReference
from algokit_utils.applications.app_client import AppClientMethodCallParams

from captre.models import EvaluateRequest, EvaluationRecord
from captre.settlement.write_attestation import (
    _get_algorand_client,
    _get_app_id,
    _get_service_account,
    read_attestation_from_box,
)
from captre.settlement.write_task import (
    _get_task_app_id,
    _task_hash_key,
    read_task_from_box,
)

logger = logging.getLogger(__name__)

# ── ARC-56 spec for LedgerApp (loaded once at import time) ───────────────────
_LEDGER_ARC56_SPEC = json.loads(
    (Path(__file__).parent.parent / "contract" / "artifacts" / "LedgerApp.arc56.json").read_text()
)


def _evaluation_id_key(evaluation_id: str) -> bytes:
    """
    Derive the 32-byte box key for an ``evaluation_id`` UUID string.

    Parameters
    ----------
    evaluation_id : str
        The server-generated UUID for this evaluation.

    Returns
    -------
    bytes
        32-byte SHA-256 digest of the UTF-8 encoded ``evaluation_id``.
    """
    return hashlib.sha256(evaluation_id.encode()).digest()


def _get_ledger_app_id() -> int:
    """
    Read the deployed LedgerApp application ID from the environment.

    Returns
    -------
    int
        The Algorand application ID of the deployed LedgerApp contract.

    Raises
    ------
    RuntimeError
        If ``LEDGER_APP_ID`` is not set in the environment.
    """
    val = os.environ.get("LEDGER_APP_ID", "").strip("'\"")
    if not val:
        raise RuntimeError("LEDGER_APP_ID is not set in .env — run `uv run captre-deploy-ledger` first")
    return int(val)


def _get_ledger_app_client(service_account):
    """
    Build an algokit-utils app client for the deployed LedgerApp contract.

    Parameters
    ----------
    service_account : SigningAccount
        The signing account used as the default sender and signer.

    Returns
    -------
    ApplicationClient
        An algokit-utils ``ApplicationClient`` configured for LedgerApp.
    """
    return _get_algorand_client().client.get_app_client_by_id(
        app_spec=_LEDGER_ARC56_SPEC,
        app_id=_get_ledger_app_id(),
        default_sender=service_account.address,
        default_signer=service_account.signer,
    )


def write_evaluation(
    request: EvaluateRequest,
    payer_address: str,
    payment_tx_id: str,
) -> EvaluationRecord:
    """
    Write a new evaluation record to on-chain box storage.

    Runs two Python-layer guards before any chain call:
      1. The referenced attestation must exist in CaptreApp.
      2. If ``request.task_hash`` is set, the task must exist in TaskApp.

    Then submits ``add_evaluation()`` to LedgerApp, which re-validates both
    references on-chain via inner transactions.

    Parameters
    ----------
    request : EvaluateRequest
        Validated client request body.
    payer_address : str
        Algorand address of the x402 payment payer — this becomes the
        ``evaluator`` field. **Never** from the request body.
    payment_tx_id : str
        Payment group ID from the x402 facilitator response.

    Returns
    -------
    EvaluationRecord
        The fully-populated evaluation record that was written on-chain.

    Raises
    ------
    ValueError
        If the referenced attestation does not exist in CaptreApp.
    ValueError
        If the referenced task does not exist in TaskApp (when task_hash supplied).
    ValueError
        If this evaluation UUID has already been written (``ERR_ALREADY_EXISTS``).
    RuntimeError
        If the box write fails for any other reason after payment settled.
    """
    # --- Python-layer guards (before any chain call) ---
    existing_attest = read_attestation_from_box(request.content_hash)
    if existing_attest is None:
        raise ValueError(f"attestation not found for content_hash: {request.content_hash}")

    if request.task_hash is not None:
        existing_task = read_task_from_box(request.task_hash)
        if existing_task is None:
            raise ValueError(f"task not found for task_hash: {request.task_hash}")

    # --- Build the record ---
    evaluation_id = str(uuid.uuid4())
    now = datetime.now(tz=UTC)

    record = EvaluationRecord(
        evaluation_id=evaluation_id,
        created_at=now,
        tx_id=payment_tx_id,
        output_attestation_id=request.output_attestation_id,
        content_hash=request.content_hash,
        task_hash=request.task_hash,
        evaluator=payer_address,
        policy_hash=request.policy_hash,
        evaluation_result=request.evaluation_result,
        score=request.score,
        notes=request.notes,
    )

    metadata_json = record.model_dump_json().encode()
    eval_id_key = _evaluation_id_key(evaluation_id)

    # content_hash_key for CaptreApp.exists() — same scheme as write_attestation
    content_hash_key = hashlib.sha256(request.content_hash.encode()).digest()

    # task_hash_key for TaskApp.task_exists() — b"" when no task_hash
    if request.task_hash is not None:
        task_hash_key_bytes = _task_hash_key(request.task_hash)
        task_app_id_int = _get_task_app_id()
    else:
        task_hash_key_bytes = b""
        task_app_id_int = 0

    attest_app_id = _get_app_id()
    ledger_app_id = _get_ledger_app_id()

    service_account = _get_service_account()
    app_client = _get_ledger_app_client(service_account)

    # Build box_references: evaluation box + CaptreApp attestation box + optional TaskApp box
    box_refs = [
        BoxReference(app_id=ledger_app_id, name=b"e:" + eval_id_key),
        BoxReference(app_id=attest_app_id, name=b"a:" + content_hash_key),
    ]
    if task_hash_key_bytes:
        box_refs.append(BoxReference(app_id=task_app_id_int, name=b"t:" + task_hash_key_bytes))

    try:
        app_client.send.call(AppClientMethodCallParams(
            method="add_evaluation",
            args=[
                attest_app_id,
                task_app_id_int,
                content_hash_key,
                task_hash_key_bytes,
                eval_id_key,
                metadata_json,
            ],
            box_references=box_refs,
            # foreignApps must include both upstream contracts
            foreign_apps=[attest_app_id, task_app_id_int] if task_hash_key_bytes else [attest_app_id],
        ))
        logger.info(
            "evaluation box written | evaluation_id=%s content_hash=%s evaluator=%s",
            evaluation_id,
            request.content_hash,
            payer_address,
        )
    except Exception as exc:
        full_msg = " ".join(str(e) for e in [exc, exc.__cause__, exc.__context__] if e)
        if "ERR_ALREADY_EXISTS" in full_msg:
            raise ValueError(f"evaluation already exists: {evaluation_id}") from exc
        if "ERR_ATTESTATION_NOT_FOUND" in full_msg:
            raise ValueError(f"attestation not found on-chain: {request.content_hash}") from exc
        if "ERR_TASK_NOT_FOUND" in full_msg:
            raise ValueError(f"task not found on-chain: {request.task_hash}") from exc
        logger.error(
            "evaluation box write FAILED after payment settled | payment_tx_id=%s error=%s",
            payment_tx_id,
            full_msg,
        )
        raise RuntimeError(
            f"Evaluation box write failed after payment settled (payment_tx_id={payment_tx_id}). "
            "Retry is safe — box write is idempotent."
        ) from exc

    return record


async def write_evaluation_async(
    request: EvaluateRequest,
    payer_address: str,
    payment_tx_id: str,
) -> EvaluationRecord:
    """
    Async wrapper for ``write_evaluation`` — runs in a thread pool.

    Parameters
    ----------
    request : EvaluateRequest
        Validated client request body.
    payer_address : str
        Algorand address of the x402 payment payer.
    payment_tx_id : str
        Payment group ID from the x402 facilitator response.

    Returns
    -------
    EvaluationRecord
        The written evaluation record.
    """
    return await asyncio.to_thread(write_evaluation, request, payer_address, payment_tx_id)


def read_evaluation_from_box(evaluation_id: str) -> EvaluationRecord | None:
    """
    Read an evaluation record directly from on-chain box storage.

    Parameters
    ----------
    evaluation_id : str
        The UUID of the evaluation to look up.

    Returns
    -------
    EvaluationRecord or None
        The deserialized ``EvaluationRecord`` if a box exists, or ``None``.
    """
    service_account = _get_service_account()
    app_client = _get_ledger_app_client(service_account)

    key = _evaluation_id_key(evaluation_id)
    ledger_app_id = _get_ledger_app_id()

    result = app_client.send.call(AppClientMethodCallParams(
        method="get_evaluation",
        args=[key],
        box_references=[
            BoxReference(app_id=ledger_app_id, name=b"e:" + key),
        ],
    ))
    abi_val = result.abi_return
    if not abi_val:
        return None
    if isinstance(abi_val, (bytes, bytearray)):
        raw = bytes(abi_val)
    elif isinstance(abi_val, list):
        raw = bytes(cast(list[int], abi_val))
    else:
        raw = cast(bytes, abi_val)
    if not raw:
        return None
    return EvaluationRecord.model_validate(json.loads(raw.decode()))


async def read_evaluation_from_box_async(evaluation_id: str) -> EvaluationRecord | None:
    """
    Async wrapper for ``read_evaluation_from_box`` — runs in a thread pool.

    Parameters
    ----------
    evaluation_id : str
        The UUID of the evaluation to look up.

    Returns
    -------
    EvaluationRecord or None
        The evaluation record, or ``None`` if not found.
    """
    return await asyncio.to_thread(read_evaluation_from_box, evaluation_id)
