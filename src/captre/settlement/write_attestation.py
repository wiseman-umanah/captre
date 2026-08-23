"""
Sequential write flow for attestation and revocation.

Payment settles first (via x402-avm middleware), then this module
submits the box-write application call using the backend service account.

CRITICAL:
  - The `author` field is ALWAYS sourced from the x402 payment payload payer address.
  - Txn.sender() on the app call is always Captre's service account — useless for auth.
  - attest() writes TWO boxes atomically: attestations[content_hash] and id_index[attestation_id].
  - Both box_references must be passed — one for each box the contract touches.
  - Box key for attestations is SHA-256(content_hash_string) — 32 bytes, always within the
    64-byte Algorand box name limit. The raw content_hash string is too long to use directly.

Performance notes:
  - AlgodClient, AlgorandClient, and SigningAccount are all module-level singletons —
    constructed once at import time, reused across every request.  This avoids a TLS
    handshake on every algod call.
  - list_attestations_from_chain() uses a 30-second TTL in-memory cache so the explore
    page does not hammer algod on every visitor.
  - Box reads inside list_attestations_from_chain() are parallelised via a
    ThreadPoolExecutor so all N HTTP calls fire concurrently instead of sequentially.
  - Public functions that are called from async FastAPI route handlers are wrapped in
    async variants (*_async) that delegate via asyncio.to_thread so the event loop is
    never blocked by blocking algosdk I/O.
"""

import asyncio
import base64
import hashlib
import json
import logging
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any, cast

from algokit_utils import AlgorandClient, BoxReference, SigningAccount
from algokit_utils.applications.app_client import AppClientMethodCallParams
from algosdk.mnemonic import to_private_key
from algosdk.v2client.algod import AlgodClient
from algosdk.v2client.indexer import IndexerClient
from dotenv import load_dotenv

from captre.models import Attestation, AttestationStatus, AttestRequest

load_dotenv()
logger = logging.getLogger(__name__)

SERVICE_MNEMONIC = os.environ["SERVICE_MNEMONIC"]

# ── ARC-56 spec (loaded once at import time) ─────────────────────────────────
_ARC56_SPEC = json.loads(
    (Path(__file__).parent.parent / "contract" / "artifacts" / "CaptreApp.arc56.json").read_text()
)

# ── Module-level singletons — built once, reused on every request ─────────────
# AlgodClient uses a single persistent HTTP session (urllib3 connection pool).
# Re-creating it on every call wastes a full TLS handshake each time.
_algod_client: AlgodClient | None = None
_algorand_client: AlgorandClient | None = None
_service_account: SigningAccount | None = None
_singleton_lock = Lock()

# ── Thread pool for parallel box reads ───────────────────────────────────────
# max_workers=16 covers the typical 50-attestation explore page in one burst.
_BOX_EXECUTOR = ThreadPoolExecutor(max_workers=16, thread_name_prefix="captre-box")

# ── TTL cache for list_attestations_from_chain ────────────────────────────────
_CACHE_TTL_SECONDS = 30
_cache_lock = Lock()
_cache_result: list[Attestation] = []
_cache_expires_at: float = 0.0


def _content_hash_key(content_hash: str) -> bytes:
    """
    Derive the 32-byte box key for a ``content_hash`` string.

    The raw ``content_hash`` string (e.g. ``"sha256:<64 hex chars>"``) is 71+
    bytes. With the ``"a:"`` BoxMap prefix that exceeds Algorand's 64-byte box
    name limit. Hashing to a 32-byte SHA-256 digest keeps the box name at
    exactly 34 bytes (``"a:"`` + 32 bytes).

    This digest is used **both** as the ABI argument passed to the contract
    method and as the ``BoxReference`` name component — they must always be
    identical or the contract will look up the wrong box.

    Parameters
    ----------
    content_hash : str
        The original content hash string from the request (e.g.
        ``"sha256:abc123..."``).

    Returns
    -------
    bytes
        32-byte SHA-256 digest of the UTF-8 encoded ``content_hash``.
    """
    return hashlib.sha256(content_hash.encode()).digest()


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


