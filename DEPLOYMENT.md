# Vercel Deployment

The production target is one Vercel project containing the static frontend and
the FastAPI orchestration function at `api/index.py`. Frontend requests remain
same-origin. Vercel does not run PaddleOCR, PaddlePaddle, Ollama, or model
weights.

## Providers

- OCR: the official PaddleOCR AI Studio PP-OCRv5 API. Create an API task at
  `https://aistudio.baidu.com/paddleocr/task`, then copy its API URL and token.
  The server sends JSON to `POST /ocr` with base64 `file`, `fileType`, and the
  PP-OCRv5 orientation options disabled.
- LLM: Groq chat completions using `GROQ_MODEL`.
- Email: Gmail OAuth and Gmail API with the `gmail.send` scope.
- Resume storage: none. Resume bytes are retained by the browser for the
  current application, OCR text is submitted with draft/refine, and the
  original file is submitted with the reviewed send request.
- Gmail OAuth persistence: Upstash Redis stores one short-lived OAuth state
  key and one server-side Gmail credential key. No resume bytes are stored
  there.

## Vercel variables

```text
GROQ_API_KEY=<Groq API key>
GROQ_MODEL=<Groq model>
PADDLEOCR_API_URL=<API URL from the AI Studio PP-OCRv5 task>
PADDLEOCR_ACCESS_TOKEN=<AI Studio token>
GOOGLE_CLIENT_ID=<Google OAuth client ID>
GOOGLE_CLIENT_SECRET=<Google OAuth client secret>
GOOGLE_REDIRECT_URI=https://<your-vercel-domain>/auth/gmail/callback
UPSTASH_REDIS_REST_URL=<Upstash Redis REST URL>
UPSTASH_REDIS_REST_TOKEN=<Upstash Redis REST token>
```

Register the exact `GOOGLE_REDIRECT_URI` in the Google OAuth client. Keep all
provider keys and OAuth credentials server-side. Do not commit `.env`.

## Limits

Uploads are limited to 3 MB by default because Vercel function request limits
and base64 expansion apply before the OCR provider receives the document.
Increase the limit only after checking the deployed Vercel plan and provider
quota. No deployment is performed by this repository change.