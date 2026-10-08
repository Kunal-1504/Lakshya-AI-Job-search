import { drainOutbox } from "./client.mjs";

// Server-only backend connection. Operator keys are never forwarded from public requests.
export default async function gateway(req, res) {
  res.setHeader("Cache-Control", "no-store");
  const configured = process.env.LAKSHYA_BACKEND_URL;
  if (!configured) {
    return res.status(503).json({
      detail:
        "Cloud setup is in progress. Sign-in will be available when it is complete.",
    });
  }
  const path =
    req.lakshyaPath ||
    (Array.isArray(req.query.path)
      ? req.query.path.join("/")
      : req.query.path || "");
  if (!/^[a-zA-Z0-9/_-]+$/.test(path) || path.includes("..")) {
    return res.status(400).json({ detail: "Invalid request path." });
  }
  const backend = new URL(configured);
  if (backend.protocol !== "https:" || backend.username || backend.password) {
    return res
      .status(503)
      .json({ detail: "Server configuration needs attention." });
  }
  backend.pathname = `/api/${path}`;
  const incoming = new URL(req.url, "https://localhost");
  incoming.searchParams.delete("path");
  backend.search = incoming.search;
  const headers = {};
  for (const key of ["content-type", "cookie", "origin", "sec-fetch-site"]) {
    if (req.headers[key]) headers[key] = req.headers[key];
  }
  if (process.env.LAKSHYA_SERVICE_KEY) {
    headers["x-lakshya-service"] = process.env.LAKSHYA_SERVICE_KEY;
    headers["x-lakshya-public-host"] = req.headers.host;
    // Vercel supplies the trusted client address; caller-supplied IP headers are ignored.
    headers["x-real-ip"] =
      req.headers["x-vercel-forwarded-for"] || req.socket?.remoteAddress || "";
  }
  try {
    let body;
    if (!["GET", "HEAD"].includes(req.method)) {
      if (req.body !== undefined) {
        body =
          typeof req.body === "string" || Buffer.isBuffer(req.body)
            ? req.body
            : JSON.stringify(req.body);
      } else {
        const chunks = [];
        for await (const chunk of req) chunks.push(chunk);
        body = Buffer.concat(chunks);
      }
    }
    const upstream = await fetch(backend, {
      method: req.method,
      headers,
      body,
      redirect: "manual",
    });
    if (
      process.env.LAKSHYA_SERVICE_KEY &&
      upstream.ok &&
      !path.endsWith("/events")
    ) {
      try {
        await drainOutbox();
      } catch {
        console.error("Cloud outbox remains pending for recovery");
      }
    }
    res.status(upstream.status);
    for (const key of ["content-type", "content-disposition"]) {
      const value = upstream.headers.get(key);
      if (value) res.setHeader(key, value);
    }
    const cookies = upstream.headers.getSetCookie();
    if (cookies.length) res.setHeader("Set-Cookie", cookies);
    if (upstream.body) {
      for await (const chunk of upstream.body) res.write(Buffer.from(chunk));
    }
    res.end();
  } catch {
    if (!res.headersSent)
      return res
        .status(502)
        .json({ detail: "We couldn’t reach the server. Please try again." });
    res.end();
  }
}
