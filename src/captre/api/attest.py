"""
POST /attest — x402-paid endpoint.

Payment is handled by the x402-avm middleware before this handler runs.
The middleware injects request.state.payment_payload after settlement.
Payer address is decoded from the AVM payment group (transactions[payment_index].sender).
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from x402.mechanisms.avm import decode_payment_group

from captre.models import AttestRequest, AttestResponse, ErrorResponse
from captre.settlement.write_attestation import (
    read_attestation_from_box,
    write_attestation,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _extract_payer(payment_payload: Any) -> tuple[str, str]:
    """
    Decode the payer address and a stable transaction reference from an x402
    payment payload object injected by the middleware.

    Parameters
    ----------
    payment_payload : Any
        The object attached to ``request.state.payment_payload`` by the x402
        middleware after a successful settlement. Expected to have a ``.payload``
        attribute containing a dict with ``"paymentGroup"`` (base64-encoded AVM
        transaction group) and ``"paymentIndex"`` (int index of the payment tx).

    Returns
    -------
    tuple[str, str]
        A two-element tuple of ``(payer_address, tx_id)`` where:

        * ``payer_address`` — the Algorand address of the account that signed
          the payment transaction (the true author / caller identity).
        * ``tx_id`` — the group ID of the payment transaction group, used as a
          stable reference for retry tracing. Falls back to
          ``"group-idx-<payment_index>"`` when no group ID is present.

    Notes
    -----
    This is the **only** place where the real author address should be
    extracted. Do **not** use ``Txn.sender()`` from the AVM app call — that
    is always the backend service account.
    """
    inner = payment_payload.payload
    payment_group = inner["paymentGroup"]
    payment_index = inner["paymentIndex"]
    group_info = decode_payment_group(payment_group, payment_index)
    payer = group_info.transactions[payment_index].sender
    # Use the group_id as a stable tx reference; fall back to payment_index
    tx_id = group_info.group_id or f"group-idx-{payment_index}"
    return payer, tx_id


@router.post(
    "/attest",
    response_model=AttestResponse,
    responses={
        409: {"model": ErrorResponse, "description": "content_hash already claimed"},
        402: {"description": "Payment required"},
    },
    summary="Create a first-claim attestation",
    description=(
        "Anchor a content hash on Algorand. "
        "A content_hash can only ever be claimed once — revocation does not reopen it."
    ),
)
async def attest(request: Request, body: AttestRequest) -> AttestResponse:
    """
    Handle a paid POST /attest request.

    Parameters
    ----------
    request : Request
        The incoming FastAPI request. Must have ``request.state.payment_payload``
        set by the x402 middleware; returns 402 otherwise.
    body : AttestRequest
        Validated JSON request body containing at minimum ``content_hash``.

    Returns
    -------
    AttestResponse
        The newly created attestation record wrapped in a response envelope.

    Raises
    ------
    HTTPException(402)
        If no payment payload is present on the request state.
    HTTPException(409)
        If the ``content_hash`` has already been claimed. The response detail
        contains the existing attestation.
    HTTPException(500)
        If the box write fails after payment has already settled.
    """
    # middleware injects payment_payload into request.state after settlement
    payment_payload = getattr(request.state, "payment_payload", None)
    if payment_payload is None:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Payment required",
        )

    payer_address, payment_tx_id = _extract_payer(payment_payload)

    try:
        attestation = write_attestation(
            request=body,
            payer_address=payer_address,
            payment_tx_id=payment_tx_id,
        )
    except ValueError:
        # content_hash already claimed — return 409 with the existing attestation
        existing = read_attestation_from_box(body.content_hash)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ErrorResponse(
                error="content_hash already claimed",
                existing_attestation=existing,
            ).model_dump(mode="json"),
        )
    except RuntimeError as exc:
        logger.error("attest write failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )

    return AttestResponse(attestation=attestation)
