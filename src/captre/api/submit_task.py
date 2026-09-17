"""
POST /submit-task — x402-paid endpoint.

Payment is handled by the x402-avm middleware before this handler runs.
The middleware injects request.state.payment_payload after settlement.
Payer address is decoded from the AVM payment group — this becomes the
task ``author`` field (never self-reported).
"""

import logging

from fastapi import APIRouter, HTTPException, Request, status

from captre.api.attest import _extract_payer
from captre.models import SubmitTaskRequest, SubmitTaskResponse
from captre.settlement.write_task import read_task_from_box, write_task

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/submit-task",
    response_model=SubmitTaskResponse,
    responses={
        409: {"description": "Task content already claimed"},
        402: {"description": "Payment required"},
    },
    summary="Submit a task for on-chain registration",
    description=(
        "Anchor a task's content hash on Algorand. "
        "The task content hash can only ever be claimed once. "
        "The submitter identity is proven by the x402 payment wallet."
    ),
)
async def submit_task(request: Request, body: SubmitTaskRequest) -> SubmitTaskResponse:
    """
    Handle a paid POST /submit-task request.

    Parameters
    ----------
    request : Request
        The incoming FastAPI request. Must have ``request.state.payment_payload``
        set by the x402 middleware; returns 402 otherwise.
    body : SubmitTaskRequest
        Validated JSON request body containing ``content``.

    Returns
    -------
    SubmitTaskResponse
        The newly created task record wrapped in a response envelope.

    Raises
    ------
    HTTPException(402)
        If no payment payload is present on the request state.
    HTTPException(409)
        If the task content hash has already been claimed.
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
        task = write_task(
            request=body,
            payer_address=payer_address,
            payment_tx_id=payment_tx_id,
        )
    except ValueError:
        import hashlib
        task_hash = "sha256:" + hashlib.sha256(body.content.encode()).hexdigest()
        existing = read_task_from_box(task_hash)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "task content already claimed", "existing_task": existing.model_dump(mode="json") if existing else None},
        )
    except RuntimeError as exc:
        logger.error("submit_task write failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )

    return SubmitTaskResponse(task=task)
