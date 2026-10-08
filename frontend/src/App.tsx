import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bell,
  Download,
  FileText,
  LayoutDashboard,
  ListChecks,
  LogOut,
  Moon,
  Play,
  Search,
  Settings as SettingsIcon,
  Sun,
  Target,
  Workflow,
} from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { BrowserRouter, Link, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { API, APIError, type User } from "./api/client";
import Auth from "./Auth";
import Setup from "./Setup";
import { Button } from "./components/ui/button";
import { Applications, ApplicationDetail, Jobs, Dashboard, Activity, SettingsPage } from "./pages";

const SessionContext = createContext<{ api: API; toast: (text: string) => void } | null>(null);
export function useSession() {
  const context = useContext(SessionContext);
  if (!context) throw new Error("Connect first");
  return context;
}
export function human(value: string) {
  return value.replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase());
}
export function Badge({ value }: { value: string }) {
  return (
    <span
      className={`badge ${["approved", "completed", "applied", "offer"].includes(value) ? "badge-green" : ["failed", "needs_human_review"].includes(value) ? "badge-red" : ""}`}
    >
      {human(value)}
    </span>
  );
}
export function Loading() {
  return (
    <div aria-label="Loading" className="grid gap-4 md:grid-cols-3">
      {[1, 2, 3].map((i) => (
        <div className="panel h-36 animate-pulse" key={i} />
      ))}
    </div>
  );
}
export function ErrorBox({ error }: { error: Error | null }) {
  return error ? (
    <div role="alert" className="panel border-red-500/40 text-red-500">
      {error.message}
    </div>
  ) : null;
}

