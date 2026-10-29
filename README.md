# gdrive-dl docs

Astro source for the gdrive-dl documentation site.

- Live site: https://lococoi.github.io/gdrive-dl/
- Main project: https://github.com/lococoi/gdrive-dl

## Local development

```bash
npm install
npm run dev
```

The site is served under `/gdrive-dl/` because it is a GitHub Pages project site.

## Build

```bash
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
    index.astro          English home
    es/index.astro       Spanish home
    docs/index.astro     English documentation
    es/docs/index.astro  Spanish documentation
  layouts/               Base and docs layouts
  components/            Header, footer, icons, code blocks, callouts
  data/site.ts           Navigation and localized labels
  styles/global.css      Design system and responsive layout
```
