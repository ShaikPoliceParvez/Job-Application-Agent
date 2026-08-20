from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.agents.draft import build_draft_prompt


client = TestClient(app)


def test_draft_prompt_contains_requested_email_constraints():
    prompt = build_draft_prompt(
        '{"job_title":"AI/ML/GenAI Engineer Intern",'
        '"application":{"required_subject":"Application for AI/ML/GenAI Engineer Intern - Your Name"}}',
        {"name": "Shaik P Parvez", "skills": ["RAG", "LangGraph"]},
        "Built AI applications using RAG and LangGraph.",
    )

    assert "Body maximum: 120 words" in prompt
    assert 'Return JSON only with exactly two keys: subject and body' in prompt
    assert "Best regards," in prompt
    assert "Never invent or exaggerate" in prompt
    assert "RAG" in prompt
    assert "LangGraph" in prompt


def test_draft_prompt_contains_profile_signature_without_placeholders():
    prompt = build_draft_prompt(
        "AI/ML Engineer Intern",
        {
            "name": "Shaik Parvez",
            "education": [{"institution": "Indian Institute of Technology Hyderabad"}],
            "email": "parvez@example.com",
            "phone": "+91 99999 99999",
            "links": {"linkedin": "linkedin.com/in/parvez", "github": ""},
        },
        "Resume text",
    )

    assert "Best regards,\nShaik Parvez" in prompt
    assert "Indian Institute of Technology Hyderabad" in prompt
    assert "parvez@example.com" in prompt
    assert "+91 99999 99999" in prompt
    assert "LinkedIn: linkedin.com/in/parvez" in prompt
    assert "GitHub:" not in prompt
    assert "[Email Address]" not in prompt
    assert "[Phone Number]" not in prompt


def test_chat_homepage_is_served():
    response = client.get("/")

    assert response.status_code == 200
    assert "Job Application Agent" in response.text


def test_draft_streams_pasted_text_and_model_tokens():
    with patch("backend.app.main.load_candidate_context") as load_context, patch("backend.app.main.stream_draft") as stream:
        load_context.return_value = ({"name": "Candidate"}, "Python resume", "resume.txt")
        stream.return_value = iter(["Subject: Application\n\n", "Hello HR,"])

        response = client.post(
            "/draft",
            data={"message": "We are hiring a Python engineer.", "recipient": "hr@example.com"},
        )

    assert response.status_code == 200
    assert "event: extracted_text" in response.text
    assert "We are hiring a Python engineer." in response.text
    assert "event: draft_token" in response.text
    assert "Subject: Application" in response.text
    assert "event: complete" in response.text
    assert "resume.txt" in response.text


def test_draft_requires_a_source():
    response = client.post("/draft", data={"message": ""})

    assert response.status_code == 400


def test_refine_streams_revised_draft():
    with patch("backend.app.main.load_candidate_context") as load_context, patch("backend.app.main.stream_refinement") as stream:
        load_context.return_value = ({"name": "Candidate"}, "resume", "resume.txt")
        stream.return_value = iter(["Subject: Revised\n\n", "Dear HR Team,"])

        response = client.post(
            "/refine",
            data={
                "instruction": "Make the opening warmer.",
                "current_draft": "Subject: Old\n\nDear HR Team,\n\nHello.",
                "posting": "Python internship",
            },
        )

    assert response.status_code == 200
    assert "Applying your edit with Ollama" in response.text
    assert "Subject: Revised" in response.text
    assert "event: complete" in response.text


def test_refine_requires_existing_draft_and_instruction():
    assert client.post("/refine", data={"instruction": "Make it shorter"}).status_code == 400
    assert client.post("/refine", data={"current_draft": "Subject: Test"}).status_code == 400