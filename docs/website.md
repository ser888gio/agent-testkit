# Create `PRODUCT.md`

## Summary

Create one source-of-truth Markdown file containing:

1. Customer-facing homepage copy
2. A concise product one-pager
3. A short investor narrative
4. Messaging guidance and reusable claims

The primary audience is engineering and security teams shipping AI agents. The narrative will lead with the adaptive assurance vision and drive readers toward a “Join the waitlist” CTA, while clearly distinguishing shipped MVP capabilities from roadmap capabilities.

## Content and Positioning

- Open with a narrow, matter-of-fact description following [YC’s guidance](https://www.ycombinator.com/howtoapply.html): agentkit tests AI agents through their real interfaces, tries to make them fail, and produces evidence teams can act on.
- Structure the homepage copy as:
  - Hero: outcome-led headline, plain-language subhead, primary waitlist CTA, secondary local-MVP CTA
  - Problem: conventional tests verify responses but miss unsafe real-world actions
  - Solution: discover, profile, generate a harness, attack, score, and report
  - Differentiation: black-box operation, side-effect verification, agent-specific testing, audit-ready evidence
  - How it works: three concise customer-oriented steps
  - Current proof: 27 shipped tests, core/agentic/treasury/email packs, CI gating, dashboard, regression comparison, redaction, and compliance evidence reports
  - Privacy and deployment: endpoint-only testing today; customer-hosted runner clearly labeled as direction
  - Final waitlist CTA
- Include a one-page overview covering audience, problem, product, benefits, use cases, current capabilities, roadmap, and limitations.
- Include an investor brief covering the wedge, why now, differentiation, expansion path, and current product status. Do not invent traction, market size, pricing, customers, or business-model claims.
- Use competitive YC examples only as presentation inspiration: clear problem/solution framing, concrete workflows, and outcome-based claims, as seen in [Casco](https://www.ycombinator.com/companies/casco), [Superagent](https://www.ycombinator.com/companies/superagent), and [Decipher AI](https://www.ycombinator.com/companies/decipher-ai).

## Accuracy Rules

- Mark adaptive discovery, generated harnesses, dynamic planning, iterative attacks, and customer-hosted deployment as vision or roadmap.
- Present fixed packs, black-box HTTP/callable execution, sandbox side-effect assertions, scoring, CI gates, redaction, SQLite history, dashboard, reports, and comparisons as available now.
- Describe EU AI Act, ISO 42001, NIST, and OWASP outputs as technical readiness evidence—not certification or a compliance determination.
- Use `{{WAITLIST_URL}}` as an explicit placeholder because no live waitlist URL exists.
- Keep wording direct, specific, jargon-light, and free of unsupported superlatives or invented social proof.

## Validation

- Cross-check every current-product claim against the repository implementation and documentation.
- Verify all vision capabilities are visibly qualified.
- Confirm the copy answers within the first paragraph: what it is, who it is for, what problem it solves, and why it is different.
- Check that homepage, one-pager, and investor versions use consistent positioning.
- Review Markdown rendering, links, CTA placeholders, and compliance language.
- No code, public API, schema, or automated-test changes are required.

## Assumptions

- The new artifact will be `PRODUCT.md` at the repository root.
- It is an internal messaging source of truth, not a finished HTML landing page.
- “Join the waitlist” is the primary CTA; running the existing CLI locally is secondary.
- The adaptive assurance platform is the lead story, with an explicit “Available today / Where we’re going” distinction.
