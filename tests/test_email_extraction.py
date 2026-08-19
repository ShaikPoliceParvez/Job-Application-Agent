from app.models.paddle_ocr import extract_email_candidates


def test_extracts_single_email():
    text = "Please send your resume to hr@abctechnologies.com for review."
    assert extract_email_candidates(text) == ["hr@abctechnologies.com"]


def test_extracts_multiple_emails_preserving_order():
    text = """
    Contact us:
    hr@company.com
    or
    careers@company.com
    or
    support@company.com
    """
    result = extract_email_candidates(text)
    assert result == ["hr@company.com", "careers@company.com", "support@company.com"]


def test_deduplicates_case_insensitively():
    text = "Email HR@Company.com or hr@company.com"
    result = extract_email_candidates(text)
    assert result == ["HR@Company.com"]


def test_returns_empty_list_when_no_email_present():
    text = "We are hiring an AI Engineer Intern. Apply on our careers page."
    assert extract_email_candidates(text) == []


def test_strips_trailing_punctuation_from_ocr_artifacts():
    # OCR line breaks / punctuation sometimes glue onto the end of an email.
    text = "Send to hr@company.com, thanks."
    assert extract_email_candidates(text) == ["hr@company.com"]


def test_does_not_match_malformed_strings():
    text = "version @2.0 or user@localhost or just plain text"
    result = extract_email_candidates(text)
    # "user@localhost" has no TLD-like suffix, our regex requires 2+ letters after a dot
    assert "user@localhost" not in result
