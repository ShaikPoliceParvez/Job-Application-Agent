"""Single-command local launcher for the chat application.

Run ``.venv\Scripts\python.exe run.py``. Ollama is reused when already
running and started automatically otherwise; the browser opens at the UI.
"""

import subprocess
import threading
import time
import urllib.error
import urllib.request
import webbrowser

import uvicorn


OLLAMA_URL = "http://127.0.0.1:11434/"
APP_URL = "http://127.0.0.1:8000"


def ollama_is_running() -> bool:
    try:
        with urllib.request.urlopen(OLLAMA_URL, timeout=1) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError):
        return False


def ensure_ollama() -> None:
    if ollama_is_running():
        print("Ollama is already running.")
        return
    print("Starting Ollama...")
    subprocess.Popen(
        ["ollama", "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    for _ in range(20):
        if ollama_is_running():
            print("Ollama started.")
            return
        time.sleep(0.5)
    raise RuntimeError("Ollama did not become available on http://127.0.0.1:11434")


def open_browser() -> None:
    webbrowser.open(APP_URL)


if __name__ == "__main__":
    ensure_ollama()
    threading.Timer(1.5, open_browser).start()
    uvicorn.run("backend.app.main:app", host="127.0.0.1", port=8000, reload=False)
