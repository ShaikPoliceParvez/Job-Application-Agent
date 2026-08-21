from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.ocr.storage import retain_recent_screenshots

client = TestClient(app)

FIXTURE = "tests/fixtures/test_job_screenshot.png"


def test_screenshot_retention_keeps_only_five_newest(tmp_path):
    paths = []
    for index in range(7):
        path = tmp_path / f"shot-{index}.png"
        path.write_bytes(str(index).encode())
        path.touch()
        paths.append(path)

    # Make ordering deterministic on filesystems with coarse timestamps.
    for index, path in enumerate(paths):
        import os

        os.utime(path, (index, index))

    removed = retain_recent_screenshots(tmp_path, limit=5)

    assert {path.name for path in removed} == {"shot-0.png", "shot-1.png"}
    assert {path.name for path in tmp_path.iterdir()} == {
        "shot-2.png", "shot-3.png", "shot-4.png", "shot-5.png", "shot-6.png"
    }


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


def test_analyze_accepts_pdf_with_hosted_ocr():
    with patch("backend.app.main.extract_ocr_text") as extract:
        extract.return_value = {"text": "A job posting", "confidence": 0.95, "blocks": []}
        response = client.post(
            "/analyze",
            files={"file": ("job.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )
    assert response.status_code == 200
    assert response.json()["success"] is True


def test_analyze_rejects_unsupported_file_type():
    response = client.post(
        "/analyze",
        files={"file": ("resume.txt", b"plain text", "text/plain")},
    )
    assert response.status_code == 400


def test_analyze_rejects_empty_file():
    response = client.post(
        "/analyze",
        files={"file": ("empty.png", b"", "image/png")},
    )
    assert response.status_code == 400


@patch("backend.app.main.extract_ocr_text")
def test_analyze_success_with_mocked_ocr(extract):
    result = _fake_predict_result()[0]
    extract.return_value = {
        "text": "\n".join(result["rec_texts"]),
        "confidence": 0.97,
        "blocks": [
            {"text": text, "confidence": score, "bbox": bbox}
            for text, score, bbox in zip(result["rec_texts"], result["rec_scores"], result["rec_polys"])
        ],
    }

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
    assert data["screenshot_path"] is None


@patch("backend.app.main.extract_ocr_text")
def test_analyze_flags_low_confidence(extract):
    extract.return_value = {
        "text": "blurry text",
        "confidence": 0.3,
        "blocks": [{"text": "blurry text", "confidence": 0.3, "bbox": []}],
    }

    with open(FIXTURE, "rb") as f:
        response = client.post(
            "/analyze",
            files={"file": ("test_job_screenshot.png", f, "image/png")},
        )

    data = response.json()
    assert data["success"] is True
    assert data["low_confidence"] is True


@patch("backend.app.main.extract_ocr_text")
def test_analyze_handles_ocr_engine_failure_gracefully(extract):
    extract.side_effect = RuntimeError("simulated hosted OCR failure")

    with open(FIXTURE, "rb") as f:
        response = client.post(
            "/analyze",
            files={"file": ("test_job_screenshot.png", f, "image/png")},
        )

    # Endpoint should not crash — it returns success=False with an error message.
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert "simulated hosted OCR failure" in data["error"]
