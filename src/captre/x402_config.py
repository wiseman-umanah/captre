"""
x402 payment configuration for Captre.

Correct API (v2.0.2):
  - RouteConfig(accepts=PaymentOption(...))  — NOT payment_options=
  - PaymentOption fields: scheme, pay_to, price, network
  - Middleware: payment_middleware(routes, server) as @app.middleware("http")
  - Payment payload injected as request.state.payment_payload
  - Server setup: x402ResourceServer + register_exact_avm_server(server)
  - Bazaar discovery: extensions=declare_discovery_extension(...) on each RouteConfig
    Middleware auto-registers BazaarResourceServerExtension when it sees "bazaar" in extensions.
"""

import os

from dotenv import load_dotenv
from x402.extensions.bazaar.resource_service import (
    OutputConfig,
    declare_discovery_extension,
)
from x402.http.types import PaymentOption, RouteConfig
from x402.mechanisms.avm import ALGORAND_MAINNET_CAIP2, ALGORAND_TESTNET_CAIP2

load_dotenv()

# --- Network selection ---
_USE_MAINNET = os.environ.get("ALGORAND_NETWORK", "testnet").lower() == "mainnet"
NETWORK = ALGORAND_MAINNET_CAIP2 if _USE_MAINNET else ALGORAND_TESTNET_CAIP2

# --- Receiver wallet ---
RECEIVER_ADDRESS: str = os.environ["RECEIVER_ADDRESS"]

# --- Pricing ---
ATTEST_PRICE: str = os.environ.get("ATTEST_PRICE", "$0.05")
REVOKE_PRICE: str = os.environ.get("REVOKE_PRICE", "$0.05")
SUBMIT_TASK_PRICE: str = os.environ.get("SUBMIT_TASK_PRICE", "$0.01")
EVALUATE_PRICE: str = os.environ.get("EVALUATE_PRICE", "$0.01")

# --- Facilitator (required by competition rules — do not change) ---
FACILITATOR_URL: str = os.environ.get(
    "FACILITATOR_URL", "https://facilitator.goplausible.xyz"
)

# --- Route configs ---
# RouteConfig takes `accepts=` (not `payment_options=`)

def _discovery(base: dict) -> dict:
    """
    Inject the required competition tag into a Bazaar discovery extension dict.

    The ``x402-global-challenge`` tag is mandatory for the endpoint to appear
    on the GoPlausible competition leaderboard. It is added at the top level of
    the ``"bazaar"`` object because the library types use ``extra="allow"``.

    Parameters
    ----------
    base : dict
        The dict returned by ``declare_discovery_extension()``, shaped as
        ``{"bazaar": {...}}``.

    Returns
    -------
    dict
        The same dict with ``base["bazaar"]["tags"]`` set to
        ``["x402-global-challenge"]``.
    """
    base["bazaar"]["tags"] = ["x402-global-challenge"]
    return base


