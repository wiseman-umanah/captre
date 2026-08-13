"""
Captre Web UI — server-rendered pages via Jinja2.

Routes
------
GET /              Landing page — hero, stats, how it works
GET /explore       Browse recent attestations (on-chain read)
GET /explore/{id}  Single attestation detail
GET /api-reference API endpoint reference with curl examples
GET /robots.txt    Crawler permission file
GET /sitemap.xml   XML sitemap for search engines
"""

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates

from captre.settlement.write_attestation import (
    read_attestation_from_box,
    resolve_id_from_chain,
)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=_TEMPLATES_DIR)

router = APIRouter(include_in_schema=False)

_NETWORK = os.environ.get("ALGORAND_NETWORK", "testnet")
_APP_ID = os.environ.get("APP_ID", "")
_EXPLORER_BASE = (
    "https://explorer.perawallet.app/application"
    if _NETWORK == "mainnet"
    else "https://testnet.explorer.perawallet.app/application"
)


def _ctx(request: Request, **extra: Any) -> dict[str, Any]:
    """
    Build the base template context shared by every page.

    Parameters
    ----------
    request : Request
        The incoming FastAPI request (required by Jinja2Templates).
    **extra : Any
        Additional key/value pairs merged into the context.

    Returns
    -------
    dict[str, Any]
        Context dict ready to pass to ``templates.TemplateResponse``.
    """
    return {
        "network": _NETWORK,
        "app_id": _APP_ID,
        "explorer_base": _EXPLORER_BASE,
        **extra,
    }


@router.get("/", response_class=HTMLResponse)
async def landing(request: Request) -> HTMLResponse:
    """
    Render the Captre landing page.

    Parameters
    ----------
    request : Request
        The incoming FastAPI request.

    Returns
    -------
    HTMLResponse
        The rendered ``index.html`` template.
    """
    return templates.TemplateResponse(request, "index.html", _ctx(request))


@router.get("/explore", response_class=HTMLResponse)
async def explore(request: Request) -> HTMLResponse:
    """
    Render the attestation explorer page.

    Shows a static guide to browsing on-chain attestations via the API.
    Direct on-chain enumeration is not available (BoxMap has no list method),
    so this page links to the verify/attestation endpoints with instructions.

    Parameters
    ----------
    request : Request
        The incoming FastAPI request.

    Returns
    -------
    HTMLResponse
        The rendered ``explore.html`` template.
    """
    return templates.TemplateResponse(request, "explore.html", _ctx(request))


@router.get("/explore/{attestation_id}", response_class=HTMLResponse)
async def explore_detail(request: Request, attestation_id: str) -> HTMLResponse:
    """
    Render the detail page for a single attestation.

    Resolves the ``attestation_id`` (UUID or content_hash) via the on-chain
    id_index BoxMap, then reads the full record. Renders a not-found state
    if the attestation does not exist rather than raising a 404, so the page
    always returns HTTP 200 with appropriate UI feedback.

    Parameters
    ----------
    request : Request
        The incoming FastAPI request.
    attestation_id : str
        UUID ``attestation_id`` or raw ``content_hash`` to look up.

    Returns
    -------
    HTMLResponse
        The rendered ``detail.html`` template with the attestation record or
        a not-found indicator.
    """
    attestation = None
    error = None

    try:
        content_hash = resolve_id_from_chain(attestation_id)
        if content_hash:
            attestation = read_attestation_from_box(content_hash)
        if attestation is None:
            attestation = read_attestation_from_box(attestation_id)
    except Exception as exc:  # noqa: BLE001
        error = str(exc)

    return templates.TemplateResponse(
        request,
        "detail.html",
        _ctx(
            request,
            attestation=attestation,
            lookup_id=attestation_id,
            error=error,
        ),
    )


@router.get("/api-reference", response_class=HTMLResponse)
async def api_reference(request: Request) -> HTMLResponse:
    """
    Render the API reference page with endpoint docs and curl examples.

    Parameters
    ----------
    request : Request
        The incoming FastAPI request.

    Returns
    -------
    HTMLResponse
        The rendered ``api_ref.html`` template.
    """
    return templates.TemplateResponse(request, "api_ref.html", _ctx(request))


@router.get("/robots.txt", response_class=PlainTextResponse)
async def robots() -> PlainTextResponse:
    """
    Serve a robots.txt that permits all crawlers.

    Returns
    -------
    PlainTextResponse
        A plain-text robots.txt body.
    """
    return PlainTextResponse(
        "User-agent: *\nAllow: /\nSitemap: /sitemap.xml\n"
    )


@router.get("/sitemap.xml", response_class=HTMLResponse)
async def sitemap(request: Request) -> HTMLResponse:
    """
    Serve an XML sitemap listing all public UI routes.

    Parameters
    ----------
    request : Request
        Used to build the absolute base URL.

    Returns
    -------
    HTMLResponse
        An ``application/xml`` response with the sitemap body.
    """
    base = str(request.base_url).rstrip("/")
    urls = ["", "/explore", "/api-reference"]
    items = "\n".join(
        f"  <url><loc>{base}{u}</loc></url>" for u in urls
    )
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{items}
</urlset>"""
    return HTMLResponse(content=xml, media_type="application/xml")
