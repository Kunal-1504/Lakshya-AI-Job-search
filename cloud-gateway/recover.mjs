import { timingSafeEqual } from "node:crypto";
import { drainOutbox, internal } from "./client.mjs";

export default async function recover(req, res) {
  const expected = Buffer.from(`Bearer ${process.env.CRON_SECRET}`);
  const actual = Buffer.from(req.headers.authorization || "");
  if (
    !process.env.CRON_SECRET ||
    actual.length !== expected.length ||
    !timingSafeEqual(actual, expected)
  ) {
    return res.status(401).json({ detail: "Unauthorized" });
  }
  await internal("recover", {});
  await drainOutbox();
  res.status(200).json({ ready: true });
}
