import { defineConfig } from "astro/config";

export default defineConfig({
  site: "https://lococoi.github.io",
  base: "/gdrive-dl",
  trailingSlash: "always",
  build: {
    format: "directory",
  },
});
