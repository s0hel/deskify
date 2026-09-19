import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      input: { main: "index.html", spike: "spike.html" },
      output: {
        // Route-level splitting: the admin console must not ship in the
        // employee cold-start path (TDD §10.1).
        manualChunks: { admin: ["./src/admin/AdminConsole.tsx"] },
      },
    },
  },
  test: { environment: "jsdom", globals: true },
});
