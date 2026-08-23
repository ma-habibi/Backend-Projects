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
    """
    A row from the `users` table. Excludes `password_hash` so it never
    accidentally ends up serialized into an API response.

    Attributes:
        id (str): Internal user identifier.
        username (str): The user's unique username.
        created_at (datetime): When the user was created.
    """

    id: str
    username: str
    created_at: datetime

    @classmethod
    def from_row(cls, row) -> "UserRecord":
        """
        Build a UserRecord from a raw database row.

        Args:
            row (tuple): A `(id, username, created_at)` row.

        Return:
            UserRecord: The constructed record.

        Raises:
            ValueError: If `row` is None.
        """
        if row is None:
            raise ValueError("Cannot create UserRecord from an empty row")

        id, username, created_at = row
        return cls(id=id, username=username, created_at=created_at)


@dataclass(frozen=False)
class ImageRecord:
    """
    A row from the `images` table.

    Attributes:
        id (str): Internal image identifier.
        user_id (str): Owning user, users(id).
        filename (str): Original filename provided at upload time.
        format (str): Current image format.
        width (int): Current pixel width dimension.
        height (int): Current pixel height dimension.
        size_bytes (int): Current file size in bytes.
        created_at (datetime): When the image was created.
        updated_at (datetime): When the image was updated.
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
        """
        Build an ImageRecord from a raw database row.

        Args:
            row (tuple): A `(id, user_id, filename, format, width, height,
                size_bytes, created_at, updated_at)` row.

        Return:
            ImageRecord: The constructed record.

        Raises:
            ValueError: If `row` is None.
        """
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

        Raises:
            DBManagerException: If `DATABASE_URL` is not set, or the
                connection pool fails to initialize.
        """
        self._logger = common.get_logger()
        self._base_dir = common.get_base_dir()

        self._logger.info("Initializing DBManager connection pool.")

        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise DBManagerException("DATABASE_URL environment variable is not set.")

        try:
            self._pool = ConnectionPool(conninfo=database_url, open=True)
        except psycopg.Error as e:
            raise DBManagerException(
                f"Failed to initialize the database connection pool. {e}"
            )

        self._logger.info("Successfully initialized the connection pool.")

    @contextmanager
    def _get_connection(self) -> Iterator[psycopg.Connection]:
        """
        Get a pooled connection to the database, opening a new one if needed.

        Return:
            Iterator[psycopg.Connection]: A context manager yielding an open
                connection.

        Raises:
            DBManagerException: If a connection cannot be obtained from the
                pool.
        """
        try:
            with self._pool.connection() as connection:
                yield connection
        except psycopg.Error as e:
            raise DBManagerException(
                f"Failed to obtain a database connection from the pool. {e}"
            )

    def create_user(self, username: str, password_hash: str) -> UserRecord:
        """
        Create a new user with the given username and hashed password.

        Args:
            username (str): The desired username. Must be unique.
            password_hash (str): The already-hashed password.

        Return:
            UserRecord: The newly created user.

        Raises:
            DBManagerException: If the username already exists, or the
                insert otherwise fails.
        """
        self._logger.info(f"Creating user '{username}'.")

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
            except psycopg.errors.UniqueViolation as e:
                connection.rollback()
                raise DBManagerException(f"Duplicate username '{username}'. {e}")
            except psycopg.Error as e:
                connection.rollback()
                raise DBManagerException(f"Failed to create user. {e}")

        self._logger.info("Successfully created the user.")
        return UserRecord.from_row(row)

    def get_user_by_username(self, username: str) -> Optional[UserRecord]:
        """
        Get the user matching the given username.

        Args:
            username (str): The username to search for.

        Return:
            Optional[UserRecord]: The matching user, or None if not found.

        Raises:
            DBManagerException: If the query fails.
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
        Get the user matching the given ID.

        Args:
            user_id (str): The internal user ID to search for.

        Return:
            Optional[UserRecord]: The matching user, or None if not found.

        Raises:
            DBManagerException: If the query fails.
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
        Create a new image record. Generates a new image ID (UUID).

        Args:
            user_id (str): The owning user's internal ID.
            filename (str): The original filename provided at upload time.
            metadata (dict): A dict with keys `format`, `width`, `height`,
                and `size_bytes`.

        Return:
            ImageRecord: The newly created image record.

        Raises:
            DBManagerException: If `user_id` does not reference an existing
                user, or the insert otherwise fails.
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
            except psycopg.errors.ForeignKeyViolation as e:
                connection.rollback()
                raise DBManagerException(
                    f"The referenced user '{user_id}' does not exist. {e}"
                )
            except psycopg.Error as e:
                connection.rollback()
                raise DBManagerException(f"Failed to create image. {e}")

        self._logger.info("Successfully created the image.")
        return ImageRecord.from_row(row)

    def get_image(self, image_id: str, user_id: str) -> Optional[ImageRecord]:
        """
        Get the image record matching the given ID and owning user.

        Args:
            image_id (str): The image's ID.
            user_id (str): The ID of the user who must own the image.

        Return:
            Optional[ImageRecord]: The matching image, or None if not found.

        Raises:
            DBManagerException: If the query fails.
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
        Update an existing image record's metadata.

        Args:
            image_id (str): The image's ID.
            user_id (str): The ID of the user who must own the image.
            metadata (dict): Fields to update; any of `filename`, `format`,
                `width`, `height`, `size_bytes`.

        Return:
            Optional[ImageRecord]: The updated image, or None if not found.

        Raises:
            DBManagerException: If no valid fields are provided, or the
                update fails.
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

    def list_images(
        self, user_id: str, page: int, limit: int
    ) -> tuple[list[ImageRecord], int]:
        """
        Get a paginated list of image records owned by the given user.

        Args:
            user_id (str): The owning user's internal ID.
            page (int): The 1-indexed page number.
            limit (int): Max number of records per page.

        Return:
            tuple[list[ImageRecord], int]: The page of images, and the total
                count of matching records across all pages.

        Raises:
            DBManagerException: If `page` or `limit` is invalid, or the
                query fails.
        """
        self._logger.info(
            f"Listing images for user '{user_id}', page '{page}', limit '{limit}'"
        )

        if page < 1:
            raise DBManagerException("Page must be >= 1.")
        if limit < 1:
            raise DBManagerException("Limit must be >= 1.")

        offset = (page - 1) * limit

        with self._get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) FROM images WHERE user_id = %s",
                    (user_id,),
                )
                total = cursor.fetchone()[0]

                cursor.execute(
                    """
                    SELECT id, user_id, filename, format, width, height, size_bytes, created_at, updated_at
                    FROM images
                    WHERE user_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (user_id, limit, offset),
                )
                rows = cursor.fetchall()

        images = [ImageRecord.from_row(row) for row in rows]
        self._logger.info(
            f"Successfully Obtained {len(images)} image(s), total {total}"
        )
        self._logger.debug(rows)
        return images, total

    def delete_image(self, image_id: str, user_id: str) -> None:
        """
        Delete the image record matching the given ID and owning user.

        Args:
            image_id (str): The image's ID.
            user_id (str): The ID of the user who must own the image.

        Return:
            None:

        Raises:
            DBManagerException: If the query fails.
        """
        self._logger.info(f"Deleting image by ID '{image_id}' for user '{user_id}'")

        with self._get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM images
                    WHERE id = %s AND user_id = %s
                    """,
                    (image_id, user_id),
                )
                deleted_count = cursor.rowcount

        if deleted_count == 0:
            self._logger.info("No such image")
        else:
            self._logger.info("Successfully Deleted the image")

    def get_password_hash_by_username(self, username: str) -> Optional[str]:
        """
        Get the stored password hash for the given username.

        Args:
            username (str): The username to search for.

        Return:
            Optional[str]: The stored password hash, or None if no user
                with that username exists.

        Raises:
            DBManagerException: If the query fails.
        """
        self._logger.info(f"Getting password hash for username '{username}'.")
        with self._get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT password_hash
                    FROM users
                    WHERE username = %s
                    """,
                    (username,),
                )
                row = cursor.fetchone()

        if row is None:
            self._logger.info("No such user")
            return None
        self._logger.info("Successfully obtained the password hash")
        return next(iter(row), None)
