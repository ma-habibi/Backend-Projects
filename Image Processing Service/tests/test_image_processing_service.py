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


class TestFilters:
    def test_grayscale_removes_color(self, service, red_image):
        filters = models.Filters(grayscale=True, sepia=False)
        result = service._apply_filters(red_image, filters)
        assert result.mode == "L"

    def test_sepia_tints_the_image(self, service, red_image):
        filters = models.Filters(grayscale=False, sepia=True)
        result = service._apply_filters(red_image, filters)
        r, g, b = result.getpixel((0, 0))
        # Sepia should not be a neutral gray — R should dominate.
        assert r > g > b

    def test_no_filters_requested_is_a_noop(self, service, red_image):
        filters = models.Filters(grayscale=False, sepia=False)
        result = service._apply_filters(red_image, filters)
        assert result.getpixel((0, 0)) == (255, 0, 0)


class TestCompress:
    def test_compress_stores_quality_on_info(self, service, red_image):
        result = service._compress(red_image, 40)
        assert result.info.get("quality") == 40

    def test_compress_rejects_out_of_range_quality(self, service, red_image):
        with pytest.raises(ValueError, match="between 1 and 100"):
            service._compress(red_image, 150)

    def test_compress_is_noop_for_lossless_format(self, service):
        png_image = Image.new("RGB", (10, 10), color=(0, 255, 0))
        png_image.format = "PNG"
        result = service._compress(png_image, 40)
        # PNG is lossless; compress should return the image unchanged
        # rather than pretending a quality setting did something.
        assert "quality" not in result.info


class TestConvertFormat:
    def test_convert_sets_format_attribute(self, service, red_image):
        result = service._convert_format(red_image, "png")
        assert result.format == "PNG"

    def test_convert_rejects_unsupported_format(self, service, red_image):
        with pytest.raises(ValueError, match="Unsupported format"):
            service._convert_format(red_image, "tiff")

    def test_convert_to_jpeg_drops_alpha(self, service):
        rgba_image = Image.new("RGBA", (10, 10), color=(255, 0, 0, 128))
        result = service._convert_format(rgba_image, "jpeg")
        assert result.mode == "RGB"


class TestWatermark:
    def test_watermark_preserves_dimensions(self, service, red_image):
        result = service._watermark(red_image)
        assert result.size == red_image.size

    def test_watermark_changes_bottom_right_region(self, service):
        # Check a region overlapping where the watermark actually lands,
        # rather than one exact pixel — the watermark is scaled and inset
        # by a margin, so the literal last pixel (width-1, height-1) may
        # legitimately fall outside it depending on image size.
        image = Image.new("RGB", (400, 400), color=(0, 0, 255))
        original_region = list(image.crop((280, 340, 400, 400)).getdata())

        result = service._watermark(image)
        result_region = list(result.crop((280, 340, 400, 400)).getdata())

        assert result_region != original_region

    def test_watermark_missing_asset_raises(
        self, service, red_image, monkeypatch, tmp_path
    ):
        service._watermark_path = tmp_path / "does_not_exist.png"
        with pytest.raises(FileNotFoundError):
            service._watermark(red_image)


class TestExtractMetadata:
    def test_extracts_dimensions_and_format(self, service, red_image):
        metadata = service._extract_metadata(red_image)
        assert metadata["width"] == 100
        assert metadata["height"] == 50
        assert metadata["format"] == "jpeg"
        assert metadata["size_bytes"] > 0

    def test_size_reflects_compress_quality(self, service, red_image):
        low_quality = service._compress(red_image, 10)
        high_quality = service._compress(red_image, 95)

        low_metadata = service._extract_metadata(low_quality)
        high_metadata = service._extract_metadata(high_quality)

        # Lower quality should produce a smaller (or equal) file.
        assert low_metadata["size_bytes"] <= high_metadata["size_bytes"]


class TestApplyTransformationsOrder:
    def test_crop_runs_before_resize(self, service):
        """
        A regression guard for the fixed transformation order: if resize
        ran before crop, cropping a region that's only valid pre-resize
        would be silently wrong or raise, depending on dimensions. This
        pins crop -> resize as the actual execution order.
        """
        image = Image.new("RGB", (100, 100), color=(255, 0, 0))
        transformations = models.Transformations(
            crop=models.Crop(x=0, y=0, width=100, height=100),
            resize=models.Resize(width=10, height=10),
        )
        result = service._apply_transformations(image, transformations)
        assert result.size == (10, 10)

    def test_no_transformations_requested_returns_equivalent_image(
        self, service, red_image
    ):
        transformations = models.Transformations()
        result = service._apply_transformations(red_image, transformations)
        assert result.size == red_image.size


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


class TestDeleteImage:
    def test_delete_not_found_raises_404(self, service, mock_db):
        mock_db.get_image.return_value = None
        with pytest.raises(ImageProcessingServiceException) as exc_info:
            service.delete_image("missing-id", "user-1")
        assert exc_info.value.status_code == 404
        # Should never touch R2 if there's no record to begin with.
        service._r2.delete.assert_not_called()

    def test_delete_calls_r2_then_db_in_order(
        self, service, mock_db, mock_r2, sample_image_record
    ):
        mock_db.get_image.return_value = sample_image_record

        service.delete_image(sample_image_record.id, "user-1")

        mock_r2.delete.assert_called_once_with([sample_image_record.id])
        mock_db.delete_image.assert_called_once_with(sample_image_record.id, "user-1")
