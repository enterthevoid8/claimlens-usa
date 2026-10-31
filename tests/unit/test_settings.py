import pytest
from pydantic import ValidationError

from claimlens.settings import Settings


def test_prod_refuses_dev_auth_and_local_backend() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="prod", backend="azure", auth_mode="dev")
    with pytest.raises(ValidationError):
        Settings(
            environment="prod",
            backend="local",
            auth_mode="entra",
            entra_tenant_id="t",
            entra_audience="a",
        )
    with pytest.raises(ValidationError):
        Settings(
            environment="prod", backend="azure", auth_mode="entra"
        )  # tenant and audience missing
    with pytest.raises(ValidationError):
        Settings(
            environment="prod",
            backend="azure",
            auth_mode="entra",
            entra_tenant_id="t",
            entra_audience="a",
            inline_processing=True,
        )
    ok = Settings(
        environment="prod",
        backend="azure",
        auth_mode="entra",
        entra_tenant_id="t",
        entra_audience="a",
    )
    assert ok.environment == "prod"


def test_env_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAIMLENS_MAX_UPLOAD_BYTES", "123")
    assert Settings().max_upload_bytes == 123
