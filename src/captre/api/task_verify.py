"""
GET /task/:id — free endpoint, lookup by task_id (UUID) or task_hash.

No payment required. Looks up the task by the task_hash stored in the
on-chain TaskApp box.
"""

import logging

from algosdk.error import AlgodResponseError
from fastapi import APIRouter, HTTPException, status

from captre.models import TaskRecord
from captre.settlement.write_task import read_task_from_box_async

_CHAIN_ERRORS = (AlgodResponseError, TimeoutError, OSError, ConnectionError)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/task/{task_hash}",
    response_model=TaskRecord,
    responses={404: {"description": "Task not found"}},
    summary="Retrieve a task record by task hash",
    description=(
        "Free lookup. Returns the full task record for a given ``sha256:<hex>`` task hash."
    ),
)
async def get_task(task_hash: str) -> TaskRecord:
    """
    Retrieve a task record by its ``sha256:<hex>`` task hash.

    Parameters
    ----------
    task_hash : str
        The ``sha256:<hex>`` hash of the task content used at submit time.

    Returns
    -------
    TaskRecord
        The matching task record read from on-chain box storage.

    Raises
    ------
    HTTPException(404)
        If no task box exists for the given hash.
    HTTPException(503)
        If the algod node is unreachable.
    """
    try:
        task = await read_task_from_box_async(task_hash)
    except _CHAIN_ERRORS as exc:
        logger.error("algod connectivity error on /task/:id: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to reach the Algorand node. Try again in a few seconds.",
        ) from exc

    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No task found for task_hash: {task_hash}",
        )
    return task
