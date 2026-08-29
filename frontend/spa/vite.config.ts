import { defineConfig } from "vite";
import type { ViteDevServer } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

declare const process: { env: Record<string, string | undefined> };

const API_URL = process.env.AGENTAUDIT_API_URL ?? "http://127.0.0.1:8000";
const PROXIED = ["/api", "/static", "/login", "/logout", "/auth"];

// index.html is not in the module graph, so editing it needs a full reload.
function reloadOnHtmlChange() {
  return {
    name: "reload-on-html-change",
    configureServer(server: ViteDevServer) {
      server.watcher.on("change", (file: string) => {
        if (file.endsWith(".html")) server.ws.send({ type: "full-reload" });
      });
    },
  };
}

// base "/assets/" matches app.py's StaticFiles mount, but only for a build --
// in dev it would host the app at :5173/assets/.
export default defineConfig(({ command }) => ({
  plugins: [react(), tailwindcss(), reloadOnHtmlChange()],
  base: command === "build" ? "/assets/" : "/",
  build: {
    outDir: "../agentaudit/web/spa_dist",
    emptyOutDir: true,
    assetsDir: "",
  },
  server: {
    proxy: Object.fromEntries(PROXIED.map((path) => [path, API_URL])),
  },
}));
