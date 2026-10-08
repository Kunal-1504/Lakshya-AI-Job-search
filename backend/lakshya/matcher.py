"""Semantic, skill and title scoring with hard eligibility gates."""

import math
import re
from collections import Counter
from collections.abc import Callable
from typing import Any

from rapidfuzz.fuzz import token_sort_ratio

from lakshya.config import Settings
from lakshya.llm import LLM
from lakshya.models import JDAnalysis, Job, MatchResult, Profile
from lakshya.utils import extract_skills, is_fresh, mentions, normalize


def required_years(text: str) -> float | None:
    words = {
        "zero": "0",
        "one": "1",
        "two": "2",
        "three": "3",
        "four": "4",
        "five": "5",
        "six": "6",
        "seven": "7",
        "eight": "8",
        "nine": "9",
        "ten": "10",
    }
    text = text.lower()
    for word, number in words.items():
        text = re.sub(r"\b" + word + r"\b", number, text)
    values = []
    pattern = r"(?P<more>more than\s+|over\s+)?(?P<low>\d+(?:\.\d+)?)\s*(?:\+|[-–—]\s*\d+|to\s+\d+)?\s*(?:years?|yrs?)\s*(?:of\s+)?(?:(?:relevant|professional|industry|work|commercial|hands-on|practical|full-time|engineering|software|development|data|analytics|research|production|technical)\s+){0,3}experience"
    for match in re.finditer(pattern, text):
        value = float(match["low"]) + (0.01 if match["more"] else 0)
        # Explicitly preferred experience is not treated as a hard requirement.
        tail = text[match.end() : match.end() + 25]
        if not re.match(r"\s*(?:is\s+)?(?:preferred|a plus|a bonus|optional)", tail):
            values.append(value)
    # Also catch "experience: minimum 3 years".
    for match in re.finditer(
        r"experience\s*[:–-]\s*(?:minimum\s+|at least\s+)?(\d+)\s*\+?\s*(?:years?|yrs?)", text
    ):
        values.append(float(match[1]))
    return max(values) if values else None


def location_allowed(job: Job, settings: Settings) -> bool:
    location = normalize(job.location)
    description = normalize(job.description)
    if re.search(r"(?:except|excluding|not available in)\s+india", description + " " + location):
        return False
    remote = job.remote_type == "remote" or "remote" in location
    if remote:
        if job.location_restrictions:
            allowed = {normalize(x) for x in job.location_restrictions}
            india = any(x in {"india", "in", "ind"} for x in allowed)
            global_eligible = any(x in {"worldwide", "global", "anywhere"} for x in allowed)
            if not india and not global_eligible:
                return False
        # An explicit non-India country-only requirement overrides a worldwide tag.
        restricted = re.search(
            r"(?:must be (?:based|located|resident) in|only (?:in|within)|residents? of|authorized to work in) "
            r"(?:the )?(united states|usa|us|canada|uk|united kingdom|europe|eu|australia)",
            description,
        )
        if restricted:
            return False
        if settings.allow_remote_india and (
            mentions(location, "India")
            or location in {"in", "ind"}
            or any(mentions(location, city) for city in settings.locations)
        ):
            return True
        if settings.allow_global_remote and any(
            mentions(location, x) for x in ("worldwide", "global", "anywhere", "everywhere")
        ):
            return True
        if job.location_restrictions:
            return settings.allow_remote_india and any(
                normalize(x) in {"india", "in", "ind"} for x in job.location_restrictions
            )
        return False
    return any(mentions(location, city) for city in settings.locations)


def title_score(title: str, roles: list[str]) -> float:
    def canonical(value: str) -> str:
        value = normalize(value)
        value = value.replace("artificial intelligence", "ai").replace("machine learning", "ml")
        return re.sub(
            r"\b(?:junior|jr|associate|graduate|entry level|fresher|intern)\b", "", value
        ).strip()

    value = canonical(title)
    return max((token_sort_ratio(value, canonical(role)) for role in roles), default=0)


def role_allowed(job: Job, settings: Settings) -> bool:
    """Require role meaning: similar spelling cannot make Data Engineer a Data Analyst."""

    def words(text: str) -> set[str]:
        text = (
            normalize(text)
            .replace("artificial intelligence", "ai")
            .replace("machine learning", "ml")
        )
        return set(re.findall(r"[a-z0-9]+", text))

    title, description = words(job.title), words(job.description)
    qualifiers = {
        "junior",
        "jr",
        "associate",
        "graduate",
        "entry",
        "level",
        "and",
        "or",
        "in",
        "of",
    }
    for role in settings.target_roles:
        requested = words(role) - qualifiers
        domain = {"ai", "ml"} & requested
        if domain:
            occupation = requested - domain
            domain_matches = bool(domain & title) or (
                {"software", "engineer"} <= occupation and bool(domain & description)
            )
            if occupation <= title and domain_matches:
                return True
        elif requested and requested <= title:
            return True
    return False


