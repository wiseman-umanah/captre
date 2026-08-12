"""
GET /verify          — free, lookup by content_hash query param
GET /attestation/:id — free, lookup by attestation_id (via SQLite index)

Verify calls do not contribute to leaderboard volume (free endpoints).
"""

import logging

from fastapi import APIRouter, HTTPException, Query, status

from captre.index_db import get as index_get
from captre.models import VerifyResponse
from captre.settlement.write_attestation import read_attestation_from_box

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
    summary="Retrieve an attestation by ID",
    description="Free full retrieval by attestation_id.",
)
async def get_attestation(attestation_id: str) -> VerifyResponse:
    content_hash = index_get(attestation_id)
    if content_hash is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No attestation found for id: {attestation_id}",
        )
    attestation = read_attestation_from_box(content_hash)
    if attestation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No attestation found for id: {attestation_id}",
        )
    return VerifyResponse(attestation=attestation)
