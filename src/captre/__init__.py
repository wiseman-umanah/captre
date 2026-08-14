"""
Captre FastAPI application entry point.

Run (dev):
    uv run captre
    uv run uvicorn captre:create_app --factory --reload

Run (prod):
    uv run captre
    uv run uvicorn captre:create_app --factory --host 0.0.0.0 --port 8000
"""

import logging
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles

# NOTE: import is `x402`, NOT `x402_avm`
from x402.http.middleware.fastapi import payment_middleware

from captre.api.attest import router as attest_router
from captre.api.revoke import router as revoke_router
from captre.api.verify import router as verify_router
from captre.ui import router as ui_router
from captre.x402_config import ROUTES_CONFIG, build_x402_server

_STATIC_DIR = Path(__file__).parent / "ui" / "static"

logging.basicConfig(level=logging.INFO)


def create_app() -> FastAPI:
    """
    Construct and return the configured FastAPI application instance.

    Registers all routers (attest, verify, revoke), the root and health
    endpoints, and the x402 payment middleware. This factory is used both
    by the uvicorn entry point (``--factory`` flag) and by tests.

    Returns
    -------
    FastAPI
        A fully configured, ready-to-serve application instance.

    Notes
    -----
    The x402 middleware **must** be added after routers are registered so
    that route matching is available when payment_middleware evaluates
    incoming requests.
    """
    app = FastAPI(
        title="Captre",
        description=(
            "On-chain attestation service. "
            "Proves first claim to a content hash, settled via x402 on Algorand."
        ),
        version="0.1.0",
    )

    # Static files (CSS)
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # API routers
    app.include_router(attest_router)
    app.include_router(verify_router)
    app.include_router(revoke_router)

    # UI pages (must come after API routers so /verify etc. are not shadowed)
    app.include_router(ui_router)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    # x402 middleware — function-based, registered via @app.middleware("http")
    # Must be added after routes are registered so route matching works
    server = build_x402_server()
    middleware_fn = payment_middleware(ROUTES_CONFIG, server)

    @app.middleware("http")
    async def x402_middleware(request: Request, call_next) -> Response:
        return await middleware_fn(request, call_next)

    return app


def main() -> None:
    """
    Entry point for ``uv run captre``.

    Starts a uvicorn server in development mode (reload enabled) on
    ``0.0.0.0:8000``.
    """
    import uvicorn
    uvicorn.run("captre:create_app", factory=True, host="0.0.0.0", port=8000, reload=True)
