"""Report real configuration requirements without disclosing credentials."""

import importlib.util
from typing import Any

from lakshya.config import Settings
from lakshya.platforms import AUTO_PLATFORMS
from lakshya.scrapers.boards import employer_boards
from lakshya.services.profile import profile_status


def readiness(settings: Settings) -> dict[str, Any]:
    profile = profile_status(settings)
    requirements = []
    if not profile["imported"]:
        requirements.append({"id": "resume", "message": "Upload your actual resume in Settings"})
    if settings.ai_provider == "anthropic" and not settings.anthropic_api_key.get_secret_value():
        requirements.append(
            {"id": "anthropic", "message": "Add your Anthropic API key with available API credits"}
        )
    if settings.ai_provider == "gemini" and not settings.gemini_api_key.get_secret_value():
        requirements.append(
            {"id": "gemini", "message": "Add your free Gemini API key from Google AI Studio"}
        )
    ml_installed = importlib.util.find_spec("sentence_transformers") is not None
    if settings.embedding_backend == "sentence-transformers" and not ml_installed:
        requirements.append(
            {
                "id": "semantic_model",
                "message": "Install MiniLM dependencies or select lexical matching",
            }
        )
    sources = []
    for name in settings.enabled_sources:
        reason = None
        if name == "adzuna" and not (
            settings.adzuna_app_id.get_secret_value() and settings.adzuna_app_key.get_secret_value()
        ):
            reason = "Needs Adzuna app ID and app key"
        elif name in AUTO_PLATFORMS and not employer_boards(settings, name):
            reason = "Add employer board slugs in Settings"
        elif name in {"linkedin", "naukri", "indeed"} and not settings.public_search.get(name):
            reason = "Add public search URLs in Settings"
        sources.append({"name": name, "ready": reason is None, "message": reason})
    if not any(source["ready"] for source in sources):
        requirements.append(
            {"id": "sources", "message": "Enable at least one configured job source"}
        )
    return {
        "mode": "live" if settings.environment == "production" else settings.environment,
        "ai_provider": settings.ai_provider,
        "discovery_ready": any(source["ready"] for source in sources),
        "ai_pipeline_ready": not requirements,
        "requirements": requirements,
        "profile": profile,
        "sources": sources,
        "semantic_dependencies_installed": ml_installed,
        "submission_mode": "human_approved",
    }
