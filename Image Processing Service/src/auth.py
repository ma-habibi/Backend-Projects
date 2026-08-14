import os
import pathlib

import jwt
from dotenv import load_dotenv

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Auth:
    def __init__(self) -> None:
        pass

    @staticmethod
    def create_access_token(user_id: str, expire: int) -> str:
        """
        Create an access token for a user.

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

        return jwt.encode(payload, os.getenv("JWT_SECRET"), algorithm="HS256")
