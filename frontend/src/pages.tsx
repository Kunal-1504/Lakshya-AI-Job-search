import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { DndContext, useDraggable, useDroppable, type DragEndEvent } from "@dnd-kit/core";
import { Background, Controls, ReactFlow, type Node } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  ArrowUpRight,
  Check,
  Clock,
  Download,
  FileCheck,
  MapPin,
  TrendingUp,
  Layers,
  GripVertical,
  Search,
  SlidersHorizontal,
  Target,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { type Application, type Agent, type AgentEvent, type Run } from "./api/client";
import { Badge, ErrorBox, human, Loading, useSession } from "./App";
import { Button } from "./components/ui/button";

function PageTitle({
  label,
  title,
  description,
  children,
}: {
  label: string;
  title: string;
  description: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="page-title">
      <div>
        <p className="eyebrow">{label}</p>
        <h1>{title}</h1>
        <p className="muted mt-2">{description}</p>
      </div>
      {children}
    </div>
  );
}
function DateLabel({ value }: { value: string | null }) {
  return (
    <>
      {value
        ? new Date(value).toLocaleDateString(undefined, { month: "short", day: "numeric" })
        : "Unknown date"}
    </>
  );
}

export function Dashboard() {
  const { api } = useSession();
  const stats = useQuery({
    queryKey: ["stats"],
    queryFn: () => api.stats(),
    refetchInterval: 5000,
  });
  const applications = useQuery({
    queryKey: ["applications"],
    queryFn: () => api.applications(),
    refetchInterval: 5000,
  });
  return (
    <>
      <PageTitle
        label="YOUR SEARCH AT A GLANCE"
        title="Your job search, all in one place."
        description="Find a role, get a tailored resume, and track what happens next."
      />
      <ErrorBox error={stats.error} />
      {stats.isPending ? (
        <Loading />
      ) : (
        stats.data && (
          <>
            <div className="stat-grid">
              {(
                [
                  ["Discovered jobs", stats.data.jobs, Search, "Discovered across your sources"],
                  [
                    "Ready for review",
                    stats.data.review_queue,
                    FileCheck,
                    "Your approval comes next",
                  ],
                  ["Applications sent", stats.data.applied, Target, "Track every next step"],
                  [
                    "Response rate",
                    `${stats.data.response_rate.toFixed(0)}%`,
                    ArrowUpRight,
                    "From confirmed applications",
                  ],
                ] satisfies [string, string | number, typeof Search, string][]
              ).map(([label, value, Icon, hint]) => {
                const Glyph = Icon as typeof Search;
                return (
                  <div className="panel stat-card" key={String(label)}>
                    <div className="flex items-center justify-between gap-3">
                      <span className="font-medium">{String(label)}</span>
                      <span className="stat-icon">
                        <Glyph size={21} aria-hidden="true" />
                      </span>
                    </div>
                    <strong>{String(value)}</strong>
                    <small>{String(hint)}</small>
                  </div>
                );
              })}
            </div>
            <div className="dashboard-grid">
              <section className="panel">
                <div className="section-heading">
                  <h2>Application momentum</h2>
                  <span className="muted text-sm">LAST 7 DAYS</span>
                </div>
                {stats.data.weekly.some((day) => day.applications > 0) ? (
                  <div className="h-60">
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={stats.data.weekly}>
                        <defs>
                          <linearGradient id="momentum" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor="#10b981" stopOpacity={0.3} />
                            <stop offset="100%" stopColor="#10b981" stopOpacity={0} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
                        <XAxis
                          dataKey="day"
                          tickFormatter={(d) => d.slice(5)}
                          tick={{ fontSize: 13, fill: "var(--graph-text)" }}
                          axisLine={false}
                          tickLine={false}
                        />
                        <YAxis
                          allowDecimals={false}
                          tick={{ fontSize: 13, fill: "var(--graph-text)" }}
                          axisLine={false}
                          tickLine={false}
                        />
                        <Tooltip />
                        <Area
                          type="monotone"
                          dataKey="applications"
                          stroke="#10b981"
                          fill="url(#momentum)"
                          strokeWidth={2}
                        />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                ) : (
                  <div className="empty-state">
                    <TrendingUp aria-hidden="true" />
                    <strong>Your momentum starts here</strong>
                    <p>Confirmed applications will appear in your weekly progress chart.</p>
                  </div>
                )}
              </section>
              <section className="panel">
                <div className="section-heading">
                  <h2>Your pipeline</h2>
                  <SlidersHorizontal size={16} className="muted" />
                </div>
                {Object.values(stats.data.funnel).some((count) => count > 0) ? (
                  <div className="h-60">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart
                        layout="vertical"
                        data={Object.entries(stats.data.funnel)
                          .filter(([, n]) => n > 0)
                          .map(([name, count]) => ({ name: human(name), count }))}
                      >
                        <XAxis type="number" allowDecimals={false} hide />
                        <YAxis
                          type="category"
                          dataKey="name"
                          width={125}
                          tick={{ fontSize: 13, fill: "var(--graph-text)" }}
                          axisLine={false}
                          tickLine={false}
                        />
                        <Tooltip />
                        <Bar dataKey="count" fill="#10b981" radius={[0, 4, 4, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                ) : (
                  <div className="empty-state">
                    <Layers aria-hidden="true" />
                    <strong>Every stage, in one place</strong>
                    <p>Matched roles and prepared applications will populate your pipeline.</p>
                  </div>
                )}
              </section>
            </div>
            <section className="panel mt-6">
              <div className="section-heading">
                <h2>Next on your list</h2>
                <Link to="/review" className="text-sm text-emerald-500">
                  View review queue →
                </Link>
              </div>
              {applications.data?.length ? (
                <div className="job-list">
                  {applications.data.slice(0, 4).map((application) => (
                    <Link
                      className="job-row"
                      to={`/applications/${application.id}`}
                      key={application.id}
                    >
                      <span className="company-icon">{application.job.company.slice(0, 1)}</span>
                      <div className="flex-1">
                        <strong>{application.job.title}</strong>
                        <p className="muted text-sm">
                          {application.job.company} · {application.job.location}
                        </p>
                      </div>
                      <span className="score">
                        {application.job.match_score?.toFixed(0) ?? "—"}
                        <small>FIT</small>
                      </span>
                      <Badge value={application.status} />
                      <ArrowUpRight size={16} />
                    </Link>
                  ))}
                </div>
              ) : (
                <div className="empty-state">
                  <Search aria-hidden="true" />
                  <strong>Explore your next opportunity</strong>
                  <p>
                    Start a real search. Import your resume in Settings for personalized matches.
                  </p>
                  <Link to="/jobs" className="button-link">
                    Browse discovered jobs <ArrowUpRight size={16} />
                  </Link>
                </div>
              )}
            </section>
            <div className="mt-5 flex flex-wrap gap-6 text-sm muted">
              <span>
                <Clock size={14} className="inline mr-2" />
                {stats.data.due_followups} follow-ups due
              </span>
              <span>
                Average response: {stats.data.average_response_days?.toFixed(1) ?? "—"} days
              </span>
              <span>Only roles posted in the last 24 hours enter a new search.</span>
            </div>
          </>
        )
      )}
    </>
  );
}

export function Jobs() {
  const { api, toast } = useSession();
  const [preparing, setPreparing] = useState("");
  async function prepare(identity: string) {
    setPreparing(identity);
    try {
      await api.post(`/jobs/${identity}/prepare`);
      toast("We’re tailoring your resume. Check Search progress for updates.");
    } catch (error) {
      toast((error as Error).message);
    } finally {
      setPreparing("");
    }
  }
  const [search, setSearch] = useState("");
  const [source, setSource] = useState("");
  const [minimum, setMinimum] = useState("0");
  const [fresh, setFresh] = useState(false);
  const query = useQuery({
    queryKey: ["jobs", search, source, minimum, fresh],
    queryFn: () =>
      api.jobs(
        `?q=${encodeURIComponent(search)}&source=${source}&min_score=${minimum}${fresh ? "&freshness_hours=24" : ""}`,
      ),
    refetchInterval: 5000,
  });
  const apps = useQuery({ queryKey: ["applications"], queryFn: () => api.applications() });
  return (
    <>
      <PageTitle
        label="DISCOVERY"
        title="Jobs for you"
        description="Browse roles for your preferences. We prepare applications for jobs posted in the last 24 hours."
      />
      <div className="filters">
        <input
          className="input flex-1"
          aria-label="Search jobs"
          placeholder="Search role or company"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select
          className="input"
          aria-label="Source filter"
          value={source}
          onChange={(e) => setSource(e.target.value)}
        >
          <option value="">All sources</option>
          {[
            "adzuna",
            "remotive",
            "remoteok",
            "wwr",
            "himalayas",
            "greenhouse",
            "lever",
            "ashby",
            "recruitee",
            "linkedin",
            "naukri",
            "indeed",
          ].map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
        <select
          className="input"
          aria-label="Minimum fit"
          value={minimum}
          onChange={(e) => setMinimum(e.target.value)}
        >
          <option value="0">Any fit</option>
          <option value="65">65+ fit</option>
          <option value="80">80+ fit</option>
        </select>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={fresh} onChange={(e) => setFresh(e.target.checked)} />
          Last 24h
        </label>
      </div>
      <ErrorBox error={query.error} />
      {query.isPending ? (
        <Loading />
      ) : (
        <div className="cards-grid">
          {query.data?.map((job) => {
            const app = apps.data?.find((a) => a.job.id === job.id);
            return (
              <article className="panel opportunity" key={job.id}>
                <div className="flex items-start justify-between">
                  <span className="company-icon">{job.company[0]}</span>
                  <span className="score">
                    {job.match_score?.toFixed(0) ?? "—"}
                    <small>MATCH</small>
                  </span>
                </div>
                <p className="muted mt-5 text-sm">
                  {job.company}
                  {job.is_demo && <span className="ml-2 badge">Demo</span>}
                </p>
                <h2 className="mt-1 text-lg font-semibold">{job.title}</h2>
                <p className="muted text-sm mt-2 job-meta">
                  <MapPin size={17} aria-hidden="true" />
                  <span>
                    {job.location} · {human(job.remote_type)}
                  </span>
                </p>
                <div className="flex flex-wrap gap-2 my-5">
                  {job.matched_skills.slice(0, 5).map((skill) => (
                    <span className="skill" key={skill}>
                      {skill}
                    </span>
                  ))}
                </div>
                <p className="muted job-reason line-clamp-3">
                  {job.match_reasoning ?? "Run matching to calculate fit."}
                </p>
                <div className="job-footer">
                  <span className="muted text-sm">
                    {job.source} · <DateLabel value={job.posted_at} />
                  </span>
                  {!app?.resume_path &&
                    (!app || app.status === "new" || app.status === "shortlisted") && (
                      <Button disabled={Boolean(preparing)} onClick={() => void prepare(job.id)}>
                        {preparing === job.id ? "Preparing…" : "Tailor my resume"}
                      </Button>
                    )}
                  {app ? (
                    <Link to={`/applications/${app.id}`} className="button-link">
                      View role <ArrowUpRight size={16} />
                    </Link>
                  ) : (
                    <a
                      href={job.apply_url}
                      target="_blank"
                      rel="noreferrer"
                      className="button-link"
                    >
                      View listing <ArrowUpRight size={16} />
                    </a>
                  )}
                </div>
              </article>
            );
          })}
          {query.data?.length === 0 && (
            <div className="panel col-span-full muted">
              No jobs match these filters. Start a search or adjust the filters.
            </div>
          )}
        </div>
      )}
    </>
  );
}

function DraggableCard({ application }: { application: Application }) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: application.id,
  });
  return (
    <div
      ref={setNodeRef}
      style={{
        transform: transform ? `translate3d(${transform.x}px,${transform.y}px,0)` : undefined,
        opacity: isDragging ? 0.55 : 1,
        zIndex: isDragging ? 10 : 0,
      }}
      className="kanban-card"
    >
      <div className="flex justify-between">
        <Link to={`/applications/${application.id}`} className="font-medium text-sm">
          {application.job.title}
        </Link>
        <button aria-label={`Move ${application.job.title}`} {...attributes} {...listeners}>
          <GripVertical size={15} />
        </button>
      </div>
      <p className="muted text-sm mt-2">{application.job.company}</p>
      {application.auto_apply?.reasons[0] && (
        <p className="text-sm mt-2">{application.auto_apply.reasons[0]}</p>
      )}
      <div className="mt-4 flex justify-between">
        <span className="text-emerald-500 text-sm">
          {application.job.match_score?.toFixed(0) ?? "—"}% fit
        </span>
        {application.job.is_demo && <span className="muted text-sm">Demo</span>}
      </div>
    </div>
  );
}
function Column({ status, items }: { status: string; items: Application[] }) {
  const { setNodeRef, isOver } = useDroppable({ id: status });
  return (
    <section
      ref={setNodeRef}
      className={`kanban-column ${isOver ? "ring-1 ring-emerald-500" : ""}`}
    >
      <h2 className="flex justify-between text-sm font-semibold mb-4">
        {human(status)}
        <span className="muted">{items.length}</span>
      </h2>
      {items.map((a) => (
        <DraggableCard key={a.id} application={a} />
      ))}
    </section>
  );
}

