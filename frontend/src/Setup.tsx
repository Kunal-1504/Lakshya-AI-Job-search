import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Check, FileText, Sparkles, Target } from "lucide-react";
import { Link } from "react-router-dom";
import { useSession } from "./App";
import { Button } from "./components/ui/button";

export default function Setup() {
  const { api } = useSession();
  const query = useQuery({ queryKey: ["settings"], queryFn: () => api.settings() });
  if (query.isPending) return <p>Loading your preferences…</p>;
  if (!query.data) return <p role="alert">{query.error?.message}</p>;
  return <SetupForm initial={query.data} />;
}
function SetupForm({ initial }: { initial: import("./api/client").Settings }) {
  const { api, toast } = useSession();
  const client = useQueryClient();
  const [roles, setRoles] = useState(initial.target_roles.join(", "));
  const [cities, setCities] = useState(initial.locations.join(", "));
  const [auto, setAuto] = useState(initial.application_mode === "auto");
  const [cap, setCap] = useState(Math.min(10, Number(initial.daily_application_cap ?? 5)));
  const [busy, setBusy] = useState(false);
  const [boards, setBoards] = useState<Record<string, string>>(
    Object.fromEntries(
      ["greenhouse", "lever", "ashby", "recruitee"].map((name) => [
        name,
        (initial.boards?.[name] ?? []).join(", "),
      ]),
    ),
  );
  async function upload(file: File) {
    if (file.size > 4 * 1024 * 1024) {
      toast("Choose a resume smaller than 4 MB.");
      return;
    }
    setBusy(true);
    try {
      const data = new FormData();
      data.append("file", file);
      await api.request("/profile/import", { method: "POST", body: data });
      toast("Resume uploaded. We’ll use your real experience in every tailored resume.");
      await client.invalidateQueries();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function save() {
    setBusy(true);
    try {
      await api.patch("/settings", {
        target_roles: roles
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        locations: cities
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        application_mode: auto ? "auto" : "assist",
        daily_application_cap: cap,
        max_applications_per_run: cap,
        live_search_enabled: true,
        boards: Object.fromEntries(
          Object.entries(boards).map(([name, value]) => [
            name,
            value
              .split(",")
              .map((s) => s.trim())
              .filter(Boolean),
          ]),
        ),
        enabled_sources: auto
          ? Array.from(
              new Set([
                ...(initial.enabled_sources ?? []),
                "greenhouse",
                "lever",
                "ashby",
                "recruitee",
              ]),
            )
          : initial.enabled_sources,
      });
      await client.invalidateQueries();
      toast("Preferences saved. Your search will run automatically.");
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="page-title">
        <div>
          <p className="eyebrow">GET STARTED</p>
          <h1>Your job search in 3 steps</h1>
          <p className="muted mt-2">
            Set this up once. Lakshya takes care of matching and resume preparation.
          </p>
        </div>
      </div>

      {initial.cloud && (
        <p className="muted mb-5">
          Your search runs in the cloud, even when your computer is off. Each search prepares up to
          2 matching resumes.
        </p>
      )}
      <div className="setup-steps">
        <section className="panel">
          <div className="step-heading">
            <span className="step-number">1</span>
            <FileText />
            <h2>Upload your resume</h2>
          </div>
          <p className="muted mb-5">
            Use your current resume. Every tailored version uses only your actual skills and
            experience.
          </p>
          <label className="upload-area">
            {initial.profile.imported ? (
              <>
                <Check />
                Resume added — upload again to replace
              </>
            ) : (
              <>
                <FileText />
                Choose your resume
              </>
            )}
            <input
              aria-label="Upload your resume"
              type="file"
              accept=".pdf,.docx,.txt,.md"
              disabled={busy}
              onChange={(e) => {
                if (e.target.files?.[0]) void upload(e.target.files[0]);
              }}
            />
            <small>PDF, DOCX or text · up to 4 MB</small>
          </label>
        </section>
        <section className="panel">
          <div className="step-heading">
            <span className="step-number">2</span>
            <Target />
            <h2>Choose the jobs you want</h2>
          </div>
          <label className="auth-field">
            Job titles
            <input
              className="input"
              value={roles}
              onChange={(e) => setRoles(e.target.value)}
              placeholder="AI Engineer, Data Analyst"
            />
          </label>
          <label className="auth-field">
            Preferred cities
            <input
              className="input"
              value={cities}
              onChange={(e) => setCities(e.target.value)}
              placeholder="Pune, Bangalore, Hyderabad"
            />
          </label>
          <p className="muted text-sm">
            Separate titles and cities with commas. India and worldwide remote jobs are included.
          </p>
        </section>
        <section className="panel">
          <div className="step-heading">
            <span className="step-number">3</span>
            <Sparkles />
            <h2>Choose how to apply</h2>
          </div>
          <label className={`mode-choice ${!auto ? "selected" : ""}`}>
            <input type="radio" name="apply-mode" checked={!auto} onChange={() => setAuto(false)} />
            <div>
              <strong>Prepare and review</strong>
              <p>We create a tailored resume. You check it and apply.</p>
            </div>
          </label>
          <label className={`mode-choice ${auto ? "selected" : ""}`}>
            <input type="radio" name="apply-mode" checked={auto} onChange={() => setAuto(true)} />
            <div>
              <strong>Apply automatically where supported</strong>
              <p>
                Send checked resumes to supported Greenhouse, Lever, Ashby and Recruitee forms with
                a fit score of 80 or more.
              </p>
            </div>
          </label>
          {auto && (
            <div className="mt-4">
              <label className="auth-field">
                Maximum applications per day
                <input
                  aria-label="Maximum applications per day"
                  className="input"
                  type="number"
                  min={1}
                  max={10}
                  value={cap}
                  onChange={(e) => setCap(Number(e.target.value))}
                />
              </label>
              <p className="muted text-sm">
                Selecting this mode allows Lakshya to send your resume and stored answers to those
                employers. We pause for login, CAPTCHA, consent or missing answers.
              </p>
            </div>
          )}
          <Button className="mt-6" disabled={busy} onClick={save}>
            Save and start my search
          </Button>
        </section>
      </div>
      <section className="panel mt-6">
        <h2 className="font-semibold">Direct employer job feeds</h2>
        <p className="muted mt-2 mb-4">
          Starter feeds include Jumio, Glean, Netomi, Ema, Emergence and Metyis. These are live
          company listings, not a guarantee of a suitable opening today. Your role, location and
          experience preferences still apply.
        </p>
        <div className="grid gap-4 md:grid-cols-3">
          {Object.entries(boards).map(([name, value]) => (
            <label className="auth-field" key={name}>
              {name.charAt(0).toUpperCase() + name.slice(1)} company boards
              <input
                className="input"
                aria-label={`${name} company boards`}
                value={value}
                onChange={(event) => setBoards({ ...boards, [name]: event.target.value })}
              />
            </label>
          ))}
        </div>
        <p className="muted text-sm mt-3">
          Use company names from their board URLs, separated by commas. Empty lists use the starter
          feeds. Save with the button above. Other websites remain available through the application
          link and tailored resume; login, CAPTCHA and unsupported forms need your input.
        </p>
      </section>
      <div className="panel mt-6">
        <h2 className="font-semibold">Need to add application answers or an AI key?</h2>
        <p className="muted mt-2">
          Free resume tailoring works without an AI key. Add your screening answers and optional
          Gemini key in advanced settings.
        </p>
        <Link className="button-link mt-4" to="/advanced">
          Advanced settings
        </Link>
      </div>
    </>
  );
}
