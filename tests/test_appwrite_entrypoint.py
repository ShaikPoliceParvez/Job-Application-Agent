from types import SimpleNamespace

from backend.main import main


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
