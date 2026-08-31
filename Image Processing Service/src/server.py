"""
TODO:
#### New file server.py
Wires together `FastAPI`, `Auth`, and `ImageProcessingService` into the HTTP API. Constructs a single `DbManager`, `R2BucketHandler`, and `ImageProcessingService` at module load (so each request reuses the same pooled DB connection / R2 client rather than re-initializing them), then defines the route handlers below. All routes except `/register`, `/login`, and `/health` are protected via `Depends(Auth.get_current_user)`, which supplies `user_id: int` to the handler.

Route handlers are plain module-level `async` functions registered via `@app.<method>(...)` decorators, not methods on a class — FastAPI has no notion of dispatching to instance methods, so there's no `Server` class.

- A `@app.exception_handler(ImageProcessingServiceException)` handler translates the service-layer exception into the appropriate HTTP status code and JSON error body, so individual route handlers don't need repetitive `try/except` blocks.

# - `GET /images/{image_id}` → `retrieve_image(image_id: str, format: str | None = None, user_id: int = Depends(Auth.get_current_user))`: Calls `ImageProcessingService.get_image(image_id, user_id, format)` and returns a `StreamingResponse` of the image bytes with the appropriate `Content-Type`. When `format` is omitted, the image is streamed as currently stored; when supplied (e.g. `?format=webp`), the response reflects a one-off, non-persisted conversion. Returns `404 Not Found` via `ImageProcessingServiceException` if missing or not owned by `user_id`, `400 Bad Request` if `format` is unsupported.
# - `GET /images` → `list_images(page: int = 1, limit: int | None = None, user_id: int = Depends(Auth.get_current_user)) -> dict`: Defaults `limit` to `APP_PAGINATION_LIMIT` from the environment when not supplied, calls `ImageProcessingService.list_images(user_id, page, limit)`, and returns `{"images": [...], "total": ..., "page": ..., "limit": ...}`.
# - `GET /health` → `health() -> dict`: Returns `{"status": "ok"}`; used by the `Dockerfile` `HEALTHCHECK` and the `db` service's healthiness gating on `app` startup.


"""

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
from .r2_bucket_handler import R2BucketHandler
from .r2_bucket_handler_exception import R2BucketHandlerException
from .image_processing_service import ImageProcessingService
from .image_processing_service_exception import ImageProcessingServiceException
from src import models

_LOGGER = common.get_logger()
_BASE_DIR = common.get_base_dir()
app = FastAPI()
_LOGGER.info("Initializing application dependencies.")

try:
    db_manager = DBManager()
    r2_bucket_handler = R2BucketHandler()
except (DBManagerException, R2BucketHandlerException) as e:
    _LOGGER.error(f"Can't start the server. {e}")
    sys.exit(1)

image_processing_service = ImageProcessingService(db=db_manager, r2=r2_bucket_handler)
_LOGGER.info("Successfully initialized application dependencies.")


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


@app.exception_handler(ImageProcessingServiceException)
async def handle_image_processing_service_exception(
    request, exc: ImageProcessingServiceException
) -> JSONResponse:
    """
    Translate an ImageProcessingServiceException into an HTTP response.

    Args:
        request: The incoming request (unused, required by FastAPI).
        exc (ImageProcessingServiceException): The raised exception.

    Return:
        JSONResponse: A response using the exception's status_code.
    """
    _LOGGER.info(f"Handling ImageProcessingServiceException: {exc}")
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})


@app.post("/register")
async def sign_up(user: models.User) -> dict:
    """
    Register a new user and log them in.

    Args:
        user (models.User): The username/password payload.

    Return:
        dict: {"user": {...}, "token": "..."}
    """
    _LOGGER.info(f"Handling POST /register for username '{user.username}'.")

    created_user = image_processing_service.register_user(user.username, user.password)
    token, _ = image_processing_service.login(user.username, user.password)

    _LOGGER.info(f"Successfully handled POST /register for username '{user.username}'.")
    return {
        "user": _user_to_dict(created_user),
        "token": token,
    }


