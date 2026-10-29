const rawBase = import.meta.env.BASE_URL;

export const base = rawBase.endsWith("/") ? rawBase : `${rawBase}/`;

export function withBase(path = ""): string {
  return `${base}${path.replace(/^\/+/, "")}`;
}

export function homePath(lang: "en" | "es"): string {
  return lang === "es" ? withBase("es/") : withBase("");
}

export function docsPath(lang: "en" | "es"): string {
  return lang === "es" ? withBase("es/docs/") : withBase("docs/");
}
