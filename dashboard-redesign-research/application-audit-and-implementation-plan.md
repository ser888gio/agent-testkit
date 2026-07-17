# RS Generator — Preliminary Application Audit and Prioritized Redesign Plan

**Prepared:** 2026-07-17  
**Status:** Research and planning gate complete. Source-code implementation is blocked pending repository or source-archive access.  
**Evidence available:** The user’s latest application/thesis documentation and architecture diagram. No application repository was present locally, and the connected GitHub account exposed no repositories to this session.

## 1. Audit scope and confidence

This is a **documentation-based product and architecture audit**, not yet a source-level frontend audit.

The available documentation describes:

- A Next.js / React / TypeScript frontend using the App Router.
- A highly interactive client-rendered root because the application uses browser APIs including WebSocket, MediaRecorder and AudioContext.
- A single-page, two-column work area: conversation on the left and a progressively populated Requirement Specification plus analysis on the right.
- Network concerns abstracted into modules and browser-specific behavior encapsulated in hooks.
- A central page-level state orchestrator.
- Microsoft Entra ID authentication.
- SSE for streamed chat responses, WebSocket for voice/live communication, uploads, discovery, diagrams, document generation and feedback endpoints.
- Firestore for session/state/feedback, Cloud Storage for files, BigQuery views for analytics, and separate frontend/backend Cloud Run services.
- A journey from an empty 0% specification, through live completeness updates, to readiness/finalization, analysis and DOCX export.

These facts are enough to propose information architecture and migration phases. They are not enough to verify routes, component boundaries, CSS/design tokens, exact data types, test coverage, accessibility, rendering behavior or regressions.

## 2. Current experience — inferred structure

### Current primary journey

1. Authenticate with Microsoft Entra ID.
2. Enter the single main workspace.
3. Converse with the AI assistant.
4. Watch the Requirement Specification fill in live.
5. Track an aggregate completeness percentage.
6. Continue until the system signals readiness.
7. Trigger finalization.
8. Wait through a processing overlay/polling phase.
9. Review analysis/recommendations/risks.
10. Download the generated DOCX.

### Current strengths

- **Immediate feedback:** streamed responses and a live document preview make progress tangible.
- **Direct manipulation of the core task:** chat and structured output are visible together.
- **Clear lifecycle milestone:** completeness and readiness provide a sense of progress.
- **Multimodal capability:** file upload, voice, transcripts and diagrams can support richer evidence.
- **Recoverable state:** historical sessions and persisted state are described.
- **Separation of concerns in architecture:** frontend and backend are independently deployable, and network/hooks are intended to be isolated from presentation.
- **Deterministic workflow control:** the documented backend state machine can support predictable UI states instead of relying solely on generative text.

## 3. Gap analysis against the strongest Playwright/Cypress patterns

