import { defineConfig } from "astro/config";

const base = "/gdrive-dl";

export default defineConfig({
  site: "https://lococoi.github.io",
  base,
  trailingSlash: "always",
  build: {
    format: "directory",
  },
  redirects: {
    "/docs": `${base}/`,
    "/es/docs": `${base}/es/`,
  },
});
