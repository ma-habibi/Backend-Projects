import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Optional
from datetime import datetime

from common import common
from db_manager_exception import DBManagerException

import psycopg
from psycopg_pool import ConnectionPool


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

    id: int
    username: str
    created_at: datetime


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

        return UserRecord(
            id=next(iter(row), None),
            username=next(iter(row), None),
            created_at=next(iter(row), None),
        )

    def get_user_by_username(self, username: str) -> Optional[UserRecord]:
        """
        Return the user matching the given username, or None if no such user exists.
        """

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
            return None
        return UserRecord(id=row[0], username=row[1], created_at=row[2])
