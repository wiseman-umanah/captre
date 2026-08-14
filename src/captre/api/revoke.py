"""
POST /revoke — x402-paid endpoint.

Authorization:
  The x402 payer address of the revoke request must match the stored `author` field.
  Comparison uses payer address decoded from the AVM payment group — NOT Algorand
  tx senders, since the service account submits all app calls regardless of who revokes.
"""

import logging

from algosdk.error import AlgodResponseError
from fastapi import APIRouter, HTTPException, Request, status

from captre.api.attest import _extract_payer
from captre.models import ErrorResponse, RevokeRequest, RevokeResponse
from captre.settlement.write_attestation import (
    read_attestation_from_box,
    resolve_id_from_chain,
    revoke_attestation,
)

_CHAIN_ERRORS = (AlgodResponseError, TimeoutError, OSError, ConnectionError)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/revoke",
    response_model=RevokeResponse,
    responses={
        403: {"model": ErrorResponse, "description": "Payer is not the original author"},
        404: {"description": "Attestation not found"},
        402: {"description": "Payment required"},
    },
    summary="Revoke an attestation",
    description=(
        "Mark an attestation as revoked. Only the original author (payer of /attest) can revoke. "
        "Revoked attestations remain visible. The hash is permanently closed to new claims."
    ),
)
async def revoke(request: Request, body: RevokeRequest) -> RevokeResponse:
    """
    Handle a paid POST /revoke request.

    Parameters
    ----------
    request : Request
        The incoming FastAPI request. Must have ``request.state.payment_payload``
        set by the x402 middleware; returns 402 otherwise.
    body : RevokeRequest
        Validated JSON request body. ``attestation_id`` may be either a UUID
        or a raw ``content_hash`` — the endpoint resolves either.

    Returns
    -------
    RevokeResponse
        The updated attestation record with ``status="revoked"``.

    Raises
    ------
    HTTPException(402)
        If no payment payload is present on the request state.
    HTTPException(403)
        If the payer address does not match the original author stored on-chain.
    HTTPException(404)
        If no attestation can be found for the given ``attestation_id``.
    HTTPException(500)
        If the on-chain box update fails after payment has already settled.
    """
    payment_payload = getattr(request.state, "payment_payload", None)
    if payment_payload is None:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Payment required",
        )

    payer_address, payment_tx_id = _extract_payer(payment_payload)

    # Resolve content_hash: try as content_hash directly, then resolve via on-chain id_index.
    try:
        content_hash = body.attestation_id
        existing = read_attestation_from_box(content_hash)
        if existing is None:
            resolved = resolve_id_from_chain(body.attestation_id)
            if resolved:
                content_hash = resolved
                existing = read_attestation_from_box(content_hash)
    except _CHAIN_ERRORS as exc:
        logger.error("algod connectivity error on /revoke lookup: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Unable to reach the Algorand node — the request timed out or the node is "
                "temporarily unavailable. Try again in a few seconds."
            ),
        ) from exc
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No attestation found for: {body.attestation_id}",
        )

    try:
        updated = revoke_attestation(
            content_hash=content_hash,
            payer_address=payer_address,
            existing=existing,
            payment_tx_id=payment_tx_id,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )
    except RuntimeError as exc:
        logger.error("revoke failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )

    return RevokeResponse(attestation=updated)