def _get_algod_client() -> AlgodClient:
    """
    Return the module-level ``AlgodClient`` singleton, creating it on first call.

    The client is constructed once and shared across all subsequent calls,
    eliminating per-request TLS handshakes to the algod node.

    Returns
    -------
    AlgodClient
        A shared ``AlgodClient`` connected to the configured ``ALGOD_URL``.
    """
    global _algod_client
    if _algod_client is None:
        with _singleton_lock:
            if _algod_client is None:
                algod_url = os.environ["ALGOD_URL"]
                algod_token = os.environ.get("ALGOD_TOKEN", "")
                _algod_client = AlgodClient(algod_token, algod_url)
    return _algod_client


def _get_service_account() -> SigningAccount:
    """
    Return the module-level ``SigningAccount`` singleton, creating it on first call.

    The account is derived from ``SERVICE_MNEMONIC`` once and reused for all
    subsequent on-chain calls.

    Returns
    -------
    SigningAccount
        An algokit-utils ``SigningAccount`` whose address is the Captre service
        wallet. All on-chain app calls are submitted from this account.
    """
    global _service_account
    if _service_account is None:
        with _singleton_lock:
            if _service_account is None:
                private_key = to_private_key(SERVICE_MNEMONIC)
                _service_account = SigningAccount(private_key=private_key)
    return _service_account


def _get_algorand_client() -> AlgorandClient:
    """
    Return the module-level ``AlgorandClient`` singleton, creating it on first call.

    Shares the same ``AlgodClient`` singleton so all algokit-utils calls and
    raw algod calls use the same underlying connection pool.

    Returns
    -------
    AlgorandClient
        A shared algokit-utils ``AlgorandClient``.
    """
    global _algorand_client
    if _algorand_client is None:
        with _singleton_lock:
            if _algorand_client is None:
                indexer_url = os.environ.get("INDEXER_URL", "https://testnet-idx.algonode.cloud")
                _algorand_client = AlgorandClient.from_clients(
                    _get_algod_client(),
                    IndexerClient("", indexer_url),
                )
    return _algorand_client


