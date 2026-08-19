from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.main import app


client = TestClient(app)


def test_extract_job_uses_local_model_and_trusted_email():
    with patch(
        "backend.app.agents.job_extraction.get_job_model"
    ) as get_model:
        get_model.return_value.generate.return_value = (
            '{"company":"ABC Technologies","role":"AI Engineer Intern",'
            '"hr_name":"","recipient_email":"hr@abc.example",'
            '"requirements":["Python"],"deadline":""}'
        )

        response = client.post(
            "/extract-job",
            json={
                "text": "ABC Technologies is hiring. Email hr@abc.example.",
                "candidate_emails": ["hr@abc.example"],
            },
        )

    assert response.status_code == 200
    assert response.json()["job"]["role"] == "AI Engineer Intern"
    assert response.json()["job"]["recipient_email"] == "hr@abc.example"


def test_extract_job_clears_untrusted_model_email():
    with patch("backend.app.agents.job_extraction.get_job_model") as get_model:
        get_model.return_value.generate.return_value = (
            '{"recipient_email":"invented@example.com"}'
        )

        response = client.post(
            "/extract-job",
            json={"text": "A job posting without an email", "candidate_emails": []},
        )

    assert response.status_code == 200
    assert response.json()["job"]["recipient_email"] == ""


def test_extract_job_accepts_string_requirements_from_small_model():
    with patch("backend.app.agents.job_extraction.get_job_model") as get_model:
        get_model.return_value.generate.return_value = (
            '{"company":"ABC Technologies","requirements":"Strong Python programming '
            'and deployment concepts"}'
        )

        response = client.post("/extract-job", json={"text": "A Python job"})

    assert response.status_code == 200
    assert response.json()["job"]["requirements"] == [
        "Strong Python programming and deployment concepts"
    ]