import test from "node:test";
import assert from "node:assert/strict";
import gateway from "../gateway.mjs";
import consume from "../consume.mjs";

function response() {
  return {
    headers: {},
    statusCode: 200,
    chunks: [],
    setHeader(k, v) {
      this.headers[k] = v;
    },
    status(n) {
      this.statusCode = n;
      return this;
    },
    json(v) {
      this.value = v;
      return this;
    },
    write(v) {
      this.chunks.push(v);
    },
    end() {
      this.ended = true;
    },
  };
}

test("API and queue modules export real handlers", () => {
  assert.equal(typeof gateway, "function");
  assert.equal(typeof consume, "function");
});

test("missing cloud config gives a readable setup response", async () => {
  delete process.env.LAKSHYA_BACKEND_URL;
  const res = response();
  await gateway({ query: { path: "auth/me" } }, res);
  assert.equal(res.statusCode, 503);
  assert.match(res.value.detail, /setup/);
});

test("multipart resume, session cookie and server identity survive the gateway", async () => {
  process.env.LAKSHYA_BACKEND_URL = "https://private.example.invalid";
  process.env.LAKSHYA_SERVICE_KEY = "synthetic-service-key";
  const previous = globalThis.fetch;
  const bytes = Buffer.from("--boundary\r\nsynthetic resume\r\n--boundary--");
  let forwarded;
  globalThis.fetch = async (url, init) => {
    if (new URL(url).pathname === "/internal/outbox") return Response.json([]);
    forwarded = init;
    return Response.json(
      { imported: true },
      {
        headers: {
          "set-cookie":
            "lakshya_session=fixture; HttpOnly; Secure; SameSite=Lax",
        },
      },
    );
  };
  try {
    const res = response();
    await gateway(
      {
        method: "POST",
        url: "/profile/import",
        lakshyaPath: "profile/import",
        query: {},
        body: bytes,
        headers: {
          host: "jobs.example.invalid",
          origin: "https://jobs.example.invalid",
          cookie: "lakshya_session=fixture",
          "content-type": "multipart/form-data; boundary=boundary",
          "x-api-key": "must-never-forward",
          "x-real-ip": "untrusted",
          "x-vercel-forwarded-for": "203.0.113.5",
        },
      },
      res,
    );
    assert.equal(res.statusCode, 200);
    assert.equal(forwarded.body, bytes);
    assert.equal(forwarded.headers["x-api-key"], undefined);
    assert.equal(forwarded.headers["x-real-ip"], "203.0.113.5");
    assert.equal(
      forwarded.headers["x-lakshya-public-host"],
      "jobs.example.invalid",
    );
    assert.equal(forwarded.headers.cookie, "lakshya_session=fixture");
    assert.match(res.headers["Set-Cookie"][0], /HttpOnly/);
    assert.deepEqual(JSON.parse(Buffer.concat(res.chunks)), { imported: true });
  } finally {
    globalThis.fetch = previous;
  }
});

test("path traversal is rejected before reaching the private service", async () => {
  const res = response();
  await gateway({ query: { path: "../internal/step" } }, res);
  assert.equal(res.statusCode, 400);
});
