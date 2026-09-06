import os
import sys
from io import BytesIO
from typing import Optional

import uvicorn
from fastapi import Depends, FastAPI, File, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from .auth import Auth
from .common import common
from .db_manager import DBManager, ImageRecord, UserRecord
from .db_manager_exception import DBManagerException
from .image_processing_service import ImageProcessingService
from .image_processing_service_exception import ImageProcessingServiceException
from .r2_bucket_handler import R2BucketHandler
from .r2_bucket_handler_exception import R2BucketHandlerException
from src import models


_LOGGER = common.get_logger()
_BASE_DIR = common.get_base_dir()


def _user_to_dict(user: UserRecord) -> dict:
    """
    Shape a UserRecord into the dict returned by /register and /login.

    Args:
        user (UserRecord): The user to serialize.

    Return:
        dict: {"id": ..., "username": ..., "created_at": ...}
    """
    return {
        "id": user.id,
        "username": user.username,
        "created_at": user.created_at.isoformat(),
    }


def _image_to_dict(image: ImageRecord) -> dict:
    """
    Shape an ImageRecord into the dict returned by the image endpoints.

    Includes a `url`, derived here from CLOUDFLARE_ACCOUNT_ID/
    CLOUDFLARE_R2_BUCKET and the image's ID rather than stored on
    ImageRecord itself, since the DB layer has no reason to know about
    Cloudflare-specific naming.

    Args:
        image (ImageRecord): The image to serialize.

    Return:
        dict: The image's metadata plus a derived "url".
    """
    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID")
    bucket = os.getenv("CLOUDFLARE_R2_BUCKET")

    return {
        "id": image.id,
        "user_id": image.user_id,
        "filename": image.filename,
        "format": image.format,
        "width": image.width,
        "height": image.height,
        "size_bytes": image.size_bytes,
        "url": f"https://{account_id}.r2.cloudflarestorage.com/{bucket}/{image.id}",
        "created_at": image.created_at.isoformat(),
        "updated_at": image.updated_at.isoformat(),
    }


