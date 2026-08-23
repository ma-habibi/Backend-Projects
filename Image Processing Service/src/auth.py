import os
import pathlib
from datetime import datetime, timedelta, timezone

import jwt
from dotenv import load_dotenv
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from common import common

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
SECURITY = HTTPBearer()
ALGORITHM = "HS256"
_LOGGER = common.get_logger()


class Auth:
    """
    Handles user authentication: decoding/validating access tokens and
    issuing new ones.
    """

    @staticmethod
    def get_current_user(
        credentials: HTTPAuthorizationCredentials = Depends(SECURITY),
    ) -> str:
        """
        Decode user's access token into her internal ID while checking its expiration.

        Args:
            credentials (HTTPAuthorizationCredentials): Access token credentials.

        Returns:
            str: User's internal ID.

        Raises:
            HTTPException: When access token expired or invalid.
        """
        _LOGGER.info("Validating access token.")
        token = credentials.credentials
        try:
            payload = jwt.decode(
                token, os.getenv("APP_JWT_SECRET"), algorithms=[ALGORITHM]
            )
            user_id = payload.get("sub")
            if user_id is None:
                raise HTTPException(status_code=401, detail="Invalid token.")
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Expired token.")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Invalid token.")

        _LOGGER.info(f"Successfully validated token for user '{user_id}'.")
        return user_id

    @staticmethod
    def create_access_token(user_id: str, expire_minutes: int) -> str:
        """
        Create an access token for a user using her internal ID.

        Args:
            user_id (str): The ID of the user.
            expire_minutes (int): Minutes from now until the token expires.

        Returns:
            str: The access token.
        """
        _LOGGER.info(f"Creating access token for user '{user_id}'.")

        expire_at = datetime.now(timezone.utc) + timedelta(minutes=expire_minutes)
        payload = {
            "sub": user_id,
            "exp": expire_at,
        }
        token = jwt.encode(payload, os.getenv("APP_JWT_SECRET"), algorithm=ALGORITHM)

        _LOGGER.info(f"Successfully created access token for user '{user_id}'.")
        return token
