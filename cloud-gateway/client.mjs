import { QueueClient } from "@vercel/queue";

export const queue = new QueueClient({ region: "sin1" });

export function backendURL(path) {
  const url = new URL(process.env.LAKSHYA_BACKEND_URL);
  if (url.protocol !== "https:" || url.username || url.password)
    throw new Error("Invalid service URL");
  url.pathname = path;
  return url;
}

export async function internal(path, body) {
  const response = await fetch(backendURL(`/internal/${path}`), {
    method: body === undefined ? "GET" : "POST",
    headers: {
      "content-type": "application/json",
      "x-lakshya-service": process.env.LAKSHYA_SERVICE_KEY,
    },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(270000),
  });
  if (!response.ok)
    throw new Error(`Cloud service returned ${response.status}`);
  return response.json();
}

export async function drainOutbox() {
  const commands = await internal("outbox");
  for (const command of commands) {
    await queue.send(
      "lakshya-work",
      { id: command.id },
      {
        idempotencyKey: command.id,
        delaySeconds: command.delay_seconds,
        retentionSeconds: 604800,
        region: "sin1",
      },
    );

    await internal("dispatched", { id: command.id });
  }
}
