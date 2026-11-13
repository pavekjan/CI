import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Vyvoj: `npm run dev` (port 5173) a v druhem okne `python server.py` (API na 8765).
export default defineConfig({
  plugins: [react()],
  base: "/",
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
  build: { outDir: "dist", chunkSizeWarningLimit: 1200 },
});
