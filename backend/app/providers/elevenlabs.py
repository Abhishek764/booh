"""Fixed-host, bounded ElevenLabs text-to-speech adapter."""

from __future__ import annotations

import asyncio
import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
from collections.abc import Sequence
from threading import BoundedSemaphore, Timer
from typing import Protocol
from urllib.parse import quote

from backend.app.speech_config import ElevenLabsSettings
from backend.app.speech_contracts import (
    AUDIO_CONTENT_TYPE,
    MAX_AUDIO_BYTES,
    MAX_SPEECH_TEXT_CHARS,
    SpeechAudio,
    SpeechError,
    SpeechProvider,
)

ELEVENLABS_HOST = "api.elevenlabs.io"
ELEVENLABS_PORT = 443
ELEVENLABS_PROVIDER = "elevenlabs"
OUTPUT_FORMAT = "mp3_44100_128"
TRANSPORT_TIMEOUT_SECONDS = 10.0
_TRANSPORT_SLOTS = BoundedSemaphore(2)


class ElevenLabsProviderError(SpeechError):
    def __init__(self, code: str = "tts_provider_unavailable") -> None:
        super().__init__(code)


class ElevenLabsTransport(Protocol):
    async def synthesize(self, *, voice_id: str, model: str, text: str) -> bytes: ...


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ElevenLabsProviderError("tts_provider_unavailable")
    return remaining


def _pinned_addresses() -> Sequence[tuple[int, int, int, str, tuple[object, ...]]]:
    try:
        records = socket.getaddrinfo(
            ELEVENLABS_HOST, ELEVENLABS_PORT, type=socket.SOCK_STREAM
        )
    except Exception:
        raise ElevenLabsProviderError() from None
    if not records:
        raise ElevenLabsProviderError()
    for family, _, _, _, destination in records:
        if family not in {socket.AF_INET, socket.AF_INET6}:
            raise ElevenLabsProviderError()
        try:
            address = ipaddress.ip_address(destination[0])
        except ValueError:
            raise ElevenLabsProviderError() from None
        if not address.is_global or address.is_multicast or address.is_reserved:
            raise ElevenLabsProviderError()
    return records


class PinnedElevenLabsTransport:
    """One public DNS result set, original-host TLS, no redirects or retries."""

    def __init__(self, settings: ElevenLabsSettings) -> None:
        self._settings = settings

    async def synthesize(self, *, voice_id: str, model: str, text: str) -> bytes:
        return await asyncio.to_thread(self._request, voice_id, model, text)

    def _request(self, voice_id: str, model: str, text: str) -> bytes:
        if not _TRANSPORT_SLOTS.acquire(blocking=False):
            raise ElevenLabsProviderError("tts_provider_busy")
        connection: http.client.HTTPConnection | None = None
        sock: socket.socket | None = None
        timer: Timer | None = None

        def abort_socket() -> None:
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

        try:
            deadline = time.monotonic() + min(
                TRANSPORT_TIMEOUT_SECONDS, self._settings.timeout_seconds
            )
            family, kind, protocol, _, destination = _pinned_addresses()[0]
            sock = socket.socket(family, kind, protocol)
            sock.settimeout(_remaining(deadline))
            timer = Timer(_remaining(deadline), abort_socket)
            timer.daemon = True
            timer.start()
            sock.connect(destination)
            sock = ssl.create_default_context().wrap_socket(
                sock, server_hostname=ELEVENLABS_HOST, do_handshake_on_connect=False
            )
            sock.settimeout(_remaining(deadline))
            sock.do_handshake()
            connection = http.client.HTTPSConnection(
                ELEVENLABS_HOST, ELEVENLABS_PORT, timeout=_remaining(deadline)
            )
            connection.sock = sock
            body = json.dumps(
                {"text": text, "model_id": model},
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("ascii")
            path = f"/v1/text-to-speech/{quote(voice_id, safe='-_.~')}"
            path += f"?output_format={OUTPUT_FORMAT}"
            headers = {
                "Accept": AUDIO_CONTENT_TYPE,
                "Accept-Encoding": "identity",
                "Connection": "close",
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
                "xi-api-key": self._settings.api_key,
            }
            sock.settimeout(_remaining(deadline))
            connection.request("POST", path, body=body, headers=headers)
            sock.settimeout(_remaining(deadline))
            response = connection.getresponse()
            content_type = response.getheader("Content-Type", "")
            length = response.getheader("Content-Length")
            if (
                response.status != 200
                or not re.fullmatch(r"audio/mpeg(?:;\s*charset=utf-8)?", content_type, re.I)
                or response.getheader("Content-Encoding", "identity").lower() != "identity"
                or length is not None
                and (
                    not re.fullmatch(r"\d{1,8}", length)
                    or int(length) > MAX_AUDIO_BYTES
                )
            ):
                raise ElevenLabsProviderError()
            received = bytearray()
            while True:
                sock.settimeout(_remaining(deadline))
                chunk = response.read1(min(8192, MAX_AUDIO_BYTES + 1 - len(received)))
                if not chunk:
                    break
                received.extend(chunk)
                if len(received) > MAX_AUDIO_BYTES:
                    raise ElevenLabsProviderError()
            if not received or _remaining(deadline) <= 0:
                raise ElevenLabsProviderError()
            return bytes(received)
        except ElevenLabsProviderError:
            raise
        except Exception:
            raise ElevenLabsProviderError() from None
        finally:
            if timer is not None:
                timer.cancel()
            if connection is not None:
                connection.close()
            if sock is not None:
                sock.close()
            _TRANSPORT_SLOTS.release()


class ElevenLabsProvider(SpeechProvider):
    """Provider adapter with no request-selected host, voice, or model."""

    def __init__(
        self,
        settings: ElevenLabsSettings,
        transport: ElevenLabsTransport | None = None,
    ) -> None:
        settings.__post_init__()
        self._settings = settings
        self._transport = transport or PinnedElevenLabsTransport(settings)

    @property
    def provider_version(self) -> str:
        return self._settings.model

    async def synthesize(self, text: str) -> SpeechAudio:
        if self._settings.disabled:
            raise ElevenLabsProviderError("tts_disabled")
        if (
            type(text) is not str
            or not 1 <= len(text) <= MAX_SPEECH_TEXT_CHARS
            or not text.isascii()
            or any(ord(char) < 32 and char not in "\t" for char in text)
        ):
            raise ElevenLabsProviderError("invalid_speech_input")
        try:
            content = await self._transport.synthesize(
                voice_id=self._settings.voice_id,
                model=self._settings.model,
                text=text,
            )
            return SpeechAudio(
                content=content,
                content_type=AUDIO_CONTENT_TYPE,
                provider=ELEVENLABS_PROVIDER,
                provider_version=self._settings.model,
            )
        except ElevenLabsProviderError:
            raise
        except SpeechError:
            raise ElevenLabsProviderError("invalid_speech_output") from None
        except Exception:
            raise ElevenLabsProviderError() from None


__all__ = [
    "ELEVENLABS_HOST",
    "MAX_AUDIO_BYTES",
    "ElevenLabsProvider",
    "ElevenLabsProviderError",
    "PinnedElevenLabsTransport",
]
