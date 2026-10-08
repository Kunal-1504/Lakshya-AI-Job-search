"""Validated YAML configuration; all credentials originate from the environment."""

import os
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from sqlalchemy.engine import make_url


class ModelPrice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_usd: float = Field(ge=0)
    output_usd: float = Field(ge=0)


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    app_name: str = "Lakshya"
    config_file: Path | None = Field(default=None, exclude=True)
    cookie_secure: bool = False
    browser_headless: bool = False
    environment: Literal["development", "test", "production"] = "development"
    data_dir: Path = Path("data")
    output_dir: Path = Path("output")
    database_url: str = "sqlite:///data/lakshya.sqlite3"
    log_file: Path = Path("data/lakshya.jsonl")
    timezone: str = "Asia/Kolkata"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    target_roles: list[str] = Field(
        default_factory=lambda: [
            "AI Engineer",
            "ML Engineer",
            "Software Engineer (AI/ML)",
            "Data Analyst",
        ]
    )
    locations: list[str] = Field(
        default_factory=lambda: [
            "Pune",
            "Bangalore",
            "Bengaluru",
            "Hyderabad",
            "Mumbai",
        ]
    )
    allow_remote_india: bool = True
    allow_global_remote: bool = True
    freshness_hours: float = Field(default=24, gt=0, le=24)
    max_experience_years: float = Field(default=2, ge=0, le=2)
    match_threshold: float = Field(default=65, ge=0, le=100)
    embedding_backend: Literal["sentence-transformers", "lexical"] = "sentence-transformers"
    http_timeout: float = Field(default=30, gt=0, le=120)
    max_pages: int = Field(default=3, ge=1, le=10)
    max_jobs_per_source: int = Field(default=200, ge=1, le=1000)
    browser_profile: Path = Path("data/browser-profile")
    answers: dict[str, str] = Field(default_factory=dict)
    form_selectors: dict[str, dict[str, str]] = Field(default_factory=dict)
    permitted_feed_urls: list[str] = Field(default_factory=list)
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    daily_application_cap: int = Field(default=10, ge=1, le=100)
    max_applications_per_run: int = Field(default=10, ge=1, le=100)
    max_run_tokens: int = Field(default=100000, ge=1)
    max_day_tokens: int = Field(default=500000, ge=1)
    max_run_cost_usd: float = Field(default=5, gt=0)
    max_day_cost_usd: float = Field(default=10, gt=0)
    max_agent_iterations: int = Field(default=3, ge=1, le=3)
    request_delay_min_seconds: float = Field(default=3, ge=3)
    request_delay_max_seconds: float = Field(default=6, ge=3)
    follow_up_days: int = Field(default=7, ge=1)
    application_mode: Literal["assist", "auto"] = "assist"
    ai_provider: Literal["local", "gemini", "anthropic"] = "local"
    llm_free_tier: bool = True
    llm_request_interval_seconds: float = Field(default=20, ge=0, le=120)
    max_run_llm_calls: int = Field(default=16, ge=1, le=1000)
    max_day_llm_calls: int = Field(default=20, ge=1, le=10000)
    live_search_enabled: bool = False
    live_search_interval_minutes: int = Field(default=60, ge=30, le=1440)
    enabled_sources: list[str] = Field(default_factory=list)
    boards: dict[str, list[str]] = Field(default_factory=dict)
    public_search: dict[str, list[str]] = Field(default_factory=dict)
    agent_models: dict[str, str] = Field(default_factory=dict)
    model_prices_per_million: dict[str, ModelPrice] = Field(default_factory=dict)
    api_key: SecretStr = Field(default_factory=lambda: SecretStr(""), exclude=True)
    anthropic_api_key: SecretStr = Field(default_factory=lambda: SecretStr(""), exclude=True)
    gemini_api_key: SecretStr = Field(default_factory=lambda: SecretStr(""), exclude=True)
    adzuna_app_id: SecretStr = Field(default_factory=lambda: SecretStr(""), exclude=True)
    adzuna_app_key: SecretStr = Field(default_factory=lambda: SecretStr(""), exclude=True)

    @model_validator(mode="after")
    def constraints(self) -> "Settings":
        ZoneInfo(self.timezone)
        if self.request_delay_max_seconds < self.request_delay_min_seconds:
            raise ValueError("Maximum request delay must be >= minimum delay")
        if self.max_run_tokens > self.max_day_tokens:
            raise ValueError("Run token cap cannot exceed daily token cap")
        if self.max_run_cost_usd > self.max_day_cost_usd:
            raise ValueError("Run cost cap cannot exceed daily cost cap")
        if self.max_applications_per_run > self.daily_application_cap:
            raise ValueError("Run application cap cannot exceed daily application cap")
        url = make_url(self.database_url)
        if url.get_backend_name() not in {"sqlite", "postgresql"}:
            raise ValueError("Use a SQLite or PostgreSQL database URL")
        if self.environment == "production":
            if "*" in self.cors_origins:
                raise ValueError("Production requires explicit CORS origins")
            key = self.api_key.get_secret_value()
            if len(key) < 32 or key == "local-demo-key-change-me":
                raise ValueError("Production requires a non-demo API key of at least 32 characters")
        return self

    @property
    def request_delay_min(self) -> float:
        return self.request_delay_min_seconds

    @property
    def request_delay_max(self) -> float:
        return self.request_delay_max_seconds

    def public_summary(self) -> dict[str, Any]:
        """Only explicitly safe settings are exposed; database credentials are never returned."""
        return {
            "app_name": self.app_name,
            "cloud": os.getenv("LAKSHYA_CLOUD") == "1",
            "max_resumes_per_search": 2 if os.getenv("LAKSHYA_CLOUD") == "1" else None,
            "environment": self.environment,
            "timezone": self.timezone,
            "target_roles": self.target_roles,
            "locations": self.locations,
            "match_threshold": self.match_threshold,
            "freshness_hours": self.freshness_hours,
            "application_mode": self.application_mode,
            "ai_provider": self.ai_provider,
            "llm_free_tier": self.llm_free_tier,
            "daily_application_cap": self.daily_application_cap,
            "enabled_sources": self.enabled_sources,
            "live_search_enabled": self.live_search_enabled,
            "live_search_interval_minutes": self.live_search_interval_minutes,
            "agent_models": self.agent_models,
            "credential_status": {
                "api_key": bool(self.api_key.get_secret_value()),
                "anthropic": bool(self.anthropic_api_key.get_secret_value()),
                "gemini": bool(self.gemini_api_key.get_secret_value()),
                "adzuna": bool(
                    self.adzuna_app_id.get_secret_value() and self.adzuna_app_key.get_secret_value()
                ),
            },
        }


