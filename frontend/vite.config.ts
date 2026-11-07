import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// La compilation produit des fichiers statiques dans app/static/v2, servis par FastAPI.
// Omar n'a donc jamais besoin de Node.js : seul le développeur compile.
export default defineConfig({
  plugins: [react()],
  base: "/static/v2/",
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  build: { outDir: "../app/static/v2", emptyOutDir: true, sourcemap: false },
  server: {
    // En développement (npm run dev), les appels /api partent vers l'application Python.
    proxy: { "/api": "http://127.0.0.1:8765" },
  },
});
