"""
agents/researcher.py — ResearcherAgent

Simulates an AI research agent that follows the full Captre provenance chain:
  1. Registers the task on-chain via POST /submit-task (proves task existed first).
  2. Produces a research finding and attests it via POST /attest (proves authorship).
  3. Shares attestation records in the registry so the auditor can evaluate them.
  4. Revokes its second finding (simulating a retraction).

Every step is paid with the agent's own wallet — identity is proven by who signed.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from shared.captre_client import DuplicateClaimError, DuplicateTaskError, attest, revoke, submit_task
from shared.hashing import sha256
from shared.log import log
from shared.wallet import AlgorandWallet

# ── Simulated research tasks + outputs ───────────────────────────────────────
# Each entry is (slug, task_template, output_template)
_WORK: list[tuple[str, str, str]] = [
    (
        "climate-model-v1",
        "Analyse CMIP6 ensemble data and project global mean temperature anomaly by 2050. Run {ts}.",
        ("FINDING: Global mean temperature anomaly projected at +1.8°C by 2050 "
         "(95% CI: 1.4–2.3°C). Based on CMIP6 ensemble, {ts}."),
    ),
    (
        "drug-trial-interim",
        "Perform interim analysis of Compound XR-7 Phase II trial at week 12. Run {ts}.",
        ("INTERIM ANALYSIS: Compound XR-7 shows 34% reduction in biomarker at "
         "week 12 (p=0.003, n=142). Proceeding to Phase III. Run {ts}."),
    ),
]


class ResearcherAgent:
    """
    An agent that registers tasks and attests research outputs on-chain.

    Follows the full 3-step provenance chain:
    submit_task → attest → (auditor evaluates)

    Attributes
    ----------
    name : str
        Display name used in log lines.
    wallet : AlgorandWallet
        The agent's Algorand wallet (pays x402 fees, becomes on-chain author).
    """

    name = "RESEARCHER"

    def __init__(self, wallet: AlgorandWallet) -> None:
        """
        Construct the ResearcherAgent.

        Parameters
        ----------
        wallet : AlgorandWallet
            The funded wallet for this agent.
        """
        self.wallet = wallet
        self._attestations: list[dict[str, Any]] = []

    def run(self, registry: dict[str, list[dict[str, Any]]]) -> None:
        """
        Execute the full researcher lifecycle.

        For each piece of work: registers the task, then attests the output.
        Then revokes the second finding (retraction simulation).
        Appends attestation records to ``registry["researcher"]``.

        Parameters
        ----------
        registry : dict[str, list[dict]]
            Shared world registry. Key ``"researcher"`` is populated with
            attestation records so the auditor can evaluate them.
        """
        registry.setdefault("researcher", [])
        log(self.name, "INFO", f"Starting — wallet {self.wallet.address[:12]}…")

        for slug, task_template, output_template in _WORK:
            ts = datetime.now(tz=UTC).isoformat()
            task_content = task_template.format(ts=ts)
            output_content = output_template.format(ts=ts)
            output_hash = sha256(output_content)

            # ── Step 1: Register the task ────────────────────────────────
            log(self.name, "TASK", f"Registering task: {slug}")
            task_hash: str | None = None
            try:
                task_resp = submit_task(
                    wallet=self.wallet,
                    content=task_content,
                    agent_id="researcher-agent-v1",
                    description=f"Research task: {slug}",
                    tags=["research", "task", slug],
                )
                task_hash = task_resp["task"]["task_hash"]
                log(
                    self.name, "SUCCESS",
                    f"Task registered: {slug}",
                    detail=f"task_id={task_resp['task']['task_id'][:8]}…",
                )
            except DuplicateTaskError as exc:
                task_hash = exc.existing.get("task_hash")
                log(self.name, "INFO", f"Task already registered (re-run): {slug}")
            except Exception as exc:  # noqa: BLE001
                log(self.name, "ERROR", f"Failed to register task {slug}: {exc}")

            time.sleep(1)

            # ── Step 2: Attest the output ────────────────────────────────
            log(self.name, "ATTEST", f"Attesting output: {slug}", detail=output_hash[:30] + "…")
            try:
                resp = attest(
                    wallet=self.wallet,
                    content_hash=output_hash,
                    agent_id="researcher-agent-v1",
                    output_type="research",
                    description=f"Research finding: {slug}",
                    tags=["research", "automated", slug],
                    extra={
                        "content_preview": output_content[:120],
                        **({"task_hash": task_hash} if task_hash else {}),
                    },
                )
                record = resp["attestation"]
                # Carry task_hash in the record so the auditor can use it
                record["_task_hash"] = task_hash
                self._attestations.append(record)
                registry["researcher"].append(record)
                log(
                    self.name, "SUCCESS",
                    f"Output attested: {slug}",
                    detail=f"id={record['attestation_id'][:8]}…",
                )
            except DuplicateClaimError as exc:
                log(self.name, "INFO", f"Output already attested (re-run): {slug}",
                    detail=str(exc.existing.get("attestation_id", ""))[:12])
            except Exception as exc:  # noqa: BLE001
                log(self.name, "ERROR", f"Failed to attest output {slug}: {exc}")

            time.sleep(2)

        # ── Step 3: Revoke second finding (retraction) ───────────────────
        if len(self._attestations) >= 2:
            to_revoke = self._attestations[1]
            log(
                self.name, "REVOKE",
                "Retracting second finding (interim results superseded)",
                detail=f"id={to_revoke['attestation_id'][:8]}…",
            )
            try:
                revoke(wallet=self.wallet, attestation_id=to_revoke["attestation_id"])
                log(self.name, "SUCCESS", "Retraction confirmed on-chain.")
                to_revoke["status"] = "revoked"
            except Exception as exc:  # noqa: BLE001
                log(self.name, "ERROR", f"Retraction failed: {exc}")

        log(self.name, "INFO", "Done.")
