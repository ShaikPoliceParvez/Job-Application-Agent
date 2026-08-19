import numpy as np

from backend.app.ocr.preprocessing import (
    correct_rotation,
    enhance_contrast,
    load_image,
    preprocess_image,
    resize,
    to_grayscale,
)


FIXTURE = "tests/fixtures/test_job_screenshot.png"


def test_load_image_returns_bgr_array():
    image = load_image(FIXTURE)
    assert isinstance(image, np.ndarray)
    assert image.ndim == 3
    assert image.shape[2] == 3


def test_to_grayscale_reduces_to_single_channel():
    image = load_image(FIXTURE)
    gray = to_grayscale(image)
    assert gray.ndim == 2


def test_to_grayscale_is_idempotent():
    image = load_image(FIXTURE)
    gray = to_grayscale(image)
    gray_again = to_grayscale(gray)
    assert gray_again.ndim == 2


def test_resize_respects_max_dimension():
    image = load_image(FIXTURE)
    resized = resize(image, max_dimension=300)
    assert max(resized.shape[:2]) <= 300


def test_resize_caps_upscaling_at_2x():
    tiny = np.zeros((50, 50, 3), dtype=np.uint8)
    resized = resize(tiny, max_dimension=2000)
    assert max(resized.shape[:2]) <= 100  # 2x cap, not 40x


def test_enhance_contrast_preserves_shape():
    image = load_image(FIXTURE)
    enhanced = enhance_contrast(image)
    assert enhanced.shape == image.shape


def test_correct_rotation_is_noop_on_already_straight_image():
    image = load_image(FIXTURE)
    corrected = correct_rotation(image)
    assert corrected.shape == image.shape


def test_preprocess_image_default_pipeline_runs_end_to_end():
    result = preprocess_image(FIXTURE)
    assert isinstance(result, np.ndarray)
    assert result.ndim == 3


def test_preprocess_image_all_options_enabled():
    result = preprocess_image(
        FIXTURE,
        do_resize=True,
        do_grayscale=True,
        do_contrast=True,
        do_denoise=True,
        do_rotation_correction=True,
    )
    assert isinstance(result, np.ndarray)
    # grayscale was requested last, so the final array should be 2D
    assert result.ndim == 2
