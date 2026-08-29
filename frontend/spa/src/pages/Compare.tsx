import { Link, useSearchParams } from "react-router-dom";
import { useView, Loading } from "../components/useView";
import { EmptyState, PageHeader, Panel, StatCard, StatusBadge } from "../components/ui";
import { DataTable } from "../components/table";
import { DeltaList } from "../components/DeltaList";

interface TestDelta {
  test_id: string;
  before: string | null;
  after: string | null;
  latency_before_ms: number | null;
  latency_after_ms: number | null;
}

interface RunDiff {
  newly_failing: string[];
  newly_passing: string[];
  still_failing: string[];
  added: string[];
  removed: string[];
  latency_deltas: TestDelta[];
  score_delta: Record<string, number>;
  critical_regressions: string[];
}

export function ComparePage() {
  const [params] = useSearchParams();
  const a = params.get("a") ?? "";
  const b = params.get("b") ?? "";
  const { view, error } = useView<{ diff: RunDiff }>(
    "/compare",
    a && b ? { a, b } : undefined,
  );

  if (!a || !b) {
    return (
      <EmptyState
        title="Two runs required"
        body="Open a comparison from a run page with ?a=<run_id>&b=<run_id>."
        actionLabel="Back to runs"
        actionHref="/runs"
      />
    );
  }
  if (error) return <EmptyState title="Comparison not available" body={error} />;
  if (!view) return <Loading />;
  const { diff } = view;

  return (
    <>
      <p>
        <Link to={`/runs/${a}`}>
          Run <span className="mono">{a.slice(0, 8)}</span>
        </Link>{" "}
        ·{" "}
        <Link to={`/runs/${b}`}>
          Run <span className="mono">{b.slice(0, 8)}</span>
        </Link>
      </p>
      <PageHeader
        eyebrow="Run comparison"
        title={
          <>
            Compare <span className="mono">{a.slice(0, 8)}</span> to{" "}
            <span className="mono">{b.slice(0, 8)}</span>
          </>
        }
      />

      {diff.critical_regressions.length ? (
        <p className="form-error" role="alert">
          Critical regressions: {diff.critical_regressions.join(", ")}
        </p>
      ) : null}

      <section className="stat-grid">
        <StatCard
          label="Newly failing"
          value={diff.newly_failing.length}
          note="was passing or absent"
          tone={diff.newly_failing.length ? "danger" : undefined}
        />
        <StatCard label="Newly passing" value={diff.newly_passing.length} note="recovered tests" />
        <StatCard
          label="Still failing"
          value={diff.still_failing.length}
          note="known failures"
          tone={diff.still_failing.length ? "danger" : undefined}
        />
        <StatCard
          label="Changed coverage"
          value={diff.added.length + diff.removed.length}
          note="added or removed"
        />
      </section>

      <section className="detail-grid">
        <Panel title={<>Newly failing ({diff.newly_failing.length})</>}>
          <ul>
            <DeltaList items={diff.newly_failing} tone="status-failed" />
          </ul>
        </Panel>
        <Panel title={<>Newly passing ({diff.newly_passing.length})</>}>
          <ul>
            <DeltaList items={diff.newly_passing} tone="status-passed" />
          </ul>
        </Panel>
      </section>

      <Panel title={<>Still failing ({diff.still_failing.length})</>}>
        <ul>
          <DeltaList items={diff.still_failing} tone="status-failed" />
        </ul>
      </Panel>

      <Panel title="Added / Removed">
        <p>Added: {diff.added.join(", ") || "none"}</p>
        <p>Removed: {diff.removed.join(", ") || "none"}</p>
      </Panel>

      <Panel title="Score delta">
        <DataTable
          caption="Score metrics and how they changed between the two runs"
          rows={Object.entries(diff.score_delta)}
          rowKey={([key]) => key}
          columns={[
            { key: "metric", header: "Metric", sort: ([key]) => key, cell: ([key]) => key },
            {
              key: "delta",
              header: "Delta",
              sort: ([, value]) => value,
              cell: ([, value]) => `${value >= 0 ? "+" : ""}${(value * 100).toFixed(1)}%`,
            },
          ]}
        />
      </Panel>

      <Panel title="Latency deltas">
        <DataTable
          caption="Per-test status and latency, before and after"
          rows={diff.latency_deltas}
          rowKey={(d) => d.test_id}
          columns={[
            { key: "test", header: "Test", sort: (d) => d.test_id, cell: (d) => d.test_id },
            {
              key: "before",
              header: "Before status",
              sort: (d) => d.before ?? "",
              cell: (d) => (d.before ? <StatusBadge status={d.before} /> : "-"),
            },
            {
              key: "after",
              header: "After status",
              sort: (d) => d.after ?? "",
              cell: (d) => (d.after ? <StatusBadge status={d.after} /> : "-"),
            },
            { key: "before-ms", header: "Before (ms)", sort: (d) => d.latency_before_ms ?? -1, cell: (d) => d.latency_before_ms },
            { key: "after-ms", header: "After (ms)", sort: (d) => d.latency_after_ms ?? -1, cell: (d) => d.latency_after_ms },
          ]}
        />
      </Panel>
    </>
  );
}