ATTEST_ROUTE_CONFIG = RouteConfig(
    accepts=PaymentOption(
        scheme="exact",
        pay_to=RECEIVER_ADDRESS,
        price=ATTEST_PRICE,
        network=NETWORK,
        # NOTE: PaymentOption.extra is silently dropped by the library —
        # _build_payment_requirements_from_options never reads it.
        # The tag is injected via a custom money parser in build_x402_server().
    ),
    description="Create a first-claim attestation on Algorand",
    extensions=_discovery(declare_discovery_extension(
        input={
            "content_hash": "sha256:abc123...",
            "agent_id": "my-agent-v1",
            "output_type": "file",
            "description": "Optional description of the content",
            "tags": ["research", "v1"],
        },
        input_schema={
            "properties": {
                "content_hash": {"type": "string", "description": "SHA-256 hash of the content"},
                "agent_id": {"type": "string", "description": "Optional agent identifier"},
                "output_type": {
                    "type": "string",
                    "enum": ["research", "file", "decision", "code", "report", "other"],
                },
                "description": {"type": "string"},
                "model": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["content_hash"],
        },
        body_type="json",
        output=OutputConfig(
            example={
                "attestation": {
                    "attestation_id": "a00fe88e-c4fa-4d4a-92d6-043af786e4b4",
                    "author": "GFYF3KDNCMINZCDJ6KIQDV24WU2PPFMLNST4J5FBW2Z2YQFT54BOEEGJYY",
                    "content_hash": "sha256:abc123...",
                    "status": "active",
                    "tx_id": "QK5ATJTD7CDTXADBQIX4NX52EWC7GYOL3BSBN5YTJWZP5HQMXLLA",
                    "created_at": "2025-01-01T00:00:00Z",
                },
                "message": "Attestation created successfully",
            }
        ),
    )),
)

REVOKE_ROUTE_CONFIG = RouteConfig(
    accepts=PaymentOption(
        scheme="exact",
        pay_to=RECEIVER_ADDRESS,
        price=REVOKE_PRICE,
        network=NETWORK,
        # NOTE: PaymentOption.extra is silently dropped by the library.
        # Tag injected via custom money parser in build_x402_server().
    ),
    description="Revoke an existing attestation (original author only)",
    extensions=_discovery(declare_discovery_extension(
        input={
            "attestation_id": "a00fe88e-c4fa-4d4a-92d6-043af786e4b4",
        },
        input_schema={
            "properties": {
                "attestation_id": {
                    "type": "string",
                    "description": "UUID attestation_id or content_hash of the attestation to revoke",
                },
            },
            "required": ["attestation_id"],
        },
        body_type="json",
        output=OutputConfig(
            example={
                "attestation": {
                    "attestation_id": "a00fe88e-c4fa-4d4a-92d6-043af786e4b4",
                    "status": "revoked",
                },
                "message": "Attestation revoked successfully",
            }
        ),
    )),
)

SUBMIT_TASK_ROUTE_CONFIG = RouteConfig(
    accepts=PaymentOption(
        scheme="exact",
        pay_to=RECEIVER_ADDRESS,
        price=SUBMIT_TASK_PRICE,
        network=NETWORK,
    ),
    description="Submit a task for on-chain registration (proves submitter identity via wallet)",
    extensions=_discovery(declare_discovery_extension(
        input={
            "content": "Write a summary of the Algorand blockchain",
            "agent_id": "my-agent-v1",
            "description": "Optional task description",
            "tags": ["research"],
        },
        input_schema={
            "properties": {
                "content": {"type": "string", "description": "Raw task content whose SHA-256 hash is stored on-chain"},
                "agent_id": {"type": "string", "description": "Optional agent identifier"},
                "description": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["content"],
        },
        body_type="json",
        output=OutputConfig(
            example={
                "task": {
                    "task_id": "b11fe88e-c4fa-4d4a-92d6-043af786e4b4",
                    "author": "GFYF3KDNCMINZCDJ6KIQDV24WU2PPFMLNST4J5FBW2Z2YQFT54BOEEGJYY",
                    "task_hash": "sha256:abc123...",
                    "created_at": "2025-01-01T00:00:00Z",
                },
                "message": "Task submitted successfully",
            }
        ),
    )),
)

EVALUATE_ROUTE_CONFIG = RouteConfig(
    accepts=PaymentOption(
        scheme="exact",
        pay_to=RECEIVER_ADDRESS,
        price=EVALUATE_PRICE,
        network=NETWORK,
    ),
    description="Record an evaluation of an attested output (proves evaluator identity via wallet)",
    extensions=_discovery(declare_discovery_extension(
        input={
            "output_attestation_id": "a00fe88e-c4fa-4d4a-92d6-043af786e4b4",
            "content_hash": "sha256:abc123...",
            "policy_hash": "sha256:" + "a" * 64,
            "evaluation_result": "pass",
            "score": 0.95,
        },
        input_schema={
            "properties": {
                "output_attestation_id": {"type": "string", "description": "UUID of the attestation being evaluated"},
                "content_hash": {"type": "string", "description": "SHA-256 hash of the attested output"},
                "task_hash": {"type": "string", "description": "Optional SHA-256 hash of the originating task"},
                "policy_hash": {"type": "string", "description": "sha256:<64 hex chars> of the policy document"},
                "evaluation_result": {"type": "string", "enum": ["pass", "fail", "partial", "score_only"]},
                "score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "notes": {"type": "string"},
            },
            "required": ["output_attestation_id", "content_hash", "policy_hash", "evaluation_result"],
        },
        body_type="json",
        output=OutputConfig(
            example={
                "evaluation": {
                    "evaluation_id": "c22fe88e-c4fa-4d4a-92d6-043af786e4b4",
                    "evaluator": "GFYF3KDNCMINZCDJ6KIQDV24WU2PPFMLNST4J5FBW2Z2YQFT54BOEEGJYY",
                    "policy_hash": "sha256:abc123...",
                    "evaluation_result": "pass",
                    "created_at": "2025-01-01T00:00:00Z",
                },
                "message": "Evaluation recorded successfully",
            }
        ),
    )),
)

ROUTES_CONFIG = {
    "POST /attest": ATTEST_ROUTE_CONFIG,
    "POST /revoke": REVOKE_ROUTE_CONFIG,
    "POST /submit-task": SUBMIT_TASK_ROUTE_CONFIG,
    "POST /evaluate": EVALUATE_ROUTE_CONFIG,
}


def build_x402_server():
    """
    Build the x402ResourceServer with AVM exact scheme registered.

    Registers a custom money parser on the AVM scheme that injects
    ``"tag": "x402-global-challenge"`` into ``AssetAmount.extra``.

    Why this is necessary
    ---------------------
    ``PaymentOption.extra`` is structurally dropped by the library:
    ``_build_payment_requirements_from_options`` builds a ``ResourceConfig``
    from each ``PaymentOption`` but never reads ``option.extra``, so anything
    set there never reaches the wire.

    The only surviving path into ``accepts[0].extra`` in the 402 response is:

        parse_price() → AssetAmount.extra
            ↓
        PaymentRequirements.extra  (initial value)
            ↓
        enhance_payment_requirements() merges decimals/feePayer/genesis
            ↓
        wire: accepts[0].extra = {tag, decimals, feePayer, genesisHash, genesisId}

    The custom parser calls the default conversion first (to get the correct
    USDC amount and asset), then adds the tag to ``extra`` before returning.
    Called once at app startup.
    """
    from x402 import x402ResourceServer
    from x402.http.facilitator_client import HTTPFacilitatorClient
    from x402.mechanisms.avm.exact.register import register_exact_avm_server
    from x402.mechanisms.avm.exact.server import ExactAvmScheme
    from x402.schemas import AssetAmount

    facilitator = HTTPFacilitatorClient({"url": FACILITATOR_URL})
    server = x402ResourceServer(facilitator)
    register_exact_avm_server(server)

    # Inject competition tag into AssetAmount.extra — the only path that
    # survives into accepts[0].extra on the wire.
    def _tag_money_parser(amount: float, network: str) -> AssetAmount | None:
        """
        Custom money parser that adds the competition tag to AssetAmount.extra.

        Parameters
        ----------
        amount : float
            Decimal USD amount parsed from the price string.
        network : str
            CAIP-2 network string (e.g. ``"algorand:SGO1..."``).

        Returns
        -------
        AssetAmount or None
            ``AssetAmount`` with ``extra`` containing both AVM defaults and
            ``"tag": "x402-global-challenge"``. Returns ``None`` for
            non-Algorand networks so the default parser handles them.
        """
        if not network.startswith("algorand:"):
            return None
        # Get the scheme instance to call its default conversion
        from x402.mechanisms.avm.constants import DEFAULT_DECIMALS
        from x402.mechanisms.avm.utils import get_usdc_asa_id, to_atomic_amount
        asa_id = get_usdc_asa_id(network)
        atomic = to_atomic_amount(amount, DEFAULT_DECIMALS)
        return AssetAmount(
            amount=str(atomic),
            asset=str(asa_id),
            extra={
                "decimals": DEFAULT_DECIMALS,
                "tag": "x402-global-challenge",
            },
        )

    # Register on every ExactAvmScheme instance that was registered
    from x402.schemas.helpers import find_schemes_by_network
    avm_schemes = find_schemes_by_network(server._schemes, "algorand:*") or {}
    for scheme_obj in avm_schemes.values():
        if isinstance(scheme_obj, ExactAvmScheme):
            scheme_obj.register_money_parser(_tag_money_parser)

    return server
