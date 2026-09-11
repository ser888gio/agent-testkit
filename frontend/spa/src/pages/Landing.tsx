// Public marketing page. Unlike every other page it renders outside <Layout>
// and before the session gate in App(), so it must not call the API.

import { Link } from "react-router-dom";

const STAGES = [
  ["Discover", "Probe the endpoint for its shape, tools, and side effects."],
  ["Profile", "Model purpose, capabilities, trust boundaries, failure modes."],
  ["Attack", "Run adversarial packs against fake tools in a sandbox."],
  ["Report", "Score the run and emit compliance-ready evidence."],
];

export function LandingPage() {
  return (
    <main id="content" className="mx-auto max-w-3xl px-6 py-24">
      <p className="eyebrow">OKJUL</p>
      <h1 className="mt-2 text-4xl font-semibold tracking-tight text-ink">
        Black-box testing for AI agents.
      </h1>
      <p className="mt-4 text-lg text-ink-muted">
        Call your agent through its real endpoint, assert on what it said and what it did to
        the tools it was given, and turn the results into safety and compliance evidence.
      </p>

      <div className="mt-8 flex gap-3">
        <Link className="button-link" to="/" data-testid="landing-cta">
          Open the dashboard
        </Link>
        <a
          className="button-link button-secondary"
          href="https://github.com/ser888gio/agent-testkit"
        >
          View the source
        </a>
      </div>

      <dl className="mt-16 grid gap-6 sm:grid-cols-2">
        {STAGES.map(([term, body]) => (
          <div key={term}>
            <dt className="font-medium text-ink">{term}</dt>
            <dd className="mt-1 text-sm text-ink-muted">{body}</dd>
          </div>
        ))}
      </dl>
    </main>
  );
}
