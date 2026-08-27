import { Link, useParams } from "react-router-dom";
import { useView, Loading } from "../useView";
import { EmptyState, formatMs, PageHeader, Panel, RiskBadge, StatCard, StatusBadge } from "../ui";

interface AssertionJson {
  name: string;
  passed: boolean;
  detail: string | null;
}

interface ResultJson {
  test_id: string;
  category: string;
  risk: string;
  status: string;
  latency_ms: number | null;
  error: string | null;
  // Evidence fields are whatever the agent and sandbox produced: a plain string
  // for a text agent, but an object for an HTTP one ({text, raw, status_code,
  // error}) or a sandbox diff ({added, removed, changed}). They were typed as
  // `string | null`, which was wrong and crashed the page -- React refuses an
  // object as a child, so the whole route rendered blank. Render via evidence().
  request: unknown;
  response: unknown;
  sandbox_diff: unknown;
  assertion_results: AssertionJson[];
}

// Evidence is already redacted on the way into the store, so this only has to
// make it printable.
function evidence(value: unknown, empty = ""): string {
  if (value === null || value === undefined) return empty;
  if (typeof value === "string") return value || empty;
  return JSON.stringify(value, null, 2);
}

interface TimelineEvent {
  kind: string;
  data: Record<string, unknown>;
  ts: string;
}

interface TimelineTurn {
  index: number;
  input: string;
  events: TimelineEvent[];
}

interface Timeline {
  turns: TimelineTurn[];
  final_response: unknown;
  first_divergence: number | null;
  windowed: boolean;
  omitted_before: number;
  omitted_after: number;
}

interface TestDetailView {
  run: { run_id: string; agent_name: string };
  result: ResultJson;
  selection: { source: string; score: number; reasons: string[] } | null;
  previous_result: { test_id: string } | null;
  next_result: { test_id: string } | null;
  history: { run_id: string; status: string; started_at: string }[];
  artifact_states: { name: string; state: string; detail: string }[];
  timeline: Timeline | null;
}

