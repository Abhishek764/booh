"""Bounded auth/baby surfaces and privacy headers, including CORS/error responses."""

from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class AuthPrivacyMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        private = path.startswith("/api/v1/auth/") or path == "/api/v1/babies" or path.startswith("/api/v1/babies/")
        if scope["type"] != "http" or not private:
            await self.app(scope, receive, send)
            return

        async def private_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"] = "no-store"
                headers["Referrer-Policy"] = "no-referrer"
                headers["X-Content-Type-Options"] = "nosniff"
            await send(message)

        if len(scope.get("query_string", b"")) > 8192:
            response = JSONResponse(
                {"error": {"code": "invalid_request", "message": "The request could not be processed."}},
                status_code=400,
            )
            await response(scope, receive, private_send)
            return
        await self.app(scope, receive, private_send)
