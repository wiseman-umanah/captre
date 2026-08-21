"""
GET /verify          — free, lookup by content_hash query param
GET /attestation/:id — free, lookup by attestation_id or content_hash
GET /attestations    — free, paginated list of all attestations (newest first)

Lookup order for GET /attestation/:id:
  1. on-chain id_index box  (resolve_id: attestation_id → content_hash)
  2. try the parameter directly as a content_hash (content_hash passed as the id)
  — fully on-chain, no SQLite required

Verify calls do not contribute to leaderboard volume (free endpoints).
"""

import logging
import os

from algosdk.error import AlgodResponseError
from fastapi import APIRouter, HTTPException, Query, status

from captre.models import Attestation, VerifyResponse
from captre.settlement.write_attestation import (
    list_attestations_from_chain,
    read_attestation_from_box,
    resolve_id_from_chain,
)

_CHAIN_ERRORS = (AlgodResponseError, TimeoutError, OSError, ConnectionError)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/verify",
    response_model=VerifyResponse,
    responses={404: {"description": "No attestation found for this content_hash"}},
    summary="Verify an attestation by content hash",
    description="Free lookup. Returns full attestation details including status (active/revoked).",
)
async def verify(
    content_hash: str = Query(..., description="The content hash to verify, e.g. sha256:abc123"),
) -> VerifyResponse:
    """
    Look up an attestation by its exact ``content_hash``.

    Parameters
    ----------
    content_hash : str
        The exact hash used when the attestation was created
        (e.g. ``sha256:abc123...``). Passed as a query parameter.

    Returns
    -------
    VerifyResponse
        The matching attestation record with ``verified=True``.

    Raises
    ------
    HTTPException(404)
        If no attestation box exists for the given ``content_hash``.
    """
    try:
        attestation = read_attestation_from_box(content_hash)
    except _CHAIN_ERRORS as exc:
        logger.error("algod connectivity error on /verify: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Unable to reach the Algorand node — the request timed out or the node is "
                "temporarily unavailable. Try again in a few seconds. "
                f"(ALGOD_URL={os.environ.get('ALGOD_URL', 'unset')})"
            ),
        ) from exc
    if attestation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No attestation found for content_hash: {content_hash}",
        )
    return VerifyResponse(attestation=attestation)


@router.get(
    "/attestation/{attestation_id}",
    response_model=VerifyResponse,
    responses={404: {"description": "Attestation not found"}},
    summary="Retrieve an attestation by ID or content hash",
    description=(
        "Lookup by attestation_id (UUID) or content_hash. "
        "First checks the on-chain id_index BoxMap to resolve a UUID to its "
        "content_hash, then falls back to using the parameter directly as a "
        "content_hash. Fully on-chain — no SQLite dependency."
    ),
)
async def get_attestation(attestation_id: str) -> VerifyResponse:
    """
    Retrieve an attestation by UUID or by content hash.

    Parameters
    ----------
    attestation_id : str
        Either a UUID ``attestation_id`` (resolved via the on-chain
        ``id_index`` BoxMap) or a raw ``content_hash``.

    Returns
    -------
    VerifyResponse
        The matching attestation record with ``verified=True``.

    Raises
    ------
    HTTPException(404)
        If neither the UUID lookup nor the direct content_hash lookup finds
        a matching attestation box on-chain.
    """
    try:
        # Step 1 — on-chain id_index: resolve attestation_id UUID → content_hash
        content_hash = resolve_id_from_chain(attestation_id)
        if content_hash is not None:
            attestation = read_attestation_from_box(content_hash)
            if attestation is not None:
                return VerifyResponse(attestation=attestation)

        # Step 2 — content_hash passed directly as the id param
        attestation = read_attestation_from_box(attestation_id)
    except _CHAIN_ERRORS as exc:
        logger.error("algod connectivity error on /attestation/:id: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Unable to reach the Algorand node — the request timed out or the node is "
                "temporarily unavailable. Try again in a few seconds."
            ),
        ) from exc

    if attestation is not None:
        return VerifyResponse(attestation=attestation)

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"No attestation found for id: {attestation_id}",
    )


@router.get(
    "/attestations",
    response_model=list[Attestation],
    summary="List all attestations",
    description=(
        "Returns all attestations stored on-chain, newest first. "
        "Paginates via `limit` and `offset`. No payment required."
    ),
)
async def list_attestations(
    limit: int = Query(default=50, ge=1, le=200, description="Max records to return"),
    offset: int = Query(default=0, ge=0, description="Number of records to skip"),
) -> list[Attestation]:
    """
    List all on-chain attestations ordered by creation time (newest first).

    Enumerates box names from the deployed contract via the algod
    ``application_boxes`` endpoint, filters to attestation boxes (``a:``
    prefix), reads each value, and returns sorted results.

    Parameters
    ----------
    limit : int
        Maximum number of attestations to return (1–200). Defaults to 50.
    offset : int
        Number of sorted records to skip for pagination. Defaults to 0.

    Returns
    -------
    list[Attestation]
        Attestation records sorted newest-first. Empty list if none exist.

    Raises
    ------
    HTTPException(503)
        If the algod node is unreachable.
    """
    try:
        return list_attestations_from_chain(limit=limit, offset=offset)
    except _CHAIN_ERRORS as exc:
        logger.error("algod connectivity error on /attestations: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to reach the Algorand node. Try again in a few seconds.",
        ) from exc
