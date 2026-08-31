import { Link } from "react-router-dom";
import { useView, Loading } from "../components/useView";
import { EmptyState, PageHeader, Panel, StatCard, StatusBadge } from "../components/ui";
import { DataTable } from "../components/table";

interface TrendPoint {
  started_at: string;
  score: number;
}

interface BarRow {
  label: string;
  value: number;
  width: number;
  percent: number;
  total: number;
}

interface RiskSeg {
  risk: string;
  total: number;
  failed: number;
  share: number;
}

interface FlakyRow {
  test_id: string;
  category: string;
  rate: number;
  failed: number;
  runs: number;
}

interface AnalyticsView {
  trend: TrendPoint[];
  sparkline: string;
  categories: BarRow[];
  flaky: FlakyRow[];
  risks: RiskSeg[];
  totals: {
    runs: number;
    agents: number;
    gate_rate: number;
    critical: number;
    latest_score: number;
    delta: number;
  };
}

function deltaNote(delta: number): string {
  if (delta > 0) return `up ${delta} pts on previous run`;
  if (delta < 0) return `down ${-delta} pts on previous run`;
  return "no change";
}

export function AnalyticsPage() {
  const { view, error } = useView<AnalyticsView>("/analytics");

  if (error) return <EmptyState title="Could not load analytics" body={error} />;
  if (!view) return <Loading />;
  const { totals, trend } = view;

  return (
    <>
      <PageHeader
        eyebrow="Portfolio"
        title="Analytics"
        subtitle="Where the estate stands, and what is trending wrong across every agent you test."
      />

      {/* Onboarding actions live on the landing page, where a new user arrives. */}
      <section className="home-actions" aria-label="Primary actions">
        <Link className="home-action" to="/agents/connect" data-testid="action-connect-agent">
          <span className="home-action-kicker">Test agent</span>
          <strong>Test an agent</strong>
          <span>Open the setup page for target configs, pack selection, and the run command.</span>
        </Link>
        <Link className="home-action" to="/tests/new" data-testid="action-create-test">
          <span className="home-action-kicker">Create test</span>
          <strong>Create a test</strong>
          <span>Open the test creation page and add a YAML-backed coverage case.</span>
        </Link>
      </section>

      {!trend.length ? (
        <EmptyState
          title="Nothing to analyse yet"
          body="Run a pack against an agent and this page fills in with trends, failure rates, and the tests that break most often."
          actionLabel="View runs"
          actionHref="/runs"
        />
      ) : (
        <>
          <section className="stat-grid" aria-label="Portfolio summary">
            <StatCard
              label="Latest score"
              value={`${totals.latest_score}%`}
              note={deltaNote(totals.delta)}
              tone={totals.delta < 0 ? "danger" : undefined}
              testid="stat-latest-score"
            />
            <StatCard
              label="Gate pass rate"
              value={`${totals.gate_rate}%`}
              note={`${totals.runs} runs recorded`}
              testid="stat-gate-rate"
            />
            <StatCard
              label="Critical failures"
              value={totals.critical}
              note="across stored runs"
              tone={totals.critical ? "danger" : undefined}
              testid="stat-critical-total"
            />
            <StatCard
              label="Agents under test"
              value={totals.agents}
              note="with recorded evidence"
              testid="stat-agent-count"
            />
          </section>

          <Panel testid="chart-trend" titleId="trend-title" title="Score trend" blurb={<>Weighted score of the last {trend.length} run(s), oldest to newest.</>}>
            <figure className="chart">
              {/* Fixed 0-100 axis: a 90 must not read as a disaster next to a 95. */}
              <svg
                viewBox="0 0 100 40"
                preserveAspectRatio="none"
                role="img"
                aria-label={`Score across the last ${trend.length} runs, from ${trend[0].score}% to ${trend[trend.length - 1].score}%`}
              >
                <title>
                  {`Score across the last ${trend.length} runs, from ${trend[0].score}% to ${trend[trend.length - 1].score}%`}
                </title>
                <line className="chart-grid" x1="0" y1="20" x2="100" y2="20" />
                <line className="chart-grid" x1="0" y1="8" x2="100" y2="8" />
                <polyline className="chart-line" points={view.sparkline} />
              </svg>
              <figcaption>
                <span>{trend[0].started_at.slice(0, 10)}</span>
                <span className="quiet">50% and 80% gridlines</span>
                <span>{trend[trend.length - 1].started_at.slice(0, 10)}</span>
              </figcaption>
            </figure>
          </Panel>

          <section className="detail-grid">
            <Panel testid="chart-categories" titleId="category-title" title="Failure rate by category" blurb={<>Share of results that failed or errored. Bars scale to the worst category.</>}>
              {!view.categories.length ? (
                <p className="quiet">No categorised results yet.</p>
              ) : (
                <ul className="bar-list">
                  {view.categories.map((row) => (
                    <li key={row.label}>
                      <span className="bar-label mono">{row.label}</span>
                      <span className="bar-track">
                        {/* A failure rate has no "good" band: only zero is good. */}
                        <span
                          className={`bar-fill${
                            row.value >= 0.35
                              ? " bar-fill-bad"
                              : row.value > 0
                                ? " bar-fill-warn"
                                : " bar-fill-none"
                          }`}
                          style={{ width: `${row.width}%` }}
                        />
                      </span>
                      <span className="bar-value">
                        {row.percent}%<span className="quiet"> of {row.total}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>

            <Panel testid="chart-risk" titleId="risk-title" title="Coverage by risk" blurb={<>How much of the evidence sits at each risk level.</>}>
              {!view.risks.length ? (
                <p className="quiet">No results yet.</p>
              ) : (
                <ul className="bar-list">
                  {view.risks.map((seg) => (
                    <li key={seg.risk}>
                      <span className="bar-label">
                        <StatusBadge status={seg.risk} />
                      </span>
                      <span className="bar-track">
                        <span
                          className={`bar-fill${seg.failed ? " bar-fill-bad" : ""}`}
                          style={{ width: `${seg.share}%` }}
                        />
                      </span>
                      <span className="bar-value">
                        {seg.total}
                        <span className="quiet"> results, {seg.failed} failed</span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          </section>

          <Panel testid="table-flaky" titleId="flaky-title" title="Most frequently failing tests" blurb={<>Tests seen in more than one run, ranked by how often they fail. A test seen once
                  is untested, not flaky.</>}>
            <DataTable
              caption="Tests that fail most often, with failure rate and sample size"
              empty="No test has failed more than once yet."
              rows={view.flaky}
              rowKey={(row) => row.test_id}
              columns={[
                { key: "test", header: "Test", className: "mono", sort: (row) => row.test_id, cell: (row) => row.test_id },
                { key: "category", header: "Category", sort: (row) => row.category, cell: (row) => row.category },
                {
                  key: "rate",
                  header: "Failure rate",
                  sort: (row) => row.failed / row.runs,
                  // Not ScoreBar: here a high number is bad, so the ramp is inverted.
                  cell: (row) => (
                    <>
                      <span className="bar-track bar-track-inline">
                        <span
                          className="bar-fill bar-fill-bad"
                          style={{ width: `${Math.round(row.rate * 100)}%` }}
                        />
                      </span>{" "}
                      {Math.round(row.rate * 100)}%
                    </>
                  ),
                },
                {
                  key: "seen",
                  header: "Seen",
                  sort: (row) => row.runs,
                  cell: (row) => `${row.failed} of ${row.runs} runs`,
                },
              ]}
            />
          </Panel>
        </>
      )}
    </>
  );
}
