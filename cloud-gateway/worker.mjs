import express from "express";
import consume from "./consume.mjs";

const app = express();
app.disable("x-powered-by");
app.use(express.json());
app.post("/{*path}", consume);
app.listen(Number(process.env.PORT || 3000));
export default app;
