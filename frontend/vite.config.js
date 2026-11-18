import { defineConfig } from "vite";

// Dev: proxy /api to the FastAPI backend so there's no CORS to configure.
// Build: writes frontend/dist, which the backend serves at / (see app/main.py).
export default defineConfig({
  server: {
    proxy: { "/api": "http://localhost:8000" },
  },
  build: {
    outDir: "dist",
  },
});
