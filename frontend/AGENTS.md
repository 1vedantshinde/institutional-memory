# Institutional Memory — frontend

React + Vite + Tailwind CSS project, originally scaffolded in Figma Make.

## Development Server

Start it with `pnpm dev` (or `npm run dev`). It listens on `$PORT` (default 5173, set in `.env.local`).
Copy `.env.example` to `.env.local` first; set `VITE_USE_MOCKS=true` to run without a backend.

Verify changes with `npx tsc --noEmit`, `npx vite build` and `npx vitest run`.

## Project Structure

This is the canonical project structure. Start with task-relevant files below. Only follow imports or inspect other files when required, when a documented path is missing, or when the repository contradicts this guide.

- `src/main.tsx` - React entrypoint; imports `src/index.css` and mounts `src/App.tsx` into the `#root` element
- `src/App.tsx` - Primary application component and the usual starting point for UI work
- `src/index.css` - Global CSS entrypoint and Tailwind CSS v4 import
- `index.html` - Vite HTML shell containing the `#root` element and loading `src/main.tsx`
- `package.json` - Project dependencies and the Vite build, development, preview, and formatting scripts
- `vite.config.ts` - Vite configuration with React, Tailwind CSS v4, and Figma Make plugins plus the `@` alias for `src`
- `src/router.tsx` - Routes; every page in `src/pages/` is lazy-loaded
- `src/test/setup.ts` - The single Vitest setup file (storage mocks + MSW server lifecycle)

## Dependencies

- Runtime: React 19 and React DOM 19
- Styling: Tailwind CSS v4 with the `@tailwindcss/vite` plugin
- Build tooling: Vite 8, TypeScript 5.7, and `@vitejs/plugin-react`
- Formatting: oxfmt

## Styling

This project uses **Tailwind CSS v4** through the `@tailwindcss/vite` plugin configured in `vite.config.ts`. `src/index.css` imports Tailwind with `@import 'tailwindcss';`. Use Tailwind utility classes directly in JSX and put global CSS or Tailwind v4 theme customization in `src/index.css`. This scaffold does not need a Tailwind config file or PostCSS config.

Global element styles in `src/index.css` must stay inside `@layer base`: unlayered CSS outranks every Tailwind utility (an unlayered `* { padding: 0 }` once disabled all spacing classes).

`src/main.tsx` imports `src/index.css`, so global font wiring belongs in `src/index.css`. Keep CSS `@import` statements first, then add any `@font-face` rules and font-family defaults there.
