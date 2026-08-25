from io import BytesIO
from unittest.mock import MagicMock

import pytest
from PIL import Image

from src.common import common
from src.db_manager import DBManager, DBManagerException, ImageRecord
from src.r2_bucket_handler import R2BucketHandler, R2BucketHandlerException
from src.image_processing_service import ImageProcessingService
from src.image_processing_service_exception import ImageProcessingServiceException
from src import models


@pytest.fixture
def mock_db() -> MagicMock:
    """A MagicMock standing in for DBManager, spec'd so typos in test
    code raise AttributeError instead of silently returning a MagicMock."""
    return MagicMock(spec=DBManager)


@pytest.fixture
def mock_r2() -> MagicMock:
    """A MagicMock standing in for R2BucketHandler."""
    return MagicMock(spec=R2BucketHandler)


@pytest.fixture
def service(mock_db, mock_r2) -> ImageProcessingService:
    """An ImageProcessingService wired to the mocked DB/R2 above."""
    return ImageProcessingService(db=mock_db, r2=mock_r2)


@pytest.fixture
def red_image() -> Image.Image:
    """A 100x50 solid red JPEG-formatted image."""
    image = Image.new("RGB", (100, 50), color=(255, 0, 0))
    image.format = "JPEG"
    return image


@pytest.fixture
def sample_image_record() -> ImageRecord:
    """A representative ImageRecord as DBManager.get_image would return."""
    from datetime import datetime, timezone

    return ImageRecord(
        id="abc-123",
        user_id="user-1",
        filename="photo.jpg",
        format="jpeg",
        width=100,
        height=50,
        size_bytes=1234,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
