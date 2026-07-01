from __future__ import annotations

import os

import uvicorn
from mcp.server.transport_security import TransportSecuritySettings
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp_server.server import mcp


def _expected_key() -> str:
    key = os.environ.get("MCP_API_KEY")
    if not key:
        raise RuntimeError("Set MCP_API_KEY in the environment before starting.")
    return key


async def _require_api_key(request: Request, call_next):
    # Let unauthenticated health checks through if you want one:
    if request.url.path == "/healthz":
        return JSONResponse({"status": "ok"})

    header = request.headers.get("Authorization", "")
    token = header.removeprefix("Bearer ").strip()
    if token != _expected_key():
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    return await call_next(request)


def build_app():
    mcp.settings.stateless_http = True
    mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    )
    # The Starlette app that speaks MCP over HTTP at /mcp
    app = mcp.streamable_http_app()
    app.add_middleware(BaseHTTPMiddleware, dispatch=_require_api_key)
    return app


def main() -> None:
    _expected_key()  # fail fast if the key isn't set
    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_PORT", "8000"))
    uvicorn.run(build_app(), host=host, port=port)


if __name__ == "__main__":
    main()
