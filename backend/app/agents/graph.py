"""LangGraph orchestration for the job application workflow.

The graph is deliberately transport-agnostic: HTTP, a chat UI, or an MCP
server can provide the initial state and an approval decision. Sending is
performed only through the injected sender after explicit approval.
"""

from __future__ import annotations

from typing import Any, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph

from .draft import generate_email
from .job_extraction import extract_job
from ..config import settings
from ..models.paddle_ocr import extract_email_candidates, get_ocr_model
from ..ocr.preprocessing import preprocess_image
from ..profile.loader import load_candidate_context
from ..schemas.job import JobPosting


class GmailMCPSender(Protocol):
    """Minimal contract implemented by the configured Gmail MCP tool."""

    def send(self, recipient: str, subject: str, body: str, attachment_path: str = "") -> str:
        ...


class ApplicationState(TypedDict, total=False):
    screenshot_path: str
    source_text: str
    candidate_emails: list[str]
    job: JobPosting
    profile: dict[str, Any]
    resume_text: str
    resume_name: str
    resume_path: str
    email_subject: str
    email_body: str
    approved: bool
    sent: bool
    send_result: str
    error: str


def _ocr_node(state: ApplicationState) -> dict[str, Any]:
    if state.get("source_text", "").strip():
        text = state["source_text"].strip()
    elif state.get("screenshot_path"):
        image = preprocess_image(state["screenshot_path"])
        text = get_ocr_model().extract_text(image)["text"]
    else:
        raise ValueError("Provide source_text or screenshot_path")
    return {"source_text": text, "candidate_emails": extract_email_candidates(text)}


def _job_node(state: ApplicationState) -> dict[str, Any]:
    return {"job": extract_job(state["source_text"], state.get("candidate_emails", []))}


def _context_node(state: ApplicationState) -> dict[str, Any]:
    profile, resume_text, resume_name = load_candidate_context()
    return {"profile": profile, "resume_text": resume_text, "resume_name": resume_name}


def _draft_node(state: ApplicationState) -> dict[str, Any]:
    recipient = state.get("job", JobPosting()).recipient_email
    email = generate_email(
        state["source_text"],
        state.get("profile", {}),
        state.get("resume_text", ""),
        recipient,
    )
    return {"email_subject": email.subject, "email_body": email.body}


def _approval_node(state: ApplicationState) -> dict[str, Any]:
    return {"approved": bool(state.get("approved", False))}


def _approval_route(state: ApplicationState) -> str:
    return "send" if state.get("approved") else END


def _send_node(state: ApplicationState, sender: GmailMCPSender | None) -> dict[str, Any]:
    if sender is None:
        raise RuntimeError("No Gmail MCP sender is configured")
    recipient = state.get("job", JobPosting()).recipient_email
    if not recipient:
        raise ValueError("Cannot send without a trusted recipient email")
    result = sender.send(
        recipient=recipient,
        subject=state.get("email_subject", ""),
        body=state.get("email_body", ""),
        attachment_path=state.get("resume_name", ""),
    )
    return {"sent": True, "send_result": result}


def build_application_graph(sender: GmailMCPSender | None = None):
    """Compile the workflow; pass an MCP Gmail sender only in the send mode."""
    graph = StateGraph(ApplicationState)
    graph.add_node("ocr", _ocr_node)
    graph.add_node("extract_job", _job_node)
    graph.add_node("load_context", _context_node)
    graph.add_node("draft", _draft_node)
    graph.add_node("approval", _approval_node)
    graph.add_node("send", lambda state: _send_node(state, sender))
    graph.add_edge(START, "ocr")
    graph.add_edge("ocr", "extract_job")
    graph.add_edge("extract_job", "load_context")
    graph.add_edge("load_context", "draft")
    graph.add_edge("draft", "approval")
    graph.add_conditional_edges("approval", _approval_route, {"send": "send", END: END})
    graph.add_edge("send", END)
    return graph.compile()


def run_application(state: ApplicationState, sender: GmailMCPSender | None = None) -> ApplicationState:
    """Run through draft/review, optionally sending after approved=True."""
    if settings.email_send_mode != "gmail":
        sender = None
    return build_application_graph(sender).invoke(state)