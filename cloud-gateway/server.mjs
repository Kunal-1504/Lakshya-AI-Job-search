import express from "express";
import gateway from "./gateway.mjs";
import recover from "./recover.mjs";

const app = express();
app.disable("x-powered-by");
app.get("/api/cloud-recover", recover);
app.use(
  "/api",
  express.raw({ type: () => true, limit: "4400kb" }),
  (req, res) => {
    req.lakshyaPath = req.path.replace(/^\//, "");
    return gateway(req, res);
  },
);
app.listen(Number(process.env.PORT || 3000));
export default app;
