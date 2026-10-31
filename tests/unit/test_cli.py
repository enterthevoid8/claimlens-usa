from __future__ import annotations

from pathlib import Path

import pytest

from claimlens.cli import main


def test_register_policy_creates_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAIMLENS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLAIMLENS_MODEL_DIR", str(tmp_path / "none"))
    from claimlens.settings import get_settings

    get_settings.cache_clear()
    rc = main(
        [
            "register-policy",
            "--tenant",
            "acme",
            "--policy-id",
            "POL-1",
            "--product",
            "ppo_gold",
            "--holder",
            "Maria Garcia",
            "--start-date",
            "2025-01-01",
            "--network-provider",
            "Riverside Regional Medical Center",
        ]
    )
    get_settings.cache_clear()
    assert rc == 0
    saved = tmp_path / "db" / "acme" / "policies" / "POL-1.json"
    assert saved.exists()
    assert "Riverside Regional Medical Center" in saved.read_text()


def test_register_policy_rejects_unknown_product(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAIMLENS_DATA_DIR", str(tmp_path))
    from claimlens.settings import get_settings

    get_settings.cache_clear()
    with pytest.raises(KeyError):
        main(
            [
                "register-policy",
                "--tenant",
                "acme",
                "--policy-id",
                "P",
                "--product",
                "nope",
                "--holder",
                "X",
                "--start-date",
                "2025-01-01",
            ]
        )
    get_settings.cache_clear()
