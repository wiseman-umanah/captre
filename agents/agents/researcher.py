"""
agents/researcher.py — ResearcherAgent

Simulates an AI research agent that:
  1. Produces three "research summaries" (timestamped to guarantee unique hashes).
  2. Attests each one to Captre, paying the x402 fee from its wallet.
  3. Shares its attestation IDs via a shared registry so other agents can verify them.
  4. On request, revokes its second finding (simulating a retraction).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from shared.captre_client import DuplicateClaimError, attest, revoke
from shared.hashing import sha256
from shared.log import log
from shared.wallet import AlgorandWallet

# ── Simulated research outputs ───────────────────────────────────────────────
# Each entry is (slug, template) — timestamp injected at runtime to keep hashes unique
_FINDINGS: list[tuple[str, str]] = [
    (
        "climate-model-v1",
        "FINDING: Global mean temperature anomaly projected at +1.8°C by 2050 "
        "(95% CI: 1.4–2.3°C). Based on CMIP6 ensemble, {ts}.",
    ),
    (
        "drug-trial-interim",
        "INTERIM ANALYSIS: Compound XR-7 shows 34% reduction in biomarker at "
        "week 12 (p=0.003, n=142). Proceeding to Phase III. Run {ts}.",
    ),
    (
        "market-microstructure",
        "OBSERVATION: Bid-ask spread on ALGO/USDC narrows by ~18% in the 30 min "
        "following on-chain attestation events. Sample size: 47 events. {ts}.",
    ),
]


class ResearcherAgent:
    """
    An agent that produces research outputs and anchors them on-chain.

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

        Attests three findings, then revokes the second one (retraction).
        Appends all attestation records to ``registry["researcher"]``.

        Parameters
        ----------
        registry : dict[str, list[dict]]
            Shared world registry. Key ``"researcher"`` is populated with
            attestation records so the auditor can verify them.
        """
        registry.setdefault("researcher", [])
        log(self.name, "INFO", f"Starting — wallet {self.wallet.address[:12]}…")

        # ── Attest each finding ──────────────────────────────────────────
        for slug, template in _FINDINGS:
            ts = datetime.now(tz=timezone.utc).isoformat()
            content = template.format(ts=ts)
            h = sha256(content)

            log(self.name, "ATTEST", f"Attesting finding: {slug}", detail=h[:30] + "…")
            try:
                resp = attest(
                    wallet=self.wallet,
                    content_hash=h,
                    agent_id="researcher-agent-v1",
                    output_type="research",
                    description=f"Research finding: {slug}",
                    tags=["research", "automated", slug],
                    extra={"content_preview": content[:120]},
                )
                record = resp["attestation"]
                self._attestations.append(record)
                registry["researcher"].append(record)
                log(
                    self.name, "SUCCESS",
                    f"Attested {slug}",
                    detail=f"id={record['attestation_id'][:8]}…",
                )
            except DuplicateClaimError as exc:
                log(self.name, "ERROR", f"Duplicate for {slug} — already claimed", detail=str(exc.existing.get("attestation_id", ""))[:12])
            except Exception as exc:
                log(self.name, "ERROR", f"Failed to attest {slug}: {exc}")

            time.sleep(2)

        # ── Revoke the second finding (retraction) ───────────────────────
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
                # update registry record status
                to_revoke["status"] = "revoked"
            except Exception as exc:
                log(self.name, "ERROR", f"Retraction failed: {exc}")

        log(self.name, "INFO", "Done.")
