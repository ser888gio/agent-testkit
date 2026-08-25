import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// base "/assets/" matches the StaticFiles mount agentaudit.web.app serves the
// built bundle from; dev requests are proxied to the FastAPI server instead.
export default defineConfig({
  plugins: [react()],
  base: "/assets/",
  build: {
    outDir: "../agentaudit/web/spa_dist",
    emptyOutDir: true,
    // Empty so a URL is `/assets/<file>` — `base` already provides the
    // "assets" segment that matches app.py's StaticFiles mount.
    assetsDir: "",
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/static": "http://127.0.0.1:8000",
      "/login": "http://127.0.0.1:8000",
      "/logout": "http://127.0.0.1:8000",
      "/auth": "http://127.0.0.1:8000",
    },
  },
});
