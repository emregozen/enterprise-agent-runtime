import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: "0.0.0.0",
    port: 8842,
    proxy: {
      "/backend": {
        target: "http://127.0.0.1:8841",
        rewrite: (path) => path.replace(/^\/backend/, ""),
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
  },
});