| Area | Current documented experience | Strong reference pattern | Gap / opportunity |
|---|---|---|---|
| Entry point | A single workspace centered on one active session | Cypress Latest Runs / project dashboard | Add a session dashboard that separates active, needs-attention, ready and complete work. |
| Hierarchy | Chat and live specification share one page | Overview → prioritized queue → detail → evidence | Introduce workspace/session/section/activity hierarchy and keep it visible during drill-down. |
| Prioritization | Aggregate completeness and readiness | Cypress Tests for Review | Add “Needs attention” based on missing fields, contradictions, deferred answers, processing errors and stale sessions. |
| Granularity | One completeness percentage | Status at run, test, attempt and step level | Add section-level completeness/status, confidence and missing-aspect counts. |
| Navigation | SPA split view; route detail unknown | Stable URLs and context-preserving panels | Give sessions and tabs addressable routes/query state; preserve filters and selected section. |
| Search/filter | Not documented | Playwright/Cypress filter-first lists | Add search, owner/status/date filters, sorting and grouping on sessions and specification sections. |
| Temporal understanding | Conversation chronology exists | Trace/Replay timeline synchronized with evidence | Add an activity timeline tied to messages, extracted fields, uploads, contradictions, finalization and export events. |
| Evidence | Chat, uploads, live RS, analysis | Evidence bundle attached to selected event/item | Link each populated field to source message/file and show provenance in a side panel. |
| Retries/recovery | Finalization polling and error handling described generally | Attempt-level status and explicit retry artifacts | Model finalization/export attempts explicitly and show retry, failure reason and last successful artifact. |
| Comparison | Not documented | Prior runs, branch review, expected/actual/diff | Add specification-version comparison and “what changed since last session/version.” |
| Analytics | BigQuery views exist, UI not documented | Health, flake, duration and trend analytics | Expose completion time, drop-off, unresolved sections, regeneration/error rate and feedback trends with actions. |
| Empty/loading/error | Not documented at component level | Dedicated setup, unavailable and error states | Create reusable state panels, skeletons, retry paths and artifact-unavailable messages. |
| Responsive behavior | Two equal desktop columns implied | Desktop workbench, single-pane mobile adaptation needed | On mobile, use tabs/drawers and one primary task at a time; never compress both full panes. |
| Accessibility | Not documented | Keyboard-heavy debugging products, but room for improvement | Establish keyboard flow, live-region strategy, focus restoration, non-color status and AA contrast. |
| Design system | Tokens/components unknown | Repeated status, tab, table and evidence primitives | Define semantic tokens and reusable primitives before page redesign. |

## 4. Technical constraints and risks to verify in source

### Likely constraints

- The root component may be large because it centrally orchestrates local state.
- Client-only rendering may make route transitions and state preservation sensitive.
- SSE and WebSocket connections must survive or intentionally reconnect when navigating between tabs/routes.
- Voice recording and upload controls require permission, disconnected and unsupported-browser states.
- Finalization polling may conflict with optimistic UI or route unmounts.
- Firestore documents may not currently contain denormalized fields needed for fast dashboard lists and filters.
- The current backend may expose only per-session endpoints, not paginated dashboard aggregates.
- BigQuery data may be delayed and unsuitable for live operational status.

### Code-level items still unverified

- Actual route tree and route guards.
- Server versus client component boundaries.
- Component hierarchy and reusable primitives.
- CSS strategy, token definitions and dark/high-contrast behavior.
- State management approach beyond page-local React state.
- API client types and error normalization.
- Firestore schema/indexes and pagination strategy.
- Unit, integration and end-to-end test tooling.
- Accessibility semantics, focus order, keyboard support and screen-reader announcements.
- Existing responsive breakpoints and device coverage.
- Performance budgets and bundle composition.

## 5. Proposed information architecture

The redesign keeps the product focused on requirements elicitation while adopting the overview-to-evidence hierarchy shared by Playwright and Cypress.

```text
Workspace
├── Sessions dashboard
│   ├── Needs attention
│   ├── Active / Draft
│   ├── Ready to finalize
│   ├── Finalizing / Processing
│   └── Complete / Archived
├── Session detail
│   ├── Overview
│   ├── Conversation
│   ├── Specification
│   ├── Review issues
│   ├── Analysis
│   └── Activity / artifacts
├── Analytics
└── Settings
    ├── Profile and preferences
    ├── Integrations / authentication
    ├── Data and privacy
    └── Export defaults
```

### Proposed routes

| Route | Purpose | Notes |
|---|---|---|
| `/sessions` | Operational dashboard and default signed-in landing page | Search, filters, grouped status, needs-attention queue, recent activity. |
| `/sessions/new` | Start a new requirement session | Keep onboarding minimal; permit upload-first or chat-first entry. |
| `/sessions/[sessionId]` | Session overview | Header, lifecycle state, completeness breakdown, next actions, recent evidence. |
| `/sessions/[sessionId]?view=conversation` | Conversation workbench | Desktop split view; selected specification section can remain synchronized. |
| `/sessions/[sessionId]?view=specification` | Structured specification | Outline, section statuses, field provenance and edit/review controls. |
| `/sessions/[sessionId]?view=review` | Missing/contradictory/deferred issue queue | Equivalent of “Tests for Review”: ranked work rather than a raw checklist. |
| `/sessions/[sessionId]?view=analysis` | Final recommendations, team, risks and generated outputs | Disabled or preview state before finalization. |
| `/sessions/[sessionId]?view=activity` | Timeline of messages, extraction changes, uploads, attempts and exports | Deep links to the event’s evidence. |
| `/analytics` | Product/process health and trend analytics | Operational metrics with direct links to affected sessions. |
| `/settings` | User and workspace settings | Separate administration from core task flow. |

