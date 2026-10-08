import { z } from "zod";

export const jobSchema = z.object({
  id: z.string(),
  title: z.string(),
  company: z.string(),
  location: z.string(),
  remote_type: z.string(),
  source: z.string(),
  is_demo: z.boolean(),
  posted_at: z.string().nullable(),
  apply_url: z.string(),
  description: z.string(),
  match_score: z.number().nullable(),
  matched_skills: z.array(z.string()),
  missing_skills: z.array(z.string()),
  match_reasoning: z.string().nullable(),
  jd_analysis: z.record(z.unknown()),
});
export const applicationSchema = z.object({
  id: z.string(),
  status: z.string(),
  notes: z.string(),
  job: jobSchema,
  resume_path: z.string().nullable(),
  critic_passed: z.boolean(),
  critic_report: z.record(z.unknown()),
  allowed_statuses: z.array(z.string()),
  applied_at: z.string().nullable(),
  follow_up_date: z.string().nullable(),
  follow_up_draft: z.string().nullable(),
  follow_up_approved: z.boolean(),
  submission_state: z.string().nullable(),
  auto_apply: z
    .object({
      eligible: z.boolean(),
      state: z.string(),
      reasons: z.array(z.string()),
      platform: z.string(),
    })
    .optional(),
});
export const detailSchema = applicationSchema.extend({
  timeline: z.array(
    z.object({
      id: z.number(),
      new_status: z.string(),
      note: z.string(),
      changed_at: z.string(),
      source: z.string(),
    }),
  ),
  master_resume: z.string(),
  tailored_resume: z.string().optional(),
  changes: z.string().optional(),
  cover_note: z.string().optional(),
});
export const runSchema = z.object({
  id: z.string(),
  status: z.string(),
  started_at: z.string(),
  dry_run: z.boolean(),
  error: z.string().nullable(),
  result: z.record(z.unknown()),
  options: z.record(z.unknown()),
});
export type Job = z.infer<typeof jobSchema>;
export type Application = z.infer<typeof applicationSchema>;
export type Detail = z.infer<typeof detailSchema>;
export type Run = z.infer<typeof runSchema>;
export type Stats = {
  jobs: number;
  applications: number;
  review_queue: number;
  applied: number;
  response_rate: number;
  average_response_days: number | null;
  due_followups: number;
  funnel: Record<string, number>;
  weekly: { day: string; applications: number }[];
};
export type Settings = {
  cloud?: boolean;
  max_resumes_per_search?: number | null;
  ai_provider: "local" | "gemini" | "anthropic";
  live_search_enabled: boolean;
  live_search_interval_minutes: number;
  target_roles: string[];
  locations: string[];
  match_threshold: number;
  enabled_sources: string[];
  agent_models: Record<string, string>;
  boards: Record<string, string[]>;
  public_search: Record<string, string[]>;
  model_prices_per_million: Record<string, { input_usd: number; output_usd: number }>;
  max_run_tokens: number;
  max_day_tokens: number;
  max_run_cost_usd: number;
  max_day_cost_usd: number;
  credential_status: Record<string, boolean>;
  profile: { imported: boolean; name?: string; skills?: string[] };
  embedding_backend: string;
  [key: string]: unknown;
};
export type LiveStatus = {
  mode: string;
  ai_provider: string;
  discovery_ready: boolean;
  ai_pipeline_ready: boolean;
  requirements: { id: string; message: string }[];
  sources: { name: string; ready: boolean; message: string | null }[];
  scheduler: {
    enabled: boolean;
    running: boolean;
    interval_minutes: number;
    next_search_at: string | null;
    last_run_id: string | null;
    error: string | null;
  };
};
export type Agent = {
  name: string;
  status: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
};
export type AgentEvent = {
  id: number;
  step: string;
  message: string;
  timestamp: string;
  payload: Record<string, unknown>;
};

export type User = { id: string; email: string; name: string };

export class APIError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

export class API {
  constructor(private key: string = "") {}
  async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await fetch(`/api${path}`, {
      ...init,
      credentials: "same-origin",
      headers: {
        ...(this.key ? { "X-API-Key": this.key } : {}),
        ...(init.body && !(init.body instanceof FormData)
          ? { "Content-Type": "application/json" }
          : {}),
        ...init.headers,
      },
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      if (response.status === 401) {
        if (!path.startsWith("/auth/")) window.dispatchEvent(new Event("lakshya-session-expired"));
        throw new APIError(
          typeof error.detail === "string" ? error.detail : "Please sign in again.",
          response.status,
        );
      }
      throw new APIError(
        typeof error.detail === "string" ? error.detail : `Request failed (${response.status})`,
        response.status,
      );
    }
    return response.json();
  }
  jobs(query = "") {
    return this.request(`/jobs${query}`).then((data) => z.array(jobSchema).parse(data));
  }
  applications(query = "") {
    return this.request(`/applications${query}`).then((data) =>
      z.array(applicationSchema).parse(data),
    );
  }
  detail(id: string) {
    return this.request(`/applications/${id}`).then((data) => detailSchema.parse(data));
  }
  runs() {
    return this.request("/runs").then((data) => z.array(runSchema).parse(data));
  }
  stats() {
    return this.request<Stats>("/stats");
  }
  settings() {
    return this.request<Settings>("/settings");
  }
  live() {
    return this.request<LiveStatus>("/live");
  }
  post<T>(path: string, data: unknown = {}) {
    return this.request<T>(path, { method: "POST", body: JSON.stringify(data) });
  }
  patch<T>(path: string, data: unknown) {
    return this.request<T>(path, { method: "PATCH", body: JSON.stringify(data) });
  }
  async download(path: string, filename: string) {
    const response = await fetch(`/api${path}`, { headers: { "X-API-Key": this.key } });
    if (!response.ok) throw new Error("Download unavailable");
    const url = URL.createObjectURL(await response.blob());
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  async events(id: string, onEvent: (event: AgentEvent) => void, signal: AbortSignal) {
    const response = await fetch(`/api/runs/${id}/events`, {
      headers: { "X-API-Key": this.key },
      signal,
    });
    if (!response.ok || !response.body) throw new Error("Activity stream unavailable");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let end;
      while ((end = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, end);
        buffer = buffer.slice(end + 2);
        if (block.includes("event: agent")) {
          const line = block.split("\n").find((line) => line.startsWith("data: "));
          if (line) onEvent(JSON.parse(line.slice(6)));
        }
      }
    }
  }
}
