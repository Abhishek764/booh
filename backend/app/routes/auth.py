"""Thin HTTP routes for login, callback, logout, and current identity."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict

from backend.app.dependencies import get_auth_service, get_current_principal
from backend.app.services.auth import AuthError, AuthService, Principal


router = APIRouter(prefix="/auth", tags=["authentication"])


class CurrentUserResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    email: str
    csrf_token: str


def _set_session_cookies(response: Response, service: AuthService, *, session: str, csrf: str, max_age: int) -> None:
    settings = service.settings
    response.set_cookie(
        key=service.cookie_names.session,
        value=session,
        max_age=max_age,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,
        path=settings.cookie_path,
    )
    response.set_cookie(
        key=service.cookie_names.csrf,
        value=csrf,
        max_age=max_age,
        httponly=False,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,
        path=settings.cookie_path,
    )


def _clear_cookie(response: Response, service: AuthService, name: str, *, path: str, httponly: bool) -> None:
    settings = service.settings
    response.delete_cookie(
        key=name,
        path=path,
        secure=settings.session_cookie_secure,
        httponly=httponly,
        samesite=settings.session_cookie_samesite,
    )


@router.get("/login", status_code=303, include_in_schema=False)
@router.get("/google", status_code=303)
def login(request: Request, service: Annotated[AuthService, Depends(get_auth_service)]) -> RedirectResponse:
    if request.query_params:
        raise AuthError("invalid_callback")
    result = service.start_login()
    response = RedirectResponse(result.authorization_url, status_code=303)
    response.headers["Cache-Control"] = "no-store"
    settings = service.settings
    response.set_cookie(
        key=service.cookie_names.oauth_flow,
        value=result.oauth_flow_cookie,
        max_age=result.max_age,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path=settings.oauth_cookie_path,
    )
    return response


@router.get("/callback", status_code=303, include_in_schema=False)
@router.get("/google/callback", status_code=303)
def callback(
    request: Request,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> RedirectResponse:
    # Google may return these informational fields; none decide identity or redirects.
    limits = {"code": 2048, "state": 512, "error": 128, "error_description": 512,
              "scope": 1024, "authuser": 16, "prompt": 64, "hd": 255, "iss": 255}
    if any(
        key not in limits or len(value) > limits[key]
        or len(request.query_params.getlist(key)) != 1
        for key, value in request.query_params.multi_items()
    ):
        # Reject unexpected callback input rather than letting it influence policy.
        raise AuthError("invalid_callback")
    error = request.query_params.get("error")
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if (
        error is not None
        or code is None
        or len(code) > 2048
        or state is None
        or len(state) > 512
        or len(request.query_params.get("error_description", "")) > 512
        or len(request.query_params.getlist("code")) != 1
        or len(request.query_params.getlist("state")) != 1
        or len(request.query_params.getlist("error")) > 1
    ):
        raise AuthError("invalid_callback")
    result = service.complete_login(
        code=code,
        state=state,
        oauth_flow_cookie=request.cookies.get(service.cookie_names.oauth_flow),
    )
    response = RedirectResponse(result.redirect_to, status_code=303)
    response.headers["Cache-Control"] = "no-store"
    _set_session_cookies(
        response,
        service,
        session=result.session_cookie,
        csrf=result.csrf_cookie,
        max_age=result.max_age,
    )
    _clear_cookie(
        response,
        service,
        service.cookie_names.oauth_flow,
        path=service.settings.oauth_cookie_path,
        httponly=True,
    )
    return response


@router.post("/logout", status_code=204, include_in_schema=True)
def logout(
    request: Request,
    service: Annotated[AuthService, Depends(get_auth_service)],
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> Response:
    service.logout(
        session_cookie=request.cookies.get(service.cookie_names.session),
        csrf_cookie=request.cookies.get(service.cookie_names.csrf),
        csrf_header=csrf_header,
        origin=request.headers.get("origin"),
    )
    response = Response(status_code=204)
    response.headers["Cache-Control"] = "no-store"
    _clear_cookie(
        response,
        service,
        service.cookie_names.session,
        path=service.settings.cookie_path,
        httponly=True,
    )
    _clear_cookie(
        response,
        service,
        service.cookie_names.csrf,
        path=service.settings.cookie_path,
        httponly=False,
    )
    return response


@router.get("/me", response_model=CurrentUserResponse, status_code=200)
def current_user(
    request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
    principal: Annotated[Principal, Depends(get_current_principal)],
) -> CurrentUserResponse:
    response.headers["Cache-Control"] = "no-store"
    return CurrentUserResponse(
        user_id=str(principal.user_id), email=principal.email,
        csrf_token=service.csrf_token_for(principal, request.cookies.get(service.cookie_names.csrf)),
    )


__all__ = ["router"]
