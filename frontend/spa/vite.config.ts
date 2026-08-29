import { defineConfig } from "vite";
import type { ViteDevServer } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

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


export default defineConfig(({ command }) => ({
  plugins: [react(), tailwindcss(), reloadOnHtmlChange()],
  base: command === "build" ? "/assets/" : "/",
  build: {
    outDir: "../agentaudit/web/spa_dist",
    emptyOutDir: true,
    assetsDir: "",
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8001",
      "/static": "http://127.0.0.1:8001",
      "/login": "http://127.0.0.1:8001",
      "/logout": "http://127.0.0.1:8001",
      "/auth": "http://127.0.0.1:8001",
    },
  },
}));