A query-parameter tab model is proposed initially because it can preserve a single session shell and active stream connection. Nested routes can replace it later if the current architecture supports shared layouts cleanly.

## 6. Proposed page behavior

### 6.1 Sessions dashboard

**Header:** workspace identity, search, “New session,” profile/settings.  
**Summary strip:** needs attention, active, ready, processing, complete.  
**Primary queue:** ranked cards/rows for sessions that need input or recovery.  
**All sessions:** filterable table on desktop; compact cards on mobile.  
**Filters:** status, owner, updated date, completeness range, issue type, archived.  
**Sorting:** needs attention, recently updated, oldest waiting, completeness, title.  
**Empty state:** explanation plus start/upload actions.  
**Error state:** preserve filters and allow retry without losing the page.

### 6.2 Session detail shell

**Persistent header:** title, owner, last saved/synced time, lifecycle status, completeness, primary next action, overflow menu.  
**Tabs:** Overview, Conversation, Specification, Review, Analysis, Activity.  
**Context rail:** on wide screens, a collapsible specification outline or issue list; on narrow screens, a drawer.  
**Connection status:** subtle but explicit SSE/WebSocket state with recovery action.

### 6.3 Conversation workbench

Desktop:

- Left: conversation timeline and composer.
- Right: selected specification section, extracted values, missing aspects and provenance.
- Optional bottom/right evidence drawer: uploads, citations and activity for the selected field.

Mobile:

- One full-width pane at a time.
- A sticky segmented control switches Chat / Specification / Review.
- Composer remains reachable without covering content.
- Section changes announce and restore focus appropriately.

### 6.4 Review queue

Rank items by:

1. Blocking contradiction.
2. Required missing field.
3. Repeatedly deferred question.
4. Low-confidence extraction.
5. Finalization or export failure.
6. Suggested enhancement.

Each item contains status, affected section, reason, evidence, recommended next question/action and resolution history. Resolving an item updates both the queue and section state.

### 6.5 Specification view

- Hierarchical outline with section-level status.
- Search within fields and sections.
- Filters for missing, incomplete, conflicting, confirmed and generated.
- Expandable provenance: source message, file, transcript segment or manual edit.
- Version indicator and change summary.
- Accessible inline edit/review controls where product policy permits.

### 6.6 Activity and artifacts

A chronological event model inspired by Trace/Replay:

- Message sent / assistant response streamed.
- File upload started/completed/failed.
- Field extracted/updated/overwritten.
- Contradiction detected/resolved.
- Completeness threshold reached.
- Finalization attempt started/completed/failed/retried.
- Analysis artifact generated.
- DOCX export generated/downloaded/failed.
- Feedback submitted.

Selecting an event reveals related fields, source content, processing metadata and artifacts without leaving the session.

### 6.7 Analytics

Initial metrics should answer operational questions:

- Median time from creation to ready/finalized.
- Completion funnel by lifecycle stage.
- Most frequently missing sections/aspects.
- Sessions waiting for user input versus system processing.
- Contradiction and deferred-question rates.
- Finalization/export success, retry and failure rates.
- Upload/voice failure rates.
- User feedback and correction frequency.

Charts must have adjacent summaries, accessible data tables and links to the sessions behind a metric. Avoid vanity metrics with no action.

## 7. Component hierarchy

