"""Deterministic validation for generated application emails."""

from __future__ import annotations

import re
from dataclasses import dataclass
from email.utils import parseaddr

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_APPLICATION_INSTRUCTION_RE = re.compile(
    r"(?:send|email|forward|submit)\s+(?:my|the)?\s*(?:resume|cv|application)\s+to\s+[^.\n]+",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class EmailValidation:
    valid: bool
    errors: tuple[str, ...] = ()


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'’-]+\b", text, re.UNICODE))


def validate_email(
    subject: str,
    body: str,
    recipient: str,
    profile: dict,
    resume: str,
    word_limit: int = 120,
    require_recipient: bool = True,
) -> EmailValidation:
    errors: list[str] = []
    _, address = parseaddr(recipient.strip())
    if require_recipient and (not address or not _EMAIL_RE.fullmatch(address)):
        errors.append("Recipient email is missing or invalid")
    if not subject.strip():
        errors.append("Subject is required")
    if re.search(r"your\s+name|candidate\s+name|\[name\]", subject, re.I):
        errors.append("Subject contains a candidate-name placeholder")
    if not body.strip():
        errors.append("Body is required")
    main_body = re.split(r"\n\s*Best regards,", body, maxsplit=1, flags=re.IGNORECASE)[0]
    if word_count(main_body) > word_limit:
        errors.append(f"Body exceeds the {word_limit}-word limit")
    if not re.search(r"^Dear\b", body.strip(), re.IGNORECASE):
        errors.append("Email must start with a greeting")
    if not re.search(r"\bBest regards,", body, re.IGNORECASE):
        errors.append("Email must contain the required closing")
    if recipient and recipient.lower() in body.lower():
        errors.append("Recipient email must not appear in the body")
    if _APPLICATION_INSTRUCTION_RE.search(body):
        errors.append("Application instructions must not be copied into the email")
    if "[email address]" in body.lower() or "[phone number]" in body.lower():
        errors.append("Placeholder contact information is not allowed")

    links = profile.get("links") if isinstance(profile.get("links"), dict) else {}
    for value in (profile.get("email"), profile.get("phone"), links.get("linkedin"), links.get("github")):
        if isinstance(value, str) and value and value.lower() in body.lower():
            # Contact values belong in the verified signature, not the body.
            body_before_signature = body.lower().split("best regards,", 1)[0]
            if value.lower() in body_before_signature:
                errors.append("Contact information must not appear in the main body")
                break

    return EmailValidation(not errors, tuple(errors))
