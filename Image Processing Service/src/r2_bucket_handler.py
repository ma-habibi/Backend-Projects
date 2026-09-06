import os
from io import BytesIO
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from .common import common


class R2BucketHandlerException(Exception):
    """Raised for any R2BucketHandler failure: client initialization, or a
    failed R2 operation (upload, download, update, delete)."""


class R2BucketHandler:
    """
    An S3-compatible API client to access Cloudflare's R2 bucket.

    Provides CRUD operations on the R2 bucket specified in the .env file.
    """

    def __init__(self) -> None:
        """
        Initialize the R2BucketHandler and its S3-compatible client.

        Raises:
            R2BucketHandlerException: If a required CLOUDFLARE_* env var is
                missing, or the client fails to initialize.
        """
        self._logger = common.get_logger()
        self._base_dir = common.get_base_dir()

        self._logger.info("Initializing the R2 bucket handler.")

        account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID")
        access_key_id = os.getenv("CLOUDFLARE_ACCESS_KEY_ID")
        secret_access_key = os.getenv("CLOUDFLARE_SECRET_ACCESS_KEY")
        self._bucket = os.getenv("CLOUDFLARE_R2_BUCKET")

        if not all([account_id, access_key_id, secret_access_key, self._bucket]):
            raise R2BucketHandlerException(
                "One or more CLOUDFLARE_* environment variables are missing."
            )

        try:
            self._boto3_client = boto3.client(
                "s3",
                endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
                aws_access_key_id=access_key_id,
                aws_secret_access_key=secret_access_key,
            )
        except Exception as e:
            raise R2BucketHandlerException(
                f"Failed to initialize the bucket client. {e}"
            )

        self._logger.info("Successfully initialized the R2 bucket handler.")

    def _list_images(self) -> list[str]:
        """
        Get a list of all the objects (images) in the bucket.

        Return:
            list[str]: The list of object keys (image IDs) in the bucket.
                Not currently called by any other method — the per-key
                CRUD methods below use `_exists` (a single head_object
                call) instead, since listing the whole bucket to check one
                key doesn't scale. Kept for a future admin/reconciliation
                feature.

        Raises:
            R2BucketHandlerException: If listing the bucket fails.
        """
        self._logger.info(f"Listing images in '{self._bucket}'.")
        try:
            response = self._boto3_client.list_objects_v2(Bucket=self._bucket)
        except Exception as e:
            raise R2BucketHandlerException(f"Failed to list images. {e}")

        images = [content.get("Key", "") for content in response.get("Contents", [])]
        self._logger.info(f"Found '{len(images)}' images.")
        return images

    def _exists(self, filename: str) -> bool:
        """
        Check whether an object with the given filename (ID) exists.

        Args:
            filename (str): The object key (image ID) to check.

        Return:
            bool: True if the object exists, False otherwise.

        Raises:
            R2BucketHandlerException: If the check fails for a reason other
                than the object not existing.
        """
        try:
            self._boto3_client.head_object(Bucket=self._bucket, Key=filename)
            return True
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code")
            if error_code in ("404", "NoSuchKey"):
                return False
            raise R2BucketHandlerException(
                f"Failed to check if '{filename}' exists. {e}"
            )

    def get(self, image_id: str) -> Optional[BytesIO]:
        """
        Get an image by its ID.

        Args:
            image_id (str): The ID of the image to get.

        Return:
            Optional[BytesIO]: The image in memory, or None if not found.

        Raises:
            R2BucketHandlerException: If the download fails for a reason
                other than the object not existing.
        """
        self._logger.info(f"Getting image '{image_id}'.")
        try:
            response = self._boto3_client.get_object(Bucket=self._bucket, Key=image_id)
        except self._boto3_client.exceptions.NoSuchKey:
            self._logger.info("No such image")
            return None
        except Exception as e:
            raise R2BucketHandlerException(f"Failed to get image '{image_id}'. {e}")

        image_bytes = BytesIO(response.get("Body").read())
        image_bytes.seek(0)
        self._logger.info("Successfully obtained the image.")
        return image_bytes

    def create(
        self,
        image_bytes: BytesIO,
        filename: str,
        content_type: str = "application/octet-stream",
    ) -> None:
        """
        Create an image with the given filename (ID).

        Args:
            image_bytes (BytesIO): The image as an in-memory file.
            filename (str): The final name (ID) of the file on the R2 bucket.
            content_type (str): The MIME type to store with the object.

        Return:
            None:

        Raises:
            R2BucketHandlerException: If an image with that filename already
                exists, or the upload fails.
        """
        self._logger.info(f"Creating image '{filename}'.")

        if self._exists(filename):
            raise R2BucketHandlerException(f"Image '{filename}' already exists.")

        try:
            self._boto3_client.upload_fileobj(
                image_bytes,
                self._bucket,
                filename,
                ExtraArgs={"ContentType": content_type},
            )
        except Exception as e:
            raise R2BucketHandlerException(f"Failed to create image '{filename}'. {e}")

        self._logger.info("Successfully created the image.")

    def update(
        self,
        image_bytes: BytesIO,
        filename: str,
        content_type: str = "application/octet-stream",
    ) -> None:
        """
        Update an image with the given filename (ID).

        Args:
            image_bytes (BytesIO): The updated image as an in-memory file.
            filename (str): The name (ID) of the file on the R2 bucket.
            content_type (str): The MIME type to store with the object.

        Return:
            None:

        Raises:
            R2BucketHandlerException: If no image with that filename exists,
                or the update fails.
        """
        self._logger.info(f"Updating image '{filename}'.")

        if not self._exists(filename):
            raise R2BucketHandlerException(f"No image found for '{filename}'.")

        try:
            self._boto3_client.put_object(
                Body=image_bytes,
                Bucket=self._bucket,
                Key=filename,
                ContentType=content_type,
            )
        except Exception as e:
            raise R2BucketHandlerException(f"Failed to update image '{filename}'. {e}")

        self._logger.info("Successfully updated the image.")

    def delete(self, filenames: list[str]) -> None:
        """
        Delete images with the given filenames from the bucket.

        Args:
            filenames (list[str]): The list of image filenames (IDs) to
                delete.

        Return:
            None:

        Raises:
            R2BucketHandlerException: If the delete request fails.
        """
        self._logger.info(f"Deleting '{len(filenames)}' images.")

        if not filenames:
            self._logger.info("No filenames provided.")
            return

        try:
            response = self._boto3_client.delete_objects(
                Bucket=self._bucket,
                Delete={"Objects": [{"Key": filename} for filename in filenames]},
            )
        except Exception as e:
            raise R2BucketHandlerException(f"Failed to delete images. {e}")

        deleted_count = len(response.get("Deleted", []))
        self._logger.info(f"Deleted '{deleted_count}' images.")