```text
AppProviders
└── AuthenticatedAppShell
    ├── GlobalNavigation
    ├── TopBar
    ├── ConnectionStatus
    └── RouteContent
        ├── SessionsDashboard
        │   ├── DashboardSummary
        │   ├── AttentionQueue
        │   ├── SessionFilterBar
        │   ├── SessionTable
        │   └── SessionCardList
        └── SessionShell
            ├── SessionHeader
            ├── SessionTabs
            ├── SessionContextRail
            └── SessionView
                ├── OverviewView
                ├── ConversationWorkbench
                │   ├── MessageTimeline
                │   ├── Composer
                │   ├── SpecificationInspector
                │   └── EvidenceDrawer
                ├── SpecificationView
                │   ├── SpecificationOutline
                │   ├── SectionPanel
                │   └── ProvenancePanel
                ├── ReviewQueue
                ├── AnalysisView
                └── ActivityTimeline
```

### Reusable primitives

- `StatusBadge` and `StatusIcon` with text and icon, never color alone.
- `ProgressSummary` with aggregate and section breakdown.
- `FilterBar`, `SearchField`, `FilterChip`, `SortMenu`.
- `DataTable`, `ResponsiveCardList`, `Pagination`.
- `Tabs`, `SegmentedControl`, `Disclosure`, `Drawer`, `Dialog`.
- `StatePanel` for empty/error/unavailable/permission states.
- `Skeleton`, `InlineSpinner`, `ProgressBanner`.
- `Toast` for transient confirmation; persistent banners for recoverable failures.
- `ActivityTimeline` and `EventDetailPanel`.
- `ArtifactLink`, `AttemptList`, `RetryButton`.
- `FieldStatus`, `MissingAspectList`, `ProvenanceLink`.
- `MetricCard`, `ChartFrame`, `AccessibleDataTable`.

## 8. Design-system updates

### Token layers

1. **Foundation:** font families, type scale, spacing, radii, shadows, motion durations, breakpoints.
2. **Semantic color:** canvas, surface, border, text, muted, accent, focus, success, warning, danger, info and disabled.
3. **Component aliases:** navigation, table, badge, field, banner, chart and code/evidence surfaces.

### Recommended principles

- Preserve the existing brand accent and derive accessible hover/active/focus variants.
- Use neutral surfaces for the application shell; reserve saturated color for actions and state.
- Keep body text at least 16px on narrow screens and avoid sub-12px labels.
- Use a restrained density: compact tables on desktop, comfortable cards/controls on touch devices.
- Use 8px-based spacing with smaller 4px increments for icon/text alignment.
- Apply a visible 2px+ focus indicator with sufficient contrast and offset.
- Use icons plus labels for unfamiliar actions; tooltips supplement rather than replace names.
- Respect `prefers-reduced-motion` for streaming indicators, progress animation and drawers.
- Include a high-contrast-safe status palette and non-color markers.

## 9. Data and API dependencies

### Minimum dashboard list model

```ts
interface SessionSummary {
  id: string;
  title: string;
  owner: UserSummary;
  lifecycle: 'draft' | 'active' | 'ready' | 'finalizing' | 'complete' | 'error' | 'archived';
  completeness: number;
  sectionCounts: {
    complete: number;
    incomplete: number;
    missing: number;
    conflicting: number;
  };
  attentionReasons: AttentionReason[];
  createdAt: string;
  updatedAt: string;
  waitingOn: 'user' | 'system' | 'reviewer' | null;
  lastArtifact?: ArtifactSummary;
}
```

### Required or derived endpoints

- Paginated session summaries with server-side search, filters and sorting.
- Session detail including lifecycle, completeness by section and current workflow state.
- Review issues/missing aspects with stable identifiers and resolution status.
- Activity/events endpoint or event stream with cursor pagination.
- Artifact/finalization attempt metadata, including failure reason and retryability.
- Analytics aggregates with date/project/user filters and data-freshness timestamps.
- Optional version snapshots/diff endpoint for specification comparison.

### Migration strategy

- Phase 1 may derive summary fields from existing session data client-side for a small dataset.
- Before production scale, denormalize operational summary fields into a query-friendly Firestore collection and create required composite indexes.
- Keep BigQuery for longitudinal analytics, not live operational status.
- Normalize backend error responses into typed error codes so UI states are deterministic.
- Give SSE/WebSocket events stable event types and IDs; reconnect using a cursor or fetch-after-reconnect strategy where possible.

