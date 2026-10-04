from __future__ import annotations

from pathlib import Path

from backend.app import server


def test_supported_server_entrypoint_disables_raw_access_logging(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(*args: object, **kwargs: object) -> None:
        captured["args"] = args
        captured.update(kwargs)

    monkeypatch.setattr(server.uvicorn, "run", fake_run)
    server.run()

    assert captured["access_log"] is False
    assert captured["log_config"] is None
    assert captured["args"] == (server.app,)

    source = Path(server.__file__).read_text(encoding="utf-8")
    assert "request_line" not in source
    assert "callback?" not in source
