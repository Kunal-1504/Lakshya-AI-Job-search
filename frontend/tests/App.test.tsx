import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import Root from "../src/Root";

const application = {
  id: "app-1",
  status: "awaiting_approval",
  notes: "",
  resume_path: "resume.pdf",
  critic_passed: true,
  critic_report: { passed: true },
  allowed_statuses: ["skipped", "resume_ready"],
  applied_at: null,
  follow_up_date: null,
  follow_up_draft: null,
  follow_up_approved: false,
  submission_state: null,
  job: {
    id: "job-1",
    title: "AI Engineer",
    company: "Fictional Company",
    location: "Pune",
    source: "demo",
    is_demo: true,
    remote_type: "onsite",
    posted_at: null,
    apply_url: "https://example.invalid/job",
    description: "Python SQL",
    match_score: 85,
    matched_skills: ["Python"],
    missing_skills: [],
    match_reasoning: "Skills match",
    jd_analysis: {},
  },
};
const stats = {
  jobs: 1,
  applications: 1,
  review_queue: 1,
  applied: 0,
  response_rate: 0,
  average_response_days: null,
  due_followups: 0,
  funnel: { awaiting_approval: 1 },
  weekly: [],
};

const user = { id: "user-1", name: "Test User", email: "test@example.invalid" };
const preferences = {
  ai_provider: "local",
  application_mode: "assist",
  daily_application_cap: 5,
  target_roles: ["AI Engineer"],
  locations: ["Pune"],
  profile: { imported: false },
  enabled_sources: ["himalayas"],
};
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.history.replaceState({}, "", "/");
});
function mockAPI() {
  const fetch = vi.fn().mockImplementation(async (path: string) => {
    if (path === "/api/auth/me")
      return { ok: false, status: 401, json: async () => ({ detail: "Please sign in." }) };
    const data =
      path === "/api/auth/signin" || path === "/api/auth/signup"
        ? user
        : path === "/api/settings"
          ? preferences
          : path === "/api/stats"
            ? stats
            : path === "/api/live"
              ? {
                  ai_pipeline_ready: false,
                  requirements: [],
                  scheduler: { enabled: true, interval_minutes: 60 },
                }
              : path.startsWith("/api/jobs")
                ? [application.job]
                : path.startsWith("/api/applications/app-1")
                  ? {
                      ...application,
                      timeline: [],
                      master_resume: "Original Python evidence",
                      tailored_resume: "Tailored Python evidence",
                      changes: "Reordered skills",
                    }
                  : path.startsWith("/api/applications")
                    ? [application]
                    : {};
    return { ok: true, json: async () => data };
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}
async function signin() {
  await userEvent.type(await screen.findByLabelText("Email address"), user.email);
  await userEvent.type(screen.getByLabelText("Password"), "valid-test-password");
  await userEvent.click(screen.getByRole("button", { name: "Sign in to my account" }));
  await screen.findByRole("link", { name: "Home" });
}
test("sign in uses cookies without dashboard keys and sign out clears the workspace", async () => {
  const fetch = mockAPI();
  render(<Root />);
  await signin();
  expect(await screen.findByText("AI Engineer")).toBeInTheDocument();
  expect(fetch).toHaveBeenCalledWith(
    "/api/stats",
    expect.objectContaining({ credentials: "same-origin", headers: {} }),
  );
  expect(localStorage.length).toBe(0);
  await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
  expect(await screen.findByLabelText("Email address")).toBeInTheDocument();
});
test("signup collects identity and does not expose an API-key login", async () => {
  const fetch = mockAPI();
  render(<Root />);
  await userEvent.click(await screen.findByRole("button", { name: "Sign up" }));
  await userEvent.type(screen.getByLabelText("Your name"), "Test User");
  await userEvent.type(screen.getByLabelText("Email address"), user.email);
  await userEvent.type(screen.getByLabelText("Password"), "valid-test-password");
  await userEvent.click(screen.getByRole("button", { name: "Create my account" }));
  expect(await screen.findByRole("link", { name: "My preferences" })).toBeInTheDocument();
  expect(fetch).toHaveBeenCalledWith(
    "/api/auth/signup",
    expect.objectContaining({ method: "POST" }),
  );
  expect(screen.queryByLabelText("Lakshya dashboard key")).not.toBeInTheDocument();
});
test("bad credentials stay at sign in with an understandable error", async () => {
  const fetch = mockAPI();
  const fallback = fetch.getMockImplementation();
  fetch.mockImplementation(async (path: string, init: RequestInit) =>
    path === "/api/auth/signin"
      ? {
          ok: false,
          status: 401,
          json: async () => ({ detail: "Email or password is incorrect." }),
        }
      : fallback?.(path, init),
  );
  render(<Root />);
  await userEvent.type(await screen.findByLabelText("Email address"), user.email);
  await userEvent.type(screen.getByLabelText("Password"), "invalid-test-password");
  await userEvent.click(screen.getByRole("button", { name: "Sign in to my account" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Email or password is incorrect.");
  expect(screen.queryByRole("link", { name: "Home" })).not.toBeInTheDocument();
});
test("three-step preferences record automatic application consent and caps", async () => {
  const fetch = mockAPI();
  render(<Root />);
  await signin();
  await userEvent.click(screen.getByRole("link", { name: "My preferences" }));
  expect(await screen.findByText("Your job search in 3 steps")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("radio", { name: /Apply automatically/ }));
  await userEvent.clear(screen.getByLabelText("Maximum applications per day"));
  await userEvent.type(screen.getByLabelText("Maximum applications per day"), "3");
  await userEvent.click(screen.getByRole("button", { name: "Save and start my search" }));
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/settings",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({
          target_roles: ["AI Engineer"],
          locations: ["Pune"],
          application_mode: "auto",
          daily_application_cap: 3,
          max_applications_per_run: 3,
          live_search_enabled: true,
          boards: { greenhouse: [], lever: [], ashby: [], recruitee: [] },
          enabled_sources: ["himalayas", "greenhouse", "lever", "ashby", "recruitee"],
        }),
      }),
    ),
  );
});
test("each job has a direct resume tailoring action", async () => {
  const fetch = mockAPI();
  const fallback = fetch.getMockImplementation();
  fetch.mockImplementation(async (path: string, init: RequestInit) =>
    path === "/api/applications" ? { ok: true, json: async () => [] } : fallback?.(path, init),
  );
  render(<Root />);
  await signin();
  await userEvent.click(screen.getByRole("link", { name: "Find jobs" }));
  await userEvent.click(await screen.findByRole("button", { name: "Tailor my resume" }));
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/jobs/job-1/prepare",
      expect.objectContaining({ method: "POST" }),
    ),
  );
});
test("expired sessions return to sign in", async () => {
  const fetch = mockAPI();
  const fallback = fetch.getMockImplementation();
  render(<Root />);
  await signin();
  fetch.mockImplementation(async (path: string, init: RequestInit) =>
    path.startsWith("/api/jobs")
      ? { ok: false, status: 401, json: async () => ({ detail: "Please sign in." }) }
      : fallback?.(path, init),
  );
  await userEvent.click(screen.getByRole("link", { name: "Find jobs" }));
  expect(await screen.findByLabelText("Email address")).toBeInTheDocument();
});
test("resume detail retains the original evidence and approval action", async () => {
  const fetch = mockAPI();
  render(<Root />);
  await signin();
  await userEvent.click(await screen.findByText("AI Engineer"));
  expect(await screen.findByText("Original Python evidence")).toBeInTheDocument();
  expect(screen.getByText("Tailored Python evidence")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Approve bundle" }));
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/applications/app-1/approve",
      expect.objectContaining({ method: "POST" }),
    ),
  );
});

test("an unfinished cloud setup explains the issue and prevents misleading sign-in", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: async () => ({
        detail: "Cloud setup is in progress. Sign-in will be available when it is complete.",
      }),
    }),
  );
  render(<Root />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Cloud setup is in progress");
  expect(screen.getByRole("button", { name: "Sign in to my account" })).toBeDisabled();
  expect(screen.getByLabelText("Email address")).toBeDisabled();
});
