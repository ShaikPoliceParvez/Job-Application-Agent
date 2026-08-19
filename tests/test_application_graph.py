from unittest.mock import MagicMock, patch

from backend.app.agents.graph import build_application_graph
from backend.app.schemas.job import JobPosting


class FakeGmailMCP:
    def __init__(self):
        self.calls = []

    def send(self, recipient, subject, body, attachment_path=""):
        self.calls.append((recipient, subject, body, attachment_path))
        return "mcp-message-123"


def _model():
    model = MagicMock()
    model.generate.return_value = "Subject: Application\n\nDear HR Team,\n\nHello."
    model.generate_stream.return_value = iter(["Subject: Application\n\nDear HR Team,\n\nHello."])
    return model


def test_graph_stops_for_human_approval():
    sender = FakeGmailMCP()
    with patch("backend.app.agents.graph.extract_job") as extract, patch("backend.app.agents.graph.load_candidate_context") as context, patch("backend.app.agents.graph.get_job_model", return_value=_model()):
        extract.return_value = JobPosting(recipient_email="hr@example.com", role="Intern")
        context.return_value = ({"name": "Candidate"}, "Resume text", "resume.txt")
        result = build_application_graph(sender).invoke(
            {"source_text": "Python internship", "approved": False}
        )

    assert result["email_subject"] == "Subject: Application"
    assert sender.calls == []


def test_graph_sends_only_after_explicit_approval():
    sender = FakeGmailMCP()
    with patch("backend.app.agents.graph.extract_job") as extract, patch("backend.app.agents.graph.load_candidate_context") as context, patch("backend.app.agents.graph.get_job_model", return_value=_model()):
        extract.return_value = JobPosting(recipient_email="hr@example.com", role="Intern")
        context.return_value = ({"name": "Candidate"}, "Resume text", "resume.txt")
        result = build_application_graph(sender).invoke(
            {"source_text": "Python internship", "approved": True}
        )

    assert result["sent"] is True
    assert result["send_result"] == "mcp-message-123"
    assert sender.calls[0][0] == "hr@example.com"