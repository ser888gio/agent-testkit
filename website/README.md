# agentaudit documentation site

The user-facing documentation, built with [Docusaurus](https://docusaurus.io/).

```bash
npm install
npm start     # dev server with hot reload on http://localhost:3000
npm run build # static build into build/
npm run serve # serve the built site locally
```

## Layout

| Path | Contents |
| --- | --- |
| `docs/intro.md` | What agentaudit is, positioning, capability table. |
| `docs/getting-started/` | Install and quickstart. |
| `docs/concepts/` | How it works, test packs, sandboxes, scoring, redaction. |
| `docs/guides/` | Task walkthroughs: connect an agent, write a test, CI, compliance. |
| `docs/reference/` | CLI, target config, assertions, report formats. |
| `docs/limits.md` | What it does not do, comparisons, roadmap. |
| `docs/troubleshooting.md` | Symptom-to-fix list. |
| `sidebars.ts` | Explicit sidebar order. |

Docs are served at the site root (`routeBasePath: '/'`); there is no separate
landing page and no blog.

## Keeping it accurate

These pages describe behavior that lives in code. When you change one of the
following, update the matching page:

| You changed | Update |
| --- | --- |
| A CLI command or flag (`backend/agentaudit/cli.py`) | `docs/reference/cli.md` |
| The assertion registry (`core/assertions.py`) | `docs/reference/assertions.md` |
| The target config model (`core/config.py`) | `docs/reference/target-config.md` |
| Categories, risks or the test schema (`core/schema.py`) | `docs/concepts/test-packs.md` |
| Scoring or gate behavior (`core/scoring.py`) | `docs/concepts/scoring.md` |
| Redaction patterns or evidence policy (`core/redaction.py`) | `docs/concepts/redaction.md` |
| A sandbox's setup keys (`domains/*/sandbox.py`) | `docs/concepts/sandboxes.md` |
| Report formats (`reports/`) | `docs/reference/reports.md` |

`onBrokenLinks` is set to `throw`, so `npm run build` fails on a dead internal
link. Run it before merging a docs change.

These docs are the *product* documentation. Contributor and architecture notes
stay in the repository's `docs/` directory.