## 10. Responsive requirements

| Width | Required behavior |
|---|---|
| ≥ 1280px | Full navigation, filterable table, session context rail and two-pane workbench. |
| 768–1279px | Collapsible navigation/rail; workbench may use resizable or toggleable secondary pane. |
| 360–767px | Single-pane screens, card list instead of wide table, sticky view switcher, drawers for context/evidence. |
| 320–359px | No horizontal page scroll; labels may wrap; secondary actions move into menus without hiding primary actions. |

- Preserve message composer, primary next action and status at all widths.
- Do not show two independently scrollable full-height panes on phones.
- Touch targets should be at least 44×44 CSS pixels where practical.
- Tables must have a deliberate mobile alternative rather than relying on horizontal scrolling for core information.

## 11. Accessibility requirements

- WCAG 2.2 AA contrast for text, controls, focus and status indicators where practical.
- Complete keyboard journey: global navigation, filters, session selection, tabs, conversation, section outline, review queue, dialogs and export.
- Correct landmarks, heading order, labels, descriptions and table semantics.
- Roving keyboard behavior for tabs/segmented controls and arrow-key navigation where expected.
- `aria-live="polite"` for streamed assistant text/status summaries; avoid announcing every token.
- Explicit connection/finalization progress messages and completion/failure announcements.
- Focus restoration after dialogs/drawers and after resolving a review item.
- Status always represented by text/icon in addition to color.
- Charts paired with text summaries and accessible tables.
- Reduced-motion support and no flashing progress treatment.
- File upload/recording controls expose permission, size/type and failure information programmatically.

## 12. Prioritized implementation phases

### Phase 0 — Baseline and source audit

**Priority:** Blocking  
**Work:** Obtain repository, install dependencies, map routes/components/tokens/models, run existing app, capture desktop/mobile baseline screenshots, document current tests and API contracts.  
**Exit:** Source-level audit replaces all “unverified” items in this document; no code changes yet.

### Phase 1 — Design foundation and reusable states

**Priority:** P0  
**Work:** Semantic tokens, typography/spacing, focus style, buttons/inputs/tabs/badges/table/card primitives, skeleton/empty/error/unavailable/disabled states, accessibility helpers.  
**Exit:** Story/demo coverage for every state; no regression to existing primary journey.

### Phase 2 — App shell and sessions dashboard

**Priority:** P0  
**Work:** Authenticated shell, navigation, `/sessions`, summary counts, attention queue, search/filter/sort, responsive table/cards, URL-persisted filters.  
**Exit:** Users can find active/ready/problem sessions and open one using keyboard or touch.

### Phase 3 — Session shell and existing workbench migration

**Priority:** P0  
**Work:** Session header/tabs, move the existing chat/live specification functionality into `ConversationWorkbench`, add responsive pane behavior, preserve SSE/WebSocket/voice/upload functionality.  
**Exit:** Existing chat-to-export journey works unchanged through the new shell at desktop and mobile widths.

### Phase 4 — Section status, review queue and provenance

**Priority:** P1  
**Work:** Section-level status, issue ranking, missing/contradiction/deferred states, evidence/provenance panel, resolve/reopen actions.  
**Exit:** A user can move from session overview to the exact unresolved section and source evidence in no more than three primary interactions.

### Phase 5 — Activity, attempts and artifacts

**Priority:** P1  
**Work:** Event timeline, finalization/export attempts, retryable errors, artifact history and source links.  
**Exit:** Processing failures are diagnosable without relying on hidden logs; retry does not duplicate successful outputs.

### Phase 6 — Analytics and settings

**Priority:** P2  
**Work:** Action-oriented analytics, data freshness, accessible chart/table views, user/workspace preferences and export defaults.  
**Exit:** Each metric has a definition, freshness timestamp and route to affected sessions.

### Phase 7 — Hardening and release validation

**Priority:** P0 before release  
**Work:** Performance, keyboard/screen-reader review, visual regression, responsive E2E, lint/type/unit/E2E, error injection, stream reconnection, cross-browser checks.  
**Exit:** Acceptance criteria below are met and regressions introduced by the redesign are fixed.

