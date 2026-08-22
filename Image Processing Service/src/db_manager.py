import os
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Optional, Iterator
from datetime import datetime

import psycopg
from psycopg_pool import ConnectionPool

from common import common
from db_manager_exception import DBManagerException


@dataclass(frozen=True)
class UserRecord:
    """A row from the `users` table.

    Deliberately excludes `password_hash` so it never accidentally ends up
    serialized into an API response.

    Attributes:
        id: Internal user identifier.
        username: The user's unique username.
        created_at: When the user was created.
    """

    id: str
    username: str
    created_at: datetime

    @classmethod
    def from_row(cls, row) -> "UserRecord":
        if row is None:
            raise ValueError("Cannot create UserRecord from an empty row")

        id, username, created_at = row
        return cls(id=id, username=username, created_at=created_at)


@dataclass(frozen=False)
class ImageRecord:
    """A row from the `images` table.

    Attributes:
        id: Internal image identifier.
        user_id: Owning user, users(id).
        filename: Original filename provided at upload time.
        format: Current image format.
        width: Current pixel width dimension.
        height: Current pixel height dimension.
        size_bytes: Current file size in bytes.
        created_at: When the image was created.
        created_at: When the image was updated.
    """

    id: str
    user_id: str
    filename: str
    format: str
    width: int
    height: int
    size_bytes: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row) -> "ImageRecord":
        if row is None:
            raise ValueError("Cannot create ImageRecord from an empty row")

        (
            id,
            user_id,
            filename,
            format,
            width,
            height,
            size_bytes,
            created_at,
            updated_at,
        ) = row
        return cls(
            id=id,
            user_id=user_id,
            filename=filename,
            format=format,
            width=width,
            height=height,
            size_bytes=size_bytes,
            created_at=created_at,
            updated_at=updated_at,
        )


