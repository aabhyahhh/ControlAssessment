import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "path";

export default defineConfig({
  server: {
    host: "0.0.0.0",
    port: 8090,
    proxy: {
      "/api": {
        target: "http://localhost:4001",
        changeOrigin: false,
        proxyTimeout: 3600000,
        timeout: 3600000,
      },
    },
  },
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
