import { useRef } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useView, Loading } from "../useView";
import { DataTable } from "../table";
import {
  EmptyState,
  formatMs,
  PageHeader,
  StatCard,
  StatusBadge,
  RiskBadge,
} from "../ui";

interface TestResultJson {
  test_id: string;
  category: string;
  risk: string;
  status: string;
  latency_ms: number | null;
}

interface PlanSelection {
  test_id: string;
  source: string;
  score: number;
  reasons: string[];
}

interface RunDetailView {
  run: { run_id: string; agent_name: string };
  report: {
    gate_passed: boolean;
    overall_score: number;
    pass_rate: number;
    passed: number;
    total: number;
    critical_failures: number;
  };
  results: TestResultJson[];
  matrix: Record<string, Record<string, string>>;
  categories: string[];
  duration_ms: number | null;
  plan: {
    profile: {
      domain: string;
      interface: string;
      risk_level: string;
      multi_turn: boolean;
      tool_use: boolean;
      notes: string[];
    } | null;
    selected: PlanSelection[];
    excluded: { test_id: string; source: string; reason: string }[];
  } | null;
  status_labels: Record<string, string>;
}

export function RunDetailPage() {
  const { runId = "" } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const filters = {
    q: params.get("q") ?? "",
    status: params.get("status") ?? "all",
    category: params.get("category") ?? "all",
  };
  const { view, error } = useView<RunDetailView>(`/runs/${encodeURIComponent(runId)}`, {
    q: filters.q,
    status: filters.status,
    category: filters.category,
  });
  const searchTimer = useRef<number | undefined>(undefined);

  if (error) return <EmptyState title="Run not available" body={error} />;
  if (!view) return <Loading />;
  const { run, report, plan } = view;

  const failures = view.results.filter((r) => r.status === "failed" || r.status === "error");

  const apply = (patch: Partial<typeof filters>) => {
    const next = new URLSearchParams({ ...filters, ...patch });
    for (const [key, value] of [...next.entries()]) if (!value || value === "all") next.delete(key);
    const query = next.toString();
    navigate(query ? `?${query}` : "?");
  };

  return (
    <>
      <p>
        <Link to="/runs">Back to runs</Link> · <Link to={`/agents/${encodeURIComponent(run.agent_name)}`}>{run.agent_name}</Link>
      </p>
      <PageHeader
        eyebrow="Run detail"
        title={
          <>
            Run <span className="mono">{run.run_id.slice(0, 8)}</span>
          </>
        }
        subtitle={<span className="mono">{run.run_id}</span>}
        actions={
          <Link className="button-link" data-testid="open-harness" to={`/runs/${runId}/harness`}>
            Open Harness
          </Link>
        }
      />

      <section className="stat-grid">
        <StatCard
          label="Gate"
          value={report.gate_passed ? "PASS" : "BLOCK"}
          note="release decision"
          tone={report.gate_passed ? undefined : "danger"}
        />
        <StatCard label="Overall" value={`${Math.floor(report.overall_score * 100)}%`} note="weighted score" />
        <StatCard
          label="Pass rate"
          value={`${Math.floor(report.pass_rate * 100)}%`}
          note={`${report.passed} of ${report.total} tests`}
        />
        <StatCard
          label="Critical failures"
          value={report.critical_failures}
          note="blocks safety gate"
          tone={report.critical_failures ? "danger" : undefined}
        />
      </section>

      {plan ? (
        <section className="panel">
          <div className="panel-header">
            <div>
              <h2>Why these tests</h2>
              <p>The profile discovered for this target, and the selection it justified.</p>
            </div>
          </div>
          {plan.profile ? (
            <div className="matrix-row">
              <span className="cat">profile</span>
              <StatusBadge status={plan.profile.domain} />
              <StatusBadge status={plan.profile.interface} />
              <StatusBadge status={plan.profile.risk_level} />
              <StatusBadge status={plan.profile.multi_turn ? "multi-turn" : "stateless"} />
              <StatusBadge status={plan.profile.tool_use ? "tool use" : "text only"} />
            </div>
          ) : null}
          {(plan.profile?.notes ?? []).map((note, i) => (
            <p key={i} className="quiet">
              {note}
            </p>
          ))}
          <div className="attention-list">
            {plan.selected.map((choice) => (
              <Link key={choice.test_id} className="attention-item" to={`/runs/${runId}/tests/${encodeURIComponent(choice.test_id)}`}>
                <span>{choice.test_id}</span>
                <StatusBadge status={choice.source} />
                <span>{choice.score}</span>
                <span className="quiet">{choice.reasons.join("; ")}</span>
              </Link>
            ))}
          </div>
          {(() => {
            const external = plan.selected.filter((s) => s.source !== "local");
            if (!external.length) return null;
            return (
              <p className="quiet">
                {external.length} selection(s) run in an external tool, so this run holds no evidence
                for them: {external.map((s) => s.test_id).join(", ")}.
              </p>
            );
          })()}
          {plan.excluded.length ? (
            <>
              <h3>Not tested ({plan.excluded.length})</h3>
              <ul className="quiet">
                {plan.excluded.map((item) => (
                  <li key={item.test_id}>
                    {item.test_id} ({item.source}): {item.reason}
                  </li>
                ))}
              </ul>
            </>
          ) : null}
        </section>
      ) : null}

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2>Evidence map</h2>
            <p>Category by test status, with direct links into each result.</p>
          </div>
        </div>
        {Object.entries(view.matrix).map(([cat, tests]) => (
          <div key={cat} className="matrix-row">
            <span className="cat">{cat}</span>
            {Object.entries(tests).map(([tid, status]) => (
              <Link key={tid} to={`/runs/${runId}/tests/${encodeURIComponent(tid)}`}>
                <StatusBadge status={status} label={tid} />
              </Link>
            ))}
          </div>
        ))}
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2>Failures for review</h2>
            <p>Prioritized queue before the full result list.</p>
          </div>
        </div>
        {!failures.length ? (
          <p className="quiet">No failed or errored tests in the current result set.</p>
        ) : (
          <div className="attention-list">
            {failures.map((r) => (
              <Link key={r.test_id} className="attention-item" to={`/runs/${runId}/tests/${encodeURIComponent(r.test_id)}`}>
                <span>{r.test_id}</span>
                <StatusBadge status={r.status} />
                <RiskBadge risk={r.risk} />
                <span>{r.latency_ms !== null ? `${formatMs(r.latency_ms)}` : "no latency"}</span>
              </Link>
            ))}
          </div>
        )}
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2>Results (failed first)</h2>
            <p>Filter locally recorded results while preserving links to each evidence page.</p>
          </div>
        </div>
        <form
          className="filter-bar"
          onSubmit={(event) => {
            event.preventDefault();
            apply({});
          }}
        >
          <label>
            Search
            <input type="search" name="q" defaultValue={filters.q} placeholder="Test or category" autoComplete="off"
              onChange={(e) => {
                // Debounced, matching the old poll.js filter behavior.
                window.clearTimeout(searchTimer.current);
                const value = e.target.value;
                searchTimer.current = window.setTimeout(() => apply({ q: value }), 350);
              }} />
          </label>
          <label>
            Status
            <select name="status" value={filters.status} onChange={(e) => apply({ status: e.target.value })}>
              {Object.entries(view.status_labels).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Category
            <select name="category" value={filters.category} onChange={(e) => apply({ category: e.target.value })}>
              <option value="all">All categories</option>
              {view.categories.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          <Link className="button-secondary" to={`/runs/${runId}`}>
            Reset
          </Link>
        </form>
        <DataTable
          caption="Every test in this run, with risk, outcome and latency"
          empty="No results match the current filters."
          rows={view.results}
          rowKey={(r) => r.test_id}
          columns={[
            {
              key: "test",
              header: "Test",
              cell: (r) => (
                <Link to={`/runs/${runId}/tests/${encodeURIComponent(r.test_id)}`}>
                  {r.test_id}
                </Link>
              ),
            },
            { key: "category", header: "Category", cell: (r) => r.category },
            { key: "risk", header: "Risk", cell: (r) => <RiskBadge risk={r.risk} /> },
            { key: "status", header: "Status", cell: (r) => <StatusBadge status={r.status} /> },
            { key: "latency", header: "Latency", cell: (r) => formatMs(r.latency_ms) },
          ]}
        />
      </section>
    </>
  );
}
