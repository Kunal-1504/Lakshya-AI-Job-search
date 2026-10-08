"""Versioned immutable resume evidence, with hash-based parse caching."""

import hashlib
import json
from pathlib import Path

from lakshya.config import Settings
from lakshya.models import Profile
from lakshya.resume_parser import parse_resume
from lakshya.schemas import Contact, EvidenceFact, MasterProfile
from lakshya.utils import write_json

DEMO_RESUME = """Aarav Demo
candidate@example.invalid
Summary
Graduate with academic projects in Python, machine learning and data analysis.
Technical Skills
Python, SQL, Pandas, NumPy, scikit-learn, Git, Excel, Machine Learning
Projects
Customer Churn Classifier | Academic project
Built a classification pipeline using Python, Pandas and scikit-learn.
Explored features and evaluated classification predictions using a train/test split.
Sales Analysis Dashboard | Academic project
Cleaned datasets using SQL and Pandas and prepared Excel visualizations.
Education
Bachelor of Technology in Computer Science | Demo University | 2025
"""


def import_profile(path: Path, settings: Settings, demo: bool = False) -> MasterProfile:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    target = settings.data_dir / ("demo_master_profile.json" if demo else "master_profile.json")
    if target.exists():
        cached = MasterProfile.model_validate_json(target.read_text())
        if cached.source_sha256 == digest:
            return cached
    parsed = parse_resume(path)
    master = MasterProfile(
        contact=Contact.model_validate(parsed.contact.model_dump()),
        skills=parsed.skills,
        projects=parsed.projects,
        education=parsed.education,
        experience=parsed.experience,
        keywords=parsed.keywords,
        strengths=parsed.strengths,
        raw_text=parsed.raw_text,
        facts=[
            EvidenceFact(
                id=f.id, section=f.section, text=f.text, source_excerpt=f.text, context_id=f.section
            )
            for f in parsed.facts
        ],
        source_sha256=digest,
        search_queries=parsed.search_queries,
        role_variants=settings.target_roles,
        location_variants=settings.locations,
    )
    write_json(target, master.model_dump(mode="json"))
    # Immutable versions permit later audits after a new resume is imported.
    write_json(settings.data_dir / "profiles" / f"{digest}.json", master.model_dump(mode="json"))
    return master


def load_profile(settings: Settings, demo: bool = False) -> tuple[MasterProfile, Profile]:
    path = settings.data_dir / ("demo_master_profile.json" if demo else "master_profile.json")
    if demo and not path.exists():
        resume = settings.data_dir / "demo_resume.txt"
        resume.parent.mkdir(parents=True, exist_ok=True)
        resume.write_text(DEMO_RESUME)
        import_profile(resume, settings, True)
    if not path.exists():
        raise ValueError("Import your resume in Settings or run lakshya import-resume PATH first")
    master = MasterProfile.model_validate_json(path.read_text())
    data = master.model_dump()
    for key in ("source_sha256", "role_variants", "location_variants"):
        data.pop(key)
    data["facts"] = [{"id": f.id, "section": f.section, "text": f.text} for f in master.facts]
    data["source_file"] = str(path)
    return master, Profile.model_validate(data)


def profile_status(settings: Settings) -> dict[str, object]:
    path = settings.data_dir / "master_profile.json"
    if not path.exists():
        return {"imported": False}
    data = json.loads(path.read_text())
    return {
        "imported": True,
        "name": data["contact"]["name"],
        "skills": data["skills"],
        "source_sha256": data["source_sha256"],
        "facts": len(data["facts"]),
    }
