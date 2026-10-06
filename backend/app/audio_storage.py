"""External audio storage references with bounded, traversal-safe local backing."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol

from backend.app.speech_contracts import (
    AUDIO_CONTENT_TYPE,
    MAX_AUDIO_BYTES,
    SpeechError,
)


class AudioStorageError(SpeechError):
    def __init__(self) -> None:
        super().__init__("audio_storage_unavailable")


class AudioStorage(Protocol):
    def put(self, key: str, content: bytes, content_type: str) -> int: ...

    def read(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...


_KEY = re.compile(r"^audio/[0-9a-f]{32}\.mp3$")


class FileAudioStorage:
    """A deployment-provided directory outside the database and web source tree."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        if type(key) is not str or _KEY.fullmatch(key) is None:
            raise AudioStorageError()
        path = (self._root / key).resolve()
        try:
            path.relative_to(self._root)
        except ValueError:
            raise AudioStorageError() from None
        return path

    def put(self, key: str, content: bytes, content_type: str) -> int:
        path = self._path(key)
        if (
            type(content) is not bytes
            or not 1 <= len(content) <= MAX_AUDIO_BYTES
            or content_type != AUDIO_CONTENT_TYPE
        ):
            raise AudioStorageError()
        try:
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with path.open("xb") as handle:
                handle.write(content)
            path.chmod(0o600)
        except Exception:
            raise AudioStorageError() from None
        return len(content)

    def read(self, key: str) -> bytes:
        path = self._path(key)
        try:
            content = path.read_bytes()
        except Exception:
            raise AudioStorageError() from None
        if not 1 <= len(content) <= MAX_AUDIO_BYTES:
            raise AudioStorageError()
        return content

    def delete(self, key: str) -> None:
        path = self._path(key)
        try:
            path.unlink(missing_ok=True)
        except Exception:
            raise AudioStorageError() from None


__all__ = ["AudioStorage", "AudioStorageError", "FileAudioStorage"]
