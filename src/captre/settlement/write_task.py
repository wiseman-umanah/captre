"""
Sequential write flow for task submission.

Payment settles first (via x402-avm middleware), then this module
submits the box-write application call to TaskApp using the backend
service account.

CRITICAL:
  - The ``author`` field is ALWAYS sourced from the x402 payment payer.
  - Txn.sender() on the app call is always the service account — useless.
  - Box key for tasks is SHA-256(content_string) — 32 bytes.
  - task_hash stored in the record is sha256:<hex> of the content string;
    the box key is SHA-256 of that task_hash string (same two-level scheme as CaptreApp).
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

from captre.models import SubmitTaskRequest, TaskRecord
from captre.settlement.write_attestation import (
    _get_algorand_client,
    _get_service_account,
)

logger = logging.getLogger(__name__)

# ── ARC-56 spec for TaskApp (loaded once at import time) ─────────────────────
_TASK_ARC56_SPEC = json.loads(
    (Path(__file__).parent.parent / "contract" / "artifacts" / "TaskApp.arc56.json").read_text()
)


def _task_content_hash(content: str) -> str:
    """
    Compute the ``sha256:<hex>`` hash of raw task content.

    This is stored as ``task_hash`` in the ``TaskRecord``. The on-chain box
    key is derived by a further SHA-256 of this string via
    ``_task_hash_key()``.

    Parameters
    ----------
    content : str
        The raw task content string (prompt, specification, etc.).

    Returns
    -------
    str
        A ``sha256:<64 hex chars>`` string.
    """
    return "sha256:" + hashlib.sha256(content.encode()).hexdigest()


def _task_hash_key(task_hash: str) -> bytes:
    """
    Derive the 32-byte box key for a ``task_hash`` string.

    The raw ``task_hash`` string (e.g. ``"sha256:<64 hex chars>"``) is 71
    bytes. With the ``"t:"`` BoxMap prefix that exceeds Algorand's 64-byte
    box name limit. Hashing to a 32-byte SHA-256 digest keeps the name at
    exactly 34 bytes (``"t:"`` + 32 bytes).

    Parameters
    ----------
    task_hash : str
        The ``sha256:<hex>`` string from ``_task_content_hash()``.

    Returns
    -------
    bytes
        32-byte SHA-256 digest of the UTF-8 encoded ``task_hash``.
    """
    return hashlib.sha256(task_hash.encode()).digest()


def _get_task_app_id() -> int:
    """
    Read the deployed TaskApp application ID from the environment.

    Returns
    -------
    int
        The Algorand application ID of the deployed TaskApp contract.

    Raises
    ------
    RuntimeError
        If ``TASK_APP_ID`` is not set in the environment.
    """
    val = os.environ.get("TASK_APP_ID", "").strip("'\"")
    if not val:
        raise RuntimeError("TASK_APP_ID is not set in .env — run `uv run captre-deploy-task` first")
    return int(val)


def _get_task_app_client(service_account):
    """
    Build an algokit-utils app client for the deployed TaskApp contract.

    Parameters
    ----------
    service_account : SigningAccount
        The signing account used as the default sender and signer.

    Returns
    -------
    ApplicationClient
        An algokit-utils ``ApplicationClient`` configured for TaskApp.
    """
    return _get_algorand_client().client.get_app_client_by_id(
        app_spec=_TASK_ARC56_SPEC,
        app_id=_get_task_app_id(),
        default_sender=service_account.address,
        default_signer=service_account.signer,
    )


def write_task(
    request: SubmitTaskRequest,
    payer_address: str,
    payment_tx_id: str,
) -> TaskRecord:
    """
    Write a new task record to on-chain box storage.

    Generates a UUID ``task_id``, computes the content hash, builds the
    full ``TaskRecord``, then submits the ``submit_task()`` AVM method call
    which writes one box atomically.

    Parameters
    ----------
    request : SubmitTaskRequest
        Validated client request body. Must contain ``content``.
    payer_address : str
        Algorand address of the x402 payment payer — this becomes the
        ``author`` field. **Never** use ``Txn.sender()`` here.
    payment_tx_id : str
        Payment group ID from the x402 facilitator response.

    Returns
    -------
    TaskRecord
        The fully-populated task record that was written on-chain.

    Raises
    ------
    ValueError
        If the task content hash has already been claimed
        (contract aborts with ``ERR_ALREADY_CLAIMED``).
    RuntimeError
        If the box write fails for any other reason after payment settled.
    """
    task_id = str(uuid.uuid4())
    now = datetime.now(tz=UTC)
    task_hash = _task_content_hash(request.content)

    record = TaskRecord(
        task_id=task_id,
        author=payer_address,
        created_at=now,
        tx_id=payment_tx_id,
        task_hash=task_hash,
        agent_id=request.agent_id,
        description=request.description,
        tags=request.tags,
        extra=request.extra,
    )

    metadata_json = record.model_dump_json().encode()
    task_hash_key = _task_hash_key(task_hash)
    task_id_bytes = task_id.encode()
    task_hash_bytes = task_hash.encode()

    service_account = _get_service_account()
    app_client = _get_task_app_client(service_account)
    app_id = _get_task_app_id()

    try:
        app_client.send.call(AppClientMethodCallParams(
            method="submit_task",
            args=[task_hash_key, task_hash_bytes, task_id_bytes, payer_address, metadata_json],
            box_references=[
                BoxReference(app_id=app_id, name=b"t:" + task_hash_key),
            ],
        ))
        logger.info(
            "task box written | task_id=%s task_hash=%s author=%s",
            task_id,
            task_hash,
            payer_address,
        )
    except Exception as exc:
        full_msg = " ".join(str(e) for e in [exc, exc.__cause__, exc.__context__] if e)
        if "ERR_ALREADY_CLAIMED" in full_msg:
            raise ValueError(f"task content already claimed: {task_hash}") from exc
        logger.error(
            "task box write FAILED after payment settled | payment_tx_id=%s task_hash=%s error=%s",
            payment_tx_id,
            task_hash,
            full_msg,
        )
        raise RuntimeError(
            f"Task box write failed after payment settled (payment_tx_id={payment_tx_id}). "
            "Retry is safe — box write is idempotent."
        ) from exc

    return record


async def write_task_async(
    request: SubmitTaskRequest,
    payer_address: str,
    payment_tx_id: str,
) -> TaskRecord:
    """
    Async wrapper for ``write_task`` — runs in a thread pool.

    Prevents blocking the FastAPI event loop when called from an async
    route handler.

    Parameters
    ----------
    request : SubmitTaskRequest
        Validated client request body.
    payer_address : str
        Algorand address of the x402 payment payer.
    payment_tx_id : str
        Payment group ID from the x402 facilitator response.

    Returns
    -------
    TaskRecord
        The written task record.
    """
    return await asyncio.to_thread(write_task, request, payer_address, payment_tx_id)


def read_task_from_box(task_hash: str) -> TaskRecord | None:
    """
    Read a task record directly from on-chain box storage.

    Parameters
    ----------
    task_hash : str
        The ``sha256:<hex>`` task hash used as the logical key.
        The ``"t:"`` prefix required by the contract is applied internally.

    Returns
    -------
    TaskRecord or None
        The deserialized ``TaskRecord`` if a box exists for this hash,
        or ``None`` if the box does not exist.
    """
    service_account = _get_service_account()
    app_client = _get_task_app_client(service_account)

    key = _task_hash_key(task_hash)
    app_id = _get_task_app_id()

    result = app_client.send.call(AppClientMethodCallParams(
        method="get_task",
        args=[key],
        box_references=[
            BoxReference(app_id=app_id, name=b"t:" + key),
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
    return TaskRecord.model_validate(json.loads(raw.decode()))


async def read_task_from_box_async(task_hash: str) -> TaskRecord | None:
    """
    Async wrapper for ``read_task_from_box`` — runs in a thread pool.

    Parameters
    ----------
    task_hash : str
        The ``sha256:<hex>`` task hash to look up.

    Returns
    -------
    TaskRecord or None
        The task record, or ``None`` if not found.
    """
    return await asyncio.to_thread(read_task_from_box, task_hash)
