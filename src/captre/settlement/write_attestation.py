"""
Sequential write flow for attestation and revocation.

Payment settles first (via x402-avm middleware), then this module
submits the box-write application call using the backend service account.

CRITICAL:
  - The `author` field is ALWAYS sourced from the x402 payment payload payer address.
  - Txn.sender() on the app call is always Captre's service account — useless for auth.
  - attest() writes TWO boxes atomically: attestations[content_hash] and id_index[attestation_id].
  - Both box_references must be passed — one for each box the contract touches.
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
from algosdk.error import AlgodResponseError
from dotenv import load_dotenv

from captre.models import Attestation, AttestationStatus, AttestRequest

load_dotenv()
logger = logging.getLogger(__name__)

SERVICE_MNEMONIC = os.environ["SERVICE_MNEMONIC"]


def _get_app_id() -> int:
    """
    Read the deployed contract app ID from the environment.

    Returns
    -------
    int
        The Algorand application ID of the deployed CaptreApp contract.

    Raises
    ------
    RuntimeError
        If ``APP_ID`` is not set in the environment (deploy has not been run).
    """
    val = os.environ.get("APP_ID", "")
    if not val:
        raise RuntimeError("APP_ID is not set in .env — run `uv run python -m captre.contract.deploy` first")
    return int(val)


def _get_service_account() -> SigningAccount:
    """
    Construct the backend service ``SigningAccount`` from the environment mnemonic.

    Returns
    -------
    SigningAccount
        An algokit-utils ``SigningAccount`` whose address is the Captre service
        wallet. All on-chain app calls are submitted from this account.
    """
    private_key = to_private_key(SERVICE_MNEMONIC)
    return SigningAccount(private_key=private_key)


_ARC56_SPEC = json.loads(
    (Path(__file__).parent.parent / "contract" / "artifacts" / "CaptreApp.arc56.json").read_text()
)


def _get_app_client(service_account: SigningAccount):
    """
    Build an algokit-utils app client for the deployed CaptreApp contract.

    Parameters
    ----------
    service_account : SigningAccount
        The signing account used as the default sender and signer for all
        method calls made through the returned client.

    Returns
    -------
    ApplicationClient
        An algokit-utils ``ApplicationClient`` configured with the ARC-56 spec,
        the current ``APP_ID``, and the provided ``service_account``.
    """
    algod_url = os.environ["ALGOD_URL"]
    algod_token = os.environ.get("ALGOD_TOKEN", "")
    algod_timeout = int(os.environ.get("ALGOD_TIMEOUT", "15"))
    from algosdk.v2client.indexer import IndexerClient as _IdxClient
    client = AlgorandClient.from_clients(
        AlgodClient(algod_token, algod_url, timeout=algod_timeout),
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
    payer_address: str,
    payment_tx_id: str,
) -> Attestation:
    """
    Write a new attestation to on-chain box storage.

    Generates a UUID ``attestation_id``, builds the full ``Attestation`` record,
    then submits the ``attest()`` AVM method call which writes two boxes
    atomically: ``attestations[content_hash]`` and ``id_index[attestation_id]``.

    Parameters
    ----------
    request : AttestRequest
        Validated client request body. Must contain at minimum ``content_hash``.
    payer_address : str
        Algorand address of the x402 payment payer — this becomes the
        ``author`` field in the stored attestation. **Never** pass
        ``Txn.sender()`` here; that is always the service account.
    payment_tx_id : str
        Payment group ID from the x402 facilitator response. Used as the
        ``tx_id`` reference in the stored record and in retry-trace logs.

    Returns
    -------
    Attestation
        The fully-populated attestation record that was written on-chain.

    Raises
    ------
    ValueError
        If the ``content_hash`` has already been claimed (contract aborts
        with ``ERR_ALREADY_CLAIMED``).
    RuntimeError
        If the box write fails for any other reason after payment has already
        settled. The error message includes the ``payment_tx_id`` to allow
        manual follow-up. Re-submitting is safe — the write is idempotent.
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

    attestation_id_bytes = attestation_id.encode()

    try:
        app_client.send.call(AppClientMethodCallParams(
            method="attest",
            args=[content_hash_bytes, attestation_id_bytes, payer_address, metadata_json],
            box_references=[
                BoxReference(app_id=_get_app_id(), name=b"a:" + content_hash_bytes),
                BoxReference(app_id=_get_app_id(), name=b"i:" + attestation_id_bytes),
            ],
        ))
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
    payer_address: str,
    existing: Attestation,
    payment_tx_id: str,
) -> Attestation:
    """
    Revoke an existing attestation by overwriting its on-chain box with an
    updated record whose ``status`` is set to ``"revoked"``.

    Parameters
    ----------
    content_hash : str
        The ``content_hash`` key for the attestation box to update.
    payer_address : str
        Algorand address of the x402 payment payer for this /revoke request.
        Must equal ``existing.author`` or a ``PermissionError`` is raised
        before any chain call is made.
    existing : Attestation
        The current attestation record read from on-chain storage. All fields
        except ``status`` are preserved verbatim in the updated record.
    payment_tx_id : str
        Payment group ID from the x402 facilitator response, used in
        error-trace logs.

    Returns
    -------
    Attestation
        A copy of ``existing`` with ``status="revoked"``, reflecting what
        was written back to the on-chain box.

    Raises
    ------
    PermissionError
        If ``payer_address`` does not match ``existing.author``. Raised
        **before** any on-chain call so no ALGO is consumed.
    RuntimeError
        If the box update fails for any reason after payment has settled.
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
            box_references=[
                BoxReference(app_id=_get_app_id(), name=b"a:" + content_hash_bytes),
            ],
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
    Read an attestation record directly from on-chain box storage.

    Parameters
    ----------
    content_hash : str
        The ``content_hash`` used as the box key (e.g. ``sha256:abc123...``).
        The ``"a:"`` key prefix required by the contract is applied internally.

    Returns
    -------
    Attestation or None
        The deserialized ``Attestation`` if a box exists for this hash,
        or ``None`` if the box is empty or does not exist.
    """
    service_account = _get_service_account()
    app_client = _get_app_client(service_account)

    content_hash_bytes = content_hash.encode()

    result = app_client.send.call(AppClientMethodCallParams(
        method="get_attestation",
        args=[content_hash_bytes],
        box_references=[
            BoxReference(app_id=_get_app_id(), name=b"a:" + content_hash_bytes),
        ],
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


def resolve_id_from_chain(attestation_id: str) -> str | None:
    """
    Resolve an ``attestation_id`` UUID to its ``content_hash`` using the
    on-chain ``id_index`` BoxMap.

    Parameters
    ----------
    attestation_id : str
        The UUID assigned at attest time (e.g.
        ``"a00fe88e-c4fa-4d4a-92d6-043af786e4b4"``). The ``"i:"`` key prefix
        required by the contract is applied internally.

    Returns
    -------
    str or None
        The ``content_hash`` string if the id_index box exists for this UUID,
        or ``None`` if not found (the UUID has never been attested).
    """
    service_account = _get_service_account()
    app_client = _get_app_client(service_account)

    attestation_id_bytes = attestation_id.encode()

    result = app_client.send.call(AppClientMethodCallParams(
        method="resolve_id",
        args=[attestation_id_bytes],
        box_references=[
            BoxReference(app_id=_get_app_id(), name=b"i:" + attestation_id_bytes),
        ],
    ))
    abi_val = result.abi_return
    if not abi_val:
        return None
    if isinstance(abi_val, (list, bytes, bytearray)):
        raw = bytes(abi_val)
    else:
        raw = cast(bytes, abi_val)
    return raw.decode() if raw else None
