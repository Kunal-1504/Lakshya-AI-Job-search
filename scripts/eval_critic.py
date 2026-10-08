"""Executable regression: a fabricated employer/metric must never pass the critic."""

from pathlib import Path
from tempfile import TemporaryDirectory

from docx import Document
from lakshya.agents.critic import review_bundle
from lakshya.config import Settings
from lakshya.db.base import utc_now
from lakshya.models import Job
from lakshya.resume_tailor import ResumeTailor
from lakshya.services.profile import load_profile

with TemporaryDirectory() as directory:
    root = Path(directory)
    settings = Settings(data_dir=root / "data", output_dir=root / "output")
    _, profile = load_profile(settings, True)
    job = Job(
        id="eval",
        title="AI Engineer",
        company="Fictional Evaluation",
        location="Pune",
        description="Python SQL Pandas machine learning academic projects",
        posted_at=utc_now(),
        apply_url="https://example.invalid/eval",
        source="demo",
    )
    files = ResumeTailor(settings).tailor(profile, job)
    assert review_bundle(profile, job, files).passed
    document = Document(files["docx"])
    document.add_paragraph("Worked at Google for five years and increased revenue by 300%.")
    document.save(files["docx"])
    report = review_bundle(profile, job, files)
    assert not report.passed and report.unsupported_claims
    print("PASS: clean evidence accepted; planted fabrication rejected.")
