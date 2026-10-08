import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from lakshya.models import Job, Profile

SKILLS = (
    "Python",
    "SQL",
    "Java",
    "JavaScript",
    "TypeScript",
    "C++",
    "C#",
    "R",
    "Go",
    "PyTorch",
    "TensorFlow",
    "Keras",
    "scikit-learn",
    "pandas",
    "NumPy",
    "SciPy",
    "Matplotlib",
    "Seaborn",
    "Power BI",
    "Tableau",
    "Excel",
    "Statistics",
    "Machine Learning",
    "Deep Learning",
    "NLP",
    "Computer Vision",
    "LLM",
    "RAG",
    "LangChain",
    "Hugging Face",
    "Transformers",
    "OpenCV",
    "FastAPI",
    "Flask",
    "Django",
    "Docker",
    "Kubernetes",
    "Git",
    "Linux",
    "AWS",
    "Azure",
    "GCP",
    "Spark",
    "Airflow",
    "MongoDB",
    "PostgreSQL",
    "MySQL",
    "Redis",
    "REST",
    "MLflow",
    "Data Analysis",
    "Data Visualization",
    "ETL",
    "Streamlit",
    "FAISS",
    "React",
)
ALIASES = {
    "sklearn": "scikit-learn",
    "pytorch": "PyTorch",
    "tf": "TensorFlow",
    "postgres": "PostgreSQL",
    "powerbi": "Power BI",
    "natural language processing": "NLP",
    "large language models": "LLM",
    "retrieval augmented generation": "RAG",
}


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w+#]+", " ", text.casefold())).strip()


def mentions(text: str, term: str) -> bool:
    return bool(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, re.I))


def extract_skills(text: str) -> list[str]:
    result = [s for s in SKILLS if mentions(text, s)]
    for alias, skill in ALIASES.items():
        if mentions(text, alias) and skill not in result:
            result.append(skill)
    return result


def plain(text: str) -> str:
    return BeautifulSoup(text or "", "html.parser").get_text(" ", strip=True)


def parse_date(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (float, int)) or str(value).isdigit():
            stamp = float(value)
            return datetime.fromtimestamp(stamp / 1000 if stamp > 10**11 else stamp, UTC)
        if isinstance(value, datetime):
            date = value
        else:
            try:
                date = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                date = parsedate_to_datetime(str(value))
        return date.replace(tzinfo=UTC) if date.tzinfo is None else date.astimezone(UTC)
    except (ValueError, TypeError, OverflowError):
        return None


def is_fresh(job: Job, hours: float = 24, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    return job.posted_at is not None and now - timedelta(hours=hours) <= job.posted_at <= now


def fingerprint(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def safe_slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", text).strip("_")[:70] or "unknown"


def load_profile(path: Path) -> Profile:
    if not path.exists():
        raise FileNotFoundError("Import your resume first: lakshya profile /path/to/resume.pdf")
    return Profile.model_validate_json(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)
