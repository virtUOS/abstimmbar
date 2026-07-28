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
  },
});
