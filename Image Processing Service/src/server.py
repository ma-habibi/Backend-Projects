"""
TODO:
#### New file server.py
Wires together `FastAPI`, `Auth`, and `ImageProcessingService` into the HTTP API. Constructs a single `DbManager`, `R2BucketHandler`, and `ImageProcessingService` at module load (so each request reuses the same pooled DB connection / R2 client rather than re-initializing them), then defines the route handlers below. All routes except `/register`, `/login`, and `/health` are protected via `Depends(Auth.get_current_user)`, which supplies `user_id: int` to the handler.

Route handlers are plain module-level `async` functions registered via `@app.<method>(...)` decorators, not methods on a class — FastAPI has no notion of dispatching to instance methods, so there's no `Server` class.

- A `@app.exception_handler(ImageProcessingServiceException)` handler translates the service-layer exception into the appropriate HTTP status code and JSON error body, so individual route handlers don't need repetitive `try/except` blocks.

# - `POST /login` → `log_in(user: models.User) -> dict`: Calls `ImageProcessingService.login(user.username, user.password)` and returns `{"user": ..., "token": ...}`. Returns `401 Unauthorized` if `ImageProcessingServiceException` indicates bad credentials.
# - `POST /images` → `upload(file: UploadFile, user_id: int = Depends(Auth.get_current_user)) -> dict`: Reads the multipart file into a `BytesIO`, calls `ImageProcessingService.upload_image(user_id, image_bytes, file.filename)`, and returns the resulting `ImageRecord` (URL + metadata) as JSON. Returns `400 Bad Request` if `ImageProcessingServiceException` indicates an unsupported/invalid image.
# - `POST /images/{image_id}/transform` → `transform(image_id: str, req: models.ImageTransformRequest, user_id: int = Depends(Auth.get_current_user)) -> dict`: Calls `ImageProcessingService.transform_image(image_id, user_id, req.transformations)` and returns the updated `ImageRecord`. Returns `404 Not Found` if the image doesn't exist or isn't owned by `user_id`, `400 Bad Request` for invalid transformation parameters — both signaled via `ImageProcessingServiceException`.
# - `GET /images/{image_id}` → `retrieve_image(image_id: str, format: str | None = None, user_id: int = Depends(Auth.get_current_user))`: Calls `ImageProcessingService.get_image(image_id, user_id, format)` and returns a `StreamingResponse` of the image bytes with the appropriate `Content-Type`. When `format` is omitted, the image is streamed as currently stored; when supplied (e.g. `?format=webp`), the response reflects a one-off, non-persisted conversion. Returns `404 Not Found` via `ImageProcessingServiceException` if missing or not owned by `user_id`, `400 Bad Request` if `format` is unsupported.
# - `GET /images` → `list_images(page: int = 1, limit: int | None = None, user_id: int = Depends(Auth.get_current_user)) -> dict`: Defaults `limit` to `APP_PAGINATION_LIMIT` from the environment when not supplied, calls `ImageProcessingService.list_images(user_id, page, limit)`, and returns `{"images": [...], "total": ..., "page": ..., "limit": ...}`.
# - `GET /health` → `health() -> dict`: Returns `{"status": "ok"}`; used by the `Dockerfile` `HEALTHCHECK` and the `db` service's healthiness gating on `app` startup.


"""

import pathlib

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import JSONResponse

import models
from common import common
from db_manager import DBManager
from image_processing_service import (
    ImageProcessingService,
    ImageProcessingServiceException,
)

_LOGGER = common.get_logger()
_BASE_DIR = common.get_base_dir()
app = FastAPI()
_LOGGER.info("Initializing application dependencies.")
db_manager = DBManager()
image_processing_service = ImageProcessingService(db=db_manager)
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
    token = image_processing_service.login(user.username, user.password)

    _LOGGER.info(f"Successfully handled POST /register for username '{user.username}'.")
    return {
        "user": {
            "id": created_user.id,
            "username": created_user.username,
            "created_at": created_user.created_at.isoformat(),
        },
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


if __name__ == "__main__":
    uvicorn.run("server:app", port=8000, log_level="info")
