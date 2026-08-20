import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5174,
    // Required so file changes are picked up inside the Docker container.
    watch: {
      usePolling: true,
    },
    // Uploaded images are stored as relative /media/… URLs (portable across
    // environments; served by Caddy in prod). In dev the SPA origin (Vite)
    // must forward those to the backend container, or an inserted image would
    // load the SPA's index.html and show as a broken image. `backend:8000` is
    // the compose service (this dev server runs inside the frontend container).
    proxy: {
      "/media": { target: "http://backend:8000", changeOrigin: true },
    },
  },
});
