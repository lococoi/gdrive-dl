export type Lang = "en" | "es";

export const repoUrl = "https://github.com/lococoi/gdrive-dl";
export const releasesUrl = `${repoUrl}/releases`;
export const issuesUrl = `${repoUrl}/issues`;
export const licenseUrl = `${repoUrl}/blob/main/LICENSE`;

export const navLabels: Record<
  Lang,
  { home: string; docs: string; cli: string; api: string; github: string }
> = {
  en: {
    home: "Home",
    docs: "Docs",
    cli: "CLI",
    api: "API",
    github: "GitHub",
  },
  es: {
    home: "Inicio",
    docs: "Documentación",
    cli: "CLI",
    api: "API",
    github: "GitHub",
  },
};

export const docsNav: Record<Lang, { id: string; label: string }[]> = {
  en: [
    { id: "quickstart", label: "Quick start" },
    { id: "cli", label: "CLI reference" },
    { id: "api", label: "HTTP API" },
    { id: "architecture", label: "Architecture" },
    { id: "security", label: "Security" },
    { id: "build", label: "Build and release" },
    { id: "troubleshooting", label: "Troubleshooting" },
  ],
  es: [
    { id: "quickstart", label: "Inicio rápido" },
    { id: "cli", label: "Referencia CLI" },
    { id: "api", label: "API HTTP" },
    { id: "architecture", label: "Arquitectura" },
    { id: "security", label: "Seguridad" },
    { id: "build", label: "Build y release" },
    { id: "troubleshooting", label: "Solución de problemas" },
  ],
};

export const footerLabels: Record<
  Lang,
  {
    product: string;
    resources: string;
    docs: string;
    releases: string;
    issues: string;
    license: string;
    built: string;
    tagline: string;
  }
> = {
  en: {
    product: "Product",
    resources: "Resources",
    docs: "Documentation",
    releases: "Releases",
    issues: "Issues",
    license: "Apache-2.0 License",
    built: "Built with Astro. Deployed with GitHub Pages.",
    tagline: "Private Google Drive downloads with an isolated Chrome session.",
  },
  es: {
    product: "Producto",
    resources: "Recursos",
    docs: "Documentación",
    releases: "Releases",
    issues: "Issues",
    license: "Licencia Apache-2.0",
    built: "Hecho con Astro. Desplegado con GitHub Pages.",
    tagline: "Descargas privadas de Google Drive con una sesión aislada de Chrome.",
  },
};
