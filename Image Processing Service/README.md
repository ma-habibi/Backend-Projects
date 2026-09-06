# Image Processing Service

A backend service for uploading, transforming, and retrieving images — similar in spirit to Cloudinary. Built as the `Image Processing Service` project from `roadmap.sh`: [https://roadmap.sh/projects/image-processing-service](https://roadmap.sh/projects/image-processing-service)

**Live instance:** https://image-processing-service-39j4.onrender.com/

The service handles user authentication (JWT-based), image upload with metadata extraction, a range of image transformations (resize, crop, rotate, flip, mirror, watermark, compress, format conversion, grayscale/sepia filters), and paginated retrieval — with image bytes stored in Cloudflare R2 and metadata stored in PostgreSQL.

> ⚠️ Note on the free-hosted demo above: it runs on Render's free tier and a free Neon Postgres instance. Both spin down after periods of inactivity, so the first request after idle time may take 30–60 seconds to respond. This is expected behavior, not a bug.

---

## Table of Contents

- [Features](#features)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Environment Variables](#environment-variables)
- [Running Locally](#running-locally)
- [Docker](#docker)
- [API](#api)
- [Testing](#testing)
- [Known Limitations](#known-limitations)

---

## Features

**Authentication**
- Sign-up and login with hashed passwords (`bcrypt`)
- JWT-based authentication on all image endpoints

**Image management**
- Upload images with automatic metadata extraction (format, dimensions, size)
- Retrieve images, optionally converted to a different format on the fly
- Paginated listing of a user's images
- Delete images (removes both the stored bytes and the metadata record)

**Transformations** — applied via a single `POST /images/{id}/transform` call, any combination at once:
- Resize
- Crop
- Rotate
- Flip (vertical) / Mirror (horizontal)
- Watermark
- Compress (JPEG/WebP quality)
- Format conversion (JPEG, PNG, WebP, GIF, BMP)
- Filters: grayscale, sepia

Transformations are applied in a fixed order — crop → resize → rotate → flip/mirror → filters → watermark → format/compress — regardless of the order fields appear in the request body, so results are deterministic.

## Tech Stack

| Layer | Choice |
|---|---|
| API framework | [FastAPI](https://fastapi.tiangolo.com/) + Uvicorn |
| Database | PostgreSQL ([`psycopg3`](https://www.psycopg.org/) + connection pooling), hosted on [Neon](https://neon.tech) in production |
| Object storage | Cloudflare R2 (S3-compatible API via `boto3`) |
| Image processing | [Pillow](https://pillow.readthedocs.io/) |
| Auth | JWT (`PyJWT`) + `bcrypt` password hashing |
| Containerization | Docker + Docker Compose |
| Hosting | [Render](https://render.com) (free web service) |
| Testing | `pytest` |

## Project Structure

```
Image Processing Service/
├── assets/
│   └── watermark.png          # Bundled watermark asset used by the watermark transformation
├── db/
│   └── schema.sql              # Postgres schema, auto-run on first container start
├── src/
│   ├── auth.py                 # JWT creation/validation
│   ├── common.py                # Shared logger + base-dir utilities
│   ├── db_manager.py            # Postgres access layer (users, images)
│   ├── db_manager_exception.py
│   ├── r2_bucket_handler.py      # Cloudflare R2 client (image bytes)
│   ├── r2_bucket_handler_exception.py
│   ├── image_processing_service.py         # Core business logic + transformations
│   ├── image_processing_service_exception.py
│   ├── models.py                # Pydantic request/response models
│   └── server.py                 # FastAPI app and route handlers
├── tests/
│   └── test_image_processing_service.py
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── .env                          # Not committed — see Environment Variables below
```

## Environment Variables

All variables are read from a `.env` file at the project root (or injected directly by the hosting platform, e.g. Render's environment settings).

### Cloudflare

| Variable | Description |
|---|---|
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare account identifier; used to build the R2 S3-compatible endpoint URL. |
| `CLOUDFLARE_R2_BUCKET` | Name of the R2 bucket where image bytes are stored. |
| `CLOUDFLARE_ACCESS_KEY_ID` | S3-compatible access key ID for authenticating with R2. |
| `CLOUDFLARE_SECRET_ACCESS_KEY` | S3-compatible secret access key paired with the access key ID. |
| `CLOUDFLARE_TOKEN_VALUE` | Cloudflare API token. Not currently read by the app code — the R2 client authenticates via the access/secret key pair above — but kept for completeness / direct Cloudflare API management. |

### Application

| Variable | Description |
|---|---|
| `APP_JWT_SECRET` | Secret key used to sign and verify JWTs. Should be a long, random, high-entropy string. |
| `APP_JWT_TOKEN_EXPIRATION_MINUTES` | Minutes until an issued JWT expires. |
| `APP_PAGINATION_LIMIT` | Default page size for `GET /images` when no `limit` query parameter is given. |
| `APP_QUEUE_WORKERS` | Reserved for a future async transformation queue. Not currently used. |
| `APP_RATE_LIMIT_PER_SECOND` | Reserved for future rate limiting on transformation requests. Not currently enforced. |
| `APP_SERVER_TIMEOUT` | Reserved for future request/operation timeouts. Not currently enforced. |

### Database

| Variable | Description |
|---|---|
| `DATABASE_URL` | Full Postgres connection string, e.g. `postgresql://user:pass@host:5432/dbname`. Used directly by the app; takes priority when set. |
| `DB_POSTGRES_USER` | Postgres username. Used by `docker-compose.yml` to initialize the local `db` container and to compose `DATABASE_URL` for it. |
| `DB_NAME` | Postgres database name. Same use as above. |
| `DB_PORT` | Port the local Postgres container is exposed on. |
| `DB_POSTGRES_PASSWORD` | Postgres password. Same use as above. |

> In production (Render), `DATABASE_URL` points directly at a managed Postgres instance (Neon); the `DB_*` variables are only relevant to the local `docker-compose` `db` service.

## Running Locally

```bash
cp .env.example .env   # fill in real values
docker compose up --build
```

This starts both the `db` (Postgres) and `app` (FastAPI) containers. The schema in `db/schema.sql` is applied automatically the first time the `db` container starts against an empty volume.

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

## Docker

**`Dockerfile`** — builds the `app` image from `python:3.12-slim`:
- Installs `libpq-dev`, `gcc` (for `psycopg`'s non-binary build path and any native extensions) and `curl` (used by the container's own healthcheck).
- Installs Python dependencies from `requirements.txt`, then copies in `src/`.
- Runs `uvicorn src.server:app` bound to `0.0.0.0:${PORT:-8000}` — respecting a platform-injected `PORT` (e.g. Render) when present, defaulting to `8000` for local/Compose use.
- Declares a `HEALTHCHECK` hitting `/health`.

**`docker-compose.yml`** — two services, for local development:
- **`db`**: `postgres:17`, with `db/schema.sql` mounted into `/docker-entrypoint-initdb.d/`. Postgres's official image auto-runs any `.sql` file found there **the first time it starts against an empty data volume** — this is how the schema gets created without a separate migration step. It will *not* re-run on subsequent starts or if the schema changes; dropping the named volume (`docker compose down -v`) is required to re-initialize it.
- **`app`**: depends on `db` via a healthcheck condition (`pg_isready`), so it doesn't attempt to connect before Postgres is actually ready to accept connections. Receives all Cloudflare/App variables via `env_file: .env`, and a separately composed `DATABASE_URL` pointing at the `db` service by its Compose network name.

**In production**, only the `app` half of this setup is actually deployed — Render builds and runs the `Dockerfile` directly (not `docker-compose.yml`), and `DATABASE_URL` points at an external managed Postgres instance (Neon) instead of the `db` Compose service. `docker-compose.yml` remains the source of truth for local development only.

## API

All endpoints are prefixed with the deployed base URL (e.g. `https://image-processing-service-39j4.onrender.com`). Replace with `http://localhost:8000` for local runs.

Every endpoint below except `/register`, `/login`, and `/health` requires an `Authorization: Bearer <token>` header, using the token returned by `/register` or `/login`.

### `POST /register`

Create a new account and receive a token for it immediately.

```bash
curl -X POST https://image-processing-service-39j4.onrender.com/register \
  -H "Content-Type: application/json" \
  -d '{
    "username": "default_test",
    "password": "123"
  }'
```

```json
{
  "user": {
    "id": "8",
    "username": "default_test",
    "created_at": "2026-08-23T14:39:30.658811+00:00"
  },
  "token": $TOKEN
}
```

### `POST /login`

Authenticate an existing user.

```bash
curl -X POST https://image-processing-service-39j4.onrender.com/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "default_test",
    "password": "123"
  }'
```

```json
{
  "user": {
    "id": "8",
    "username": "default_test",
    "created_at": "2026-08-23T14:39:30.658811+00:00"
  },
  "token": $TOKEN
}
```

### `POST /images`

Upload a new image. Multipart form-data with the file under the `file` field.

```bash
curl -X POST "https://image-processing-service-39j4.onrender.com/images" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/path/to/image.jpg"
```

```json
{
  "id": "b13083c6-abc1-4f4e-9ee4-dc48396ab8dd",
  "user_id": "8",
  "filename": "image.jpg",
  "format": "jpeg",
  "width": 1920,
  "height": 1080,
  "size_bytes": 245012,
  "url": "https://<account_id>.r2.cloudflarestorage.com/<bucket>/b13083c6-abc1-4f4e-9ee4-dc48396ab8dd",
  "created_at": "2026-08-23T11:20:45.079706+00:00",
  "updated_at": "2026-08-23T11:20:45.079706+00:00"
}
```

### `POST /images/{image_id}/transform`

Apply one or more transformations in a single request. Any combination of fields may be included; only the ones present are applied.

```bash
curl -X POST https://image-processing-service-39j4.onrender.com/images/$IMAGE_ID/transform \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "transformations": {
      "resize": {
        "width": 1280,
        "height": 800
      },
      "filters": {
        "grayscale": true,
        "sepia": false
      },
      "flip": true
    }
  }'
```

Full set of supported transformation fields:

```json
{
  "transformations": {
    "resize":   { "width": "number", "height": "number" },
    "crop":     { "width": "number", "height": "number", "x": "number", "y": "number" },
    "rotate":   "number",
    "flip":     "boolean",
    "mirror":   "boolean",
    "watermark": "boolean",
    "compress": "number (1-100)",
    "format":   "string (jpeg | png | webp | gif | bmp)",
    "filters":  { "grayscale": "boolean", "sepia": "boolean" }
  }
}
```

Response — the updated image record, same shape as the upload response:

```json
{
  "id": "b13083c6-abc1-4f4e-9ee4-dc48396ab8dd",
  "user_id": "8",
  "filename": "image.jpg",
  "format": "jpeg",
  "width": 1280,
  "height": 800,
  "size_bytes": 189320,
  "url": "https://<account_id>.r2.cloudflarestorage.com/<bucket>/b13083c6-abc1-4f4e-9ee4-dc48396ab8dd",
  "created_at": "2026-08-23T11:20:45.079706+00:00",
  "updated_at": "2026-08-23T13:38:05.229247+00:00"
}
```

### `GET /images/{image_id}`

Retrieve the actual image bytes. Optionally add `?format=<format>` to convert on the fly — this conversion is **not** persisted; it only affects this one response.

```bash
curl --output downloaded.jpeg -X GET "https://image-processing-service-39j4.onrender.com/images/$IMAGE_ID" \
  -H "Authorization: Bearer $TOKEN"
```

Response: the raw image bytes, with `Content-Type` set to `image/<format>`. There is no JSON body.

### `GET /images`

List the authenticated user's images, paginated.

```bash
curl -X GET "https://image-processing-service-39j4.onrender.com/images?page=1&limit=10" \
  -H "Authorization: Bearer $TOKEN"
```

```json
{
  "images": [
    {
      "id": "b13083c6-abc1-4f4e-9ee4-dc48396ab8dd",
      "user_id": "8",
      "filename": "image.jpg",
      "format": "jpeg",
      "width": 1280,
      "height": 800,
      "size_bytes": 189320,
      "url": "https://<account_id>.r2.cloudflarestorage.com/<bucket>/b13083c6-abc1-4f4e-9ee4-dc48396ab8dd",
      "created_at": "2026-08-23T11:20:45.079706+00:00",
      "updated_at": "2026-08-23T13:38:05.229247+00:00"
    }
  ],
  "total": 54,
  "page": 1,
  "limit": 10
}
```

`page`/`limit` are both optional; `limit` defaults to `APP_PAGINATION_LIMIT` when omitted.

### `GET /health`

Basic liveness check, used by the container healthcheck and Render's health monitoring.

```bash
curl -X GET https://image-processing-service-39j4.onrender.com/health
```

```json
{"status": "ok"}
```

### Error responses

All errors from the service layer share one shape:

```json
{"detail": "Invalid username or password."}
```

| Status | Meaning |
|---|---|
| `400` | Invalid input (bad transformation parameters, unsupported format, invalid image file) |
| `401` | Invalid credentials |
| `404` | Image not found, or not owned by the authenticated user |
| `409` | Username already taken |
| `500` | Unexpected failure in the database or storage layer |

## Testing

```bash
pip install -r requirements.txt
pytest tests/ -v
```

The suite covers each transformation method in isolation (resize, crop, rotate, flip, mirror, watermark, filters, compress, format conversion) using small in-memory test images, plus orchestration tests for `upload_image`/`delete_image` with `DBManager`/`R2BucketHandler` mocked out.

## Known Limitations

These are called out explicitly rather than left implicit:

- **No async transformation queue** — `APP_QUEUE_WORKERS` is reserved but transformations run synchronously within the request.
- **No rate limiting** — `APP_RATE_LIMIT_PER_SECOND` is reserved but not enforced.
- **No request timeouts** — `APP_SERVER_TIMEOUT` is reserved but not enforced.
- **No caching for on-the-fly format conversions** — `GET /images/{id}?format=...` re-converts on every request.
- **Free-tier hosting** — the live demo cold-starts after inactivity (both Render and the Neon database scale to zero when idle).
