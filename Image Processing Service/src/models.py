from pydantic import BaseModel


class User(BaseModel):
    username: str
    password: str


class Resize(BaseModel):
    width: float
    height: float


class Crop(BaseModel):
    width: float
    height: float
    x: float
    y: float


class Filters(BaseModel):
    grayscale: bool
    sepia: bool


class Transformations(BaseModel):
    resize: Resize | None = None
    crop: Crop | None = None
    rotate: float | None = None
    flip: bool = False
    mirror: bool = False
    watermark: bool = False
    compress: int | None = None  # target quality, 1-100
    format: str | None = None
    filters: Filters | None = None


class ImageTransformRequest(BaseModel):
    transformations: Transformations
