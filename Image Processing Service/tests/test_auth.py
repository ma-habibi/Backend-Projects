from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from src.auth import Auth, ALGORITHM

SECRET = "4kYkfCyepWTQgD95FcKRd942nGdpyttpC4P3vget-xZj7s6V6aFCNkTAtsKMJeGXlbwBkqfxBoxlvV62l2c7vA"  # matches the conftest app_env fixture


def _credentials(token: str) -> HTTPAuthorizationCredentials:
    """Wrap a raw token string the way FastAPI's HTTPBearer would."""
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def _make_token(payload: dict, secret: str = SECRET) -> str:
    """Encode an arbitrary payload, bypassing Auth.create_access_token so
    tests can construct malformed/edge-case tokens directly."""
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


class TestCreateAccessToken:
    def test_token_contains_expected_claims(self):
        token = Auth.create_access_token(user_id="user-1", expire_minutes=15)
        payload = jwt.decode(token, SECRET, algorithms=[ALGORITHM])

        assert payload["sub"] == "user-1"
        assert "exp" in payload

    def test_user_id_is_coerced_to_string(self):
        token = Auth.create_access_token(user_id=42, expire_minutes=15)
        payload = jwt.decode(token, SECRET, algorithms=[ALGORITHM])

        assert payload["sub"] == "42"

    def test_expiration_reflects_expire_minutes(self):
        token = Auth.create_access_token(user_id="user-1", expire_minutes=30)
        payload = jwt.decode(token, SECRET, algorithms=[ALGORITHM])

        expected = datetime.now(timezone.utc) + timedelta(minutes=30)
        actual = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        # A few seconds of tolerance for test execution time.
        assert abs((actual - expected).total_seconds()) < 5


class TestGetCurrentUser:
    def test_valid_token_returns_user_id(self):
        token = Auth.create_access_token(user_id="user-1", expire_minutes=15)
        user_id = Auth.get_current_user(credentials=_credentials(token))
        assert user_id == "user-1"

    def test_expired_token_raises_401(self):
        expired_payload = {
            "sub": "user-1",
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
        }
        token = _make_token(expired_payload)

        with pytest.raises(HTTPException) as exc_info:
            Auth.get_current_user(credentials=_credentials(token))

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Expired token."

    def test_wrong_secret_raises_401_invalid(self):
        token = _make_token(
            {"sub": "user-1", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
            secret="4kYkfCyepWTQgD95FcKRd942nGdpyttpC4P3vget-xZj7s6V6aFCNkTAtsKMJeGXlbwBkqfxBoxlvV62l2c7vB",
        )

        with pytest.raises(HTTPException) as exc_info:
            Auth.get_current_user(credentials=_credentials(token))

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid token."

    def test_malformed_token_raises_401_invalid(self):
        with pytest.raises(HTTPException) as exc_info:
            Auth.get_current_user(credentials=_credentials("not-a-jwt-at-all"))

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid token."

    def test_missing_sub_claim_raises_401_invalid(self):
        token = _make_token(
            {"exp": datetime.now(timezone.utc) + timedelta(minutes=5)}
        )

        with pytest.raises(HTTPException) as exc_info:
            Auth.get_current_user(credentials=_credentials(token))

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid token."

    def test_token_missing_expiration_is_accepted(self):
        token = _make_token({"sub": "user-1"})
        user_id = Auth.get_current_user(credentials=_credentials(token))
        assert user_id == "user-1"