function GmailSuggestions() {
  const { api, toast } = useSession();
  const client = useQueryClient();
  const [suggestions, setSuggestions] = useState<
    {
      application_id: string;
      company: string;
      suggested_status: string;
      subject: string;
      message_id: string;
    }[]
  >([]);
  const [loading, setLoading] = useState(false);
  async function scan() {
    setLoading(true);
    try {
      const rows = await api.post<typeof suggestions>("/gmail/suggestions");
      setSuggestions(rows);
      toast(
        rows.length
          ? "Review the suggested updates below"
          : "No unambiguous status suggestions found",
      );
    } catch (error) {
      toast((error as Error).message);
    } finally {
      setLoading(false);
    }
  }
  return (
    <div className="mb-5">
      <Button variant="outline" disabled={loading} onClick={scan}>
        {loading ? "Reading…" : "Check Gmail updates"}
      </Button>
      {suggestions.map((row) => (
        <div
          className="panel mt-3 flex flex-wrap items-center justify-between gap-4 text-sm"
          key={row.message_id}
        >
          <div>
            <strong>
              {row.company}: {human(row.suggested_status)}
            </strong>
            <p className="muted text-sm mt-1">{row.subject}</p>
          </div>
          <Button
            variant="outline"
            onClick={async () => {
              try {
                await api.patch(`/applications/${row.application_id}`, {
                  status: row.suggested_status,
                  note: "User confirmed Gmail suggestion",
                });
                setSuggestions((old) => old.filter((item) => item.message_id !== row.message_id));
                toast("Status confirmed");
                await client.invalidateQueries();
              } catch (error) {
                toast((error as Error).message);
              }
            }}
          >
            Confirm update
          </Button>
        </div>
      ))}
    </div>
  );
}

