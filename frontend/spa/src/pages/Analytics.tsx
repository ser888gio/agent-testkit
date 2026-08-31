import { Link } from "react-router-dom";
import { useView, Loading } from "../components/useView";
import { Breadcrumb, EmptyState, PageHeader, Panel, StatCard, StatusBadge } from "../components/ui";
import { DataTable } from "../components/table";
import { DonutChart, PassFailBarChart, RateBarChart, ScoreAreaChart } from "../components/Chart";

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

  const trendData = trend.map((p) => ({ label: p.started_at.slice(0, 10), score: p.score }));
  // The gate rate is a share of runs, so the ring is pass vs the remainder.
  const passedRuns = Math.round((totals.gate_rate / 100) * totals.runs);
  const gateDonut = [
    { label: "Passed gate", value: passedRuns, color: "var(--pass-text)" },
    { label: "Failed gate", value: totals.runs - passedRuns, color: "var(--fail-text)" },
  ];
  const riskBars = view.risks.map((seg) => ({
    label: seg.risk,
    passed: seg.total - seg.failed,
    failed: seg.failed,
  }));
  const categoryBars = view.categories.map((row) => ({ label: row.label, percent: row.percent }));

  return (
    <>
      <Breadcrumb items={[{ label: "Analytics" }]} />
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
          <section className="summary-grid" aria-label="Portfolio summary">
            <Panel testid="chart-gate" titleId="gate-title" title="Gate outcome" blurb={<>Across the {totals.runs} most recent stored runs.</>}>
              <div className="summary-split">
                <DonutChart
                  data={gateDonut}
                  centerValue={`${totals.gate_rate}%`}
                  centerLabel="passed gate"
                />
                <dl className="summary-facts">
                  <div>
                    <dt>Runs recorded</dt>
                    <dd>{totals.runs}</dd>
                  </div>
                  <div>
                    <dt>Passed gate</dt>
                    <dd>{passedRuns}</dd>
                  </div>
                  <div>
                    <dt>Critical failures</dt>
                    <dd className={totals.critical ? "is-bad" : undefined}>{totals.critical}</dd>
                  </div>
                  <div>
                    <dt>Agents under test</dt>
                    <dd>{totals.agents}</dd>
                  </div>
                </dl>
              </div>
            </Panel>

            <section className="stat-grid stat-grid-compact">
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
          </section>

          <Panel
            testid="chart-trend"
            titleId="trend-title"
            title="Score trend"
            blurb={<>Weighted score of the last {trend.length} run(s), oldest to newest.</>}
          >
            <ScoreAreaChart data={trendData} />
          </Panel>

          <section className="detail-grid">
            <Panel
              testid="chart-categories"
              titleId="category-title"
              title="Failure rate by category"
              blurb={<>Share of results that failed or errored, worst first.</>}
            >
              {!categoryBars.length ? (
                <p className="quiet">No categorised results yet.</p>
              ) : (
                <RateBarChart data={categoryBars} height={Math.max(200, categoryBars.length * 34)} />
              )}
            </Panel>

            <Panel
              testid="chart-risk"
              titleId="risk-title"
              title="Coverage by risk"
              blurb={<>How much of the evidence sits at each risk level, and how much of it failed.</>}
            >
              {!riskBars.length ? (
                <p className="quiet">No results yet.</p>
              ) : (
                <>
                  <PassFailBarChart data={riskBars} />
                  <ul className="risk-legend">
                    {view.risks.map((seg) => (
                      <li key={seg.risk}>
                        <StatusBadge status={seg.risk} />
                        <span className="quiet">
                          {seg.total} results, {seg.failed} failed
                        </span>
                      </li>
                    ))}
                  </ul>
                </>
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
