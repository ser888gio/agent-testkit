# agentaudit dashboard (SPA)

The GUI. React 18 + TypeScript + Vite, served by `agentaudit.web.app` — see
[`../agentaudit/web/CLAUDE.md`](../agentaudit/web/CLAUDE.md) for the API side.

```bash
npm ci
npm run dev      # Vite dev server, proxies /api to 127.0.0.1:8000
npm run build    # tsc -b && vite build -> ../agentaudit/web/spa_dist/
```

The FastAPI server must be running for `dev` to have data: `bash ../../infra/dev.sh`.

## UI libraries

The dependency list is deliberately short. Two constraints drive it:

1. **Air gap.** `backend/agentaudit/reports/charts.py` documents it: this ships self-hosted
   and often air-gapped, so **no CDN-loaded assets** — no remote script tags, no remote
   fonts, no remote stylesheets. npm-bundled dependencies are fine.
2. **No `dangerouslySetInnerHTML`.** Enforced by `tests/test_web.py::test_spa_poller_avoids_html_injection_sinks`,
   which greps every `src/**/*.tsx` for that and `innerHTML`/`insertAdjacentHTML`.

### In use today

| Library | Version | What it is used for |
| --- | --- | --- |
| `react` / `react-dom` | ^18.3.1 | Everything. Not React 19. |
| `react-router-dom` | ^6.28.0 | Routing (`BrowserRouter`, no data router / loaders). |
| `vite` | ^5.4.11 | Build and dev server. |
| `typescript` | ^5.6.3 | `tsc -b` runs as part of `npm run build`. |

That is the complete runtime dependency list: **three packages**. There is currently no
component library, no icon package, no chart library, no state-management library, and no
CSS framework. Everything below is hand-written.

### Being adopted (UI modernization, in progress)

| Library | Role | Status |
| --- | --- | --- |
| `tailwindcss` + `@tailwindcss/vite` | Utility CSS, v4 (Vite plugin — no `tailwind.config.js`) | pending |
| shadcn/ui | Component source, copied into the repo via `npx shadcn@latest add` — not a dependency | pending |
| Radix UI | Accessible primitives behind shadcn (dropdown, dialog, tooltip) | pending, per-component |
| `clsx` + `tailwind-merge` + `class-variance-authority` | Class composition and variants | pending |
| `lucide-react` | Icons, replacing ~9 hand-inlined SVG sets | pending |
| `vitest` + `@testing-library/react` | Component tests (the SPA has no test runner today) | pending |

**Token bridging:** the existing CSS custom properties stay the single source of truth.
Tailwind reads them via `@theme inline`, and shadcn's vocabulary (`--color-card`,
`--color-primary`, …) is aliased onto ours in the same block, so pasted components are
correctly themed on arrival.

**No `dark:` or `light:` variants in our own code.** The app is dark-by-default with an
opt-in light theme — the inverse of Tailwind's model. Because `@theme inline` resolves
utilities through the custom properties at runtime, every utility is already theme-correct.
Encode any theme difference as a *token*, not a variant.

### Deliberately not used

| Not used | Why |
| --- | --- |
| Any chart library (Recharts, visx, Chart.js, D3) | Chart geometry is computed in Python (`backend/agentaudit/reports/charts.py`) and rendered as inline SVG / CSS bars. The sparkline's y-axis is **deliberately pinned to 0–100** so a run at 90 does not look like a disaster next to runs at 95. Chart libraries auto-fit domains by default; we would install a dependency and then fight it to restore behavior we already have — and misleading charts on a compliance-evidence tool is the worst failure mode available. |
| TanStack Table | Every table is server-filtered and server-sorted — the filter bars build `URLSearchParams` and navigate. TanStack's value is client-side state. No table needs row selection, column resizing, or virtualization. |
| shadcn `sidebar` block | Brings a provider, cookie-persisted collapse state and keyboard shortcuts for what is a 6-item static nav. |
| Radix `Select` | Native `<select>` is lighter and better on mobile; no dropdown needs custom option rendering. |

## Styling

All styling is global CSS classes in **one stylesheet**:
`../agentaudit/web/static/style.css`. It is currently served by FastAPI's `/static` mount
and linked from `index.html` — **Vite does not see it**, so there is no hashing, no style
HMR, and no dead-code elimination. Moving it into the Vite build is Phase 1 of the
modernization.

Design tokens are CSS custom properties on `:root`: a four-step surface ladder
(`--surface-1..4`), an ink ramp (`--ink` / `-muted` / `-subtle` / `-tertiary`), one
chromatic accent (`--accent`), and a semantic status palette (`--pass-*`, `--fail-*`,
`--warn-*`, `--neutral-*`). Colors are tuned per theme for contrast — the light theme is not
a naive inversion.

**Theme switching** is a `data-theme` attribute on `<html>` plus `localStorage` key
`aa-theme`. The inline script in `index.html` stamps it before first paint; it must stay
inline in the head, or a light-theme user gets a dark flash.

