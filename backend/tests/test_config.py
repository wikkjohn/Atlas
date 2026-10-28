import pytest

from app.config import Settings


def test_cors_origins_accept_comma_separated_values() -> None:
    settings = Settings(cors_origins="http://a.test, http://b.test")

    assert settings.cors_origins == ["http://a.test", "http://b.test"]


def test_blank_optional_values_become_none() -> None:
    settings = Settings(redis_url="  ", build_sha="")

    assert settings.redis_url is None
    assert settings.build_sha is None


@pytest.mark.parametrize(
    "raw",
    ["http://a.test,http://b.test", '["http://a.test", "http://b.test"]'],
)
def test_cors_origins_from_environment(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("ATLAS_CORS_ORIGINS", raw)

    assert Settings().cors_origins == ["http://a.test", "http://b.test"]
