"""
#### New classes ImageProcessingService and ImageProcessingServiceException (image_processing_service.py)
Contains the core business logic, orchestrating `Auth`, `DbManager`, and `R2BucketHandler` on behalf of the endpoint handlers in `server.py`. Endpoint handlers call into this class rather than talking to `DbManager`/`R2BucketHandler` directly, so route code stays thin. Image manipulation itself is delegated to [`Pillow`](https://pillow.readthedocs.io/).

- `__init__(self, db: DbManager, r2: R2BucketHandler)`: Stores references to an already-initialized `DbManager` and `R2BucketHandler` (constructed once at app startup and injected here, rather than each service call opening its own clients).
- Public method `list_images(self, user_id: int, page: int, limit: int) -> tuple[list[ImageRecord], int]`: Delegates directly to `DbManager.list_images`.
- Public method `delete_image(self, image_id: str, user_id: int) -> None`: Confirms ownership via `DbManager.get_image`, then deletes the object via `R2BucketHandler.delete` and the record via `DbManager.delete_image`. Raises `ImageProcessingServiceException` if not found or not owned by `user_id`.
- Will raise `ImageProcessingServiceException` on invalid credentials, missing/unauthorized images, invalid transformation parameters, or unsupported image formats — wrapping and re-raising any underlying `DbManagerException` / `R2BucketHandlerException` it catches, so `server.py` only needs to handle one exception type from this layer.
"""

import os
from io import BytesIO
from typing import Optional

import bcrypt
from PIL import Image, ImageOps, UnidentifiedImageError

from .image_processing_service_exception import ImageProcessingServiceException
from .auth import Auth
from .common import common
from .db_manager import DBManager, DBManagerException, UserRecord, ImageRecord
from .r2_bucket_handler import R2BucketHandler, R2BucketHandlerException
from src import models