class DBManager:
    """
    A client that will use psycopg3 to interact with the postgresql database.

    Provides CRUD operations on the users and images tables.
    """

    def __init__(self) -> None:
        """
        Initialize the DBManager and open a connection pool.

        Reads the `DATABASE_URL` environment variable and uses it to create
        a `psycopg_pool.ConnectionPool`. The pool is opened upon initialization so that
        connection failures surface immediately raising a DBManagerException.

        Raises:
            DBManagerException: If `DATABASE_URL` is not set, or the
                connection pool fails to initialize (e.g. the database is
                unreachable or credentials are invalid).
        """
        self._logger = common.get_logger()
        self._base_dir = common.get_base_dir()

        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise DBManagerException("DATABASE_URL environment variable is not set.")

        try:
            self._pool = ConnectionPool(conninfo=database_url, open=True)
        except psycopg.Error as e:
            self._logger.error("Failed to initialize the connection pool: %s", e)
            raise DBManagerException(
                "Failed to initialize the database connection pool."
            ) from e

    @contextmanager
    def _get_connection(self) -> Iterator[psycopg.Connection]:
        """ """
        try:
            with self._pool.connection() as connection:
                yield connection
        except psycopg.Error as e:
            raise DBManagerException(
                f"Failed to obtain a database connection from the pool. {e}"
            )

    def create_user(self, username: str, password_hash: str) -> UserRecord:
        """
        Insert a new user with the given username and hashed password. Returns the created UserRecord. Raises DbManagerException if the username already exists.
        """
        with self._get_connection() as connection:
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                            INSERT INTO users (username, password_hash)
                            VALUES (%s, %s)
                            RETURNING id, username, created_at
                            """,
                        (username, password_hash),
                    )
                    row = cursor.fetchone()
                connection.commit()
            except psycopg.errors.UniqueViolation:
                connection.rollback()
                raise DBManagerException(f"Duplicate username '{username}'.")
            except psycopg.Error as e:
                connection.rollback()
                self._logger.error("Failed to create user '%s': %s", username, e)
                raise DBManagerException("Failed to create user.") from e

        return UserRecord.from_row(row)

    def get_user_by_username(self, username: str) -> Optional[UserRecord]:
        """
        Return the user matching the given username, or None if no such user exists.
        """

        self._logger.info(f"Getting user by username '{username}")
        with self._get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, username, created_at
                    FROM users
                    WHERE username = %s
                    """,
                    (username,),
                )
                row = cursor.fetchone()
            connection.commit()

        if row is None:
            self._logger.info("No such user")
            return None
        self._logger.info("Successfully Obtained the user")
        self._logger.debug(row)
        return UserRecord.from_row(row)

    def get_user_by_id(self, user_id: str) -> Optional[UserRecord]:
        """
        Return the user matching the given ID, or None if no such user exists.

        Args:
            user_id (str):

        Returns:
        """

        self._logger.info(f"Getting user by ID '{user_id}")
        with self._get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, username, created_at
                    FROM users
                    WHERE id = %s
                    """,
                    (user_id,),
                )
                row = cursor.fetchone()
            connection.commit()

        if row is None:
            self._logger.info("No such user")
            return None
        self._logger.info("Successfully Obtained the user")
        self._logger.debug(row)
        return UserRecord.from_row(row)

    def create_image(self, user_id: str, filename: str, metadata: dict) -> ImageRecord:
        """
        Insert a new image record and return the created ImageRecord.
        """

        self._logger.info(f"Creating image '{filename}'.")
        image_id = str(uuid.uuid4())
        with self._get_connection() as connection:
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO images
                            (id, user_id, filename, format, width, height, size_bytes)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        RETURNING
                            id, user_id, filename, format, width, height,
                            size_bytes, created_at, updated_at
                        """,
                        (
                            image_id,
                            user_id,
                            filename,
                            metadata.get("format"),
                            metadata.get("width"),
                            metadata.get("height"),
                            metadata.get("size_bytes"),
                        ),
                    )
                    row = cursor.fetchone()
                connection.commit()
                self._logger.info("Successfully created the image.")
            except psycopg.errors.ForeignKeyViolation as e:
                connection.rollback()
                raise DBManagerException(
                    f"The referenced user '{user_id}' does not exist. {e}"
                )
            except psycopg.Error as e:
                connection.rollback()
                raise DBManagerException(f"Failed to create image. {e}")

        return ImageRecord.from_row(row)

    def get_image(self, image_id: str, user_id: str) -> Optional[ImageRecord]:
        """
        Return the image record matching the given ID and owning user, or None if not found.
        """

        self._logger.info(f"Getting image by ID '{image_id}")
        with self._get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, user_id, filename, format, width, height, size_bytes, created_at, updated_at
                    FROM images
                    WHERE id = %s AND user_id = %s
                    """,
                    (image_id, user_id),
                )
                row = cursor.fetchone()

        if row is None:
            self._logger.info("No such image")
            return None
        self._logger.info("Successfully Obtained the image")
        self._logger.debug(row)
        return ImageRecord.from_row(row)

    def update_image(
        self, image_id: str, user_id: str, metadata: dict
    ) -> Optional[ImageRecord]:
        """
        Update an existing image record's metadata (e.g. after a transformation) and return the updated ImageRecord, or None if not found.
        """
        self._logger.info(f"Updating image by ID '{image_id}'")

        allowed_fields = ("filename", "format", "width", "height", "size_bytes")
        fields_to_update = {k: v for k, v in metadata.items() if k in allowed_fields}

        if not fields_to_update:
            raise DBManagerException("No valid fields provided to update.")

        set_clause = ", ".join(f"{field} = %s" for field in fields_to_update)
        values = list(fields_to_update.values())

        with self._get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    UPDATE images
                    SET {set_clause}, updated_at = now()
                    WHERE id = %s AND user_id = %s
                    RETURNING id, user_id, filename, format, width, height, size_bytes, created_at, updated_at
                    """,
                    (*values, image_id, user_id),
                )
                row = cursor.fetchone()

        if row is None:
            self._logger.info("No such image")
            return None
        self._logger.info("Successfully Updated the image")
        self._logger.debug(row)
        return ImageRecord.from_row(row)
