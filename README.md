# gdrive-dl docs

Astro source for the gdrive-dl documentation site.

- Live docs: https://lococoi.github.io/gdrive-dl/
- Live overview: https://lococoi.github.io/gdrive-dl/home/
- Main project: https://github.com/lococoi/gdrive-dl

The documentation lives at the site root. The product overview remains available at `/home/`.

## Local development

```bash
npm install
npm run dev
```

The site is served under `/gdrive-dl/` because it is a GitHub Pages project site.

## Build

```bash
npm run check
npm run build
npm run preview
```

## Deployment

Pushes to the orphan `gh-pages` branch trigger `.github/workflows/deploy.yml`, which builds the site with Astro and deploys the `dist` artifact to GitHub Pages.

The site includes light and dark themes, English and Spanish documentation, a docs sidebar, a generated table of contents, code copy buttons, and responsive navigation.

## Structure

```text
src/
  pages/
    index.astro            English documentation at /
    es/index.astro         Spanish documentation at /es/
    home/index.astro       English overview at /home/
    es/home/index.astro    Spanish overview at /es/home/
  layouts/                 Base and docs layouts
  components/              Header, footer, logo, icons, code blocks, callouts
  data/site.ts             Navigation and localized labels
  styles/global.css        Design system and responsive layout
```