export function Applications({ review = false }: { review?: boolean }) {
  const { api, toast } = useSession();
  const client = useQueryClient();
  const [kanban, setKanban] = useState(false);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const query = useQuery({
    queryKey: ["applications"],
    queryFn: () => api.applications(),
    refetchInterval: 5000,
  });
  const mutation = useMutation({
    mutationFn: ({ application, next }: { application: Application; next: string }) =>
      api.patch(`/applications/${application.id}`, {
        status: next,
        expected_status: application.status,
      }),
    onMutate: async ({ application, next }) => {
      await client.cancelQueries({ queryKey: ["applications"] });
      const previous = client.getQueryData<Application[]>(["applications"]);
      client.setQueryData<Application[]>(["applications"], (old) =>
        old?.map((a) => (a.id === application.id ? { ...a, status: next } : a)),
      );
      return { previous };
    },
    onError: (error, _variables, context) => {
      client.setQueryData(["applications"], context?.previous);
      toast(error.message);
    },
    onSettled: () => client.invalidateQueries({ queryKey: ["applications"] }),
  });
  const items = (query.data ?? []).filter(
    (a) =>
      (!review || ["awaiting_approval", "needs_human_review"].includes(a.status)) &&
      (!status || a.status === status) &&
      `${a.job.company} ${a.job.title}`.toLowerCase().includes(q.toLowerCase()),
  );
  const columns = [
    "new",
    "shortlisted",
    "awaiting_approval",
    "approved",
    "applied",
    "viewed",
    "interview_scheduled",
    "offer",
    "rejected",
    "needs_human_review",
    "failed",
    "skipped",
  ];
  function move(event: DragEndEvent) {
    const application = query.data?.find((a) => a.id === event.active.id);
    const next = String(event.over?.id ?? "");
    if (application && next && next !== application.status) mutation.mutate({ application, next });
  }
  return (
    <>
      <PageTitle
        label={review ? "HUMAN CHECKPOINT" : "YOUR APPLICATIONS"}
        title={review ? "Applications that need your help" : "Your applications"}
        description={
          review
            ? "Compare the original and tailored resume before approving a bundle."
            : "A clear record of every role, decision, and conversation."
        }
      >
        <Button variant="outline" onClick={() => setKanban(!kanban)}>
          {kanban ? "Table view" : "Board view"}
        </Button>
      </PageTitle>
      <div className="filters">
        <input
          className="input flex-1"
          aria-label="Search applications"
          placeholder="Search applications"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <select
          className="input"
          aria-label="Application status filter"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        >
          <option value="">All stages</option>
          {columns.map((s) => (
            <option key={s} value={s}>
              {human(s)}
            </option>
          ))}
        </select>
        <span className="muted text-sm">{items.length} applications</span>
      </div>
      {!review && <GmailSuggestions />}
      <ErrorBox error={query.error} />
      {query.isPending ? (
        <Loading />
      ) : kanban ? (
        <DndContext onDragEnd={move}>
          <div className="kanban">
            {columns.map((s) => (
              <Column key={s} status={s} items={items.filter((a) => a.status === s)} />
            ))}
          </div>
        </DndContext>
      ) : (
        <section className="panel overflow-x-auto">
          <table className="data-table">
            <thead>
              <tr>
                <th>Role & company</th>
                <th>Location</th>
                <th>Fit</th>
                <th>Status</th>
                <th>Applied</th>
                <th>Next step</th>
              </tr>
            </thead>
            <tbody>
              {items.map((a) => (
                <tr key={a.id}>
                  <td>
                    <Link to={`/applications/${a.id}`} className="font-medium">
                      {a.job.title}
                    </Link>
                    <div className="muted text-sm mt-1">
                      {a.job.company}
                      {a.job.is_demo ? " · Demo" : ""}
                    </div>
                    {a.auto_apply?.reasons[0] && (
                      <p className="text-sm mt-2 max-w-sm">{a.auto_apply.reasons[0]}</p>
                    )}
                  </td>
                  <td className="muted">{a.job.location}</td>
                  <td className="text-emerald-500 font-medium">
                    {a.job.match_score?.toFixed(0) ?? "—"}
                  </td>
                  <td>
                    <Badge value={a.status} />
                  </td>
                  <td className="muted">
                    <DateLabel value={a.applied_at} />
                  </td>
                  <td>
                    <select
                      className="input text-sm max-w-44"
                      aria-label={`Change status for ${a.job.title}`}
                      value=""
                      disabled={mutation.isPending}
                      onChange={(e) => {
                        if (e.target.value)
                          mutation.mutate({ application: a, next: e.target.value });
                      }}
                    >
                      <option value="">Update stage…</option>
                      {a.allowed_statuses.map((s) => (
                        <option key={s} value={s}>
                          {human(s)}
                        </option>
                      ))}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!items.length && (
            <p className="muted py-10 text-center">
              {review
                ? "The review queue is clear. Run the pipeline to prepare new bundles."
                : "No applications match your search."}
            </p>
          )}
        </section>
      )}
    </>
  );
}

export function ApplicationDetail() {
  const { id = "" } = useParams();
  const { api, toast } = useSession();
  const client = useQueryClient();
  const [notes, setNotes] = useState<string | null>(null);
  const [draft, setDraft] = useState<string | null>(null);
  const query = useQuery({ queryKey: ["application", id], queryFn: () => api.detail(id) });

  async function action(path: string, body: unknown = {}) {
    try {
      await api.post(`/applications/${id}/${path}`, body);
      toast(human(path) + " saved");
      await client.invalidateQueries();
    } catch (error) {
      toast((error as Error).message);
    }
  }
  const a = query.data;
  if (query.isPending) return <Loading />;
  if (!a) return <ErrorBox error={query.error} />;
  return (
    <>
      <Link to="/applications" className="muted text-sm">
        ← Applications
      </Link>
      <PageTitle
        label={a.job.company}
        title={a.job.title}
        description={`${a.job.location} · ${a.job.source} · ${a.job.match_score?.toFixed(0) ?? "—"}% match`}
      >
        <Badge value={a.status} />
      </PageTitle>
      {a.auto_apply && a.auto_apply.state !== "finished" && (
        <section className="panel mb-6" aria-label="Application next steps">
          <h2 className="font-semibold">
            {a.auto_apply.eligible ? "Ready for automatic application" : "What happens next"}
          </h2>
          {a.auto_apply.eligible ? (
            <p className="muted mt-2">
              Your checked resume is eligible for the next automatic submission stage. Daily limits
              still apply.
            </p>
          ) : (
            <ul className="mt-3 list-disc pl-5 space-y-2">
              {a.auto_apply.reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          )}
          {!a.auto_apply.eligible && (
            <div className="flex flex-wrap gap-3 mt-4">
              <Link className="button-link mt-4" to="/settings">
                My preferences
              </Link>
              <Link className="button-link mt-4" to="/advanced#screening-answers">
                Add my application answers
              </Link>
            </div>
          )}
        </section>
      )}
      <div className="flex flex-wrap gap-3 mb-6">
        {a.status === "awaiting_approval" && (
          <>
            <Button onClick={() => action("approve")}>
              <Check size={16} />
              Approve bundle
            </Button>
            <Button variant="outline" onClick={() => action("reject")}>
              <X size={16} />
              Reject
            </Button>
          </>
        )}
        {[
          "awaiting_approval",
          "needs_human_review",
          "resume_ready",
          "approved",
          "shortlisted",
        ].includes(a.status) && (
          <Button variant="outline" onClick={() => action("rerender")}>
            Regenerate
          </Button>
        )}
        {a.resume_path &&
          ["pdf", "docx", "report", "cover_note"].map((kind) => (
            <Button
              variant="outline"
              key={kind}
              onClick={() =>
                api
                  .download(
                    `/applications/${id}/files/${kind}`,
                    kind === "report"
                      ? "changes_report.md"
                      : kind === "cover_note"
                        ? "cover_note.txt"
                        : `resume.${kind}`,
                  )
                  .catch((e) => toast(e.message))
              }
            >
              <Download size={14} />
              {human(kind)}
            </Button>
          ))}
        {!a.job.is_demo && (
          <a href={a.job.apply_url} target="_blank" rel="noreferrer" className="button-link">
            Open application <ArrowUpRight size={15} />
          </a>
        )}
      </div>
      {a.status === "approved" && (
        <div className="panel mb-6 border-emerald-500/30">
          <p>
            Bundle approved.{" "}
            {a.job.is_demo
              ? "This fictional role is for testing."
              : "Download your tailored resume and open the job link to finish on the employer’s website. Confirm below only after the employer shows a successful submission."}
          </p>
          {!a.job.is_demo && (
            <>
              <Button
                className="mt-4"
                variant="outline"
                onClick={() => action("confirm-manual", { confirmed: true })}
              >
                I submitted this application successfully
              </Button>
            </>
          )}
        </div>
      )}
      <div className="detail-grid">
        <section className="panel">
          <div className="section-heading">
            <h2>Original evidence</h2>
            <span className="badge">MASTER RESUME</span>
          </div>
          <pre className="resume-preview">{a.master_resume}</pre>
        </section>
        <section className="panel">
          <div className="section-heading">
            <h2>Tailored resume</h2>
            <span className="badge badge-green">
              {a.critic_passed ? "CRITIC PASSED" : "REVIEW REQUIRED"}
            </span>
          </div>
          <pre className="resume-preview">
            {a.tailored_resume ?? "Run tailoring to create a resume for this role."}
          </pre>
        </section>
      </div>
      <div className="detail-grid mt-6">
        <section className="panel">
          <h2 className="mb-4 font-semibold">Independent critic</h2>
          <pre className="text-sm whitespace-pre-wrap muted">
            {JSON.stringify(a.critic_report, null, 2)}
          </pre>
          <h2 className="mt-6 mb-3 font-semibold">What changed</h2>
          <pre className="text-sm whitespace-pre-wrap muted">{a.changes ?? "No changes yet."}</pre>
        </section>
        <section className="panel">
          <h2 className="mb-4 font-semibold">Job description</h2>
          <p className="whitespace-pre-wrap text-sm muted leading-relaxed">{a.job.description}</p>
          <div className="mt-5 flex flex-wrap gap-2">
            {a.job.missing_skills.map((s) => (
              <span className="badge badge-red" key={s}>
                Gap: {s}
              </span>
            ))}
          </div>
        </section>
      </div>
      <div className="detail-grid mt-6">
        <section className="panel">
          <h2 className="mb-4 font-semibold">Notes & follow-up</h2>
          <textarea
            className="input min-h-28 w-full"
            aria-label="Application notes"
            value={notes ?? a.notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Keep interview notes and next steps here…"
          />
          <Button
            className="mt-3"
            variant="outline"
            onClick={async () => {
              try {
                await api.patch(`/applications/${id}`, { notes: notes ?? a.notes });
                toast("Notes saved");
                await client.invalidateQueries();
              } catch (error) {
                toast((error as Error).message);
              }
            }}
          >
            Save notes
          </Button>
          <p className="muted text-sm mt-6 mb-3">
            Follow-up due: <DateLabel value={a.follow_up_date} />. Drafts are never sent
            automatically.
          </p>
          <textarea
            aria-label="Follow-up draft"
            className="input min-h-32 w-full"
            value={draft ?? a.follow_up_draft ?? ""}
            onChange={(e) => setDraft(e.target.value)}
          />
          <div className="mt-3 flex gap-3">
            <Button
              variant="outline"
              onClick={() => action("followup", { draft: draft ?? a.follow_up_draft ?? "" })}
            >
              Save draft
            </Button>
            <Button
              disabled={!(draft ?? a.follow_up_draft)}
              onClick={() => action("followup", { approve: true })}
            >
              Approve draft
            </Button>
          </div>
          {a.follow_up_approved && (
            <p className="text-emerald-500 text-sm mt-3">Approved for you to copy and send.</p>
          )}
        </section>
        <section className="panel">
          <h2 className="mb-5 font-semibold">Application timeline</h2>
          {a.timeline.map((item) => (
            <div className="timeline-event" key={item.id}>
              <span className="status-dot" />
              <div>
                <Badge value={item.new_status} />
                <p className="muted text-sm mt-2">{item.note}</p>
                <time className="muted text-sm">
                  {new Date(item.changed_at).toLocaleString()} · {item.source}
                </time>
              </div>
            </div>
          ))}
        </section>
      </div>
    </>
  );
}

const stages = [
  "profile",
  "scout",
  "dedup",
  "jd_analyst",
  "matcher",
  "tailor",
  "critic",
  "approval",
  "tracker",
  "followup",
];
export function Activity() {
  const { api, toast } = useSession();
  const client = useQueryClient();
  const [selected, setSelected] = useState("");
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => api.runs(), refetchInterval: 2000 });
  const agents = useQuery({
    queryKey: ["agents"],
    queryFn: () => api.request<Agent[]>("/agents"),
    refetchInterval: 2000,
  });
  const run = selected || runs.data?.[0]?.id || "";
  const current = runs.data?.find((r) => r.id === run);
  useEffect(() => {
    if (!run) return;
    const controller = new AbortController();
    api
      .events(
        run,
        (event) => setEvents((old) => (old.some((e) => e.id === event.id) ? old : [...old, event])),
        controller.signal,
      )
      .catch((error) => {
        if (error.name !== "AbortError") toast(error.message);
      });
    return () => controller.abort();
  }, [api, run, toast]);
  const nodes: Node[] = stages.map((name, index) => {
    const last = events
      .filter((e) => String((e as AgentEvent & { run_id?: string }).run_id) === run)
      .filter((e) => e.step === name || e.step.startsWith(name + ":"))
      .at(-1);
    const active = last?.message === "Started";
    return {
      id: name,
      position: { x: (index % 5) * 185, y: Math.floor(index / 5) * 110 },
      data: { label: human(name) },
      style: {
        width: 160,
        background: active ? "hsl(var(--accent-surface))" : "var(--graph-node)",
        fontSize: 15,
        color: "var(--graph-text)",
        border: `1px solid ${last?.message === "failed" ? "#ef4444" : last ? "#10b981" : "var(--chart-grid)"}`,
        borderRadius: 10,
        padding: 14,
      },
    };
  });
  async function control(action: string) {
    try {
      await api.post(`/runs/${run}/${action}`);
      toast(`Run ${action} requested`);
      await client.invalidateQueries();
    } catch (error) {
      toast((error as Error).message);
    }
  }
  const runEvents = events.filter(
    (e) => String((e as AgentEvent & { run_id?: string }).run_id) === run,
  );
  return (
    <>
      <PageTitle
        label="AGENT ACTIVITY"
        title="What your search is doing"
        description="Watch discovery, analysis, and preparation unfold in your workspace."
      />
      <ErrorBox error={runs.error} />
      <div className="filters">
        <select
          aria-label="Select pipeline run"
          className="input flex-1"
          value={run}
          onChange={(e) => setSelected(e.target.value)}
        >
          <option value="">Choose a run</option>
          {runs.data?.map((r) => (
            <option key={r.id} value={r.id}>
              {new Date(r.started_at).toLocaleString()} · {r.options.demo ? "Demo" : "Live"} ·{" "}
              {r.status}
            </option>
          ))}
        </select>
        {current && <Badge value={current.status} />}
        <Button variant="outline" disabled={!run} onClick={() => control("pause")}>
          Pause
        </Button>
        <Button variant="outline" disabled={!run} onClick={() => control("resume")}>
          Resume
        </Button>
        <Button variant="outline" disabled={!run} onClick={() => control("stop")}>
          Stop
        </Button>
      </div>
      {current?.error && <div className="panel text-red-500 mb-5">{current.error}</div>}
      <section className="panel h-80 p-0 overflow-hidden">
        <ReactFlow
          nodes={nodes}
          edges={stages.slice(1).map((name, i) => ({
            id: `${i}`,
            source: stages[i],
            target: name,
            animated: current?.status === "running",
            style: { stroke: "#10b981" },
          }))}
          fitView
          nodesDraggable={false}
          nodesConnectable={false}
        >
          <Background color="var(--chart-grid)" gap={20} />
          <Controls showInteractive={false} />
        </ReactFlow>
      </section>
      <div className="detail-grid mt-6">
        <section className="panel">
          <h2 className="font-semibold mb-4">Live event stream</h2>
          <div className="event-feed">
            {runEvents.map((e) => (
              <div className="event-line" key={e.id}>
                <time className="muted text-sm">{new Date(e.timestamp).toLocaleTimeString()}</time>
                <span className="text-emerald-500 text-sm">{e.step}</span>
                <span className="text-sm">{e.message}</span>
              </div>
            ))}
            {!runEvents.length && (
              <p className="muted text-sm">Run the pipeline to see agent events here.</p>
            )}
          </div>
        </section>
        <section className="panel">
          <h2 className="font-semibold mb-4">Agent health & usage</h2>
          <table className="data-table text-sm">
            <thead>
              <tr>
                <th>Agent</th>
                <th>State</th>
                <th>Tokens</th>
                <th>Cost</th>
              </tr>
            </thead>
            <tbody>
              {agents.data?.map((a) => (
                <tr key={a.name}>
                  <td>{human(a.name)}</td>
                  <td>
                    <Badge value={a.status} />
                  </td>
                  <td>{a.input_tokens + a.output_tokens}</td>
                  <td>${a.cost_usd.toFixed(4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
      <section className="panel mt-6">
        <h2 className="font-semibold mb-4">Run history</h2>
        <div className="space-y-3">
          {runs.data?.map((r) => (
            <RunRow key={r.id} run={r} onClick={() => setSelected(r.id)} />
          ))}
        </div>
      </section>
    </>
  );
}
function RunRow({ run, onClick }: { run: Run; onClick: () => void }) {
  return (
    <button
      className="flex w-full items-center justify-between border-b border-border pb-3 text-sm text-left"
      onClick={onClick}
    >
      <span>
        {new Date(run.started_at).toLocaleString()}
        <small className="muted ml-3">
          {run.options.demo ? "Demo" : "Real sources"} · {run.dry_run ? "Dry run" : "Approval mode"}
        </small>
      </span>
      <Badge value={run.status} />
    </button>
  );
}

const sources = [
  "adzuna",
  "remotive",
  "remoteok",
  "wwr",
  "himalayas",
  "greenhouse",
  "lever",
  "ashby",
  "recruitee",
  "linkedin",
  "naukri",
  "indeed",
];
export function SettingsPage() {
  const { api } = useSession();
  const location = useLocation();
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api.settings() });
  useEffect(() => {
    if (settings.data && location.hash === "#screening-answers") {
      document.getElementById("screening-answers")?.scrollIntoView({ block: "center" });
    }
  }, [settings.data, location.hash]);
  if (settings.isPending) return <Loading />;
  if (!settings.data) return <ErrorBox error={settings.error} />;
  return <SettingsForm initial={settings.data} />;
}
function SettingsForm({ initial }: { initial: import("./api/client").Settings }) {
  const { api, toast } = useSession();
  const client = useQueryClient();
  const settings = { data: initial, error: null, isPending: false };
  const [roles, setRoles] = useState(initial.target_roles.join(", "));
  const [locations, setLocations] = useState(initial.locations.join(", "));
  const [threshold, setThreshold] = useState(initial.match_threshold);
  const [enabled, setEnabled] = useState<string[]>(initial.enabled_sources);
  const [aiProvider, setAiProvider] = useState(initial.ai_provider);
  const [liveEnabled, setLiveEnabled] = useState(initial.live_search_enabled);
  const [liveInterval, setLiveInterval] = useState(initial.live_search_interval_minutes);
  const live = useQuery({ queryKey: ["live"], queryFn: () => api.live(), refetchInterval: 5000 });
  const [advanced, setAdvanced] = useState(
    JSON.stringify(
      {
        agent_models: initial.agent_models,
        model_prices_per_million: initial.model_prices_per_million,
        boards: initial.boards,
        public_search: initial.public_search,
        max_run_tokens: initial.max_run_tokens,
        max_day_tokens: initial.max_day_tokens,
        max_run_cost_usd: initial.max_run_cost_usd,
        max_day_cost_usd: initial.max_day_cost_usd,
        embedding_backend: initial.embedding_backend,
        llm_free_tier: initial.llm_free_tier,
        llm_request_interval_seconds: initial.llm_request_interval_seconds,
        max_run_llm_calls: initial.max_run_llm_calls,
        max_day_llm_calls: initial.max_day_llm_calls,
      },
      null,
      2,
    ),
  );
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [secret, setSecret] = useState("");
  const [provider, setProvider] = useState("gemini");
  const [busy, setBusy] = useState(false);
  const answers = useQuery({
    queryKey: ["answers"],
    queryFn: () =>
      api.request<{ id: string; question: string; answer: string }[]>("/screening-answers"),
  });

  async function save() {
    setBusy(true);
    try {
      await api.patch("/settings", {
        ai_provider: aiProvider,
        live_search_enabled: liveEnabled,
        live_search_interval_minutes: liveInterval,
        target_roles: roles
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        locations: locations
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        match_threshold: threshold,
        enabled_sources: enabled,
        ...JSON.parse(advanced),
      });
      toast("Settings saved");
      await client.invalidateQueries();
    } catch (error) {
      toast((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function upload(file: File) {
    setBusy(true);
    const form = new FormData();
    form.append("file", file);
    try {
      await api.request("/profile/import", { method: "POST", body: form });
      toast("Resume imported. Your evidence is ready.");
      await client.invalidateQueries();
    } catch (error) {
      toast((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <PageTitle
        label="YOUR PREFERENCES"
        title="A search that fits you."
        description="Your resume, target roles, sources, and agent preferences."
      />
      <ErrorBox error={settings.error} />
      {settings.isPending ? (
        <Loading />
      ) : (
        <>
          <section className="panel mb-6">
            <div className="section-heading">
              <h2>Continuous real job search</h2>
              <Badge
                value={
                  live.data?.scheduler?.running && live.data.scheduler.enabled ? "running" : "idle"
                }
              />
            </div>
            <div className="flex flex-wrap items-center gap-5 text-sm">
              <label className="flex gap-2">
                <input
                  type="checkbox"
                  checked={liveEnabled}
                  onChange={(e) => setLiveEnabled(e.target.checked)}
                />
                Search automatically
              </label>
              <label>
                Interval (minutes)
                <input
                  aria-label="Search interval"
                  className="input ml-3 w-24"
                  type="number"
                  min="30"
                  max="1440"
                  value={liveInterval}
                  onChange={(e) => setLiveInterval(Number(e.target.value))}
                />
              </label>
            </div>
            <p className="muted text-sm mt-4">
              Next check:{" "}
              {live.data?.scheduler?.next_search_at
                ? new Date(live.data.scheduler.next_search_at).toLocaleString()
                : "Automatic searches disabled"}
              .{" "}
              {settings.data?.cloud
                ? "Searches run in the cloud, even when this computer is off."
                : "The computer and Docker services must stay running."}{" "}
              Sources refresh on their own schedules.
            </p>
            <div className="flex flex-wrap gap-2 mt-4">
              {live.data?.sources?.map((source) => (
                <span
                  title={source.message ?? "Connected public source"}
                  key={source.name}
                  className="badge"
                >
                  {human(source.name)}: {source.ready ? "Ready" : source.message}
                </span>
              ))}
            </div>
          </section>
          <section className="panel mb-6">
            <div className="section-heading">
              <h2>Master resume</h2>
              <Badge value={settings.data?.profile.imported ? "imported" : "not_imported"} />
            </div>
            <p className="muted text-sm mb-4">
              Upload your actual PDF, DOCX, or text resume for evidence-based matching and
              preparation.
            </p>
            <input
              type="file"
              aria-label="Import resume"
              accept=".pdf,.docx,.txt,.md"
              disabled={busy}
              onChange={(e) => {
                if (e.target.files?.[0]) void upload(e.target.files[0]);
              }}
            />
            {settings.data?.profile.imported && (
              <p className="text-emerald-500 text-sm mt-4">
                {settings.data.profile.name} · {settings.data.profile.skills?.join(", ")}
              </p>
            )}
          </section>
          <div className="detail-grid">
            <section className="panel space-y-5">
              <h2 className="font-semibold">Search preferences</h2>
              <label className="block text-sm">
                Target roles
                <input
                  className="input w-full mt-2"
                  value={roles}
                  onChange={(e) => setRoles(e.target.value)}
                />
              </label>
              <label className="block text-sm">
                Preferred cities
                <input
                  className="input w-full mt-2"
                  value={locations}
                  onChange={(e) => setLocations(e.target.value)}
                />
              </label>
              <label className="block text-sm">
                Minimum fit: {threshold}
                <input
                  type="range"
                  min="0"
                  max="100"
                  className="block w-full mt-3 accent-emerald-500"
                  value={threshold}
                  onChange={(e) => setThreshold(Number(e.target.value))}
                />
              </label>
              <p className="muted text-sm">
                New searches accept postings from the last 24 hours and roles requiring at most 2
                years of experience.
              </p>
              <h2 className="font-semibold">Enabled sources</h2>
              <div className="grid grid-cols-2 gap-3 text-sm">
                {sources.map((s) => (
                  <label className="flex gap-2 items-center" key={s}>
                    <input
                      type="checkbox"
                      checked={enabled.includes(s)}
                      onChange={(e) =>
                        setEnabled(
                          e.target.checked ? [...enabled, s] : enabled.filter((x) => x !== s),
                        )
                      }
                    />
                    {human(s)}
                  </label>
                ))}
              </div>
              <p className="muted text-sm">
                Employer boards need company slugs below. Public page sources run only on configured
                URLs and stop at login or CAPTCHA walls.
              </p>
            </section>
            <section className="panel">
              <h2 className="font-semibold mb-4">AI processing</h2>
              <select
                aria-label="AI provider"
                className="input w-full mb-3"
                value={aiProvider}
                onChange={(e) => {
                  const value = e.target.value as typeof aiProvider;
                  setAiProvider(value);
                  if (value === "local") return;
                  try {
                    const data = JSON.parse(advanced);
                    const model =
                      value === "gemini" ? "gemini-3.5-flash-lite" : "claude-sonnet-4-6";
                    data.agent_models = {
                      ...data.agent_models,
                      jd_analyst: model,
                      matcher: model,
                      tailor: model,
                      critic: model,
                    };
                    data.model_prices_per_million = {
                      ...data.model_prices_per_million,
                      [model]:
                        value === "gemini"
                          ? { input_usd: 0.3, output_usd: 2.5 }
                          : { input_usd: 3, output_usd: 15 },
                    };
                    data.llm_free_tier = value === "gemini";
                    setAdvanced(JSON.stringify(data, null, 2));
                  } catch {
                    toast("Fix the configuration JSON before changing model presets");
                  }
                }}
              >
                <option value="local">Local processing — no API key or API charges</option>
                <option value="gemini">Gemini — free-tier API key</option>
                <option value="anthropic">Anthropic — paid API key</option>
              </select>
              <p className="muted text-sm mb-5">
                Local processing uses MiniLM matching, extracted evidence and deterministic checks.
                Gemini adds model reasoning; create a free-project key in{" "}
                <a
                  className="text-emerald-500"
                  href="https://aistudio.google.com/api-keys"
                  target="_blank"
                  rel="noreferrer"
                >
                  Google AI Studio
                </a>
                . Free-tier quotas apply and content may be used to improve Google's products. Keep
                billing disabled if you want free-only usage; Lakshya's cost display cannot control
                Google billing.
              </p>
              <h2 className="font-semibold mb-4">Models, budgets & company boards</h2>
              <p className="muted text-sm mb-4">
                Set each agent's model ID and current input/output prices per million tokens before
                using remote AI. Request caps and pacing help keep within your free quota.
              </p>
              <textarea
                aria-label="Advanced configuration"
                spellCheck={false}
                className="input config-editor w-full"
                value={advanced}
                onChange={(e) => setAdvanced(e.target.value)}
              />
            </section>
          </div>
          <Button className="mt-5" onClick={save} disabled={busy}>
            Save preferences
          </Button>
          <div className="detail-grid mt-6">
            <section className="panel">
              <h2 className="font-semibold mb-4">Private credentials</h2>
              <div className="flex flex-wrap gap-3 mb-4">
                {Object.entries(settings.data?.credential_status ?? {}).map(([name, value]) => (
                  <span className="badge" key={name}>
                    {human(name)}: {value ? "Configured" : "Missing"}
                  </span>
                ))}
              </div>
              <select
                aria-label="Credential provider"
                className="input mb-3 w-full"
                value={provider}
                onChange={(e) => setProvider(e.target.value)}
              >
                <option value="gemini">Gemini API key (free tier)</option>
                <option value="anthropic">Anthropic API key</option>
                <option value="adzuna_app_id">Adzuna app ID</option>
                <option value="adzuna_app_key">Adzuna app key</option>
              </select>
              <input
                type="password"
                autoComplete="off"
                aria-label="Private API credential"
                className="input w-full mb-3"
                value={secret}
                onChange={(e) => setSecret(e.target.value)}
                placeholder="Paste private key"
              />
              <Button
                disabled={!secret}
                variant="outline"
                onClick={async () => {
                  try {
                    await api.post("/settings/credentials", { provider, value: secret });
                    setSecret("");
                    toast("Credential stored privately");
                    await client.invalidateQueries();
                  } catch (error) {
                    toast((error as Error).message);
                  }
                }}
              >
                Save credential
              </Button>
              <p className="muted text-sm mt-4">
                Values are masked, stored privately, and never returned by the API.
              </p>
            </section>
            <section className="panel" id="screening-answers">
              <h2 className="font-semibold mb-4">Screening answers</h2>
              <p className="muted text-sm mb-4">
                Your own exact answers are reused for matching form labels. Unknown questions remain
                for your review.
              </p>
              <input
                aria-label="Screening question"
                className="input w-full mb-3"
                placeholder="Exact question or field label"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
              />
              <textarea
                aria-label="Screening answer"
                className="input w-full mb-3"
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
              />
              <Button
                variant="outline"
                disabled={!question || !answer}
                onClick={async () => {
                  try {
                    await api.request("/screening-answers", {
                      method: "PUT",
                      body: JSON.stringify({ question, answer }),
                    });
                    setQuestion("");
                    setAnswer("");
                    toast("Answer saved");
                    await client.invalidateQueries();
                  } catch (error) {
                    toast((error as Error).message);
                  }
                }}
              >
                Save answer
              </Button>
              <div className="mt-4 space-y-3">
                {answers.data?.map((a) => (
                  <div key={a.id} className="text-sm">
                    <strong>{a.question}</strong>
                    <p className="muted mt-1">{a.answer}</p>
                  </div>
                ))}
              </div>
            </section>
          </div>
        </>
      )}
    </>
  );
}
