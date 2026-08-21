"""
Central configuration for the Job Application Agent.

Only the PHASE 1 fields (OCR / paths / logging) are actually used right now.
The rest (models, Gmail, DB) are declared up front so later phases can be
added without reshaping this file, and so .env.example stays in sync with
what the app will eventually read.
"""

from pathlib import Path
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=("settings_",),
    )

    # ---- Paths -------------------------------------------------------
    base_dir: Path = Path(__file__).resolve().parent.parent.parent
    screenshot_directory: Path = Path("data/screenshots")
    resume_directory: Path = Path("data/resumes")
    profile_path: Path = Path("data/profile/profile.json")

    # ---- Hosted OCR -----------------------------------------------------
    model_ocr: str = "PP-OCRv5"
    ocr_confidence_threshold: float = 0.80
    paddleocr_api_url: str = Field(default="", validation_alias=AliasChoices("PADDLEOCR_API_URL"))
    paddleocr_access_token: str | None = Field(default=None, validation_alias=AliasChoices("PADDLEOCR_ACCESS_TOKEN"))
    paddleocr_timeout_seconds: float = 120.0

    # ---- Groq LLM -------------------------------------------------------
    groq_api_key: str | None = Field(default=None, validation_alias=AliasChoices("GROQ_API_KEY"))
    groq_model: str = Field(default="llama-3.1-8b-instant", validation_alias=AliasChoices("GROQ_MODEL"))
    groq_timeout_seconds: float = 120.0
    groq_max_tokens: int = 500
    groq_temperature: float = 0.2
    email_word_limit: int = 120
    email_max_regeneration_attempts: int = 3
    cors_allowed_origins: str = ""

    # ---- Email sending (PHASE 6+) --------------------------------------
    email_send_mode: str = "gmail"  # "mock" | "gmail"
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/auth/gmail/callback"

    # ---- Upstash Redis server-side Gmail persistence -------------------
    upstash_redis_rest_url: str = ""
    upstash_redis_rest_token: str = ""

    # ---- Database (PHASE 9+) -------------------------------------------
    database_url: str = "sqlite:///applications.db"

    # ---- Uploads ---------------------------------------------------------
    max_upload_size_mb: int = 3
    allowed_upload_types: tuple[str, ...] = (
        "application/pdf", "image/png", "image/jpeg", "image/jpg", "image/webp"
    )

    # ---- Logging -----------------------------------------------------
    log_dir: Path = Path("logs")


settings = Settings()

# Resolve configured relative paths once so the app behaves the same no
# matter which directory was used to launch Uvicorn.
settings.base_dir = settings.base_dir.resolve()
for path_name in ("screenshot_directory", "resume_directory", "profile_path", "log_dir"):
    configured_path = getattr(settings, path_name)
    if not configured_path.is_absolute():
        setattr(settings, path_name, settings.base_dir / configured_path)