@app.post("/login")
async def log_in(user: models.User) -> dict:
    """
    Authenticate an existing user.

    Args:
        user (models.User): The username/password payload.

    Return:
        dict: {"user": {...}, "token": "..."}
    """
    _LOGGER.info(f"Handling POST /login for username '{user.username}'.")

    token, logged_in_user = image_processing_service.login(user.username, user.password)

    _LOGGER.info(f"Successfully handled POST /login for username '{user.username}'.")
    return {
        "user": _user_to_dict(logged_in_user),
        "token": token,
    }


@app.post("/images")
async def upload(
    file: UploadFile = File(...),
    user_id: str = Depends(Auth.get_current_user),
) -> dict:
    """
    Upload a new image.

    Args:
        file (UploadFile): The multipart image file.
        user_id (str): The authenticated user's ID.

    Return:
        dict: The uploaded image's metadata (URL + metadata).
    """
    _LOGGER.info(f"Handling POST /images for user '{user_id}'.")

    image_bytes = BytesIO(await file.read())
    record = image_processing_service.upload_image(user_id, image_bytes, file.filename)

    _LOGGER.info(f"Successfully handled POST /images for user '{user_id}'.")
    return _image_to_dict(record)


@app.post("/images/{image_id}/transform")
async def transform(
    image_id: str,
    req: models.ImageTransformRequest,
    user_id: str = Depends(Auth.get_current_user),
) -> dict:
    """
    Apply transformations to an existing image.

    Args:
        image_id (str): The image's ID.
        req (models.ImageTransformRequest): The requested transformations.
        user_id (str): The authenticated user's ID.

    Return:
        dict: The updated image's metadata.
    """
    _LOGGER.info(f"Handling POST /images/{image_id}/transform for user '{user_id}'.")

    record = image_processing_service.transform_image(
        image_id, user_id, req.transformations
    )

    _LOGGER.info(
        f"Successfully handled POST /images/{image_id}/transform for user '{user_id}'."
    )
    return _image_to_dict(record)


@app.get("/images/{image_id}")
async def retrieve_image(
    image_id: str,
    format: Optional[str] = None,
    user_id: str = Depends(Auth.get_current_user),
) -> StreamingResponse:
    """
    Retrieve an image's bytes, optionally converted to a different format.

    Args:
        image_id (str): The image's ID.
        format (Optional[str]): If given, a one-off, non-persisted format
            conversion applied before streaming.
        user_id (str): The authenticated user's ID.

    Return:
        StreamingResponse: The image bytes, with a Content-Type matching
            either `format` (if given) or the image's stored format.
    """
    _LOGGER.info(f"Handling GET /images/{image_id} for user '{user_id}'.")

    image_bytes, record = image_processing_service.get_image(image_id, user_id, format)
    content_type = f"image/{(format or record.format).lower()}"

    _LOGGER.info(f"Successfully handled GET /images/{image_id} for user '{user_id}'.")
    return StreamingResponse(iter([image_bytes.getvalue()]), media_type=content_type)


@app.get("/images")
async def list_images(
    page: int = 1,
    limit: Optional[int] = None,
    user_id: str = Depends(Auth.get_current_user),
) -> dict:
    """
    List the authenticated user's images, paginated.

    Args:
        page (int): The 1-indexed page number. Defaults to 1.
        limit (Optional[int]): Max items per page. Defaults to
            APP_PAGINATION_LIMIT when not supplied.
        user_id (str): The authenticated user's ID.

    Return:
        dict: {"images": [...], "total": ..., "page": ..., "limit": ...}
    """
    if limit is None:
        limit = int(os.getenv("APP_PAGINATION_LIMIT", "10"))

    _LOGGER.info(
        f"Handling GET /images for user '{user_id}', page {page}, limit {limit}."
    )

    images, total = image_processing_service.list_images(user_id, page, limit)

    _LOGGER.info(f"Successfully handled GET /images for user '{user_id}'.")
    return {
        "images": [_image_to_dict(image) for image in images],
        "total": total,
        "page": page,
        "limit": limit,
    }


if __name__ == "__main__":
    uvicorn.run("src.server:app", port=8000, log_level="info")
