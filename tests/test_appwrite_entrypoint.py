from types import SimpleNamespace

from backend.main import _body, _dispatch, main


class MockResponse:
    def json(self, body, status_code=200):
        return {"body": body, "status_code": status_code}

    def text(self, body, status_code=200, headers=None):
        return {"body": body, "status_code": status_code, "headers": headers or {}}


class MockContext:
    def __init__(self):
        self.req = SimpleNamespace(
            method="GET",
            path="/health",
            queryString={"check": "true"},
            headers={"accept": "application/json"},
            body=b"",
        )
        self.res = MockResponse()
        self.errors = []

    def error(self, message):
        self.errors.append(message)


def test_appwrite_entrypoint_returns_fastapi_response():
    context = MockContext()

    result = main(context)

    assert result["status_code"] == 200
    assert result["body"]["status"] == "ok"
    assert result["body"]["service"] == "job-application-agent"
    assert context.errors == []


def test_appwrite_entrypoint_preserves_binary_request_body():
    request = SimpleNamespace(bodyBinary="%PDF\x89\x00binary")

    assert _body(request) == b"%PDF\x89\x00binary"


def test_appwrite_entrypoint_forwards_multipart_resume(monkeypatch, tmp_path):
    import app.main as deployed_main
    from app.config import settings

    boundary = "----appwrite-test-boundary"
    resume_bytes = b"%PDF\x89\x00binary"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="resume.pdf"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode("ascii") + resume_bytes + f"\r\n--{boundary}--\r\n".encode("ascii")
    monkeypatch.setattr(deployed_main, "appwrite_storage_configured", lambda: False)
    monkeypatch.setattr(settings, "resume_directory", tmp_path)

    response = _dispatch(
        SimpleNamespace(
            method="POST",
            path="/resume",
            queryString="",
            headers={
                "content-type": f"multipart/form-data; boundary={boundary}",
                "host": "function.example",
                "content-length": str(len(body)),
            },
            bodyBinary=body,
        )
    )

    assert response.status_code == 200
    assert response.json()["size_bytes"] == len(resume_bytes)
    assert (tmp_path / "default_resume.pdf").read_bytes() == resume_bytes
