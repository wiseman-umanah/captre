"""
GET /verify          — free, lookup by content_hash query param
GET /attestation/:id — free, lookup by attestation_id or content_hash

Lookup order for GET /attestation/:id:
  1. on-chain id_index box  (resolve_id: attestation_id → content_hash)
  2. try the parameter directly as a content_hash (content_hash passed as the id)
  — fully on-chain, no SQLite required

Verify calls do not contribute to leaderboard volume (free endpoints).
"""

import logging

from fastapi import APIRouter, HTTPException, Query, status

from captre.models import VerifyResponse
from captre.settlement.write_attestation import read_attestation_from_box, resolve_id_from_chain

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
    attestation = read_attestation_from_box(content_hash)
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
        "First checks the local SQLite index, then falls back to querying "
        "on-chain box storage directly using the parameter as a content_hash. "
        "The on-chain fallback ensures this endpoint works even after a fresh "
        "deploy with no local database."
    ),
)
async def get_attestation(attestation_id: str) -> VerifyResponse:
    # Step 1 — on-chain id_index: resolve attestation_id UUID → content_hash
    content_hash = resolve_id_from_chain(attestation_id)
    if content_hash is not None:
        attestation = read_attestation_from_box(content_hash)
        if attestation is not None:
            return VerifyResponse(attestation=attestation)

    # Step 2 — content_hash passed directly as the id param
    attestation = read_attestation_from_box(attestation_id)
    if attestation is not None:
        return VerifyResponse(attestation=attestation)

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"No attestation found for id: {attestation_id}",
    )
