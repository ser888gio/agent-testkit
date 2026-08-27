import { defineConfig } from "vite";
import type { ViteDevServer } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// index.html is not in the module graph the way a .tsx is, so editing it (the
// theme boot script, the shell) leaves the page stale until a manual reload.
// Watch it and push a full reload instead.
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

// base "/assets/" matches the StaticFiles mount agentaudit.web.app serves the
// built bundle from; dev requests are proxied to the FastAPI server instead.
export default defineConfig({
  plugins: [react(), tailwindcss(), reloadOnHtmlChange()],
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
