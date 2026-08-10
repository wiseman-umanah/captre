"""
x402 payment configuration for Captre.

Correct API (v2.0.2):
  - RouteConfig(accepts=PaymentOption(...))  — NOT payment_options=
  - PaymentOption fields: scheme, pay_to, price, network
  - Middleware: payment_middleware(routes, server) as @app.middleware("http")
  - Payment payload injected as request.state.payment_payload
  - Server setup: x402ResourceServer + register_exact_avm_server(server)
"""

import os

from dotenv import load_dotenv
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
)

REVOKE_ROUTE_CONFIG = RouteConfig(
    accepts=PaymentOption(
        scheme="exact",
        pay_to=RECEIVER_ADDRESS,
        price=REVOKE_PRICE,
        network=NETWORK,
    ),
    description="Revoke an existing attestation (original author only)",
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
