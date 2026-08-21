# Job Application Agent

A same-origin FastAPI and static JavaScript application for turning a job posting into a reviewed application email. Production runs on Vercel and uses hosted PP-OCRv5 for document extraction, Groq for structured extraction and drafting, and Gmail OAuth for sending.

## Production architecture

```text
Browser -> Vercel static frontend + /api FastAPI function
                    |-> PaddleOCR AI Studio PP-OCRv5 API
                    |-> Groq chat completions API
                    `-> Gmail API (gmail.send)
```

No local OCR engine, PaddlePaddle runtime, Ollama server, Cloud Run service, Docker image, or model weights are required in production. Resume bytes are held in the browser for the current application. OCR text is sent for drafting, and the original file is sent only with the reviewed Gmail request.

## Deploy

1. Install dependencies with `pip install -r requirements.txt`.
2. Create the Vercel project from this repository. `vercel.json` routes all same-origin paths to `api/index.py`.
3. Add the variables documented in [DEPLOYMENT.md](DEPLOYMENT.md), including the exact deployed Gmail callback URL.
4. Configure the Google OAuth client for the `gmail.send` scope and deployed callback URL.
5. Deploy with Vercel. Never commit `.env`, OAuth credentials, provider keys, or Gmail token files.

Copy the starter names from [.env.example](.env.example). The OCR API URL and token come from an official PaddleOCR AI Studio PP-OCRv5 task. The default Groq model is `llama-3.1-8b-instant`; set `GROQ_MODEL` to another supported model when needed.

## Local development

For a local server, install `requirements-local.txt` and run:

```text
python run.py
```

The local requirements retain compatibility-only OCR/Ollama modules and tests; application routes still use the hosted provider adapters. Set the same provider variables as production, with `GOOGLE_REDIRECT_URI=http://127.0.0.1:8000/auth/gmail/callback`.

## Tests

```text
pytest -q
```

Provider calls are mocked in the focused endpoint tests. Live OCR, Groq, and Gmail credentials are not required for the test suite.
