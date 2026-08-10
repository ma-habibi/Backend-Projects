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

from logger import logger

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent


class DBHandler:
    def __init__(self):
        """
        Initialize the S3-compatible API client to access cloudflare's R2 bucket.
        Provides CRUD operations on the R2 bucket specified at the `.env` file.
        """
        load_dotenv(BASE_DIR / ".env")

        self._boto3_client = boto3.client(
            "s3",
            endpoint_url=f"https://{os.getenv('ACCOUNT_ID')}.r2.cloudflarestorage.com",
            aws_access_key_id=os.getenv("ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("SECRET_ACCESS_KEY"),
        )

        self._bucket = os.getenv("R2_BUCKET")

        logger.info(
            f"Connecting to https://{os.getenv('ACCOUNT_ID')}.r2.cloudflarestorage.com"
        )

    def _list_images(self) -> list[str]:
        """
        Get a list of all the objects (images) in the bucket.

        Returns:
            list[str]: The list of objects (images).
        """
        try:
            logger.info(f"Listing images in '{self._bucket}'.")
            response = self._boto3_client.list_objects_v2(
                Bucket=self._bucket,
            )
            images = [
                content.get("Key", "") for content in response.get("Contents", [])
            ]
            logger.info(f"Found '{len(images)}' images.")
            return images
        except (Exception,):
            return []

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
        except (Exception,):
            return None

    def create(self, image_bytes: BytesIO, filename: str) -> None:
        """
        Create an image with the given filename (ID).

        Args:
            image_bytes (BytesIO): The image as an in-memory file.
            filename (str): The final name (ID) of the file on the R2 bucket.

        Returns:
            None

        Raises:
            Exception: If HTTP error occurred during the creation.
        """
        try:
            logger.info(f"Creating image '{filename}'.")
            existing_images = self._list_images()
            if filename in existing_images:
                logger.info("Image already exists.")
                return []

            self._boto3_client.upload_fileobj(
                image_bytes,
                self._bucket,
                filename,
                ExtraArgs={"ContentType": "image/webp"},
            )
            logger.info("Image created successfully.")
        except Exception:
            logger.error("Failed to create image")
