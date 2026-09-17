"""
GET /evaluation/:id — free endpoint, lookup by evaluation_id (UUID).

No payment required. Looks up the evaluation record from on-chain LedgerApp
box storage by UUID.
"""

import logging

from algosdk.error import AlgodResponseError
from fastapi import APIRouter, HTTPException, status

from captre.models import EvaluationRecord
from captre.settlement.write_evaluation import read_evaluation_from_box_async

_CHAIN_ERRORS = (AlgodResponseError, TimeoutError, OSError, ConnectionError)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/evaluation/{evaluation_id}",
    response_model=EvaluationRecord,
    responses={404: {"description": "Evaluation not found"}},
    summary="Retrieve an evaluation record by ID",
    description=(
        "Free lookup. Returns the full evaluation record for a given evaluation UUID."
    ),
)
async def get_evaluation(evaluation_id: str) -> EvaluationRecord:
    """
    Retrieve an evaluation record by its UUID.

    Parameters
    ----------
    evaluation_id : str
        The server-generated UUID assigned at evaluation time.

    Returns
    -------
    EvaluationRecord
        The matching evaluation record read from on-chain box storage.

    Raises
    ------
    HTTPException(404)
        If no evaluation box exists for the given UUID.
    HTTPException(503)
        If the algod node is unreachable.
    """
    try:
        evaluation = await read_evaluation_from_box_async(evaluation_id)
    except _CHAIN_ERRORS as exc:
        logger.error("algod connectivity error on /evaluation/:id: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to reach the Algorand node. Try again in a few seconds.",
        ) from exc

    if evaluation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No evaluation found for id: {evaluation_id}",
        )
    return evaluation
