"""
POST /evaluate — x402-paid endpoint.

Payment is handled by the x402-avm middleware before this handler runs.
The middleware injects request.state.payment_payload after settlement.
Payer address is decoded from the AVM payment group — this becomes the
``evaluator`` field (never self-reported).

NOTE: _extract_payer is imported from attest.py (same function, same rule as
revoke.py). Both captre.api.evaluate._extract_payer AND
captre.api.attest._extract_payer must be patched in tests.
"""

import logging

from fastapi import APIRouter, HTTPException, Request, status

from captre.api.attest import _extract_payer
from captre.models import EvaluateRequest, EvaluateResponse
from captre.settlement.write_evaluation import write_evaluation

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/evaluate",
    response_model=EvaluateResponse,
    responses={
        402: {"description": "Payment required"},
        404: {"description": "Attestation or task not found"},
        409: {"description": "Evaluation already exists"},
    },
    summary="Record an evaluation of an attested output",
    description=(
        "Write an on-chain evaluation record linking a policy hash, evaluator "
        "identity (proven by x402 payment), and settlement result to an existing "
        "attestation. The evaluator identity is the x402 payment wallet — not a "
        "self-reported field."
    ),
)
async def evaluate(request: Request, body: EvaluateRequest) -> EvaluateResponse:
    """
    Handle a paid POST /evaluate request.

    Parameters
    ----------
    request : Request
        The incoming FastAPI request. Must have ``request.state.payment_payload``
        set by the x402 middleware; returns 402 otherwise.
    body : EvaluateRequest
        Validated JSON request body. No ``evaluator`` field — identity comes
        from the x402 payment payer address.

    Returns
    -------
    EvaluateResponse
        The newly created evaluation record wrapped in a response envelope.

    Raises
    ------
    HTTPException(402)
        If no payment payload is present on the request state.
    HTTPException(404)
        If the referenced attestation or task does not exist.
    HTTPException(409)
        If this evaluation UUID has already been written.
    HTTPException(500)
        If the box write fails after payment has already settled.
    """
    payment_payload = getattr(request.state, "payment_payload", None)
    if payment_payload is None:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Payment required",
        )

    payer_address, payment_tx_id = _extract_payer(payment_payload)

    try:
        evaluation = write_evaluation(
            request=body,
            payer_address=payer_address,
            payment_tx_id=payment_tx_id,
        )
    except ValueError as exc:
        msg = str(exc)
        if "already exists" in msg:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=msg,
            )
        # attestation or task not found
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=msg,
        )
    except RuntimeError as exc:
        logger.error("evaluate write failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )

    return EvaluateResponse(evaluation=evaluation)
