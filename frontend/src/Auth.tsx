import { useState } from "react";
import { ArrowRight, Check, Target } from "lucide-react";
import { Button } from "./components/ui/button";
import { API, type User } from "./api/client";

export default function Auth({
  onSuccess,
  serviceError,
}: {
  onSuccess: (user: User) => void;
  serviceError?: string;
}) {
  const [signup, setSignup] = useState(false);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const user = await new API().post<User>(signup ? "/auth/signup" : "/auth/signin", {
        name,
        email,
        password,
      });
      setPassword("");
      if (signup) window.history.replaceState({}, "", "/settings");
      onSuccess(user);
    } catch (e) {
      setError(
        e instanceof TypeError ? "We couldn't connect. Please try again." : (e as Error).message,
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="login">
      <div className="login-copy">
        <div className="brand mb-10">
          <span className="brand-mark">
            <Target size={30} />
          </span>
          Lakshya
        </div>
        <p className="eyebrow">YOUR JOB SEARCH, MADE SIMPLE</p>
        <h1>
          Find a job.
          <br />
          <span className="text-emerald-500">We’ll handle the busywork.</span>
        </h1>
        <p className="muted mt-6 text-lg">
          Upload your resume once. Find matching jobs, get a resume tailored to each role, and keep
          track of your applications.
        </p>
        <div className="login-benefits mt-8">
          {[
            "Resumes tailored to each job description",
            "Automatic applications on supported job sites",
            "Your own private account and application history",
          ].map((text) => (
            <p key={text}>
              <Check size={19} />
              {text}
            </p>
          ))}
        </div>
      </div>
      <form className="panel login-form" onSubmit={submit}>
        <div className="auth-tabs mb-6">
          <button
            type="button"
            className={!signup ? "active" : ""}
            onClick={() => {
              setSignup(false);
              setError("");
            }}
          >
            Sign in
          </button>
          <button
            type="button"
            className={signup ? "active" : ""}
            onClick={() => {
              setSignup(true);
              setError("");
            }}
          >
            Sign up
          </button>
        </div>
        <h2 className="text-2xl font-semibold">
          {signup ? "Create your account" : "Welcome back"}
        </h2>
        <p className="muted mt-2 mb-6">
          {signup
            ? "Start your job search in a few simple steps."
            : "Sign in to continue your job search."}
        </p>
        {serviceError && (
          <div role="alert" className="mb-5">
            <p>{serviceError}</p>
            <Button
              type="button"
              variant="outline"
              className="mt-3"
              onClick={() => window.location.reload()}
            >
              Try again
            </Button>
          </div>
        )}
        {error && (
          <p role="alert" className="badge badge-red mb-4 w-full">
            {error}
          </p>
        )}
        {signup && (
          <label className="auth-field">
            Your name
            <input
              className="input"
              required
              disabled={!!serviceError}
              maxLength={100}
              autoComplete="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
        )}
        <label className="auth-field">
          Email address
          <input
            className="input"
            type="email"
            disabled={!!serviceError}
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        <label className="auth-field">
          Password
          <input
            className="input"
            type="password"
            disabled={!!serviceError}
            required
            minLength={12}
            maxLength={128}
            autoComplete={signup ? "new-password" : "current-password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {signup && (
          <p className="muted text-sm mb-5">Use at least 12 characters for your password.</p>
        )}
        <Button
          type="submit"
          aria-label={signup ? "Create my account" : "Sign in to my account"}
          className="w-full"
          disabled={busy || !!serviceError}
        >
          {busy ? "Please wait…" : signup ? "Create account" : "Sign in"}
          <ArrowRight size={16} />
        </Button>
        <p className="muted text-sm mt-5">
          {signup ? "Already have an account?" : "New to Lakshya?"}{" "}
          <button
            type="button"
            className="text-emerald-500 font-semibold"
            onClick={() => {
              setSignup(!signup);
              setError("");
            }}
          >
            {signup ? "Sign in" : "Create an account"}
          </button>
        </p>
      </form>
    </div>
  );
}
