from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient

from claimlens.analysis import Models
from claimlens.container import Container, build_container
from claimlens.domain.models import Role
from claimlens.ml.price_book import default_price_book
from claimlens.process import register_policy
from claimlens.settings import Settings
from claimlens.synthetic.generator import SyntheticCase, generate_dataset

DEV_SECRET = "dev-only-secret-change-me-0123456789abcdef"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        backend="local",
        data_dir=tmp_path / "data",
        model_dir=tmp_path / "no-models",
    )


@pytest.fixture
def container(settings: Settings) -> Container:
    c = build_container(settings)
    c.models = Models(price_book=default_price_book())  # no risk model: fast, deterministic
    return c


@pytest.fixture(scope="session")
def cases() -> list[SyntheticCase]:
    return generate_dataset(120, seed=2024, tenant_id="t1")


def make_token(
    subject: str,
    tenant: str,
    role: Role,
    secret: str = DEV_SECRET,
    expires: timedelta = timedelta(hours=1),
    **extra: object,
) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": subject,
        "tenant_id": tenant,
        "roles": [role.value],
        "aud": "claimlens-dev",
        "iat": now,
        "exp": now + expires,
        **extra,
    }
    return jwt.encode(claims, secret, algorithm="HS256")


def auth(subject: str, tenant: str, role: Role) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(subject, tenant, role)}"}


@pytest.fixture
def client(container: Container) -> Iterator[TestClient]:
    from claimlens_api.deps import get_container
    from claimlens_api.main import app

    app.dependency_overrides[get_container] = lambda: container
    with TestClient(app) as tc:
        yield tc
    app.dependency_overrides.clear()


@pytest.fixture
def seeded(container: Container, cases: list[SyntheticCase]) -> SyntheticCase:
    case = cases[0]
    register_policy(container, case.policy)
    return case
