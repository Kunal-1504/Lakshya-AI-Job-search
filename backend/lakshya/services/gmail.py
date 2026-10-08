"""Opt-in Gmail read-only suggestions. No sending or automatic status updates."""

import os
import re
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from lakshya.db.models import ApplicationRecord, JobRecord

READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


def suggest_statuses(session: Session) -> list[dict[str, Any]]:
    token = os.getenv("GMAIL_ACCESS_TOKEN", "")
    if not token:
        raise ValueError("Set an OAuth GMAIL_ACCESS_TOKEN with only gmail.readonly scope to opt in")
    with httpx.Client(timeout=30) as client:
        scope_response = client.get(
            "https://oauth2.googleapis.com/tokeninfo", params={"access_token": token}
        )
        scope_response.raise_for_status()
        scopes = set(scope_response.json().get("scope", "").split())
        if READONLY_SCOPE not in scopes or scopes - {READONLY_SCOPE, "openid", "email", "profile"}:
            raise ValueError("Gmail integration requires a token restricted to gmail.readonly")
        headers = {"Authorization": f"Bearer {token}"}
        response = client.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            headers=headers,
            params={"q": "newer_than:30d {application interview offer rejected}", "maxResults": 50},
        )
        response.raise_for_status()
        tracked = list(
            session.execute(
                select(ApplicationRecord, JobRecord)
                .join(JobRecord, ApplicationRecord.job_id == JobRecord.id)
                .where(ApplicationRecord.applied_at.is_not(None), JobRecord.is_demo.is_(False))
            )
        )
        suggestions = []
        for message in response.json().get("messages", []):
            detail = client.get(
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message['id']}",
                headers=headers,
                params={"format": "metadata"},
            )
            detail.raise_for_status()
            row = detail.json()
            header_map = {
                h["name"].lower(): h["value"] for h in row.get("payload", {}).get("headers", [])
            }
            subject = header_map.get("subject", "")
            text = (subject + " " + row.get("snippet", "")).lower()
            status = next(
                (
                    value
                    for pattern, value in (
                        (r"not selected|unfortunately|regret|rejected", "rejected"),
                        (r"interview|schedule.*call", "interview_scheduled"),
                        (r"offer letter|pleased to offer", "offer"),
                    )
                    if re.search(pattern, text)
                ),
                None,
            )
            if not status:
                continue
            candidates = [(app, job) for app, job in tracked if job.company.casefold() in text]
            if len(candidates) == 1:
                app, job = candidates[0]
                suggestions.append(
                    {
                        "application_id": app.id,
                        "company": job.company,
                        "suggested_status": status,
                        "subject": subject,
                        "message_id": message["id"],
                        "reason": "Company name and status language matched; confirm manually",
                    }
                )
        return suggestions
