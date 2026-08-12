"""
Captre FastAPI application entry point.

Run (dev):
    uv run uvicorn captre:create_app --factory --reload

Run (prod):
    uv run uvicorn captre:create_app --factory --host 0.0.0.0 --port 8000
"""

import logging

from fastapi import FastAPI

from captre.api.attest import router as attest_router
from captre.api.revoke import router as revoke_router
from captre.api.verify import router as verify_router
from captre.x402_config import ROUTES_CONFIG, build_x402_server

# NOTE: import is `x402`, NOT `x402_avm`
from x402.http.middleware.fastapi import payment_middleware

logging.basicConfig(level=logging.INFO)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Captre",
        description=(
            "On-chain attestation service. "
            "Proves first claim to a content hash, settled via x402 on Algorand."
        ),
        version="0.1.0",
    )

    # Routers
    app.include_router(attest_router)
    app.include_router(verify_router)
    app.include_router(revoke_router)

    @app.get("/")
    async def root() -> dict:
        return {
            "name": "Captre",
            "description": "On-chain attestation service — first-claim proofs anchored on Algorand via x402",
            "version": "0.1.0",
            "endpoints": {
                "POST /attest": "Create a first-claim attestation (x402 paid)",
                "GET /verify": "Verify an attestation by content hash (free)",
                "GET /attestation/{id}": "Retrieve attestation by ID (free)",
                "POST /revoke": "Revoke an attestation — original author only (x402 paid)",
                "GET /health": "Service health check",
            },
            "docs": "http://localhost:8000/docs",
            "network": "testnet",
            "contract": {
                "app_id": 769033926,
                "explorer": "https://testnet.explorer.perawallet.app/application/769033926",
            },
        }

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    # x402 middleware — function-based, registered via @app.middleware("http")
    # Must be added after routes are registered so route matching works
    server = build_x402_server()
    middleware_fn = payment_middleware(ROUTES_CONFIG, server)

    @app.middleware("http")
    async def x402_middleware(request, call_next):
        return await middleware_fn(request, call_next)

    return app


def main() -> None:
    import uvicorn
    uvicorn.run("captre:create_app", factory=True, host="0.0.0.0", port=8000, reload=True)