def load_settings(path: Path | None = None) -> Settings:
    path = (path or Path(os.getenv("LAKSHYA_CONFIG", "config.yaml"))).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Missing configuration: {path}")
    load_dotenv(path.parent / ".env", override=False)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("config.yaml must contain an object")
    secret_keys = {
        "api_key",
        "anthropic_api_key",
        "gemini_api_key",
        "adzuna_app_id",
        "adzuna_app_key",
    }
    if secret_keys.intersection(data):
        raise ValueError("Credentials must be supplied through environment variables, never YAML")
    if os.getenv("LAKSHYA_ENVIRONMENT"):
        data["environment"] = os.environ["LAKSHYA_ENVIRONMENT"]
    if os.getenv("LAKSHYA_AI_PROVIDER"):
        data["ai_provider"] = os.environ["LAKSHYA_AI_PROVIDER"]
    for field, env in (
        ("api_key", "LAKSHYA_API_KEY"),
        ("anthropic_api_key", "ANTHROPIC_API_KEY"),
        ("gemini_api_key", "GEMINI_API_KEY"),
        ("adzuna_app_id", "ADZUNA_APP_ID"),
        ("adzuna_app_key", "ADZUNA_APP_KEY"),
    ):
        data[field] = SecretStr(os.getenv(env, ""))
    override = os.getenv("LAKSHYA_DATABASE_URL")
    if override:
        data["database_url"] = override
    for field in ("data_dir", "output_dir", "log_file", "browser_profile"):
        override_path = os.getenv("LAKSHYA_" + field.upper())
        value = Path(override_path or data.get(field, getattr(Settings.model_construct(), field)))
        data[field] = value if value.is_absolute() else path.parent / value
    url = make_url(data.get("database_url", "sqlite:///data/lakshya.sqlite3"))
    if url.password and not override:
        raise ValueError("Database passwords must be supplied in LAKSHYA_DATABASE_URL, never YAML")
    if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
        location = Path(url.database)
        if not location.is_absolute():
            url = url.set(database=str(path.parent / location))
        data["database_url"] = url.render_as_string(hide_password=False)
    private_path = Path(data["data_dir"]) / "credentials.json"
    if private_path.exists():
        import json

        saved = json.loads(private_path.read_text())
        for field, env in (
            ("anthropic_api_key", "ANTHROPIC_API_KEY"),
            ("gemini_api_key", "GEMINI_API_KEY"),
            ("adzuna_app_id", "ADZUNA_APP_ID"),
            ("adzuna_app_key", "ADZUNA_APP_KEY"),
        ):
            if not data[field].get_secret_value() and saved.get(env):
                data[field] = SecretStr(saved[env])
    data["config_file"] = path
    data["cookie_secure"] = os.getenv("LAKSHYA_COOKIE_SECURE", "false").lower() == "true"
    return Settings.model_validate(data)
