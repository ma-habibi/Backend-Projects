"""
TODO:
  - Read about cloud DB                                     [*]
  - Rename this module to bucket handler                      [ ]
  - Set up DB backend as a module DBConnector (simple rwr)  [...]
"""
import os
import pathlib

from dotenv import load_dotenv
from io import BytesIO
from typing import Optional

import boto3

from PIL import Image

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent


class DBHandler:
    def __init__(self):
        """
        Initialize the S3-compatible API client to access cloudflare's R2 bucket.
        Provides CRUD operations on the R2 bucket specified at the `.env` file.
        """

        load_dotenv(BASE_DIR / '.env')

        self._boto3_client = boto3.client(
            "s3",
            endpoint_url=f"https://{os.getenv('ACCOUNT_ID')}.r2.cloudflarestorage.com",
            aws_access_key_id=os.getenv("ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("SECRET_ACCESS_KEY"),
        )

        self._bucket = os.getenv("R2_BUCKET")

        print(f"Connecting to https://{os.getenv('ACCOUNT_ID')}.r2.cloudflarestorage.com")

    def get(self, image_id: str) -> Optional[BytesIO]:
        """
        Get an image by its ID.

        Args:
            image_id (str): The ID of the image to get.

        Return:
            Optional[BytesIO]: The image in memory if found.
        """

        try:
            response = self._boto3_client.get_object(
                Bucket=self._bucket,
                Key=image_id,
            )
            image_bytes: BytesIO = BytesIO(response.get("Body").read())
            image_bytes.seek(0)
            return image_bytes
        except self._boto3_client.exceptions.NoSuchKey:
            return None
        except (Exception, ):
            return None
