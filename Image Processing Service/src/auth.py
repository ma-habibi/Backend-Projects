import os
import pathlib

import jwt
from dotenv import load_dotenv

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
SECURITY = HTTPBearer()
ALGORITHM = "HS256"
load_dotenv(BASE_DIR / ".env")


class Auth:
    def __init__(self) -> None:
        pass

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
            HTTPException (HTTPException): When access token expired or invalid.
        """
        token = credentials.credentials
        try:
            payload = jwt.decode(token, os.getenv("JWT_SECRET"), algorithms=[ALGORITHM])
            user_id = payload.get("sub")
            if user_id is None:
                raise HTTPException("Invalid token.")
            return user_id
        except jwt.ExpiredSignatureError:
            raise HTTPException("Expired token.")
        except jwt.InvalidTokenError:
            raise HTTPException("Invalid token.")

    @staticmethod
    def create_access_token(user_id: str, expire: int) -> str:
        """
        Create an access token for a user using her internal ID.

        Args:
            user_id (str): The ID of the user.
            expire (int): Token expiration time in minutes.

        Returns:
            str: The access token.
        """
        payload = {
            "sub": user_id,
            "exp": expire,
        }
        return jwt.encode(payload, os.getenv("JWT_SECRET"), algorithm=ALGORITHM)
