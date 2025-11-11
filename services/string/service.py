import io
from dataclasses import asdict
from typing import Any, Dict

import numpy as np
from PIL import Image, UnidentifiedImageError

from services.string.generate import (
    StringArtOptions,
    StringArtResult,
    generate_string_art_from_array,
)


class StringArtImageError(ValueError):
    """Raised when the uploaded file is not a valid image."""


def generate_string_metadata(image_bytes: bytes, options: StringArtOptions) -> Dict[str, Any]:
    image_array = _load_upload_image(image_bytes)
    result = generate_string_art_from_array(image_array, options)
    return _result_to_metadata(result)


def _load_upload_image(data: bytes) -> np.ndarray:
    try:
        with Image.open(io.BytesIO(data)) as pil_image:
            pil_image = pil_image.convert("RGB")
            return np.asarray(pil_image, dtype=np.float32)
    except UnidentifiedImageError as exc:
        raise StringArtImageError("유효한 이미지 파일을 업로드해주세요.") from exc


def _result_to_metadata(result: StringArtResult) -> Dict[str, Any]:
    return {
        "mode": result.mode,
        "pullOrders": result.pull_orders,
        "nails": result.nails,
        "scaledNails": result.scaled_nails,
        "settings": asdict(result.options),
    }
