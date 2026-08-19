from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

FIXTURE = "tests/fixtures/test_job_screenshot.png"


def _fake_predict_result():
    """Mimic paddleocr>=3.7 PaddleOCR.predict() output shape."""
    return [
        {
            "rec_texts": [
                "ABC Technologies",
                "We are hiring an AI Engineer Intern",
                "hr@abctechnologies.com",
            ],
            "rec_scores": [0.98, 0.95, 0.99],
            "rec_polys": [
                [[0, 0], [100, 0], [100, 20], [0, 20]],
                [[0, 30], [200, 30], [200, 50], [0, 50]],
                [[0, 60], [180, 60], [180, 80], [0, 80]],
            ],
        }
    ]


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["phase"] == 3
    assert "resume_name" in response.json()


def test_analyze_rejects_unsupported_file_type():
    response = client.post(
        "/analyze",
        files={"file": ("resume.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert response.status_code == 400


def test_analyze_rejects_empty_file():
    response = client.post(
        "/analyze",
        files={"file": ("empty.png", b"", "image/png")},
    )
    assert response.status_code == 400


@patch("app.models.paddle_ocr.PaddleOCRModel._load")
def test_analyze_success_with_mocked_ocr(mock_load):
    mock_engine = MagicMock()
    mock_engine.predict.return_value = _fake_predict_result()
    mock_load.return_value = mock_engine

    with open(FIXTURE, "rb") as f:
        response = client.post(
            "/analyze",
            files={"file": ("test_job_screenshot.png", f, "image/png")},
        )

    assert response.status_code == 200
    data = response.json()

    assert data["success"] is True
    assert "ABC Technologies" in data["text"]
    assert "hr@abctechnologies.com" in data["text"]
    assert data["confidence"] > 0.9
    assert len(data["blocks"]) == 3
    assert data["candidate_emails"] == ["hr@abctechnologies.com"]
    assert data["low_confidence"] is False
    assert data["screenshot_path"] is not None


@patch("app.models.paddle_ocr.PaddleOCRModel._load")
def test_analyze_flags_low_confidence(mock_load):
    mock_engine = MagicMock()
    mock_engine.predict.return_value = [
        {
            "rec_texts": ["blurry text"],
            "rec_scores": [0.3],
            "rec_polys": [[[0, 0], [50, 0], [50, 10], [0, 10]]],
        }
    ]
    mock_load.return_value = mock_engine

    with open(FIXTURE, "rb") as f:
        response = client.post(
            "/analyze",
            files={"file": ("test_job_screenshot.png", f, "image/png")},
        )

    data = response.json()
    assert data["success"] is True
    assert data["low_confidence"] is True


@patch("app.models.paddle_ocr.PaddleOCRModel._load")
def test_analyze_handles_ocr_engine_failure_gracefully(mock_load):
    mock_load.side_effect = RuntimeError("simulated model load failure")

    with open(FIXTURE, "rb") as f:
        response = client.post(
            "/analyze",
            files={"file": ("test_job_screenshot.png", f, "image/png")},
        )

    # Endpoint should not crash — it returns success=False with an error message.
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert "simulated model load failure" in data["error"]
