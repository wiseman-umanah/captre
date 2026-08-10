"""
GET /verify          — free, lookup by content_hash query param
GET /attestation/:id — free, lookup by attestation_id

Verify calls do not contribute to leaderboard volume (free endpoints).
"""

import logging

from fastapi import APIRouter, HTTPException, Query, status

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
    # Box keys are content_hash; attestation_id is stored inside the box value.
    # We can't do a direct box lookup by attestation_id without a secondary index,
    # so this endpoint requires the backend to maintain a content_hash→attestation_id
    # mapping in memory or a lightweight local store.
    # For v1, raise 501 until that index is wired up.
    # TODO: wire up attestation_id → content_hash index
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=(
            "Lookup by attestation_id requires a secondary index. "
            "Use GET /verify?content_hash=... for now."
        ),
    )
