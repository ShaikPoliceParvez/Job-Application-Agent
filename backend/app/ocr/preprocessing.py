"""
Image preprocessing utilities for the OCR pipeline.

Design intent (per spec section 5):
- Preprocessing is OPTIONAL and applied selectively, not blindly.
- A screenshot that already produces good OCR should not be preprocessed.
- Each transform is its own small function so `run_paddleocr` (Phase 1)
  and later steps can opt into exactly what they need.
"""

from __future__ import annotations

import logging

import cv2
import numpy as np
from PIL import Image

from ..config import settings

logger = logging.getLogger("ocr.preprocessing")


def load_image(path: str) -> np.ndarray:
    """Load an image from disk as a BGR numpy array (OpenCV convention)."""
    image = cv2.imread(path)
    if image is None:
        # Fall back to PIL for formats/paths cv2 sometimes chokes on (e.g. some WEBP/PNG variants)
        pil_image = Image.open(path).convert("RGB")
        image = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
    return image


def to_grayscale(image: np.ndarray) -> np.ndarray:
    if len(image.shape) == 2:
        return image
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def enhance_contrast(image: np.ndarray) -> np.ndarray:
    """CLAHE-based local contrast enhancement. Works on gray or BGR input."""
    gray = to_grayscale(image)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    if len(image.shape) == 3:
        return cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)
    return enhanced


def denoise(image: np.ndarray) -> np.ndarray:
    if len(image.shape) == 3:
        return cv2.fastNlMeansDenoisingColored(image, None, 7, 7, 7, 21)
    return cv2.fastNlMeansDenoising(image, None, 7, 7, 21)


def resize(image: np.ndarray, max_dimension: int = 1024) -> np.ndarray:
    """Upscale small screenshots / downscale huge ones for more reliable OCR."""
    height, width = image.shape[:2]
    longest_side = max(height, width)

    if longest_side == max_dimension:
        return image

    scale = max_dimension / longest_side
    # Don't upscale tiny crops excessively; cap upscaling at 2x.
    if scale > 2.0:
        scale = 2.0

    new_size = (int(width * scale), int(height * scale))
    interpolation = cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA
    return cv2.resize(image, new_size, interpolation=interpolation)


def detect_skew_angle(image: np.ndarray) -> float:
    """Estimate rotation skew (degrees) using the minAreaRect of text-like contours."""
    gray = to_grayscale(image)
    gray = cv2.bitwise_not(gray)
    thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]

    coords = np.column_stack(np.where(thresh > 0))
    if coords.shape[0] < 20:
        return 0.0

    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle
    return float(angle)


def correct_rotation(image: np.ndarray) -> np.ndarray:
    """Deskew the image if a meaningful skew angle is detected."""
    angle = detect_skew_angle(image)
    if abs(angle) < 0.5:
        return image

    (h, w) = image.shape[:2]
    center = (w // 2, h // 2)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    rotated = cv2.warpAffine(
        image, matrix, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )
    logger.info("Corrected rotation by %.2f degrees", angle)
    return rotated


def crop(image: np.ndarray, bbox: tuple[int, int, int, int]) -> np.ndarray:
    """bbox = (x1, y1, x2, y2)."""
    x1, y1, x2, y2 = bbox
    return image[y1:y2, x1:x2]


def preprocess_image(
    path: str,
    *,
    do_resize: bool = True,
    do_grayscale: bool = False,
    do_contrast: bool = False,
    do_denoise: bool = False,
    do_rotation_correction: bool = True,
) -> np.ndarray:
    """
    Apply a conservative, opt-in preprocessing pipeline.

    Defaults only resize + deskew, since PaddleOCR's own detector already
    handles a lot of normalization internally. Heavier operations
    (grayscale/contrast/denoise) are off by default and meant to be turned
    on by the caller (or automatically, later, based on a first-pass low
    confidence score).
    """
    image = load_image(path)

    if do_resize:
        image = resize(image, settings.ocr_max_side)
    if do_rotation_correction:
        image = correct_rotation(image)
    if do_denoise:
        image = denoise(image)
    if do_contrast:
        image = enhance_contrast(image)
    if do_grayscale:
        image = to_grayscale(image)

    return image