def _get_app_client(service_account: SigningAccount):
    """
    Build an algokit-utils app client for the deployed CaptreApp contract.

    Uses the shared ``AlgorandClient`` singleton so no new connections are
    opened.  The app client itself is lightweight — it holds a reference to
    the shared client and the ARC-56 spec; creating it per-call is acceptable.

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
    return _get_algorand_client().client.get_app_client_by_id(
        app_spec=_ARC56_SPEC,
        app_id=_get_app_id(),
        default_sender=service_account.address,
        default_signer=service_account.signer,
    )


def _invalidate_list_cache() -> None:
    """
    Expire the ``list_attestations_from_chain`` TTL cache immediately.

    Called after a successful ``attest()`` or ``revoke()`` so the next
    explore page load reflects the change without waiting up to 30 seconds.

    Parameters
    ----------
    (none)

    Returns
    -------
    None
    """
    global _cache_expires_at
    with _cache_lock:
        _cache_expires_at = 0.0


def _read_single_box(
    algod_client: AlgodClient,
    app_id: int,
    raw_name: bytes,
) -> Attestation | None:
    """
    Fetch and deserialise one attestation box value.

    Designed to be called from a ``ThreadPoolExecutor`` worker so multiple
    boxes can be fetched concurrently.

    Parameters
    ----------
    algod_client : AlgodClient
        The shared algod client.
    app_id : int
        The deployed contract application ID.
    raw_name : bytes
        The full raw box name including the ``b"a:"`` prefix.

    Returns
    -------
    Attestation or None
        The deserialised ``Attestation`` if the box value is non-empty,
        ``None`` on any error or empty value.
    """
    try:
        box_data = cast(dict[str, Any], algod_client.application_box_by_name(app_id, raw_name))
        value_b64: str = box_data.get("value", "")
        if not value_b64:
            return None
        raw_value = base64.b64decode(value_b64)
        if not raw_value:
            return None
        return Attestation.model_validate(json.loads(raw_value.decode()))
    except Exception as exc:  # noqa: BLE001
        logger.debug("skipping malformed box %s: %s", base64.b64encode(raw_name).decode(), exc)
        return None


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
    Invalidates the list cache on success so the next explore load is fresh.

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
    now = datetime.now(tz=UTC)

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
    content_hash_key = _content_hash_key(request.content_hash)
    # content_hash_str is stored in id_index so resolve_id() can return the human-
    # readable original string; only the attestations box key uses the digest.
    content_hash_str = request.content_hash.encode()

    service_account = _get_service_account()
    app_client = _get_app_client(service_account)

    attestation_id_bytes = attestation_id.encode()
    app_id = _get_app_id()

    try:
        app_client.send.call(AppClientMethodCallParams(
            method="attest",
            args=[content_hash_key, content_hash_str, attestation_id_bytes, payer_address, metadata_json],
            box_references=[
                BoxReference(app_id=app_id, name=b"a:" + content_hash_key),
                BoxReference(app_id=app_id, name=b"i:" + attestation_id_bytes),
            ],
        ))
        logger.info(
            "attest box written | attestation_id=%s content_hash=%s author=%s",
            attestation_id,
            request.content_hash,
            payer_address,
        )
        _invalidate_list_cache()
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

    Invalidates the list cache on success so the next explore load is fresh.

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
    content_hash_key = _content_hash_key(content_hash)

    service_account = _get_service_account()
    app_client = _get_app_client(service_account)
    app_id = _get_app_id()

    try:
        app_client.send.call(AppClientMethodCallParams(
            method="revoke",
            args=[content_hash_key, payer_address, updated_json],
            box_references=[
                BoxReference(app_id=app_id, name=b"a:" + content_hash_key),
            ],
        ))
        logger.info(
            "revoke box updated | attestation_id=%s author=%s",
            existing.attestation_id,
            payer_address,
        )
        _invalidate_list_cache()
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

    content_hash_key = _content_hash_key(content_hash)
    app_id = _get_app_id()

    result = app_client.send.call(AppClientMethodCallParams(
        method="get_attestation",
        args=[content_hash_key],
        box_references=[
            BoxReference(app_id=app_id, name=b"a:" + content_hash_key),
        ],
    ))
    abi_val = result.abi_return
    if not abi_val:
        return None
    # ABI returns Bytes as list[int] from algokit; narrow explicitly before bytes()
    if isinstance(abi_val, (bytes, bytearray)):
        raw = bytes(abi_val)
    elif isinstance(abi_val, list):
        raw = bytes(cast(list[int], abi_val))
    else:
        raw = cast(bytes, abi_val)
    if not raw:
        return None
    return Attestation.model_validate(json.loads(raw.decode()))


async def read_attestation_from_box_async(content_hash: str) -> Attestation | None:
    """
    Async wrapper for ``read_attestation_from_box`` — runs in a thread.

    Prevents blocking the FastAPI event loop when called from an async
    route handler.

    Parameters
    ----------
    content_hash : str
        The ``content_hash`` to look up (e.g. ``sha256:abc123...``).

    Returns
    -------
    Attestation or None
        The deserialized ``Attestation`` if found, ``None`` otherwise.
    """
    return await asyncio.to_thread(read_attestation_from_box, content_hash)


def list_attestations_from_chain(limit: int = 50, offset: int = 0) -> list[Attestation]:
    """
    List attestations from on-chain box storage by enumerating all box names.

    Results are cached for ``_CACHE_TTL_SECONDS`` seconds (default 30 s) to
    avoid hammering the algod node on every explore page load.  The cache is
    invalidated immediately after any successful ``attest()`` or ``revoke()``.

    Box reads are parallelised via a ``ThreadPoolExecutor`` — all N
    ``application_box_by_name`` calls fire concurrently rather than
    sequentially, cutting explorer latency from O(N × RTT) to ~O(RTT).

    Parameters
    ----------
    limit : int
        Maximum number of attestations to return after sorting. Defaults to 50.
    offset : int
        Number of sorted results to skip before returning. Defaults to 0.

    Returns
    -------
    list[Attestation]
        Attestation records sorted by ``created_at`` descending (newest first).
        Returns an empty list if no boxes exist or the contract is not deployed.

    Raises
    ------
    RuntimeError
        If ``APP_ID`` is not set in the environment.
    """
    global _cache_result, _cache_expires_at

    now = time.monotonic()
    with _cache_lock:
        if now < _cache_expires_at and _cache_result:
            logger.debug("list_attestations_from_chain: cache hit")
            cached = _cache_result
            return cached[offset : offset + limit]

    algod_client = _get_algod_client()
    app_id = _get_app_id()

    # list all box names — returns {"boxes": [{"name": base64}, ...]}
    # algosdk stubs type these as bytes; cast to dict for pyright.
    try:
        result = cast(dict[str, Any], algod_client.application_boxes(app_id))
    except Exception:  # noqa: BLE001
        return []

    boxes: list[dict[str, Any]] = result.get("boxes", [])

    # Collect only attestation box names (prefix b"a:"); skip id_index boxes ("i:")
    attestation_box_names: list[bytes] = []
    for box in boxes:
        name_b64: str = box.get("name", "")
        raw_name = base64.b64decode(name_b64)
        if raw_name.startswith(b"a:"):
            attestation_box_names.append(raw_name)

    if not attestation_box_names:
        return []

    # Parallel fetch — fire all box reads concurrently via the shared executor
    attestations: list[Attestation] = []
    futures = {
        _BOX_EXECUTOR.submit(_read_single_box, algod_client, app_id, name): name
        for name in attestation_box_names
    }
    for future in as_completed(futures):
        att = future.result()
        if att is not None:
            attestations.append(att)

    # sort newest-first
    attestations.sort(key=lambda a: a.created_at, reverse=True)

    # store in cache
    with _cache_lock:
        _cache_result = attestations
        _cache_expires_at = time.monotonic() + _CACHE_TTL_SECONDS
        logger.debug("list_attestations_from_chain: cached %d records", len(attestations))

    return attestations[offset : offset + limit]


async def list_attestations_async(limit: int = 50, offset: int = 0) -> list[Attestation]:
    """
    Async wrapper for ``list_attestations_from_chain`` — runs in a thread.

    Prevents blocking the FastAPI event loop when called from an async
    route handler.

    Parameters
    ----------
    limit : int
        Maximum number of attestations to return. Defaults to 50.
    offset : int
        Number of records to skip. Defaults to 0.

    Returns
    -------
    list[Attestation]
        Attestation records sorted newest-first.
    """
    return await asyncio.to_thread(list_attestations_from_chain, limit, offset)


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
    # A UUID is 36 bytes (b"i:" + 36 = 38 bytes) — well within the 64-byte limit.
    # A raw content_hash string (e.g. "sha256:<64 hex>") is 71+ bytes; with the
    # "i:" prefix that exceeds 64 bytes and the algod node will reject the call.
    # content_hash strings are never stored in id_index, so return None immediately.
    attestation_id_bytes = attestation_id.encode()
    if len(attestation_id_bytes) + 2 > 64:  # +2 for the "i:" key_prefix
        return None

    service_account = _get_service_account()
    app_client = _get_app_client(service_account)
    app_id = _get_app_id()

    result = app_client.send.call(AppClientMethodCallParams(
        method="resolve_id",
        args=[attestation_id_bytes],
        box_references=[
            BoxReference(app_id=app_id, name=b"i:" + attestation_id_bytes),
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
    return raw.decode() if raw else None


async def resolve_id_from_chain_async(attestation_id: str) -> str | None:
    """
    Async wrapper for ``resolve_id_from_chain`` — runs in a thread.

    Prevents blocking the FastAPI event loop when called from an async
    route handler.

    Parameters
    ----------
    attestation_id : str
        The UUID or value to resolve.

    Returns
    -------
    str or None
        The ``content_hash`` string if found, ``None`` otherwise.
    """
    return await asyncio.to_thread(resolve_id_from_chain, attestation_id)
