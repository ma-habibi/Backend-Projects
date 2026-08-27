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


class TestResize:
    def test_resize_changes_dimensions(self, service, red_image):
        params = models.Resize(width=50, height=25)
        result = service._resize(red_image, params)
        assert result.size == (50, 25)

    @pytest.mark.parametrize("width,height", [(0, 10), (10, 0), (-5, 10)])
    def test_resize_rejects_non_positive_dimensions(
        self, service, red_image, width, height
    ):
        params = models.Resize(width=width, height=height)
        with pytest.raises(ValueError, match="positive"):
            service._resize(red_image, params)


class TestCrop:
    def test_crop_extracts_correct_region(self, service):
        # Left half red, right half blue — crop should grab only one side.
        image = Image.new("RGB", (100, 100))
        for x in range(100):
            for y in range(100):
                image.putpixel((x, y), (255, 0, 0) if x < 50 else (0, 0, 255))

        params = models.Crop(x=60, y=0, width=20, height=20)
        cropped = service._crop(image, params)

        assert cropped.size == (20, 20)
        assert cropped.getpixel((0, 0)) == (0, 0, 255)

    def test_crop_out_of_bounds_raises(self, service, red_image):
        # red_image is 100x50; this box runs past the right edge.
        params = models.Crop(x=90, y=0, width=50, height=10)
        with pytest.raises(ValueError, match="outside image bounds"):
            service._crop(red_image, params)

    def test_crop_negative_origin_raises(self, service, red_image):
        params = models.Crop(x=-5, y=0, width=10, height=10)
        with pytest.raises(ValueError, match="outside image bounds"):
            service._crop(red_image, params)


class TestRotate:
    def test_rotate_90_swaps_dimensions(self, service, red_image):
        # 100x50 rotated 90 degrees, expand=True, should become ~50x100.
        rotated = service._rotate(red_image, 90)
        assert rotated.size == (50, 100)

    def test_rotate_0_is_a_noop_on_size(self, service, red_image):
        rotated = service._rotate(red_image, 0)
        assert rotated.size == red_image.size


class TestFlipMirror:
    def test_flip_reverses_vertically(self, service):
        image = Image.new("RGB", (2, 2))
        image.putpixel((0, 0), (255, 0, 0))  # top-left red
        image.putpixel((0, 1), (0, 255, 0))  # bottom-left green

        flipped = service._flip(image)

        assert flipped.getpixel((0, 0)) == (0, 255, 0)
        assert flipped.getpixel((0, 1)) == (255, 0, 0)

    def test_mirror_reverses_horizontally(self, service):
        image = Image.new("RGB", (2, 2))
        image.putpixel((0, 0), (255, 0, 0))  # top-left red
        image.putpixel((1, 0), (0, 255, 0))  # top-right green

        mirrored = service._mirror(image)

        assert mirrored.getpixel((0, 0)) == (0, 255, 0)
        assert mirrored.getpixel((1, 0)) == (255, 0, 0)


class TestUploadImage:
    def test_upload_rejects_invalid_image_bytes(self, service):
        garbage = BytesIO(b"this is not an image")
        with pytest.raises(ImageProcessingServiceException) as exc_info:
            service.upload_image("user-1", garbage, "not_an_image.txt")
        assert exc_info.value.status_code == 400

    def test_upload_rolls_back_db_record_on_r2_failure(
        self, service, mock_db, mock_r2, sample_image_record
    ):
        mock_db.create_image.return_value = sample_image_record
        mock_r2.create.side_effect = R2BucketHandlerException("boom")

        buffer = BytesIO()
        Image.new("RGB", (10, 10)).save(buffer, format="PNG")
        buffer.seek(0)

        with pytest.raises(ImageProcessingServiceException) as exc_info:
            service.upload_image("user-1", buffer, "test.png")

        assert exc_info.value.status_code == 500
        mock_db.delete_image.assert_called_once_with(sample_image_record.id, "user-1")
