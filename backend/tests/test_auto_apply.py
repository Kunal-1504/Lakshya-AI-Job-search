import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from lakshya.db.base import utc_now
from lakshya.db.models import ApplicationRecord, JobRecord
from lakshya.pipeline import Pipeline
from lakshya.services.auto_apply import apply_ready
from lakshya.services.profile import load_profile


@pytest.fixture
def prepared_real_test_bundle(settings, database):
    pipeline = Pipeline(settings)
    run = pipeline.start({"demo": True, "offline": True, "dry_run": True})
    result = pipeline.execute(run)
    pipeline.close()
    load_profile(settings, True)
    (settings.data_dir / "master_profile.json").write_bytes(
        (settings.data_dir / "demo_master_profile.json").read_bytes()
    )
    identity = result["ready"][0]
    with database() as session, session.begin():
        app = session.get(ApplicationRecord, identity)
        job = session.get(JobRecord, app.job_id)
        job.is_demo = False
        job.match_score = 90
        job.posted_at = utc_now()
    settings.application_mode = "auto"
    settings.browser_headless = True
    return identity


@pytest.mark.parametrize(
    "unknown",
    [False, "missing", "consent", "group_saved", "group_missing", "captcha_late", "eager_upload"],
)
@pytest.mark.parametrize("platform", ["lever", "recruitee"])
def test_headless_application_confirmed_once_or_paused_for_unknown_fields(
    prepared_real_test_bundle, settings, database, monkeypatch, unknown, platform
):
    posts = []
    uploads = []
    reservation_states = []
    settings.answers["I agree to the privacy policy"] = "Yes"
    # A generic Yes answer must never answer a different question.
    settings.answers["Yes"] = "Yes"
    if unknown == "group_saved":
        settings.answers["Do you need visa sponsorship?"] = "No"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            extra = (
                '<label>I agree to the privacy policy<input type="checkbox" name="consent" required></label>'
                if unknown == "consent"
                else '<label>Notice period<input name="notice" required></label>'
                if unknown == "missing"
                else "<fieldset><legend>Do you need visa sponsorship? *</legend>"
                '<label>Yes<input type="radio" name="visa" value="true" required></label>'
                '<label>No<input type="radio" name="visa" value="false" required></label></fieldset>'
                if unknown in {"group_saved", "group_missing"}
                else '<script>document.addEventListener("input", () => { '
                'const p=document.createElement("p");p.textContent="Verify you are human";'
                "document.body.append(p); }, {once:true})</script>"
                if unknown == "captcha_late"
                else '<script>document.addEventListener("change", async e => {'
                'if (e.target.type !== "file") return;'
                'const b=document.querySelector("button[type=submit]");b.disabled=true;'
                'await fetch("/upload", {method:"POST", body:"resume selected"});b.disabled=false;'
                "});</script>"
                if unknown == "eager_upload"
                else ""
            )
            self.wfile.write(
                (
                    '<form method="post" enctype="multipart/form-data">'
                    '<label>Full name<input name="name" required></label>'
                    '<label>Email address<input name="email" type="email" required></label>'
                    '<label>Resume<input type="file" name="resume" required></label>'
                    + extra
                    + '<button type="submit">Submit application</button></form>'
                ).encode()
            )

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            with database() as session:
                reservation_states.append(
                    session.get(ApplicationRecord, prepared_real_test_bundle).submission_state
                )
            (uploads if self.path == "/upload" else posts).append(body)
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h1>Thank you for applying</h1>")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    identity = prepared_real_test_bundle
    with database() as session, session.begin():
        app = session.get(ApplicationRecord, identity)
        job = session.get(JobRecord, app.job_id)
        job.apply_url = f"http://127.0.0.1:{server.server_port}/application"
    # Only this controlled local fixture substitutes for a supported hosted ATS.
    monkeypatch.setattr("lakshya.applier.provider", lambda url: platform)
    monkeypatch.setattr("lakshya.services.auto_apply.provider", lambda url: platform)
    try:
        result = apply_ready(settings)
        with database() as session:
            app = session.get(ApplicationRecord, identity)
            paused = unknown in {"missing", "consent", "group_missing", "captcha_late"}
            if paused:
                assert posts == []
                assert result["needs_help"] == 1 and app.status == "awaiting_approval"
                assert app.submission_state is None
            else:
                assert len(posts) == 1 and b"%PDF" in posts[0]
                assert result["applied"] == 1
                assert app.status == "applied" and app.submission_state == "applied"
                if unknown == "group_saved":
                    assert b'name="visa"\r\n\r\nfalse' in posts[0]
                assert reservation_states and set(reservation_states) == {"reserved"}
                if unknown == "eager_upload":
                    assert len(uploads) == 1
        apply_ready(settings)
        assert len(posts) == (0 if paused else 1)
    finally:
        server.shutdown()
        server.server_close()


def test_manual_mode_never_starts_an_automatic_application(settings):
    assert apply_ready(settings) == {"applied": 0, "needs_help": 0}


def test_unsupported_real_application_is_counted_as_needing_help(
    prepared_real_test_bundle, settings, database, monkeypatch
):
    identity = prepared_real_test_bundle
    with database() as session, session.begin():
        app = session.get(ApplicationRecord, identity)
        session.get(
            JobRecord, app.job_id
        ).apply_url = "https://himalayas.app/companies/example/jobs/test"

    def forbidden(*args, **kwargs):
        raise AssertionError("An unsupported website must not launch a browser")

    monkeypatch.setattr("lakshya.services.auto_apply.Applier", forbidden)
    assert apply_ready(settings, [identity]) == {"applied": 0, "needs_help": 1}


@pytest.mark.parametrize(
    "status,auto,dry_run,expected",
    [
        ("completed", True, False, True),
        ("paused", True, False, False),
        ("stopped", True, False, False),
        ("completed", False, False, False),
        ("completed", True, True, False),
    ],
)
def test_worker_submits_only_after_a_completed_enabled_automatic_run(
    settings, database, monkeypatch, status, auto, dry_run, expected
):
    from unittest.mock import Mock
    from uuid import uuid4

    from lakshya.api.routes import RunManager
    from lakshya.db.models import PipelineRun

    identity = str(uuid4())
    with database() as session, session.begin():
        session.add(
            PipelineRun(
                id=identity,
                graph_thread_id=identity,
                status=status,
                options={"stage": "all", "auto": auto, "dry_run": dry_run},
            )
        )
    settings.application_mode = "auto"
    pipeline = Mock()
    monkeypatch.setattr("lakshya.api.routes.Pipeline", Mock(return_value=pipeline))
    apply = Mock(return_value={"applied": 1, "needs_help": 0})
    monkeypatch.setattr("lakshya.services.auto_apply.apply_ready", apply)
    manager = RunManager(settings, database)
    manager.dispatch(identity)
    manager.close()
    assert apply.called is expected
    with database() as session:
        run = session.get(PipelineRun, identity)
        assert ("automatic_applications" in run.result) is expected
