from datetime import timedelta
from uuid import uuid4

import pytest

from app.auth.principal import Principal
from app.auth.security import JwtTokenService, PasswordService, TokenType, TokenValidationError


def principal() -> Principal:
    return Principal(
        user_id=uuid4(),
        tenant_id=uuid4(),
        username="admin",
        email="admin@example.com",
        roles=frozenset({"admin"}),
    )


def token_service(*, access_ttl: timedelta = timedelta(minutes=30)) -> JwtTokenService:
    return JwtTokenService(
        secret="test-secret-that-is-longer-than-32-bytes",
        algorithm="HS256",
        issuer="test-issuer",
        audience="test-audience",
        access_ttl=access_ttl,
        refresh_ttl=timedelta(days=7),
    )


def test_password_service_hashes_and_verifies_passwords() -> None:
    service = PasswordService()
    password_hash = service.hash("correct-password")

    valid, replacement = service.verify_and_update("correct-password", password_hash)
    invalid, _ = service.verify_and_update("wrong-password", password_hash)

    assert password_hash != "correct-password"
    assert valid is True
    assert replacement is None
    assert invalid is False


def test_jwt_service_issues_separate_access_and_refresh_tokens() -> None:
    service = token_service()
    current = principal()

    pair = service.issue_pair(current)
    access = service.decode(pair.access_token, expected_type=TokenType.ACCESS)
    refresh = service.decode(pair.refresh_token, expected_type=TokenType.REFRESH)

    assert pair.access_token != pair.refresh_token
    assert pair.access_expires_in == 1800
    assert access.subject == current.user_id
    assert access.tenant_id == current.tenant_id
    assert access.roles == current.roles
    assert access.jti != refresh.jti


def test_jwt_token_types_cannot_be_interchanged() -> None:
    service = token_service()
    pair = service.issue_pair(principal())

    with pytest.raises(TokenValidationError):
        service.decode(pair.refresh_token, expected_type=TokenType.ACCESS)


def test_tampered_and_expired_tokens_are_rejected() -> None:
    service = token_service(access_ttl=timedelta(seconds=-1))
    pair = service.issue_pair(principal())

    with pytest.raises(TokenValidationError):
        service.decode(pair.access_token, expected_type=TokenType.ACCESS)

    normal_service = token_service()
    normal_pair = normal_service.issue_pair(principal())
    header, payload, signature = normal_pair.access_token.split(".")
    replacement = "A" if payload[0] != "A" else "B"
    tampered = ".".join((header, replacement + payload[1:], signature))
    with pytest.raises(TokenValidationError):
        normal_service.decode(tampered, expected_type=TokenType.ACCESS)
