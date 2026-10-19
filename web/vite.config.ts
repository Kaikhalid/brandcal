import { resolve } from "node:path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

// https://vite.dev/config/
export default defineConfig({
  // Served from the site root by `brandcal serve` (wiring comes in a later step).
  base: "/",
  build: {
    // Built static assets land inside the Python package so they can ship as package data.
    outDir: resolve(import.meta.dirname, "../src/brandcal/web_dist"),
    emptyOutDir: true,
  },
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": resolve(import.meta.dirname, "./src"),
    },
  },
})
