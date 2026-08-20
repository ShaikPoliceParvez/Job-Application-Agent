from email import policy
from email.parser import BytesParser

from backend.app.config import settings
from backend.app.gmail.service import build_mime_message, resume_attachment_name, text_to_html_email
from backend.app.validation.email import validate_email
from backend.app.agents.draft import generate_email
from backend.app.main import app
from fastapi.testclient import TestClient


def test_text_to_html_email_is_escaped_and_mobile_friendly():
    html = text_to_html_email("Dear HR Team,\n\nI build <safe> systems.\n\nBest regards,\nParvez")

    assert 'name="viewport"' in html
    assert "max-width:680px" in html
    assert "font-size:15px" in html
    assert "line-height:1.6" in html
    assert "&lt;safe&gt;" in html
    assert "<script" not in html.lower()
    assert "Dear HR Team," in html


def test_mime_has_alternative_parts_and_pdf_attachment(tmp_path, monkeypatch):
    resume = tmp_path / "Resume.pdf"
    resume.write_bytes(b"%PDF-test")
    monkeypatch.setattr(settings, "resume_directory", tmp_path)

    message = build_mime_message(
        "hr@example.com",
        "Application for AI Engineer Intern - Parvez",
        "Dear HR Team,\n\nPlease find my resume attached.\n\nBest regards,\nParvez",
        "Resume.pdf",
        sender="candidate@example.com",
    )
    parsed = BytesParser(policy=policy.default).parsebytes(message.as_bytes())

    assert parsed.get_content_type() == "multipart/mixed"
    assert parsed["From"] == "candidate@example.com"
    alternative = parsed.get_payload(0)
    assert alternative.get_content_type() == "multipart/alternative"
    assert [part.get_content_type() for part in alternative.iter_parts()] == [
        "text/plain",
        "text/html",
    ]
    attachment = parsed.get_payload(1)
    assert attachment.get_content_type() == "application/pdf"
    assert attachment.get_filename() == "Resume.pdf"


def test_resume_attachment_name_uses_candidate_name():
    assert resume_attachment_name("Shaik Parvez", "default_resume.pdf") == "Shaik_Parvez_resume.pdf"
    assert resume_attachment_name("", "default_resume.pdf") == "default_resume.pdf"


def test_email_validator_rejects_recipient_and_application_instruction():
    result = validate_email(
        "Application",
        "Dear HR Team,\n\nSend my resume to hr@example.com.\n\nBest regards,\nParvez",
        "hr@example.com",
        {},
        "resume",
    )

    assert not result.valid
    assert any("recipient" in error.lower() for error in result.errors)
    assert any("instructions" in error.lower() for error in result.errors)


def test_email_validator_does_not_count_signature_in_word_limit():
    signature = "\n".join(["Best regards,"] + ["Candidate"] * 20)
    result = validate_email(
        "Application",
        "Dear HR Team,\n\nPlease find my resume attached.\n\n" + signature,
        "hr@example.com",
        {},
        "resume",
        word_limit=8,
    )

    assert result.valid


def test_mock_send_writes_mime_preview(tmp_path, monkeypatch):
    resume = tmp_path / "Resume.pdf"
    resume.write_bytes(b"%PDF-test")
    preview_dir = tmp_path / "logs"
    monkeypatch.setattr(settings, "resume_directory", tmp_path)
    monkeypatch.setattr(settings, "log_dir", preview_dir)
    monkeypatch.setattr(settings, "email_send_mode", "mock")
    monkeypatch.setattr(
        "backend.app.main.load_candidate_context",
        lambda: ({}, "resume", "Resume.pdf"),
    )

    response = TestClient(app).post(
        "/gmail/send",
        data={
            "recipient": "hr@example.com",
            "subject": "Application",
            "body": "Dear HR Team,\n\nPlease find my resume attached.\n\nBest regards,\nParvez",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "MOCK_SENT"
    preview = preview_dir / "mock_email_preview.eml"
    assert preview.exists()
    assert b"multipart/alternative" in preview.read_bytes()


def test_structured_generation_regenerates_after_validation_failure(monkeypatch):
    class FakeModel:
        def __init__(self):
            self.calls = 0

        def generate(self, prompt, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return '{"subject":"Application","body":"Too short"}'
            return '{"subject":"Application","body":"Dear HR Team,\\n\\nPlease find my resume attached.\\n\\nBest regards,\\nParvez"}'

    model = FakeModel()
    monkeypatch.setattr("backend.app.agents.draft.get_job_model", lambda: model)
    result = generate_email("Python internship", {"name": "Parvez"}, "Resume", "hr@example.com")

    assert result.subject == "Application - Parvez"
    assert "Best regards" in result.body
    assert model.calls == 2


def test_resume_identity_fills_subject_and_signature(monkeypatch):
    class FakeModel:
        def generate(self, prompt, **kwargs):
            assert "2004parvez@gmail.com" in prompt
            assert "8341765885" in prompt
            return '{"subject":"Application for AI/ML Engineer Intern - Your Name","body":"Dear HR Team,\\n\\nPlease find my resume attached.\\n\\nBest regards,\\nShaik Police Parvez\\nIndian Institute of Technology Hyderabad\\n2004parvez@gmail.com\\n8341765885"}'

    monkeypatch.setattr("backend.app.agents.draft.get_job_model", lambda: FakeModel())
    result = generate_email(
        "AI/ML Engineer Intern at InnovateAI",
        {},
        "Shaik Police Parvez\nB.Tech - Computer Science\nIndian Institute of Technology Hyderabad\n8341765885 2004parvez@gmail.com",
        "hr@example.com",
    )

    assert result.subject == "Application for AI/ML Engineer Intern - Shaik Police Parvez"
    assert "2004parvez@gmail.com" in result.body
    assert "8341765885" in result.body


def test_verbose_model_output_is_trimmed_before_validation(monkeypatch):
    class FakeModel:
        def generate(self, prompt, **kwargs):
            long_body = "Dear HR Team,\n\n" + "Relevant qualification details. " * 80
            return '{"subject":"Application","body":' + repr(long_body).replace("'", '"') + "}"

    monkeypatch.setattr("backend.app.agents.draft.get_job_model", lambda: FakeModel())
    result = generate_email("Python internship", {"name": "Parvez"}, "Resume", "hr@example.com")

    assert len(result.body.split("Best regards,")[0].split()) <= 110