def create_app(
    db: DBManager,
    r2: R2BucketHandler,
) -> FastAPI:
    """
    Create and configure the FastAPI application.
    This wrapper allows the application to receive its dependencies explicitly.

    Args:
        db (DBManager): Database dependency used by the application.
        r2 (R2BucketHandler): Object-storage dependency used by the
            application.

    Return:
        FastAPI: A fully configured FastAPI application instance.
    """
    app = FastAPI()

    image_processing_service = ImageProcessingService(
        db=db,
        r2=r2,
    )

    def get_image_processing_service() -> ImageProcessingService:
        """
        Provide the ImageProcessingService application dependency.

        This dependency is intentionally defined inside create_app so that
        each application instance owns its service dependency. Tests can
        override this dependency through FastAPI's dependency_overrides
        mechanism.

        Return:
            ImageProcessingService: The service used by the API endpoints.
        """
        return image_processing_service

    @app.exception_handler(ImageProcessingServiceException)
    async def handle_image_processing_service_exception(
        request,
        exc: ImageProcessingServiceException,
    ) -> JSONResponse:
        """
        Translate an ImageProcessingServiceException into an HTTP response.

        Args:
            request: The incoming request (unused, required by FastAPI).
            exc (ImageProcessingServiceException): The raised application
                exception.

        Return:
            JSONResponse: A response using the exception's status_code.
        """
        _LOGGER.info(f"Handling ImageProcessingServiceException: {exc}")

        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": str(exc)},
        )

    @app.post("/register")
    async def sign_up(
        user: models.User,
        service: ImageProcessingService = Depends(get_image_processing_service),
    ) -> dict:
        """
        Register a new user and log them in.

        Args:
            user (models.User): The username/password payload.
            service (ImageProcessingService): The image processing service
                dependency.

        Return:
            dict: {"user": {...}, "token": "..."}
        """
        _LOGGER.info(f"Handling POST /register for username '{user.username}'.")

        created_user = service.register_user(
            user.username,
            user.password,
        )

        token, _ = service.login(
            user.username,
            user.password,
        )

        _LOGGER.info(
            f"Successfully handled POST /register for username '{user.username}'."
        )

        return {
            "user": _user_to_dict(created_user),
            "token": token,
        }

    @app.post("/login")
    async def log_in(
        user: models.User,
        service: ImageProcessingService = Depends(get_image_processing_service),
    ) -> dict:
        """
        Authenticate an existing user.

        Args:
            user (models.User): The username/password payload.
            service (ImageProcessingService): The image processing service
                dependency.

        Return:
            dict: {"user": {...}, "token": "..."}
        """
        _LOGGER.info(f"Handling POST /login for username '{user.username}'.")

        token, logged_in_user = service.login(
            user.username,
            user.password,
        )

        _LOGGER.info(
            f"Successfully handled POST /login for username '{user.username}'."
        )

        return {
            "user": _user_to_dict(logged_in_user),
            "token": token,
        }

    @app.post("/images")
    async def upload(
        file: UploadFile = File(...),
        user_id: str = Depends(Auth.get_current_user),
        service: ImageProcessingService = Depends(get_image_processing_service),
    ) -> dict:
        """
        Upload a new image.

        Args:
            file (UploadFile): The image file uploaded by the client.
            user_id (str): The authenticated user's ID.
            service (ImageProcessingService): The image processing service
                dependency.

        Return:
            dict: The uploaded image's metadata (URL + metadata).
        """
        _LOGGER.info(f"Handling POST /images for user '{user_id}'.")

        image_bytes = BytesIO(await file.read())

        record = service.upload_image(
            user_id,
            image_bytes,
            file.filename,
        )

        _LOGGER.info(f"Successfully handled POST /images for user '{user_id}'.")

        return _image_to_dict(record)

    @app.post("/images/{image_id}/transform")
    async def transform(
        image_id: str,
        req: models.ImageTransformRequest,
        user_id: str = Depends(Auth.get_current_user),
        service: ImageProcessingService = Depends(get_image_processing_service),
    ) -> dict:
        """
        Apply transformations to an existing image and persist the result.

        Args:
            image_id (str): The ID of the image to transform.
            req (models.ImageTransformRequest): The requested
                transformations.
            user_id (str): The authenticated user's ID.
            service (ImageProcessingService): The image processing service
                dependency.

        Return:
            dict: The updated image's metadata.
        """
        _LOGGER.info(
            f"Handling POST /images/{image_id}/transform for user '{user_id}'."
        )

        record = service.transform_image(
            image_id,
            user_id,
            req.transformations,
        )

        _LOGGER.info(
            f"Successfully handled POST /images/{image_id}/transform "
            f"for user '{user_id}'."
        )

        return _image_to_dict(record)

    @app.get("/images/{image_id}")
    async def retrieve_image(
        image_id: str,
        format: Optional[str] = None,
        user_id: str = Depends(Auth.get_current_user),
        service: ImageProcessingService = Depends(get_image_processing_service),
    ) -> StreamingResponse:
        """
        Retrieve an image's bytes, optionally converted to a different format.

        Args:
            image_id (str): The ID of the image to retrieve.
            format (Optional[str]): Optional output format conversion.
            user_id (str): The authenticated user's ID.
            service (ImageProcessingService): The image processing service
                dependency.

        Return:
            StreamingResponse: The image bytes, with a Content-Type
                matching either `format` or the stored image format.
        """
        _LOGGER.info(f"Handling GET /images/{image_id} for user '{user_id}'.")

        image_bytes, record = service.get_image(
            image_id,
            user_id,
            format,
        )

        content_type = f"image/{(format or record.format).lower()}"

        _LOGGER.info(
            f"Successfully handled GET /images/{image_id} for user '{user_id}'."
        )

        return StreamingResponse(
            iter([image_bytes.getvalue()]),
            media_type=content_type,
        )

    @app.get("/images")
    async def list_images(
        page: int = 1,
        limit: Optional[int] = None,
        user_id: str = Depends(Auth.get_current_user),
        service: ImageProcessingService = Depends(get_image_processing_service),
    ) -> dict:
        """
        List the authenticated user's images, paginated.

        Args:
            page (int): The 1-indexed page number. Defaults to 1.
            limit (Optional[int]): Max items per page. Defaults to
                APP_PAGINATION_LIMIT when not supplied.
            user_id (str): The authenticated user's ID.
            service (ImageProcessingService): The image processing service
                dependency.

        Return:
            dict: {"images": [...], "total": ..., "page": ..., "limit": ...}
        """
        if limit is None:
            limit = int(
                os.getenv(
                    "APP_PAGINATION_LIMIT",
                    "10",
                )
            )

        _LOGGER.info(
            f"Handling GET /images for user '{user_id}', page {page}, limit {limit}."
        )

        images, total = service.list_images(
            user_id,
            page,
            limit,
        )

        _LOGGER.info(f"Successfully handled GET /images for user '{user_id}'.")

        return {
            "images": [_image_to_dict(image) for image in images],
            "total": total,
            "page": page,
            "limit": limit,
        }

    @app.get("/health")
    async def health() -> dict:
        """
        Return the application health status.

        Return:
            dict: {"status": "ok"}
        """
        return {"status": "ok"}

    return app


def main() -> FastAPI:
    """
    Create the production FastAPI application.

    Initializes the real database and Cloudflare R2 dependencies and
    injects them into the application factory.

    Return:
        FastAPI: The production-configured FastAPI application.

    Raises:
        SystemExit: If an application dependency cannot be initialized.
    """
    _LOGGER.info("Initializing application dependencies.")

    try:
        db_manager = DBManager()
        r2_bucket_handler = R2BucketHandler()
    except (DBManagerException, R2BucketHandlerException) as e:
        _LOGGER.error(f"Can't start the server. {e}")
        sys.exit(1)

    app = create_app(
        db=db_manager,
        r2=r2_bucket_handler,
    )

    _LOGGER.info("Successfully initialized application dependencies.")

    return app


app = main()


if __name__ == "__main__":
    uvicorn.run(
        "src.server:app",
        port=8000,
        log_level="info",
    )
