"""
#### New classes ImageProcessingService and ImageProcessingServiceException (image_processing_service.py)
Contains the core business logic, orchestrating `Auth`, `DbManager`, and `R2BucketHandler` on behalf of the endpoint handlers in `server.py`. Endpoint handlers call into this class rather than talking to `DbManager`/`R2BucketHandler` directly, so route code stays thin. Image manipulation itself is delegated to [`Pillow`](https://pillow.readthedocs.io/).

- `__init__(self, db: DbManager, r2: R2BucketHandler)`: Stores references to an already-initialized `DbManager` and `R2BucketHandler` (constructed once at app startup and injected here, rather than each service call opening its own clients).
- Private method `_apply_transformations(self, image: PIL.Image.Image, transformations: Transformations) -> PIL.Image.Image`: Applies the requested transformations to an in-memory `PIL.Image` in a fixed order (crop → resize → rotate → flip/mirror → filters → watermark → format/compress), returning the transformed image. Only the transformations present (non-`None`/non-default) on the `Transformations` model are applied.
- Private method `_resize(self, image: PIL.Image.Image, params: Resize) -> PIL.Image.Image`: Resizes the image to `params.width` × `params.height`.
- Private method `_crop(self, image: PIL.Image.Image, params: Crop) -> PIL.Image.Image`: Crops a `params.width` × `params.height` region starting at `(params.x, params.y)`.
- Private method `_rotate(self, image: PIL.Image.Image, degrees: float) -> PIL.Image.Image`: Rotates the image by the given number of degrees, expanding the canvas to fit.
- Private method `_flip(self, image: PIL.Image.Image) -> PIL.Image.Image`: Flips the image vertically (top/bottom).
- Private method `_mirror(self, image: PIL.Image.Image) -> PIL.Image.Image`: Mirrors the image horizontally (left/right).
- Private method `_watermark(self, image: PIL.Image.Image) -> PIL.Image.Image`: Overlays a fixed watermark asset (bundled with the app) onto the bottom-right corner of the image.
- Private method `_apply_filters(self, image: PIL.Image.Image, filters: Filters) -> PIL.Image.Image`: Applies each requested filter (`grayscale`, `sepia`) in sequence.
- Private method `_compress(self, image: PIL.Image.Image, quality: int) -> PIL.Image.Image`: Re-encodes the image at the given JPEG/WebP quality level to reduce file size.
- Private method `_extract_metadata(self, image: PIL.Image.Image) -> dict`: Reads `format`, `width`, `height`, and computes `size_bytes` from a `PIL.Image`, in the shape expected by `DbManager.create_image` / `update_image`.
- Public method `upload_image(self, user_id: int, image_bytes: BytesIO, filename: str) -> ImageRecord`: Generates a new image ID (UUID), reads metadata from the uploaded bytes via `_extract_metadata`, stores the bytes via `R2BucketHandler.create`, and persists the metadata via `DbManager.create_image`. Raises `ImageProcessingServiceException` if the file is not a valid, supported image.
- Public method `transform_image(self, image_id: str, user_id: int, transformations: Transformations) -> ImageRecord`: Confirms ownership via `DbManager.get_image`, fetches the current bytes via `R2BucketHandler.get`, applies `_apply_transformations`, writes the result back via `R2BucketHandler.update`, and updates metadata via `DbManager.update_image`. Raises `ImageProcessingServiceException` if the image is not found, not owned by `user_id`, or a transformation parameter is invalid (e.g. crop region outside image bounds).
- Public method `get_image(self, image_id: str, user_id: int, format: str | None = None) -> tuple[BytesIO, ImageRecord]`: Confirms ownership via `DbManager.get_image`, fetches bytes via `R2BucketHandler.get`. If `format` is given and differs from the stored format, converts a copy via Pillow before returning — this conversion is not persisted back to R2 or reflected in the `DbManager` record. Raises `ImageProcessingServiceException` if not found, not owned by `user_id`, or `format` is unsupported.
- Public method `list_images(self, user_id: int, page: int, limit: int) -> tuple[list[ImageRecord], int]`: Delegates directly to `DbManager.list_images`.
- Public method `delete_image(self, image_id: str, user_id: int) -> None`: Confirms ownership via `DbManager.get_image`, then deletes the object via `R2BucketHandler.delete` and the record via `DbManager.delete_image`. Raises `ImageProcessingServiceException` if not found or not owned by `user_id`.
- Will raise `ImageProcessingServiceException` on invalid credentials, missing/unauthorized images, invalid transformation parameters, or unsupported image formats — wrapping and re-raising any underlying `DbManagerException` / `R2BucketHandlerException` it catches, so `server.py` only needs to handle one exception type from this layer.
"""

import os

import bcrypt

from auth import Auth
from common import common
from image_processing_service_exception import ImageProcessingServiceException
from db_manager import DBManager, DBManagerException, UserRecord


class ImageProcessingService:
    """
    Contains the core business logic, orchestrating Auth, DbManager, and
    R2BucketHandler on behalf of the endpoint handlers in server.py.
    """

    def __init__(self, db: DBManager) -> None:
        """
        Initialize the ImageProcessingService.

        Args:
            db (DBManager): An already-initialized DBManager instance.
        """
        self._logger = common.get_logger()
        self._base_dir = common.get_base_dir()
        self._db = db

        self._logger.info("Initializing the image processing service app.")
        self._logger.info("Successfully initialized the app.")

    def register_user(self, username: str, password: str) -> UserRecord:
        """
        Hash the password and create a new user.

        Args:
            username (str): The desired username. Must be unique.
            password (str): The plaintext password to hash and store.

        Return:
            UserRecord: The newly created user.

        Raises:
            ImageProcessingServiceException: If the username is already
                taken (409), or the user could not be created (500).
        """
        self._logger.info(f"Registering user '{username}'.")

        password_hash = bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

        try:
            user = self._db.create_user(username, password_hash)
        except DBManagerException as e:
            if "Duplicate username" in str(e):
                raise ImageProcessingServiceException(
                    f"Username '{username}' already exists.", status_code=409
                )
            raise ImageProcessingServiceException(
                f"Failed to register user '{username}'. {e}", status_code=500
            )

        self._logger.info(f"Successfully registered user '{username}'.")
        return user

    def login(self, username: str, password: str) -> tuple[str, UserRecord]:
        """
        Verify credentials and issue a signed JWT.

        Args:
            username (str): The username to authenticate.
            password (str): The plaintext password to verify.

        Return:
            tuple[str, UserRecord]: The signed JWT and the authenticated user.

        Raises:
            ImageProcessingServiceException: If the username does not exist
                or the password does not match (401).
        """
        self._logger.info(f"Logging in user '{username}'.")

        try:
            password_hash = self._db.get_password_hash_by_username(username)
        except DBManagerException as e:
            raise ImageProcessingServiceException(f"Login failed. {e}", status_code=500)

        if password_hash is None:
            raise ImageProcessingServiceException(
                "Invalid username or password.", status_code=401
            )

        if not bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8")):
            raise ImageProcessingServiceException(
                "Invalid username or password.", status_code=401
            )

        user = self._db.get_user_by_username(username)
        expire_minutes = int(os.getenv("APP_JWT_TOKEN_EXPIRATION_MINUTES"))
        token = Auth.create_access_token(user_id=user.id, expire_minutes=expire_minutes)

        self._logger.info(f"Successfully logged in user '{username}'.")
        return token, user