export function TestDetailPage() {
  const { runId = "", testId = "" } = useParams();
  const { view, error } = useView<TestDetailView>(
    `/runs/${encodeURIComponent(runId)}/tests/${encodeURIComponent(testId)}`,
  );

  if (error) return <EmptyState title="Result not available" body={error} />;
  if (!view) return <Loading />;
  const { run, result } = view;
  const passed = result.assertion_results.filter((a) => a.passed).length;
  const failedCount = result.assertion_results.length - passed;
  const historyFailures = view.history.filter(
    (h) => h.status === "failed" || h.status === "error",
  ).length;

  const historySentence =
    view.history.length < 2
      ? `First recorded run of this test against ${run.agent_name}.`
      : historyFailures === 0
        ? `Passed every one of the last ${view.history.length} runs against ${run.agent_name}.`
        : `Failed ${historyFailures} of the last ${view.history.length} runs against ${run.agent_name}.`;

  return (
    <>
      <p>
        <Link to={`/runs/${runId}`}>
          Run <span className="mono">{run.run_id.slice(0, 8)}</span>
        </Link>{" "}
        ·{" "}
        <Link to={`/agents/${encodeURIComponent(run.agent_name)}`}>{run.agent_name}</Link>
      </p>
      <PageHeader eyebrow="Test evidence" title={result.test_id} />

      <section className="stat-grid">
        <StatCard
          label="Status"
          value={result.status}
          note="latest result"
          tone={result.status === "failed" || result.status === "error" ? "danger" : undefined}
        />
        <StatCard label="Category" value={result.category} note="coverage area" />
        <StatCard
          label="Risk"
          value={<RiskBadge risk={result.risk} />}
          note="impact weighting"
          tone={result.risk === "critical" ? "danger" : undefined}
        />
        <StatCard
          label="Latency"
          value={formatMs(result.latency_ms)}
          note="agent response time"
        />
      </section>

      {view.selection ? (
        <Panel title="Why this test ran" blurb={<>Selected from {view.selection.source} with a relevance score of {view.selection.score}.</>}>
          <ul className="quiet">
            {view.selection.reasons.map((reason, i) => (
              <li key={i}>{reason}</li>
            ))}
          </ul>
        </Panel>
      ) : null}

      <section className="detail-grid">
        <Panel title="Failure context" blurb={<>Assertion outcome, error text, and neighboring results.</>}>
          <div className="assertion-summary">
            <span className="pass">{passed} passed</span>
            <span className={failedCount ? "fail" : undefined}>{failedCount} failed</span>
          </div>
          {result.error ? (
            <>
              <h3>Error</h3>
              <pre className="fail">{result.error}</pre>
            </>
          ) : null}
          <div className="pager">
            {view.previous_result ? (
              <Link to={`/runs/${runId}/tests/${encodeURIComponent(view.previous_result.test_id)}`}>
                Previous: {view.previous_result.test_id}
              </Link>
            ) : (
              <span />
            )}
            {view.next_result ? (
              <Link to={`/runs/${runId}/tests/${encodeURIComponent(view.next_result.test_id)}`}>
                Next: {view.next_result.test_id}
              </Link>
            ) : null}
          </div>
        </Panel>

        <Panel title="Artifacts">
          <ul className="artifact-list">
            {view.artifact_states.map((a) => (
              <li key={a.name}>
                <strong>{a.name}</strong>
                <span>{a.state}</span>
                <small>{a.detail}</small>
              </li>
            ))}
          </ul>
        </Panel>
      </section>

      <Panel title="Assertions">
        <ul className="assertion-list">
          {result.assertion_results.map((a) => (
            <li key={a.name} className={a.passed ? "pass" : "fail"}>
              <strong>{a.name}</strong>
              <span>{a.passed ? "pass" : `fail - ${a.detail}`}</span>
            </li>
          ))}
        </ul>
      </Panel>

      <section className="detail-grid">
        <Panel title="Request">
          <pre>{evidence(result.request)}</pre>
        </Panel>

        <Panel title="Response (redacted)">
          {/* Redaction happened before storage; markers render as-is. */}
          <pre>{evidence(result.response)}</pre>
        </Panel>
      </section>

      <Panel title="Sandbox diff">
        <pre>{evidence(result.sandbox_diff, "No sandbox changes were recorded.")}</pre>
      </Panel>

      {view.timeline ? (
        <Panel testid="test-timeline" title="Timeline" blurb={<>Turn-by-turn requests and sandbox events. The first turn where this test's failure appears is highlighted.</>}>
          <ol className="timeline">
            {view.timeline.omitted_before ? (
              <li className="quiet">... {view.timeline.omitted_before} earlier turn(s) omitted ...</li>
            ) : null}
            {view.timeline.turns.map((turn) => (
              <li
                key={turn.index}
                className={turn.index === view.timeline!.first_divergence ? "fail" : undefined}
              >
                <strong>Turn {turn.index}:</strong> {turn.input}
                {turn.index === view.timeline!.first_divergence ? (
                  <span className="fail"> &larr; first divergence</span>
                ) : null}
                {turn.events.length ? (
                  <ul className="quiet">
                    {turn.events.map((event, i) => (
                      <li key={i}>
                        [{event.kind}] {JSON.stringify(event.data)}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </li>
            ))}
            {view.timeline.omitted_after ? (
              <li className="quiet">... {view.timeline.omitted_after} later turn(s) omitted ...</li>
            ) : null}
          </ol>
        </Panel>
      ) : null}

      <section className="panel" aria-labelledby="history-title" data-testid="test-history">
        <div className="panel-header">
          <div>
            <h2 id="history-title">History for this test</h2>
            <p>{historySentence}</p>
          </div>
        </div>
        {/* A strip of outcomes reads as a pattern faster than a table. */}
        <ol className="history-strip">
          {[...view.history].reverse().map((entry) => (
            <li key={`${entry.run_id}-${entry.started_at}`}>
              {/* The badge label is a single letter, so without aria-label the
                  accessible name of this link is "F". title alone does not
                  reach a keyboard or touch user. */}
              <Link
                to={`/runs/${entry.run_id}/tests/${encodeURIComponent(testId)}`}
                title={`${entry.started_at.slice(0, 16).replace("T", " ")} - ${entry.status}`}
                aria-label={`${entry.started_at.slice(0, 16).replace("T", " ")} - ${entry.status}`}
              >
                <StatusBadge
                  status={entry.status}
                  label={entry.status.charAt(0).toUpperCase()}
                />
              </Link>
            </li>
          ))}
        </ol>
        <p className="quiet history-legend">
          <span>{view.history.length ? view.history[view.history.length - 1].started_at.slice(0, 10) : ""}</span>
          <span>oldest to newest</span>
          <span>{view.history.length ? view.history[0].started_at.slice(0, 10) : ""}</span>
        </p>
      </section>
    </>
  );
}
