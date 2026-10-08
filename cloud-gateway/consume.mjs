import { drainOutbox, internal, queue } from "./client.mjs";

export default queue.handleNodeCallback(
  async (message) => {
    await internal("step", { id: message.id });
    await drainOutbox();
  },
  { visibilityTimeoutSeconds: 300 },
);
