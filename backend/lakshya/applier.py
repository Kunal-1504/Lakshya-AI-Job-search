"""Browser-assisted applications. No submission without artifact-bound approval."""

import asyncio
import logging
import re
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

from langchain_core.runnables import RunnableConfig
from playwright.async_api import Locator, Page, Route, async_playwright
from rich.console import Console

from lakshya.config import Settings
from lakshya.models import Job, Profile
from lakshya.platforms import AUTO_PLATFORMS
from lakshya.tracker import JobRecord, Tracker, job_from
from lakshya.utils import is_fresh, normalize

log = logging.getLogger(__name__)
console = Console()
SUBMIT_NAMES = re.compile(
    r"^(?:submit|submit application|send application|send my application|send)$", re.I
)
SUCCESS = re.compile(
    r"(?:application (?:has been |was )?(?:submitted|received)|"
    r"thank you for (?:applying|your application)|thanks for applying)",
    re.I,
)
MANUAL_DOMAINS = ("linkedin.com", "naukri.com")

FIELD_SCAN = r"""elements => elements.map((el, index) => {
  const labels = Array.from(el.labels || []).map(l => l.innerText.trim()).join(' ');
  const label = labels || el.getAttribute('aria-label') || el.placeholder || el.name || el.id || '';
  const group = el.closest('fieldset, [role="radiogroup"], [role="group"]');
  const labelledBy = group && (group.getAttribute('aria-labelledby') || '').split(/\s+/)
    .map(id => document.getElementById(id)?.innerText || '').join(' ');
  const question = group && (group.querySelector('legend')?.innerText || labelledBy || group.getAttribute('aria-label'));
  return {index, tag: el.tagName.toLowerCase(), type: (el.type || '').toLowerCase(),
    name: el.name || '', label, question: question || '', checked: !!el.checked,
    required: el.required || el.getAttribute('aria-required') === 'true',
    value: el.value || '', visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
    disabled: el.disabled, multiple: el.multiple,
    accept: el.accept || '', options: el.options ? Array.from(el.options).map(o => ({label:o.label,value:o.value})) : []};
})"""