Inline `style={{}}` is used only for geometry that comes from data — bar widths, the score
bar fill.

## Component inventory

### Shared primitives — [`src/ui.tsx`](src/ui.tsx)

| Component | Kind | Used in |
| --- | --- | --- |
| `StatusBadge` | Status pill | 10 pages — the most-reused component |
| `RiskBadge` | Risk pill (same tone map) | `RunDetail`, `TestDetail` |
| `badgeClass` / `BADGE_TONE` | Tone lookup with a neutral fallback | backing both badges |
| `ScoreBar` | Score meter, red <50 / amber <80 | `Runs`, `RunHarness`, `HarnessIndex`, `Agents`, `AgentDetail` |
| `StatCard` | Metric tile | 7 pages |
| `EmptyState` | Empty and error state | all 17 pages |
| `LinkButton` | Button-styled link (internal or external) | `Agents`, `Tests`, `EmptyState` |
| `PageHeader` | Eyebrow + title + subtitle + actions | all 17 pages |
| `Spinner` | Inline spinner | `Job` |
| `ErrorNote` | Inline `role="alert"` message | `TestNew`, `AgentRegister`, `AgentConnect`, `AgentDetail`, `Job`, `Generated` |
| `formatMs`, `shortDate` | Formatters (not components) | `RunDetail`, `RunHarness`, `TestDetail`, `AgentDetail` |

### Layout — [`src/layout.tsx`](src/layout.tsx)

`Layout` (sidebar + main + footer + skip link), `NavIcon`, `ThemeToggle`, and the `NAV`
config array holding 7 inline SVG icon sets.

### Data — [`src/useView.tsx`](src/useView.tsx), [`src/api.ts`](src/api.ts), [`src/session.tsx`](src/session.tsx)

`useView<T>` is the single fetch hook: one request per page, since the JSON API returns a
whole view model. `Loading` also lives here. `api.ts` holds `apiGet`/`apiSend`, `ApiError`,
the CSRF token echo, and the 401 → `/login` redirect. `session.tsx` is the one React Context.

### Page-local components (defined inline, used once)

| Component | File |
| --- | --- |
| `ExportMenu` | [`pages/RunHarness.tsx`](src/pages/RunHarness.tsx) |
| `Icon`, `FileIcon` | [`pages/RunHarness.tsx`](src/pages/RunHarness.tsx) |
| `RunsFilterBar` | [`pages/Runs.tsx`](src/pages/Runs.tsx) |
| `TestsFilterBar` | [`pages/Tests.tsx`](src/pages/Tests.tsx) |
| inline filter form | [`pages/RunDetail.tsx`](src/pages/RunDetail.tsx) |
| `Panel`, `Meta` | [`pages/Settings.tsx`](src/pages/Settings.tsx) |
| `DeltaList` | [`pages/Compare.tsx`](src/pages/Compare.tsx) |
| `useJobPolling` | [`pages/Job.tsx`](src/pages/Job.tsx) |
| `NotFound` | [`src/App.tsx`](src/App.tsx) |

### Patterns that exist only as class names

These are recurring UI patterns styled in `style.css` but **not** abstracted into
components — every page hand-writes the markup. Extracting them is Phase 3 and Phase 7 of
the modernization.

`.panel` + `.panel-header` (~78 occurrences across 13 pages) · `.table-wrap` + `<table>`
(9 tables) · `.stat-grid` (7 pages) · `.attention-list` · `.bar-list` / `.bar-track` /
`.bar-fill` · `.matrix-row` · `.test-form` · `.detail-grid` · `.harness-meta` ·
`.assertion-list` · `.artifact-list` · `.finding-stream` · `.memory-check-list` ·
`.skill-card` · `.history-strip` · `.progress-meter` · `.test-picker` · `.option-list` ·
`.timeline`

## Conventions

- **`data-testid` values are a contract.** `tests/test_web.py::test_spa_source_keeps_nav_and_action_hooks`
  greps these source files for exact quoted literals — `nav-*` and `aria-label="Primary"`
  in `layout.tsx`, `run-row`/`stat-runs` in `Runs.tsx`, `connect-form`/`connect-submit`/
  `test-picker` in `AgentConnect.tsx`, and others. Renaming one fails the suite. Keep them
  in the file the test reads.
- **Never `window.alert`.** Use `ErrorNote` — it carries `role="alert"` and is styled.
- **Prefer `ApiError.detail`** over a bare `Error.message` so the server's message reaches
  the user.
- Badge tones come from `badgeClass()`. Do not interpolate `badge-${value}` — callers pass
  open-ended server strings (profile domains, interfaces, selection sources) that have no
  status color, and an unknown tone renders as an invisible pill.

## Testing

There is no SPA test runner yet (Vitest is planned). Today's guards are:

```bash
npm run build                                   # tsc typecheck + bundle
python -m pytest tests/test_web.py              # API routes + SPA source greps
```

`TestClient` never executes JavaScript, so rendering changes need a manual pass:
`bash ../../infra/dev.sh`, then check both themes and at least 1440px and 380px widths.
