"""Single-command local launcher for the hosted-provider application."""

import threading
import webbrowser

import uvicorn


APP_URL = "http://127.0.0.1:8000"


def open_browser() -> None:
    webbrowser.open(APP_URL)


if __name__ == "__main__":
    threading.Timer(1.5, open_browser).start()
    uvicorn.run("backend.app.main:app", host="127.0.0.1", port=8000, reload=False)
