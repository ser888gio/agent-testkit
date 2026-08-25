# Product

## Register

product

## Users

Engineering and compliance teams who audit AI agents before deployment. They arrive
between runs — often after a failure or before a release gate — to answer three questions:
what needs attention, what actually happened in a run, and what evidence exists to show
for it. Context is professional and time-pressured; the tool is used loopback in dev and
behind OIDC in partner-facing deployments.

## Product Purpose

agentaudit is black-box testing and assurance for AI agents: it runs test packs against
agent endpoints, captures redacted evidence, scores results, and gates releases. The
dashboard is the read-mostly control plane over that evidence. Success is a reviewer
landing on the right run within seconds and trusting every number they see.

## Brand Personality

Precise, forensic, calm. Evidence-first language; no marketing gloss. Numbers and status
words carry meaning — a BLOCK gate must read as red and serious, never decorative.
Visually close to Linear's restraint: near-black canvas, hairline borders, surface ladder
for depth, one indigo accent.

## Anti-references

- SaaS-dashboard cliché: hero metrics with gradients, glow shadows, glassmorphism.
- Alert fatigue: everything red/bold so nothing reads as urgent.
- Decorative color: color is semantic (pass/fail/warn), never ornament.

## Design Principles

1. **Evidence over chrome.** Every pixel of emphasis must map to a fact about a run.
2. **Semantic color only.** Green/red/amber/grey mean pass/fail/error/skipped, everywhere,
   in both themes.
3. **Calm density.** Tables and matrices are the primary surfaces; whitespace and
   hairlines do the separating, not boxes-in-boxes.
4. **Failures sort first.** Any ordered list leads with what needs attention.
5. **No invented data.** The UI renders what the store holds — including `«redacted:…»`
   markers as-is.

## Accessibility & Inclusion

WCAG 2.1 AA. Preserve existing patterns: skip link, visible focus rings
(`:focus-visible`), `aria-live="polite"` status polling, reduced-motion fallbacks,
≥4.5:1 body-text contrast in both themes, keyboard-reachable controls.