def provider(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if re.fullmatch(r"[a-z0-9][a-z0-9-]*\.recruitee\.com", host) and host.split(".")[0] not in {
        "api",
        "app",
        "docs",
        "www",
        "support",
    }:
        return "recruitee"
    for name, domains in {
        "greenhouse": ("boards.greenhouse.io", "job-boards.greenhouse.io"),
        "lever": ("jobs.lever.co", "jobs.eu.lever.co"),
        "ashby": ("jobs.ashbyhq.com",),
        "workable": ("apply.workable.com", "jobs.workable.com"),
        "linkedin": ("linkedin.com",),
        "naukri": ("naukri.com",),
    }.items():
        if any(host == domain or host.endswith("." + domain) for domain in domains):
            return name
    return "generic"


def auto_consent_field(label: str) -> bool:
    return bool(re.search(r"\b(agree|consent|terms|privacy|certify|acknowledge)\b", label))


def known_answers(profile: Profile, settings: Settings, cover_note: str) -> dict[str, str]:
    contact = profile.contact
    parts = contact.name.split()
    # Single-token names aren't split or fabricated; leave missing surname to the user.
    fields = {
        "name": contact.name,
        "full name": contact.name,
        "your name": contact.name,
        "first name": parts[0] if parts else "",
        "last name": " ".join(parts[1:]),
        "email": contact.email,
        "email address": contact.email,
        "your email": contact.email,
        "phone": contact.phone,
        "phone number": contact.phone,
        "mobile number": contact.phone,
        "linkedin": contact.linkedin,
        "linkedin profile": contact.linkedin,
        "linkedin url": contact.linkedin,
        "github": contact.github,
        "github url": contact.github,
        "website": contact.website,
        "portfolio": contact.website,
        "cover letter": cover_note,
        "cover note": cover_note,
    }
    fields.update({normalize(k): v for k, v in settings.answers.items()})
    return {normalize(key): value for key, value in fields.items() if value}


class Applier:
    def __init__(
        self, settings: Settings, tracker: Tracker, prompt: Callable[[str], str] | None = None
    ) -> None:
        self.settings, self.tracker = settings, tracker
        self.prompt = prompt or input

    async def ask(self, message: str) -> str:
        return (await asyncio.to_thread(self.prompt, message)).strip()

    def preflight(self, record: JobRecord, profile_hash: str, auto: bool, dry_run: bool) -> Job:
        job = job_from(record)
        self.tracker.verify_approval(record, profile_hash)
        if record.is_demo and not dry_run:
            raise ValueError("Demo data can never be submitted. Use --dry-run.")
        if not is_fresh(job, self.settings.freshness_hours):
            raise ValueError("Posting is now outside the 24-hour freshness window")
        if auto and (record.score is None or record.score < 80):
            raise ValueError("--auto requires score >= 80")
        if auto and provider(str(job.apply_url)) not in AUTO_PLATFORMS:
            raise ValueError("--auto is restricted to supported hosted employer forms")
        if auto:
            from lakshya.matcher import location_allowed, required_years, role_allowed

            years = required_years(job.description)
            if (
                not role_allowed(job, self.settings)
                or not location_allowed(job, self.settings)
                or (years is not None and years > self.settings.max_experience_years)
                or re.search(
                    r"\b(senior|sr\.?|lead|staff|principal|manager|director|head)\b",
                    job.title,
                    re.I,
                )
            ):
                raise ValueError(
                    "Job no longer meets your role, location or experience preferences"
                )
        return job

    async def fill_form(
        self,
        page: Page,
        profile: Profile,
        record: JobRecord,
        platform: str,
        pending_uploads: list[tuple[Locator, str]] | None = None,
    ) -> list[str]:
        from sqlalchemy import select
        from sqlalchemy.orm import Session

        from lakshya.db.models import ScreeningAnswer

        with Session(self.tracker.engine) as session:
            stored_answers = {
                a.question: a.answer for a in session.scalars(select(ScreeningAnswer))
            }
        self.settings = self.settings.model_copy(
            update={"answers": self.settings.answers | stored_answers}
        )
        answers = known_answers(
            profile, self.settings, Path(record.files["cover_note"]).read_text(encoding="utf-8")
        )
        unresolved: list[str] = []
        uploaded = False

        async def attach(control: Locator, path: str) -> None:
            if pending_uploads is None:
                await control.set_input_files(path)
            else:
                # Some ATSs upload on file selection. Defer that disclosure until
                # every question is answered and the durable reservation is committed.
                pending_uploads.append((control, path))

        # A configured selector is an explicit candidate answer, never a submit action.
        overrides = self.settings.form_selectors.get(platform, {})
        for frame in page.frames:
            frame_controls = frame.locator("input, textarea, select")
            fields = await frame_controls.evaluate_all(FIELD_SCAN)
            handled_radio_groups: set[str] = set()
            for field in fields:
                control = frame_controls.nth(field["index"])
                label = normalize(field["label"]).strip()
                label = re.sub(r"\s+(?:required|optional)$", "", label)
                question = (
                    re.sub(r"\s+(?:required|optional)$", "", normalize(field["question"])) or label
                )
                if field["disabled"] or field["type"] in {"hidden", "submit", "button", "reset"}:
                    continue
                # file inputs often are intentionally invisible but usable through set_input_files.
                if not field["visible"] and field["type"] != "file":
                    continue
                try:
                    if field["type"] == "file":
                        if (
                            "resume" in label
                            or "cv" in label
                            or field["name"] in {"resume", "resume_file"}
                        ):
                            await attach(control, record.files["pdf"])
                            uploaded = True
                        elif "cover letter" in label or "cover note" in label:
                            # Upload the actual generated note only when plain text is accepted.
                            accepts = field["accept"].lower()
                            if not accepts or ".txt" in accepts or "text/plain" in accepts:
                                await attach(control, record.files["cover_note"])
                            else:
                                unresolved.append(
                                    "Cover letter upload needs a supported document format"
                                )
                        else:
                            unresolved.append(f"File upload: {field['label'] or '(unlabelled)'}")
                        continue
                    if field["type"] == "radio":
                        # Bind the saved answer to the question, never a global Yes/No label.
                        if not field["question"]:
                            unresolved.append(
                                "Radio question label unavailable; inspect the form manually"
                            )
                            continue
                        group_key = field["name"] or question
                        if group_key in handled_radio_groups:
                            continue
                        handled_radio_groups.add(group_key)
                        options = [
                            option
                            for option in fields
                            if option["type"] == "radio"
                            and (
                                option["name"]
                                or normalize(option["question"])
                                or normalize(option["label"])
                            )
                            == group_key
                            and option["visible"]
                            and not option["disabled"]
                        ]
                        if auto_consent_field(question):
                            unresolved.append(question + " (your consent is needed)")
                            continue
                        stored = {normalize(k): v for k, v in self.settings.answers.items()}
                        answer = stored.get(question)
                        selected = [
                            option
                            for option in options
                            if answer
                            and (
                                normalize(option["label"]) == normalize(answer)
                                or normalize(option["value"]) == normalize(answer)
                            )
                        ]
                        if len(selected) != 1:
                            unresolved.append(question + " (save an exact answer to this question)")
                        else:
                            await frame_controls.nth(selected[0]["index"]).check()
                        continue
                    # User- or browser-filled free-text/unknown fields still need human inspection.
                    if label not in answers:
                        unresolved.append(field["label"] or "Unlabelled field")
                        continue
                    answer = answers[label]
                    if field["type"] == "checkbox":
                        if auto_consent_field(question) or auto_consent_field(label):
                            unresolved.append(field["label"] + " (your consent is needed)")
                            continue
                        # Demographic checkboxes require an exact stored candidate answer.
                        if label not in {normalize(k) for k in self.settings.answers}:
                            unresolved.append(field["label"])
                            continue
                        if field["type"] == "checkbox" and normalize(answer) in {
                            "yes",
                            "true",
                            "no",
                            "false",
                        }:
                            await control.set_checked(normalize(answer) in {"yes", "true"})
                        else:
                            unresolved.append(field["label"])
                    elif field["tag"] == "select":
                        if field["multiple"]:
                            unresolved.append(field["label"] + " (multi-select)")
                            continue
                        option = next(
                            (
                                item
                                for item in field["options"]
                                if normalize(item["label"]) == normalize(answer)
                                or item["value"] == answer
                            ),
                            None,
                        )
                        if option:
                            await control.select_option(value=option["value"])
                        else:
                            unresolved.append(
                                field["label"] + " (configured answer isn't an option)"
                            )
                    else:
                        await control.fill(answer)
                except Exception as exc:
                    unresolved.append(f"{field['label']}: {type(exc).__name__}")
            for answer_key, selector in overrides.items():
                value = answers.get(normalize(answer_key))
                if value and await frame.locator(selector).count() == 1:
                    control = frame.locator(selector)
                    try:
                        # Only text controls can be targeted by overrides.
                        tag = await control.evaluate("el => el.tagName.toLowerCase()")
                        kind = await control.get_attribute("type")
                        if tag in {"input", "textarea"} and kind not in {
                            "submit",
                            "button",
                            "file",
                            "checkbox",
                            "radio",
                        }:
                            await control.fill(value)
                        else:
                            unresolved.append(f"Unsafe override control: {answer_key}")
                    except Exception:
                        unresolved.append(f"Override failed: {answer_key}")
        if not uploaded:
            unresolved.append("Resume upload was not found; attach the prepared PDF manually")
        if await page.locator('[role="combobox"], [contenteditable="true"]').count():
            unresolved.append("Custom combobox/editor requires manual review")
        # Form QA independently reads current DOM values after filling.
        for frame in page.frames:
            fields = await frame.locator("input, textarea, select").evaluate_all(FIELD_SCAN)
            for field in fields:
                if field["visible"] and field["required"] and not field["disabled"]:
                    if (
                        field["type"]
                        not in {"hidden", "submit", "button", "file", "checkbox", "radio"}
                        and not field["value"].strip()
                    ):
                        unresolved.append("Required field empty: " + field["label"])
                    if field["type"] == "checkbox" and not field["checked"]:
                        unresolved.append("Required checkbox unchecked: " + field["label"])
                    if field["type"] == "radio" and not any(
                        option["type"] == "radio"
                        and option["name"] == field["name"]
                        and option["checked"]
                        for option in fields
                    ):
                        unresolved.append(
                            "Required question unanswered: " + (field["question"] or field["label"])
                        )
        return list(dict.fromkeys(unresolved))

    async def final_approval(self, record: JobRecord, unresolved: list[str]) -> str:
        # A durable interrupt separates form preparation from the final submit action.
        import sqlite3

        from langgraph.checkpoint.sqlite import SqliteSaver
        from langgraph.graph import END, START, StateGraph
        from langgraph.types import Command, interrupt
        from typing_extensions import TypedDict

        class ApprovalState(TypedDict, total=False):
            answer: str

        def approve(state: ApprovalState) -> ApprovalState:
            answer = interrupt(
                {
                    "application_id": record.application_id,
                    "artifact_sha256": __import__(
                        "lakshya.services.store", fromlist=["artifact_hash"]
                    ).artifact_hash(record.files),
                    "unknown_fields": unresolved,
                    "action": "final_submit",
                }
            )
            return {"answer": str(answer)}

        with sqlite3.connect(
            self.settings.data_dir / "application-checkpoints.sqlite3", check_same_thread=False
        ) as connection:
            graph = (
                StateGraph(ApprovalState)
                .add_node("approve", approve)
                .add_edge(START, "approve")
                .add_edge("approve", END)
                .compile(checkpointer=SqliteSaver(connection))
            )
            config: RunnableConfig = {"configurable": {"thread_id": record.application_id}}
            graph.invoke({}, config)
            answer = await self.ask(
                "Inspect the form and complete flagged questions. Type SUBMIT to send, or Enter to cancel: "
            )
            result = graph.invoke(Command(resume=answer), config)
            return str(result.get("answer", ""))

    async def submit_buttons(self, page: Page) -> list[Locator]:
        candidates = []
        for frame in page.frames:
            buttons = frame.get_by_role("button", name=SUBMIT_NAMES)
            for index in range(await buttons.count()):
                button = buttons.nth(index)
                if await button.is_visible() and await button.is_enabled():
                    candidates.append(button)
        return candidates

    async def _blocked(self, page: Page) -> bool:
        if any(
            x in urlparse(page.url).path.lower()
            for x in ("login", "signin", "authwall", "checkpoint")
        ):
            return True
        for frame in page.frames:
            body = frame.locator("body")
            text = (await body.inner_text(timeout=3000)).lower() if await body.count() else ""
            if any(
                marker in text
                for marker in (
                    "verify you are human",
                    "access denied",
                    "unusual traffic",
                    "captcha challenge",
                )
            ):
                return True
            challenges = frame.locator(
                'iframe[src*="captcha"], iframe[src*="challenge"], .g-recaptcha, .h-captcha'
            )
            if await challenges.count():
                return True
        return False

    async def apply(
        self,
        record: JobRecord,
        profile: Profile,
        profile_hash: str,
        auto: bool = False,
        dry_run: bool = False,
    ) -> str:
        job = self.preflight(record, profile_hash, auto, dry_run)
        platform = provider(str(job.apply_url))
        if dry_run and record.is_demo:
            self.tracker.event(
                job.id,
                "dry_run",
                "Demo: reviewed bundle validated; browser/network submission disabled",
            )
            console.print(
                f"[yellow]DRY RUN[/yellow] {job.company}: {job.title}; PDF {record.files['pdf']}",
                markup=False,
            )
            return "dry-run"
        self.settings.browser_profile.mkdir(parents=True, exist_ok=True)
        async with async_playwright() as playwright:
            context = await playwright.chromium.launch_persistent_context(
                str(self.settings.browser_profile),
                headless=self.settings.browser_headless or auto,
                service_workers="block",
            )
            armed = False

            async def mutation_gate(route: Route) -> None:
                # Block application writes until an explicit final confirmation/reservation.
                # Dry-run blocks all non-read requests throughout, including user clicks.
                if route.request.method not in {"GET", "HEAD", "OPTIONS"} and (
                    dry_run or not armed
                ):
                    await route.abort()
                else:
                    await route.continue_()

            await context.route("**/*", mutation_gate)
            page = await context.new_page()
            try:
                await page.goto(str(job.apply_url), wait_until="domcontentloaded", timeout=45000)
                platform = provider(page.url)
                if auto and platform not in AUTO_PLATFORMS:
                    raise ValueError("Redirected outside supported --auto ATS hosts")
                if await self._blocked(page):
                    self.tracker.event(
                        job.id, "browser_blocked", "Login/CAPTCHA wall; stopped without bypass"
                    )
                    console.print(
                        "Login or CAPTCHA detected. Open the URL yourself and complete the application manually."
                    )
                    return "blocked"
                if platform in AUTO_PLATFORMS:
                    # React-hosted forms may not be mounted at DOMContentLoaded.
                    try:
                        await page.locator('input[type="file"]').first.wait_for(
                            state="attached", timeout=15000
                        )
                    except Exception:
                        pass  # fill_form reports a missing resume control without submitting.
                if platform in {"linkedin", "naukri"}:
                    console.print(
                        f"Prepared resume: {record.files['pdf']}\nCover note: {record.files['cover_note']}",
                        markup=False,
                    )
                    if dry_run:
                        await self.ask(
                            "Dry-run: submission requests are blocked. Inspect the page; Enter closes it. "
                        )
                        self.tracker.event(job.id, "dry_run", "Manual-only platform opened")
                        return "dry-run"
                    answer = await self.ask(
                        "You must click Submit yourself. Type ARM to allow your browser submission, or Enter to close: "
                    )
                    if answer != "ARM":
                        return "cancelled"
                    self.tracker.verify_approval(self.tracker.get(job.id), profile_hash)
                    self.tracker.reserve(
                        job,
                        min(10, self.settings.daily_application_cap)
                        if auto
                        else self.settings.daily_application_cap,
                        self.settings.timezone,
                    )
                    armed = True
                    answer = await self.ask(
                        "Complete the form and click Submit yourself. Type APPLIED if confirmed, otherwise Enter: "
                    )
                    self.tracker.finish_submission(job, confirmed=answer == "APPLIED")
                    return "applied" if answer == "APPLIED" else "uncertain"
                uploads: list[tuple[Locator, str]] = []
                unresolved = await self.fill_form(
                    page,
                    profile,
                    record,
                    platform,
                    pending_uploads=None if dry_run else uploads,
                )
                if unresolved:
                    console.print("Fields requiring your review:", markup=False)
                    for field in unresolved:
                        console.print(f"  - {field}", markup=False)
                    self.tracker.event(job.id, "unknown_fields", "; ".join(unresolved))
                if dry_run:
                    await self.ask(
                        "Dry-run: remote write/submission requests are blocked. Inspect the form; Enter closes it. "
                    )
                    self.tracker.event(
                        job.id, "dry_run", "Form prepared; no write requests permitted"
                    )
                    return "dry-run"
                if auto and unresolved:
                    self.tracker.event(
                        job.id,
                        "auto_paused",
                        "Unknown, unsupported or missing fields require human input",
                    )
                    console.print("--auto paused: complete these questions using assist mode.")
                    return "needs-review"
                if not auto:
                    answer = await self.final_approval(record, unresolved)
                    if answer != "SUBMIT":
                        return "cancelled"
                buttons = await self.submit_buttons(page)
                if len(buttons) != 1:
                    raise ValueError(
                        "No unique, enabled Submit button found. Complete the form manually; nothing was submitted."
                    )
                # Recheck files and freshness immediately before arming, after terminal interaction.
                if await self._blocked(page):
                    self.tracker.event(
                        job.id, "browser_blocked", "Login/CAPTCHA appeared; stopped without bypass"
                    )
                    return "blocked"
                self.preflight(self.tracker.get(job.id), profile_hash, auto, False)
                self.tracker.reserve(
                    job,
                    min(10, self.settings.daily_application_cap)
                    if auto
                    else self.settings.daily_application_cap,
                    self.settings.timezone,
                )
                armed = True
                confirmed = False
                try:
                    for control, path in uploads:
                        await control.set_input_files(path)
                    # Upload widgets can reveal an additional challenge or invalidate
                    # a form. Never try to solve or bypass it after disclosing a file.
                    if await self._blocked(page):
                        raise ValueError("Login/CAPTCHA appeared after upload")
                    await buttons[0].click(timeout=15000)
                    for _ in range(15):
                        texts = []
                        for frame in page.frames:
                            body = frame.locator("body")
                            if await body.count():
                                texts.append(await body.inner_text(timeout=3000))
                        if any(SUCCESS.search(text) for text in texts):
                            confirmed = True
                            break
                        await asyncio.sleep(1)
                except Exception as exc:
                    log.warning(
                        "Submission click/confirmation uncertain for %s: %s",
                        job.id,
                        type(exc).__name__,
                    )
                finally:
                    self.tracker.finish_submission(job, confirmed)
                if not confirmed:
                    console.print(
                        "Submission outcome uncertain. Check with the employer; automatic retry is blocked."
                    )
                return "applied" if confirmed else "uncertain"
            finally:
                await context.close()
