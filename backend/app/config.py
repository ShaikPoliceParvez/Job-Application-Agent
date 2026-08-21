"""
Central configuration for the Job Application Agent.

Only the PHASE 1 fields (OCR / paths / logging) are actually used right now.
The rest (models, Gmail, DB) are declared up front so later phases can be
added without reshaping this file, and so .env.example stays in sync with
what the app will eventually read.
"""

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=("settings_",),
    )

    app_env: Literal["local", "production"] = "local"

    # ---- Paths -------------------------------------------------------
    base_dir: Path = Path(__file__).resolve().parent.parent.parent
    screenshot_directory: Path = Path("data/screenshots")
    resume_directory: Path = Path("data/resumes")
    profile_path: Path = Path("data/profile/profile.json")

    # ---- OCR (PHASE 1) -------------------------------------------------
    # paddleocr==2.9.1 supports PP-OCR through PP-OCRv4.
    model_ocr: str = "PP-OCRv4"
    ocr_confidence_threshold: float = 0.80
    ocr_lang: str = "en"
    ocr_max_side: int = 1024
    ocr_warmup_on_startup: bool = False
    screenshot_retention_count: int = 5
    ocr_api_url: str = ""
    ocr_api_key: str = ""
    ocr_api_timeout_seconds: float = 60.0
    cors_allowed_origins: str = "http://localhost:8000,https://job-application-agent.appwrite.network"
    ocr_mode: Literal["local", "api"] = "local"

    # ---- LLMs (used from PHASE 2 onward through the Ollama adapter) -----
    llm_mode: Literal["cloud", "local"] = Field(default="cloud", validation_alias=AliasChoices("LLM_MODE"))
    ollama_base_url: str = Field(
        default="https://ollama.com",
        validation_alias=AliasChoices("OLLAMA_BASE_URL", "OLLAMA_HOST"),
    )
    ollama_api_key: str | None = Field(default=None, validation_alias=AliasChoices("OLLAMA_API_KEY"))
    ollama_model: str = Field(
        default="gemma2:2b-instruct-q2_K",
        validation_alias=AliasChoices("OLLAMA_MODEL", "MODEL_EMAIL"),
    )
    model_vision: str = "gemma3:4b"
    ollama_timeout_seconds: float = 120.0
    ollama_max_retries: int = 2
    ollama_keep_alive: str | int = -1
    ollama_num_ctx: int = 4096
    ollama_num_predict: int = 170
    ollama_draft_num_predict: int = 300
    ollama_temperature: float = 0.2
    email_word_limit: int = 120
    email_max_regeneration_attempts: int = 3

    # ---- Email sending (PHASE 6+) --------------------------------------
    email_send_mode: str = "gmail"  # "mock" | "gmail"
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/auth/gmail/callback"
    google_token_path: Path = Path("data/gmail_token.json")
    frontend_url: str = "https://job-application-agent.appwrite.network"

    # ---- Appwrite Storage ---------------------------------------------
    appwrite_endpoint: str = "https://cloud.appwrite.io/v1"
    appwrite_project_id: str = ""
    appwrite_api_key: str = ""
    appwrite_bucket_id: str = ""
    appwrite_resume_file_id: str = ""
    appwrite_resume_filename: str = "resume.pdf"

    # ---- Database (PHASE 9+) -------------------------------------------
    database_url: str = "sqlite:///applications.db"

    # ---- Uploads ---------------------------------------------------------
    max_upload_size_mb: int = 10
    allowed_image_types: tuple[str, ...] = ("image/png", "image/jpeg", "image/webp")

    # ---- Logging -----------------------------------------------------
    log_dir: Path = Path("logs")


settings = Settings()

# Resolve configured relative paths once so the app behaves the same no
# matter which directory was used to launch Uvicorn.
settings.base_dir = settings.base_dir.resolve()
for path_name in ("screenshot_directory", "resume_directory", "profile_path", "log_dir", "google_token_path"):
    configured_path = getattr(settings, path_name)
    if not configured_path.is_absolute():
        setattr(settings, path_name, settings.base_dir / configured_path)

# Ensure directories referenced by Phase 1 exist at import time.
settings.screenshot_directory.mkdir(parents=True, exist_ok=True)
settings.resume_directory.mkdir(parents=True, exist_ok=True)
settings.profile_path.parent.mkdir(parents=True, exist_ok=True)
settings.log_dir.mkdir(parents=True, exist_ok=True)