## 13. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Monolithic client root and local state | Route extraction can break active streams and shared state | Introduce a session provider/service boundary before moving visual components; migrate one view at a time. |
| Missing list/query APIs | Dashboard could require expensive per-session reads | Add denormalized summaries and Firestore indexes; define pagination before UI scale. |
| SSE/WebSocket reconnect behavior | Navigation or mobile backgrounding can lose responses | Centralize connection lifecycle, expose connection state, add resync endpoint/cursor. |
| Existing brand/design constraints unknown | New system may conflict with product identity | Inventory current tokens/assets first; map semantic tokens onto existing brand values. |
| Feature scope expansion | Redesign could become a full platform rewrite | Preserve core journey; gate analytics/settings behind later phases. |
| Status complexity | Users may not understand lifecycle versus completeness versus issues | Use explicit labels, definitions, tooltips and a single recommended next action. |
| Mobile voice/upload complexity | Permission and OS behavior may be inconsistent | Test real devices; provide text/upload fallback; preserve drafts during interruption. |
| Accessibility added late | Structural rework and regressions | Build primitives and keyboard/live-region behavior in Phase 1; test each phase. |
| Analytics freshness | Operational and warehouse values may disagree | Label data source/freshness; use Firestore for live status and BigQuery for trends. |

## 14. Assumptions to verify

- A user can own or access multiple historical sessions.
- Session lifecycle values can be mapped deterministically from the backend workflow state.
- The backend can expose section-level completeness and missing aspects.
- Contradictions/deferred fields can be represented as stable review items.
- Existing authentication can protect new routes without changing identity architecture.
- The current DOCX generation and analysis APIs remain backward compatible.
- Brand assets and any corporate design rules can be used in the redesign.
- No regulatory requirement prevents showing provenance or historical versions to the signed-in user.

## 15. Acceptance criteria

### Functional preservation

- Sign-in, session restoration, streaming chat, voice mode, uploads, live specification updates, finalization, analysis and DOCX export continue to work.
- Existing persisted sessions remain openable; route migration includes redirects where necessary.
- No successful finalization/export is duplicated by UI retry behavior.

### Usability

- Dashboard exposes active, ready, processing, complete and needs-attention states without opening each session.
- Search/filter/sort state persists in the URL and survives refresh/back navigation.
- From dashboard to a blocking review issue and its source evidence requires no more than three primary interactions.
- Desktop and mobile journeys use deliberate layouts, not clipped/squeezed desktop UI.

### States

- Every data-bearing surface has loading, empty, error and success behavior.
- Interactive controls have default, hover, focus-visible, active, selected and disabled states.
- Connection, permission, artifact-unavailable and retryable-processing failures have specific messages and actions.

### Accessibility

- No critical accessibility violations in automated checks on the primary pages.
- Primary journeys are completable using keyboard only.
- Text and controls meet WCAG AA contrast targets where practical.
- Streaming/progress completion and failure are announced without token-by-token noise.
- Status is never conveyed by color alone.

### Responsive validation

- No page-level horizontal overflow at 320, 375, 768, 1024 and 1440 CSS-pixel widths.
- Core controls remain reachable at 200% browser zoom.
- Mobile uses a single primary pane and preserves unsent composer content when switching views.

### Engineering quality

- Existing linting and type checks pass.
- Existing unit and E2E suites pass; new route/state/component behavior receives coverage.
- Main journeys have desktop and mobile E2E tests.
- Before/after screenshots are captured from stable seeded data.
- Modified files and any intentionally changed behavior are documented in the final implementation report.

## 16. Implementation gate and current blocker

The research and planning required before code changes are now documented. No application files were modified.

Implementation cannot begin in this environment because:

1. No local application repository or source archive is mounted.
2. The connected GitHub integration returned no accessible repositories.
3. File Library contains product/architecture documentation, not the frontend source tree.

Required next input: the application repository through the GitHub connection or an uploaded source archive. Once available, Phase 0 begins with a source-level audit and baseline screenshots before any code modification.
