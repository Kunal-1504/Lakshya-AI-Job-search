import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import App from "./App";

export default function Root() {
  const [client] = useState(
    () => new QueryClient({ defaultOptions: { queries: { retry: false } } }),
  );
  return (
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>
  );
}
