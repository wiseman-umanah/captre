"""
Sequential write flow for attestation and revocation.

Payment settles first (via x402-avm middleware), then this module
submits the box-write application call using the backend service account.

CRITICAL:
  - The `author` field is ALWAYS sourced from the x402 payment payload payer address.
  - Txn.sender() on the app call is always Captre's service account — useless for auth.
  - Box writes are idempotent (keyed by content_hash) — safe to retry on failure.
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from algokit_utils import AlgorandClient, BoxReference, SigningAccount
from algokit_utils.applications.app_client import AppClientMethodCallParams
from algosdk.mnemonic import to_private_key
from algosdk.v2client.algod import AlgodClient
from dotenv import load_dotenv

from captre.index_db import put as index_put
from captre.models import Attestation, AttestationStatus, AttestRequest

load_dotenv()
logger = logging.getLogger(__name__)

SERVICE_MNEMONIC = os.environ["SERVICE_MNEMONIC"]


def _get_app_id() -> int:
    val = os.environ.get("APP_ID", "")
    if not val:
        raise RuntimeError("APP_ID is not set in .env — run `uv run python -m captre.contract.deploy` first")
    return int(val)


def _get_service_account() -> SigningAccount:
    private_key = to_private_key(SERVICE_MNEMONIC)
    return SigningAccount(private_key=private_key)


_ARC56_SPEC = json.loads(
    (Path(__file__).parent.parent / "contract" / "artifacts" / "CaptreApp.arc56.json").read_text()
)


def _get_app_client(service_account: SigningAccount):
    algod_url = os.environ["ALGOD_URL"]
    algod_token = os.environ.get("ALGOD_TOKEN", "")
    from algosdk.v2client.indexer import IndexerClient as _IdxClient
    client = AlgorandClient.from_clients(
        AlgodClient(algod_token, algod_url),
        _IdxClient("", os.environ.get("INDEXER_URL", "https://testnet-idx.algonode.cloud")),
    )
    return client.client.get_app_client_by_id(
        app_spec=_ARC56_SPEC,
        app_id=_get_app_id(),
        default_sender=service_account.address,
        default_signer=service_account.signer,
    )


def write_attestation(
    request: AttestRequest,
    payer_address: str,   # extracted from x402 payment payload — the real author
    payment_tx_id: str,   # used as tx_id reference and for retry tracing
) -> Attestation:
    """
    Write a new attestation box.

    Args:
        request:         Validated client request body.
        payer_address:   Algorand address from x402 payment payload (the author).
        payment_tx_id:   Settlement tx id from x402 facilitator response.

    Returns:
        The fully-populated Attestation record.

    Raises:
        ValueError:  If the content_hash is already claimed (contract abort).
        RuntimeError: On unexpected app call failure after payment settled.
    """
    attestation_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc)

    attestation = Attestation(
        attestation_id=attestation_id,
        author=payer_address,       # from x402 payload — NEVER from Txn.sender()
        created_at=now,
        tx_id=payment_tx_id,
        status=AttestationStatus.active,
        content_hash=request.content_hash,
        agent_id=request.agent_id,
        output_type=request.output_type,
        description=request.description,
        model=request.model,
        previous_attestation=request.previous_attestation,
        tags=request.tags,
        extra=request.extra,
    )

    metadata_json = attestation.model_dump_json().encode()
    content_hash_bytes = request.content_hash.encode()

    service_account = _get_service_account()
    app_client = _get_app_client(service_account)

    try:
        app_client.send.call(AppClientMethodCallParams(
            method="attest",
            args=[content_hash_bytes, payer_address, metadata_json],
            box_references=[BoxReference(app_id=_get_app_id(), name=content_hash_bytes)],
        ))
        index_put(attestation_id, request.content_hash)
        logger.info(
            "attest box written | attestation_id=%s content_hash=%s author=%s",
            attestation_id,
            request.content_hash,
            payer_address,
        )
    except Exception as exc:
        # Walk the full exception chain — algokit wraps LogicError inside ValueError
        full_msg = " ".join(str(e) for e in [exc, exc.__cause__, exc.__context__] if e)
        if "ERR_ALREADY_CLAIMED" in full_msg:
            raise ValueError(f"content_hash already claimed: {request.content_hash}") from exc
        logger.error(
            "box write FAILED after payment settled | payment_tx_id=%s content_hash=%s error=%s",
            payment_tx_id,
            request.content_hash,
            full_msg,
        )
        raise RuntimeError(
            f"Box write failed after payment settled (payment_tx_id={payment_tx_id}). "
            "Retry is safe — box write is idempotent."
        ) from exc

    return attestation


def revoke_attestation(
    content_hash: str,
    payer_address: str,   # from x402 payment payload of the /revoke request
    existing: Attestation,
    payment_tx_id: str,
) -> Attestation:
    """
    Revoke an existing attestation box.

    Auth check: payer_address must match existing.author.
    This comparison uses the x402 payer address — NOT Algorand tx senders,
    since both the original attest and this revoke are submitted by the service account.

    Raises:
        PermissionError: If payer_address does not match existing.author.
        RuntimeError:    On unexpected app call failure after payment settled.
    """
    # Authorization check — payer address vs stored author
    if payer_address != existing.author:
        raise PermissionError(
            f"Revocation rejected: payer {payer_address} is not the "
            f"original author {existing.author}"
        )

    updated = existing.model_copy(
        update={"status": AttestationStatus.revoked}
    )
    updated_json = updated.model_dump_json().encode()
    content_hash_bytes = content_hash.encode()

    service_account = _get_service_account()
    app_client = _get_app_client(service_account)

    try:
        app_client.send.call(AppClientMethodCallParams(
            method="revoke",
            args=[content_hash_bytes, payer_address, updated_json],
            box_references=[BoxReference(app_id=_get_app_id(), name=content_hash_bytes)],
        ))
        logger.info(
            "revoke box updated | attestation_id=%s author=%s",
            existing.attestation_id,
            payer_address,
        )
    except Exception as exc:
        full_msg = " ".join(str(e) for e in [exc, exc.__cause__, exc.__context__] if e)
        if "ERR_NOT_FOUND" in full_msg:
            raise ValueError(f"attestation not found on-chain: {content_hash}") from exc
        logger.error(
            "revoke box update FAILED after payment settled | payment_tx_id=%s error=%s",
            payment_tx_id,
            str(exc),
        )
        raise RuntimeError(
            f"Revoke box update failed after payment settled (payment_tx_id={payment_tx_id})."
        ) from exc

    return updated


def read_attestation_from_box(content_hash: str) -> Attestation | None:
    """
    Read an attestation directly from on-chain box storage.
    Returns None if no box exists for this content_hash.
    """
    service_account = _get_service_account()
    app_client = _get_app_client(service_account)

    content_hash_bytes = content_hash.encode()

    result = app_client.send.call(AppClientMethodCallParams(
        method="get_attestation",
        args=[content_hash_bytes],
        box_references=[BoxReference(app_id=_get_app_id(), name=content_hash_bytes)],
    ))
    abi_val = result.abi_return
    if not abi_val:
        return None
    # ABI returns Bytes as list[int]; cast to bytes
    if isinstance(abi_val, (list, bytes, bytearray)):
        raw = bytes(abi_val)
    else:
        raw = cast(bytes, abi_val)
    if not raw:
        return None
    return Attestation.model_validate(json.loads(raw.decode()))
