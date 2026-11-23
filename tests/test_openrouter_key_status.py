"""Offline tests of the OpenRouter metadata-only diagnostic; no API requests."""
from __future__ import annotations

import io
import runpy
from pathlib import Path


class _FakeResponse:
    def __init__(self, data):
        self._data = data

    def __enter__(self):
        return io.BytesIO(self._data)

    def __exit__(self, *_args):
        return False


def _check_main():
    script = Path(__file__).resolve().parents[1] / "scripts" / "check_openrouter_key.py"
    return runpy.run_path(str(script))["main"]


def test_key_limit_diagnostic_keeps_secrets_out_of_logs(monkeypatch, capsys):
    main = _check_main()
    key = "sk-or-v1-FICTIONAL-PRIVATE-KEY"
    monkeypatch.setenv("OPENROUTER_API_KEY", key)
    def fake_open(request, timeout):
        assert request.full_url.endswith("/api/v1/key")
        assert request.get_header("Authorization") == "Bearer " + key
        assert timeout <= 15
        return _FakeResponse(
            b'{"data":{"limit":0.10,"limit_remaining":0,'
            b'"limit_reset":"monthly","usage":0.10,'
            b'"label":"private-key-identifier",'
            b'"creator_user_id":"private-user-id"}}'
        )
    monkeypatch.setitem(main.__globals__, "urlopen", fake_open)
    assert main() == 0
    output = capsys.readouterr().out
    assert '"key_spending_cap": "configured"' in output
    assert '"key_cap_remaining": "exhausted"' in output
    assert key not in output
    assert "private" not in output
    assert "0.10" not in output


def test_uncapped_key_status_is_not_account_balance(monkeypatch, capsys):
    main = _check_main()
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key")
    monkeypatch.setitem(
        main.__globals__, "urlopen",
        lambda *_args, **_kwargs: _FakeResponse(
            b'{"data":{"limit":null,"limit_remaining":null,"usage":1.23}}'),
    )
    assert main() == 0
    output = capsys.readouterr().out
    assert '"key_spending_cap": "not_configured"' in output
    assert '"account_balance_known": false' in output


def test_no_secret_means_no_key_lookup(monkeypatch, capsys):
    main = _check_main()
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setitem(main.__globals__, "urlopen", lambda *a, **k: 1 / 0)
    assert main() == 2
    assert "missing GitHub Actions secret" in capsys.readouterr().out