def lexical_similarity(a: str, b: str) -> float:
    left, right = Counter(normalize(a).split()), Counter(normalize(b).split())
    numerator = sum(value * right.get(key, 0) for key, value in left.items())
    denominator = math.sqrt(sum(x * x for x in left.values()) * sum(x * x for x in right.values()))
    return numerator / denominator if denominator else 0


class Matcher:
    def __init__(
        self,
        settings: Settings,
        llm: LLM | None = None,
        similarity: Callable[[str, str], float] | None = None,
    ) -> None:
        self.settings, self.llm = settings, llm
        self.similarity = similarity
        self.model: Any = None

    def semantic(self, profile: Profile, job: Job) -> float:
        if self.similarity:
            return self.similarity(profile.raw_text, job.description)
        if self.settings.embedding_backend == "lexical":
            return lexical_similarity(profile.raw_text, job.title + " " + job.description)
        if self.model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError(
                    "Install semantic matching: pip install -e '.[ml]'; or use --offline"
                ) from exc
            self.model = SentenceTransformer(self.settings.embedding_model)

        # Chunk to avoid silently truncating long resumes/JDs at the model's input window.
        def vector(text: str) -> Any:
            words = text.split()
            chunks = [" ".join(words[i : i + 160]) for i in range(0, len(words), 160)] or [""]
            import numpy as np

            encoded = self.model.encode(chunks, normalize_embeddings=True)
            mean = encoded.mean(axis=0)
            return mean / max(float(np.linalg.norm(mean)), 1e-9)

        return float(vector(profile.raw_text) @ vector(job.title + " " + job.description))

    def analyze(self, profile: Profile, job: Job) -> JDAnalysis:
        skills = extract_skills(job.description)
        known = {normalize(skill) for skill in profile.skills}
        years = required_years(job.description)
        senior = bool(
            re.search(
                r"\b(senior|sr\.?|lead|staff|principal|manager|director|head)\b", job.title, re.I
            )
        )
        if self.llm:
            analysis = self.llm.structured(
                "Extract explicitly required skills and minimum REQUIRED years of experience. "
                "Do not treat preferred experience as mandatory. If unknown use null. "
                "Evaluate location eligibility for a candidate based in India. Use null if unclear. "
                "Report seniority and missing_skills using only the supplied candidate skills.",
                {"candidate_skills": profile.skills, "job": job.model_dump(mode="json")},
                JDAnalysis,
            )
            # Recompute missing skills locally: an LLM cannot claim the candidate owns a skill.
            analysis.missing_skills = [
                s for s in analysis.required_skills if normalize(s) not in known
            ]
            if years is not None:
                analysis.min_years = max(analysis.min_years or 0, years)
            if senior:
                analysis.seniority = "senior"
            return analysis
        return JDAnalysis(
            required_skills=skills,
            missing_skills=[s for s in skills if normalize(s) not in known],
            seniority="senior" if senior else "entry/unspecified",
            min_years=years,
        )

    def match(self, profile: Profile, job: Job, analysis: JDAnalysis | None = None) -> MatchResult:
        analysis = analysis or self.analyze(profile, job)
        known = {normalize(s) for s in profile.skills}
        skill_score = (
            100
            * sum(normalize(s) in known for s in analysis.required_skills)
            / max(1, len(analysis.required_skills))
        )
        role = title_score(job.title, self.settings.target_roles)
        semantic = max(0, min(1, self.semantic(profile, job))) * 100
        judgment = analysis.fit_judgment if self.llm else (semantic + skill_score + role) / 3
        score = round(0.4 * semantic + 0.3 * skill_score + 0.2 * role + 0.1 * judgment, 2)
        reasons = []
        if not is_fresh(job, self.settings.freshness_hours):
            reasons.append("Posting date is unknown, in the future, or older than 24 hours")
        if not location_allowed(job, self.settings) or analysis.location_eligible is False:
            reasons.append("Location is ineligible or insufficiently specified")
        if (
            analysis.min_years is not None
            and analysis.min_years > self.settings.max_experience_years
        ):
            reasons.append(f"Requires {analysis.min_years:g}+ years of experience")
        if re.search(r"senior|lead|staff|principal|manager|director", analysis.seniority, re.I):
            reasons.append("Seniority exceeds fresher/0–1 year target")
        if role < 45 or not role_allowed(job, self.settings):
            reasons.append("Title does not resemble a target role")
        if not job.description.strip():
            reasons.append("Missing job description")
        if score < self.settings.match_threshold:
            reasons.append(f"Score below {self.settings.match_threshold:g}")
        return MatchResult(
            score=score,
            semantic_score=round(semantic, 2),
            skill_score=round(skill_score, 2),
            role_score=round(role, 2),
            analysis=analysis,
            shortlisted=not reasons,
            reasons=reasons,
            backend=self.settings.embedding_backend,
        )