function Workspace({
  api,
  disconnect,
  dark,
  toggle,
}: {
  api: API;
  disconnect: () => Promise<void>;
  dark: boolean;
  toggle: () => void;
}) {
  const { pathname } = useLocation();
  const [message, setMessage] = useState("");
  const [starting, setStarting] = useState(false);
  const [stageChoice, setStageChoice] = useState("auto");
  const [offline, setOffline] = useState(false);
  const [dryRun, setDryRun] = useState(false);
  const client = useQueryClient();
  const stats = useQuery({
    queryKey: ["stats"],
    queryFn: () => api.stats(),
    refetchInterval: 5000,
  });
  const live = useQuery({
    queryKey: ["live"],
    queryFn: () => api.live(),
    refetchInterval: 5000,
  });
  const toast = useCallback((text: string) => setMessage(text), []);
  useEffect(() => {
    if (!message) return;
    const timer = setTimeout(() => setMessage(""), 7000);
    return () => clearTimeout(timer);
  }, [message]);
  async function run() {
    setStarting(true);
    try {
      const stage =
        stageChoice === "auto" ? (live.data?.ai_pipeline_ready ? "all" : "scout") : stageChoice;
      const preferences = await api.settings();
      await api.post("/runs", {
        demo: false,
        offline,
        dry_run: dryRun,
        stage,
        auto: preferences.application_mode === "auto",
      });
      toast("Your search has started. Watch it in Search progress.");
      await client.invalidateQueries();
    } catch (error) {
      toast((error as Error).message);
    } finally {
      setStarting(false);
    }
  }
  const nav = [
    ["/", "Home", LayoutDashboard],
    ["/jobs", "Find jobs", Search],
    ["/review", "Needs your help", ListChecks],
    ["/applications", "Applications", Target],
    ["/activity", "Search progress", Workflow],
    ["/settings", "My preferences", SettingsIcon],
  ] as const;
  return (
    <SessionContext.Provider value={{ api, toast }}>
      <div className="shell">
        <aside className="sidebar">
          <Link to="/" className="brand">
            <span className="brand-mark">
              <Target size={25} />
            </span>
            <span>
              Lakshya<small>YOUR NEXT CHAPTER</small>
            </span>
          </Link>
          <div className="sidebar-label">WORKSPACE</div>
          <nav>
            {nav.map(([path, label, Icon]) => (
              <NavLink
                key={path}
                to={path}
                end={path === "/"}
                className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}
              >
                <Icon size={18} />
                {label}
                {path === "/review" && Boolean(stats.data?.review_queue) && (
                  <span className="nav-count">{stats.data?.review_queue}</span>
                )}
              </NavLink>
            ))}
          </nav>
          <div className="sidebar-bottom">
            <div className="safety">
              <span className="status-dot" />
              <div>
                You're in control
                <small>
                  Resumes use your real experience.
                  <br />
                  Automatic mode follows your preferences.
                </small>
              </div>
            </div>
            <Button
              aria-label="Sign out of workspace"
              variant="outline"
              onClick={() => void disconnect().catch((error) => toast(error.message))}
            >
              <LogOut size={16} />
              Sign out
            </Button>
          </div>
        </aside>
        <div className="workspace">
          <header className="topbar">
            <span className="muted text-sm">Find jobs. Tailor resumes. Apply.</span>
            <div className="flex items-center gap-3">
              <Link to="/review" aria-label="Review notifications">
                <Bell size={18} />
              </Link>
              <Button variant="outline" aria-label="Toggle color theme" onClick={toggle}>
                {dark ? <Sun size={18} /> : <Moon size={18} />}
              </Button>
              <Button
                variant="outline"
                aria-label="Sign out"
                onClick={() => void disconnect().catch((error) => toast(error.message))}
              >
                <LogOut size={17} />
              </Button>
            </div>
          </header>
          <main className="content">
            {pathname !== "/settings" && (
              <div className="run-strip">
                <div>
                  <div className="live-indicator">
                    <span className="status-dot" />
                    Live job search
                  </div>
                  <p className="live-caption">
                    {live.data?.scheduler?.enabled
                      ? `Checks every ${live.data.scheduler.interval_minutes} minutes`
                      : "On demand"}
                  </p>
                </div>
                <div className="run-options">
                  <select
                    className="input"
                    aria-label="Search workflow"
                    value={stageChoice}
                    onChange={(e) => setStageChoice(e.target.value)}
                  >
                    <option value="auto">
                      {live.data?.ai_pipeline_ready ? "Find jobs and prepare resumes" : "Find jobs"}
                    </option>
                    <option value="scout">Find jobs only</option>
                    <option value="all">Find matches and tailor resumes</option>
                  </select>
                  <details className="run-advanced">
                    <summary>Search options</summary>
                    <div className="run-toggles">
                      <label>
                        <input
                          type="checkbox"
                          checked={offline}
                          onChange={(e) => setOffline(e.target.checked)}
                        />
                        Local processing
                      </label>
                      <label>
                        <input
                          type="checkbox"
                          checked={dryRun}
                          onChange={(e) => setDryRun(e.target.checked)}
                        />
                        Prepare only
                      </label>
                    </div>
                  </details>
                  <Button onClick={run} disabled={starting}>
                    <Play size={14} />
                    {starting ? "Starting…" : "Search now"}
                  </Button>
                </div>
              </div>
            )}
            {pathname !== "/settings" && live.data && (live.data.requirements?.length ?? 0) > 0 && (
              <div className="setup-banner mb-6">
                <FileText size={28} aria-hidden="true" />
                <div className="setup-copy">
                  <strong>Finish your personal setup</strong>
                  <ul className="space-y-1">
                    {live.data.requirements.map((item) => (
                      <li key={item.id}>{item.message}</li>
                    ))}
                  </ul>
                </div>
                <Link to="/settings" className="button-link">
                  Set up my search →
                </Link>
              </div>
            )}
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/jobs" element={<Jobs />} />
              <Route path="/review" element={<Applications review />} />
              <Route path="/applications" element={<Applications />} />
              <Route path="/applications/:id" element={<ApplicationDetail />} />
              <Route path="/activity" element={<Activity />} />
              <Route path="/settings" element={<Setup />} />
              <Route path="/advanced" element={<SettingsPage />} />
            </Routes>
            <footer className="mt-10 flex items-center justify-between border-t border-border pt-5 text-sm text-muted-foreground">
              <span>Lakshya · Built around your evidence.</span>
              <button
                onClick={() =>
                  api
                    .download("/export", "lakshya-applications.xlsx")
                    .catch((e) => toast(e.message))
                }
                className="flex items-center gap-2"
              >
                <Download size={13} /> Export tracker
              </button>
            </footer>
          </main>
        </div>
        {message && (
          <div role="status" className="toast">
            {message}
            <button aria-label="Dismiss notification" onClick={() => setMessage("")}>
              ×
            </button>
          </div>
        )}
      </div>
    </SessionContext.Provider>
  );
}

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(true);
  const [serviceError, setServiceError] = useState("");
  const [dark, setDark] = useState(false);
  const client = useQueryClient();
  const api = useMemo(() => new API(), []);
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);
  useEffect(() => {
    api
      .request<User>("/auth/me")
      .then(setUser)
      .catch((error) => {
        setUser(null);
        if (!(error instanceof APIError && error.status === 401)) {
          setServiceError(
            error instanceof TypeError
              ? "We couldn’t connect to the server. Please try again."
              : error.message,
          );
        }
      })
      .finally(() => setChecking(false));
  }, [api]);
  useEffect(() => {
    const expired = () => {
      setUser(null);
      client.clear();
    };
    window.addEventListener("lakshya-session-expired", expired);
    return () => window.removeEventListener("lakshya-session-expired", expired);
  }, [client]);
  if (checking)
    return (
      <div className="login">
        <p>Opening your workspace…</p>
      </div>
    );
  if (!user) return <Auth onSuccess={setUser} serviceError={serviceError} />;
  return (
    <BrowserRouter>
      <Workspace
        api={api}
        dark={dark}
        toggle={() => setDark(!dark)}
        disconnect={async () => {
          await api.post("/auth/signout");
          setUser(null);
          client.clear();
        }}
      />
    </BrowserRouter>
  );
}