class ImageProcessingService:
    """
    Contains the core business logic, orchestrating Auth, DbManager, and
    R2BucketHandler on behalf of the endpoint handlers in server.py.
    """

    _SUPPORTED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF", "BMP"}
    _NO_ALPHA_FORMATS = {"JPEG", "BMP"}

    def __init__(self, db: DBManager, r2: R2BucketHandler) -> None:
        """
        Initialize the ImageProcessingService.

        Args:
            db (DBManager): An already-initialized DBManager instance.
            r2 (R2BucketHandler): An already-initialized R2BucketHandler
                instance.
        """
        self._logger = common.get_logger()
        self._base_dir = common.get_base_dir()
        self._db = db
        self._r2 = r2
        self._watermark_path = self._base_dir / "assets" / "watermark.png"

        self._logger.info("Initializing the image processing service app.")
        self._logger.info("Successfully initialized the app.")

    def _convert_format(self, image: Image.Image, format: str) -> Image.Image:
        """
        Set the image's target output format for the final save.

        Does not re-encode immediately; it only updates `.format`, which
        the caller uses when actually writing the bytes out. Converts to
        RGB first if the target format doesn't support an alpha channel.

        Args:
            image (PIL.Image.Image): The source image.
            format (str): The desired format (e.g. "jpeg", "png", "webp").

        Return:
            PIL.Image.Image: The image with `.format` set to the target.

        Raises:
            ValueError: If `format` is not a supported format.
        """
        target = format.strip().upper()
        if target not in self._SUPPORTED_FORMATS:
            raise ValueError(f"Unsupported format '{format}'.")

        if target in self._NO_ALPHA_FORMATS and image.mode in ("RGBA", "P"):
            image = image.convert("RGB")

        image.format = target
        return image

    def _extract_metadata(self, image: Image.Image) -> dict:
        """
        Read format/width/height and compute size_bytes from an image.

        If the image carries a `.info["quality"]` (set by `_compress`),
        that quality is reused when measuring size_bytes, so the reported
        size matches what will actually be written to storage.

        Args:
            image (PIL.Image.Image): The image to inspect.

        Return:
            dict: {"format": str, "width": int, "height": int,
                "size_bytes": int}, in the shape expected by
                `DbManager.create_image` / `update_image`.
        """
        self._logger.info("Extracting the metadata from the image")
        fmt = (image.format or "PNG").upper()

        save_kwargs = {}
        quality = image.info.get("quality")
        if quality is not None and fmt in ("JPEG", "WEBP"):
            save_kwargs["quality"] = quality

        save_image = image
        if fmt in self._NO_ALPHA_FORMATS and save_image.mode in ("RGBA", "P"):
            save_image = save_image.convert("RGB")

        buffer = BytesIO()
        save_image.save(buffer, format=fmt, **save_kwargs)

        metadata = {
            "format": fmt.lower(),
            "width": image.width,
            "height": image.height,
            "size_bytes": buffer.tell(),
        }
        self._logger.debug(metadata)
        self._logger.debug("Successfully extracted the metadata from the image")
        return metadata

    def _encode(self, image: Image.Image) -> BytesIO:
        """
        Serialize an image to bytes using its current .format and quality.

        Shared by transform_image and get_image's on-the-fly conversion,
        so both write bytes the same way _extract_metadata measured them.

        Args:
            image (PIL.Image.Image): The image to serialize.

        Return:
            BytesIO: The encoded image bytes, seeked to position 0.
        """
        fmt = (image.format or "PNG").upper()

        save_kwargs = {}
        quality = image.info.get("quality")
        if quality is not None and fmt in ("JPEG", "WEBP"):
            save_kwargs["quality"] = quality

        save_image = image
        if fmt in self._NO_ALPHA_FORMATS and save_image.mode in ("RGBA", "P"):
            save_image = save_image.convert("RGB")

        buffer = BytesIO()
        save_image.save(buffer, format=fmt, **save_kwargs)
        buffer.seek(0)
        return buffer

    def _resize(self, image: Image.Image, params: "models.Resize") -> Image.Image:
        """
        Resize the image to params.width x params.height.

        Args:
            image (PIL.Image.Image): The source image.
            params (models.Resize): The target width/height.

        Return:
            PIL.Image.Image: The resized image.

        Raises:
            ValueError: If width or height is not positive.
        """
        width, height = int(params.width), int(params.height)
        if width <= 0 or height <= 0:
            raise ValueError("Resize width and height must be positive.")
        return image.resize((width, height))

    def _crop(self, image: Image.Image, params: "models.Crop") -> Image.Image:
        """
        Crop a params.width x params.height region starting at (x, y).

        Args:
            image (PIL.Image.Image): The source image.
            params (models.Crop): The crop region.

        Return:
            PIL.Image.Image: The cropped image.

        Raises:
            ValueError: If the crop region is outside the image bounds, or
                width/height is not positive.
        """
        x, y = int(params.x), int(params.y)
        width, height = int(params.width), int(params.height)
        if width <= 0 or height <= 0:
            raise ValueError("Crop width and height must be positive.")

        box = (x, y, x + width, y + height)
        if x < 0 or y < 0 or box[2] > image.width or box[3] > image.height:
            raise ValueError(
                f"Crop region {box} is outside image bounds "
                f"{(image.width, image.height)}."
            )
        return image.crop(box)

    def _rotate(self, image: Image.Image, degrees: float) -> Image.Image:
        """
        Rotate the image by the given number of degrees, expanding the
        canvas to fit.

        Args:
            image (PIL.Image.Image): The source image.
            degrees (float): Degrees to rotate counter-clockwise.

        Return:
            PIL.Image.Image: The rotated image.
        """
        return image.rotate(degrees, expand=True)

    def _flip(self, image: Image.Image) -> Image.Image:
        """
        Flip the image vertically (top/bottom).

        Args:
            image (PIL.Image.Image): The source image.

        Return:
            PIL.Image.Image: The flipped image.
        """
        return image.transpose(Image.FLIP_TOP_BOTTOM)

    def _mirror(self, image: Image.Image) -> Image.Image:
        """
        Mirror the image horizontally (left/right).

        Args:
            image (PIL.Image.Image): The source image.

        Return:
            PIL.Image.Image: The mirrored image.
        """
        return image.transpose(Image.FLIP_LEFT_RIGHT)

    def _watermark(self, image: Image.Image) -> Image.Image:
        """
        Overlay the bundled watermark asset onto the bottom-right corner.

        The watermark is scaled down if it's wider than 1/4 of the base
        image's width, and inset by a fixed margin from the corner.

        Args:
            image (PIL.Image.Image): The source image.

        Return:
            PIL.Image.Image: The watermarked image.

        Raises:
            FileNotFoundError: If the watermark asset is missing.
            PIL.UnidentifiedImageError: If the watermark asset is not a
                valid image.
        """
        watermark = Image.open(self._watermark_path).convert("RGBA")

        margin = 16
        max_width = max(image.width // 4, 1)
        if watermark.width > max_width:
            scale = max_width / watermark.width
            watermark = watermark.resize(
                (max_width, max(int(watermark.height * scale), 1))
            )

        base = image.convert("RGBA")
        position = (
            base.width - watermark.width - margin,
            base.height - watermark.height - margin,
        )
        base.alpha_composite(watermark, dest=position)

        return base if image.mode == "RGBA" else base.convert(image.mode)

    def _apply_filters(
        self, image: Image.Image, filters: "models.Filters"
    ) -> Image.Image:
        """
        Apply each requested filter (grayscale, sepia) in sequence.

        Args:
            image (PIL.Image.Image): The source image.
            filters (models.Filters): Which filters to apply.

        Return:
            PIL.Image.Image: The filtered image.
        """
        if filters.grayscale:
            image = ImageOps.grayscale(image)
        if filters.sepia:
            grayscale = ImageOps.grayscale(image)
            image = ImageOps.colorize(grayscale, black="#3f2f1e", white="#f5deb3")
        return image

    def _compress(self, image: Image.Image, quality: int) -> Image.Image:
        """
        Re-encode the image at the given quality level to reduce file size.

        The chosen quality is stashed on the returned image's `.info`
        dict so that `_extract_metadata` and the final save-to-storage
        step reuse the same value — otherwise the reported size_bytes
        and the actually-stored bytes could silently diverge.

        Args:
            image (PIL.Image.Image): The source image.
            quality (int): Target JPEG/WebP quality, 1-100.

        Return:
            PIL.Image.Image: The re-encoded image.

        Raises:
            ValueError: If quality is not between 1 and 100.
        """
        if not (1 <= quality <= 100):
            raise ValueError("Compress quality must be between 1 and 100.")

        save_format = (image.format or "JPEG").upper()
        if save_format not in ("JPEG", "WEBP"):
            self._logger.warning(
                f"Can't compress an image with the format {save_format}."
            )
            return image

        working_image = image
        if save_format in self._NO_ALPHA_FORMATS and working_image.mode in (
            "RGBA",
            "P",
        ):
            working_image = working_image.convert("RGB")

        buffer = BytesIO()
        working_image.save(buffer, format=save_format, quality=quality, optimize=True)
        buffer.seek(0)

        compressed_image = Image.open(buffer)
        compressed_image.load()
        compressed_image.format = save_format
        compressed_image.info["quality"] = quality
        return compressed_image

    def _apply_transformations(
        self, image: Image.Image, transformations: "models.Transformations"
    ) -> Image.Image:
        """
        Apply the requested transformations to an in-memory image.

        Fixed order: crop -> resize -> rotate -> flip/mirror -> filters ->
        watermark -> format/compress. Only transformations present
        (non-None / non-default) on `transformations` are applied.

        Args:
            image (PIL.Image.Image): The source image.
            transformations (models.Transformations): The requested
                transformations.

        Return:
            PIL.Image.Image: The transformed image.

        Raises:
            ValueError: If a transformation parameter is invalid (e.g. a
                crop region outside the image bounds, or an unsupported
                format/quality value).
        """
        if transformations.crop is not None:
            image = self._crop(image, transformations.crop)
        if transformations.resize is not None:
            image = self._resize(image, transformations.resize)
        if transformations.rotate is not None:
            image = self._rotate(image, transformations.rotate)
        if transformations.flip:
            image = self._flip(image)
        if transformations.mirror:
            image = self._mirror(image)
        if transformations.filters is not None:
            image = self._apply_filters(image, transformations.filters)
        if transformations.watermark:
            image = self._watermark(image)
        if transformations.format is not None:
            image = self._convert_format(image, transformations.format)
        if transformations.compress is not None:
            image = self._compress(image, transformations.compress)
        return image

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

    def upload_image(
        self, user_id: str, image_bytes: BytesIO, filename: str
    ) -> ImageRecord:
        """
        Validate, store, and record a newly uploaded image.

        Args:
            user_id (str): The uploading user's internal ID.
            image_bytes (BytesIO): The raw uploaded file bytes.
            filename (str): The original filename provided by the client.

        Return:
            ImageRecord: The newly created image record.

        Raises:
            ImageProcessingServiceException: If the file is not a valid,
                supported image (400), or the upload otherwise fails (500).
        """
        self._logger.info(f"Uploading image '{filename}' for user '{user_id}'.")

        raw_bytes = image_bytes.read()
        try:
            image = Image.open(BytesIO(raw_bytes))
            image.verify()
            image = Image.open(BytesIO(raw_bytes))
            image.load()
        except UnidentifiedImageError as e:
            raise ImageProcessingServiceException(
                f"'{filename}' is not a valid image file. {e}", status_code=400
            )

        if (image.format or "").upper() not in self._SUPPORTED_FORMATS:
            raise ImageProcessingServiceException(
                f"Unsupported image format '{image.format}'.", status_code=400
            )

        metadata = self._extract_metadata(image)

        try:
            record = self._db.create_image(user_id, filename, metadata)
        except DBManagerException as e:
            raise ImageProcessingServiceException(
                f"Failed to create image record. {e}", status_code=500
            )

        try:
            self._r2.create(
                BytesIO(raw_bytes),
                record.id,
                content_type=f"image/{metadata['format']}",
            )
        except R2BucketHandlerException as e:
            try:
                self._db.delete_image(record.id, user_id)
            except DBManagerException:
                pass
            raise ImageProcessingServiceException(
                f"Failed to store image bytes for '{filename}'. {e}", status_code=500
            )

        self._logger.info(f"Successfully uploaded image '{filename}' as '{record.id}'.")
        return record

    def transform_image(
        self, image_id: str, user_id: str, transformations: "models.Transformations"
    ) -> ImageRecord:
        """
        Apply transformations to an existing image and persist the result.

        Args:
            image_id (str): The image's ID.
            user_id (str): The ID of the user who must own the image.
            transformations (models.Transformations): The requested
                transformations.

        Return:
            ImageRecord: The updated image record.

        Raises:
            ImageProcessingServiceException: If the image is not found or
                not owned by user_id (404), a transformation parameter is
                invalid (400), or storage otherwise fails (500).
        """
        self._logger.info(f"Transforming image '{image_id}' for user '{user_id}'.")

        try:
            record = self._db.get_image(image_id, user_id)
        except DBManagerException as e:
            raise ImageProcessingServiceException(
                f"Failed to fetch image record. {e}", status_code=500
            )

        if record is None:
            raise ImageProcessingServiceException(
                f"Image '{image_id}' not found.", status_code=404
            )

        try:
            image_bytes = self._r2.get(record.id)
        except R2BucketHandlerException as e:
            raise ImageProcessingServiceException(
                f"Failed to fetch image bytes. {e}", status_code=500
            )

        if image_bytes is None:
            raise ImageProcessingServiceException(
                f"Image '{image_id}' bytes not found in storage.", status_code=404
            )

        image = Image.open(image_bytes)
        image.load()

        try:
            transformed_image = self._apply_transformations(image, transformations)
        except ValueError as e:
            raise ImageProcessingServiceException(
                f"Invalid transformation parameters. {e}", status_code=400
            )
        except (FileNotFoundError, UnidentifiedImageError) as e:
            raise ImageProcessingServiceException(
                f"Failed to apply watermark. {e}", status_code=500
            )

        metadata = self._extract_metadata(transformed_image)
        output_bytes = self._encode(transformed_image)

        try:
            self._r2.update(
                output_bytes, record.id, content_type=f"image/{metadata['format']}"
            )
        except R2BucketHandlerException as e:
            raise ImageProcessingServiceException(
                f"Failed to store transformed image. {e}", status_code=500
            )

        try:
            updated_record = self._db.update_image(record.id, user_id, metadata)
        except DBManagerException as e:
            raise ImageProcessingServiceException(
                f"Failed to update image record. {e}", status_code=500
            )

        self._logger.info(f"Successfully transformed image '{image_id}'.")
        return updated_record

    def get_image(
        self, image_id: str, user_id: str, format: Optional[str] = None
    ) -> tuple[BytesIO, ImageRecord]:
        """
        Fetch an image's bytes and metadata, optionally converting format.

        Args:
            image_id (str): The image's ID.
            user_id (str): The ID of the user who must own the image.
            format (Optional[str]): If given and different from the stored
                format, a one-off, non-persisted conversion is returned.

        Return:
            tuple[BytesIO, ImageRecord]: The image bytes (possibly
                converted) and its stored metadata record (never changed
                by an on-the-fly conversion).

        Raises:
            ImageProcessingServiceException: If not found or not owned by
                user_id (404), or format is unsupported (400).
        """
        self._logger.info(f"Getting image '{image_id}' for user '{user_id}'.")

        try:
            record = self._db.get_image(image_id, user_id)
        except DBManagerException as e:
            raise ImageProcessingServiceException(
                f"Failed to fetch image record. {e}", status_code=500
            )

        if record is None:
            raise ImageProcessingServiceException(
                f"Image '{image_id}' not found.", status_code=404
            )

        try:
            image_bytes = self._r2.get(record.id)
        except R2BucketHandlerException as e:
            raise ImageProcessingServiceException(
                f"Failed to fetch image bytes. {e}", status_code=500
            )

        if image_bytes is None:
            raise ImageProcessingServiceException(
                f"Image '{image_id}' bytes not found in storage.", status_code=404
            )

        if format is None or format.strip().upper() == record.format.upper():
            self._logger.info("Successfully obtained the image.")
            return image_bytes, record

        target = format.strip().upper()
        if target not in self._SUPPORTED_FORMATS:
            raise ImageProcessingServiceException(
                f"Unsupported format '{format}'.", status_code=400
            )

        try:
            image = Image.open(image_bytes)
            image.load()
            image = self._convert_format(image, target)
            converted_bytes = self._encode(image)
        except (ValueError, UnidentifiedImageError) as e:
            raise ImageProcessingServiceException(
                f"Failed to convert image to '{format}'. {e}", status_code=400
            )

        self._logger.info(f"Successfully obtained the image, converted to '{format}'.")
        return converted_bytes, record

    def list_images(
        self, user_id: str, page: int, limit: int
    ) -> tuple[list[ImageRecord], int]:
        """
        Get a paginated list of the given user's images.

        Args:
            user_id (str): The owning user's internal ID.
            page (int): The 1-indexed page number.
            limit (int): Max number of records per page.

        Return:
            tuple[list[ImageRecord], int]: The page of images, and the
                total count across all pages.

        Raises:
            ImageProcessingServiceException: If the query fails.
        """
        try:
            return self._db.list_images(user_id, page, limit)
        except DBManagerException as e:
            raise ImageProcessingServiceException(
                f"Failed to list images. {e}", status_code=500
            )

    def delete_image(self, image_id: str, user_id: str) -> None:
        """
        Delete an image's bytes and record.

        Args:
            image_id (str): The image's ID.
            user_id (str): The ID of the user who must own the image.

        Return:
            None:

        Raises:
            ImageProcessingServiceException: If not found or not owned by
                user_id (404).
        """
        self._logger.info(f"Deleting image '{image_id}' for user '{user_id}'.")

        try:
            record = self._db.get_image(image_id, user_id)
        except DBManagerException as e:
            raise ImageProcessingServiceException(
                f"Failed to fetch image record. {e}", status_code=500
            )

        if record is None:
            raise ImageProcessingServiceException(
                f"Image '{image_id}' not found.", status_code=404
            )

        try:
            self._r2.delete([record.id])
        except R2BucketHandlerException as e:
            raise ImageProcessingServiceException(
                f"Failed to delete image bytes. {e}", status_code=500
            )

        try:
            self._db.delete_image(record.id, user_id)
        except DBManagerException as e:
            raise ImageProcessingServiceException(
                f"Failed to delete image record. {e}", status_code=500
            )

        self._logger.info(f"Successfully deleted image '{image_id}'.")
