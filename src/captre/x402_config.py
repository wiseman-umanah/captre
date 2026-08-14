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

# --- Facilitator (required by competition rules — do not change) ---
FACILITATOR_URL: str = os.environ.get(
    "FACILITATOR_URL", "https://facilitator.goplausible.xyz"
)

# --- Route configs ---
# RouteConfig takes `accepts=` (not `payment_options=`)

ATTEST_ROUTE_CONFIG = RouteConfig(
    accepts=PaymentOption(
        scheme="exact",
        pay_to=RECEIVER_ADDRESS,
        price=ATTEST_PRICE,
        network=NETWORK,
    ),
    description="Create a first-claim attestation on Algorand",
    extensions=declare_discovery_extension(
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
    ),
)

REVOKE_ROUTE_CONFIG = RouteConfig(
    accepts=PaymentOption(
        scheme="exact",
        pay_to=RECEIVER_ADDRESS,
        price=REVOKE_PRICE,
        network=NETWORK,
    ),
    description="Revoke an existing attestation (original author only)",
    extensions=declare_discovery_extension(
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
    ),
)

ROUTES_CONFIG = {
    "POST /attest": ATTEST_ROUTE_CONFIG,
    "POST /revoke": REVOKE_ROUTE_CONFIG,
}


def build_x402_server():
    """
    Build the x402ResourceServer with AVM exact scheme registered.
    Called once at app startup.
    """
    from x402 import x402ResourceServer
    from x402.http.facilitator_client import HTTPFacilitatorClient
    from x402.mechanisms.avm.exact.register import register_exact_avm_server

    facilitator = HTTPFacilitatorClient({"url": FACILITATOR_URL})
    server = x402ResourceServer(facilitator)
    register_exact_avm_server(server)
    return server
