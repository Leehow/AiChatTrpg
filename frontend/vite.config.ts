import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    // Defensive: prefer TSX over JS so a stray tsc emit next to a .tsx
    // source can't silently shadow the source. tsconfig.json now sets
    // `noEmit: true` so this should rarely matter, but the explicit
    // ordering is cheap insurance.
    extensions: [".tsx", ".ts", ".jsx", ".mjs", ".js", ".json"],
  },
  server: {
    port: 3013,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8013",
        changeOrigin: true,
      },
    },
  },
});
