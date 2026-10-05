"""Operator-owned Gemma configuration; no request-selected hosts/models/secrets."""

from __future__ import annotations

import ipaddress
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from backend.app.config import ConfigurationError


@dataclass(frozen=True, slots=True, repr=False)
class GemmaSettings:
    app_env: str = "development"
    provider: str = "disabled"
    base_url: str = ""
    model: str = ""
    api_key: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        if self.app_env not in {"development", "test", "staging", "production", "prod"}:
            raise ConfigurationError("invalid_gemma_configuration")
        if self.provider not in {"disabled", "openai"}:
            raise ConfigurationError("invalid_gemma_configuration")
        if self.provider == "disabled":
            return
        if (
            type(self.base_url) is not str or not 1 <= len(self.base_url) <= 256
            or any(char.isspace() or char in "\\%*" for char in self.base_url)
            or type(self.model) is not str
            or not re.fullmatch(r"(?:google/)?gemma[A-Za-z0-9._:-]{0,80}", self.model, re.IGNORECASE)
            or type(self.api_key) is not str or len(self.api_key) > 4096
            or any(not 33 <= ord(char) <= 126 for char in self.api_key)
        ):
            raise ConfigurationError("invalid_gemma_configuration")
        try:
            parsed = urlsplit(self.base_url)
            port = parsed.port
        except ValueError:
            raise ConfigurationError("invalid_gemma_configuration") from None
        if (
            parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in {"", "/", "/v1", "/v1/"} or parsed.query or parsed.fragment
            or port is not None and not 1 <= port <= 65535
        ):
            raise ConfigurationError("invalid_gemma_configuration")
        local = self.app_env in {"development", "test"} and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if parsed.scheme != "https" and not local:
            raise ConfigurationError("invalid_gemma_configuration")
        if self.app_env not in {"development", "test"} and not self.api_key:
            raise ConfigurationError("invalid_gemma_configuration")
        try:
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            address = None
        if (
            address is not None
            and (not address.is_global or address.is_multicast or address.is_reserved)
            and not (local and address.is_loopback)
        ):
            raise ConfigurationError("invalid_gemma_configuration")

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> GemmaSettings:
        values = os.environ if environ is None else environ
        if values.get("GEMMA_PROVIDER") == "openai" and not values.get("APP_ENV"):
            raise ConfigurationError("invalid_gemma_configuration")
        return cls(
            app_env=values.get("APP_ENV") or "development",
            provider=values.get("GEMMA_PROVIDER") or "disabled",
            base_url=values.get("GEMMA_BASE_URL") or "",
            model=values.get("GEMMA_MODEL") or "",
            api_key=values.get("GEMMA_API_KEY") or "",
        )

    @property
    def endpoint(self) -> str:
        parsed = urlsplit(self.base_url)
        return f"{parsed.scheme}://{parsed.netloc}/v1/chat/completions"
