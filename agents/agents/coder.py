"""
agents/coder.py — CoderAgent

Simulates an AI coding agent that:
  1. Generates three code artefacts (function implementations, timestamped).
  2. Attests each one, tagging the second as superseding the first via
     the ``previous_attestation`` field — demonstrating the lineage chain.
  3. Shares attestation IDs in the world registry for the auditor to inspect.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from shared.captre_client import DuplicateClaimError, attest
from shared.hashing import sha256
from shared.log import log
from shared.wallet import AlgorandWallet

_ARTEFACTS: list[tuple[str, str, str]] = [
    (
        "sort-v1",
        "def sort_list(items):\n    return sorted(items)  # v1 naive, {ts}",
        "Initial naive list sort implementation",
    ),
    (
        "sort-v2",
        "def sort_list(items, reverse=False):\n    return sorted(items, key=lambda x: x, reverse=reverse)  # v2 improved, {ts}",
        "Improved sort with reverse parameter and key support",
    ),
    (
        "graph-bfs",
        "def bfs(graph, start):\n    visited, queue = set(), [start]\n    while queue:\n        node = queue.pop(0)\n        if node not in visited:\n            visited.add(node)\n            queue.extend(graph.get(node, []))\n    return visited  # {ts}",
        "Breadth-first search implementation for adjacency-list graphs",
    ),
]


class CoderAgent:
    """
    An agent that attests code artefacts, demonstrating version lineage.

    Attributes
    ----------
    name : str
        Display name used in log lines.
    wallet : AlgorandWallet
        The agent's Algorand wallet.
    """

    name = "CODER"

    def __init__(self, wallet: AlgorandWallet) -> None:
        """
        Construct the CoderAgent.

        Parameters
        ----------
        wallet : AlgorandWallet
            The funded wallet for this agent.
        """
        self.wallet = wallet
        self._attestations: list[dict[str, Any]] = []

    def run(self, registry: dict[str, list[dict[str, Any]]]) -> None:
        """
        Execute the full coder lifecycle.

        Attests three artefacts. The second artefact sets ``previous_attestation``
        to the first, showing version lineage on-chain. Appends records to
        ``registry["coder"]``.

        Parameters
        ----------
        registry : dict[str, list[dict]]
            Shared world registry. Key ``"coder"`` is populated with attestation
            records for the auditor.
        """
        registry.setdefault("coder", [])
        log(self.name, "INFO", f"Starting — wallet {self.wallet.address[:12]}…")

        prev_id: str | None = None

        for slug, template, description in _ARTEFACTS:
            ts = datetime.now(tz=timezone.utc).isoformat()
            content = template.format(ts=ts)
            h = sha256(content)

            log(self.name, "ATTEST", f"Attesting artefact: {slug}", detail=h[:30] + "…")
            try:
                resp = attest(
                    wallet=self.wallet,
                    content_hash=h,
                    agent_id="coder-agent-v1",
                    output_type="code",
                    description=description,
                    tags=["code", "automated", slug],
                    previous_attestation=prev_id,
                    extra={"language": "python", "slug": slug},
                )
                record = resp["attestation"]
                self._attestations.append(record)
                registry["coder"].append(record)
                prev_id = record["attestation_id"]
                lineage = f"supersedes={self._attestations[-2]['attestation_id'][:8]}…" if len(self._attestations) >= 2 else ""
                log(
                    self.name, "SUCCESS",
                    f"Attested {slug}",
                    detail=f"id={record['attestation_id'][:8]}…  {lineage}",
                )
            except DuplicateClaimError as exc:
                log(self.name, "ERROR", f"Duplicate for {slug}", detail=str(exc.existing.get("attestation_id", ""))[:12])
                # Keep prev_id unchanged — still useful for lineage
            except Exception as exc:
                log(self.name, "ERROR", f"Failed to attest {slug}: {exc}")

            time.sleep(2)

        log(self.name, "INFO", "Done.")
