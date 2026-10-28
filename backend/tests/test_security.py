import pytest
from pydantic import ValidationError

from app.config import DEV_JWT_SECRET, Settings
from app.core.security import hash_password, verify_password


def test_password_hashing_round_trip() -> None:
    encoded = hash_password("s3cret-passphrase")

    assert encoded.startswith("scrypt$")
    assert "s3cret-passphrase" not in encoded
    assert verify_password("s3cret-passphrase", encoded)
    assert not verify_password("wrong", encoded)
    # Each hash is salted.
    assert hash_password("s3cret-passphrase") != encoded


def test_malformed_hashes_never_verify() -> None:
    for encoded in ("", "plain", "bcrypt$1$2$3$4$5", "scrypt$x$8$1$salt$key"):
        assert not verify_password("anything", encoded)


def test_production_requires_a_real_signing_secret() -> None:
    with pytest.raises(ValidationError, match="ATLAS_JWT_SECRET"):
        Settings(environment="production")
    with pytest.raises(ValidationError, match="ATLAS_JWT_SECRET"):
        Settings(environment="staging", jwt_secret="too-short")

    assert Settings(environment="production", jwt_secret="x" * 40).environment == "production"


def test_blank_secret_never_becomes_an_empty_signing_key() -> None:
    assert Settings(jwt_secret="").jwt_secret.get_secret_value() == DEV_JWT_SECRET
    with pytest.raises(ValidationError, match="ATLAS_JWT_SECRET"):
        Settings(environment="production", jwt_secret="  ")
