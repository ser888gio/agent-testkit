import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useView, Loading } from "../useView";
import { DataTable } from "../table";
import { EmptyState, PageHeader, Panel, ScoreBar, StatCard, StatusBadge } from "../ui";

interface RunRowView {
  id: string;
  short_id: string;
  agent_id: string;
  started: string;
  launched_by: string;
  status: string;
  score_percent: number;
  critical_failures: number;
  failed: number;
  passed: number;
  needs_attention: boolean;
}

interface RunsView {
  runs: RunRowView[];
  all_runs: RunRowView[];
  attention: RunRowView[];
  agents: string[];
  stats: {
    total_runs: number;
    failed_runs: number;
    critical_failures: number;
    avg_score: number;
  };
  status_labels: Record<string, string>;
}

export function RunsPage() {
  const [params] = useSearchParams();
  const filters = {
    q: params.get("q") ?? "",
    status: params.get("status") ?? "all",
    agent: params.get("agent") ?? "all",
    sort: params.get("sort") ?? "attention",
  };
  const { view, error } = useView<RunsView>("/runs", {
    q: filters.q,
    status: filters.status,
    agent: filters.agent,
    sort: filters.sort,
  });

  if (error) return <EmptyState title="Could not load runs" body={error} />;
  if (!view) return <Loading />;
  const { stats } = view;

  return (
    <>
      <PageHeader
        eyebrow="Run operations"
        title="Runs"
        subtitle="Every recorded run, failure-first. Connect an agent or author a test to add more."
      />

      {!view.all_runs.length ? (
        <EmptyState
          title="No runs yet"
          body="Run your first pack with agentaudit run <packs_dir> --target <config.yaml>."
          actionLabel="View tests"
          actionHref="/tests"
        />
      ) : (
        <>
          <section className="stat-grid" aria-label="Run summary">
            <StatCard label="Runs" value={stats.total_runs} note="latest 100 recorded" testid="stat-runs" />
            <StatCard
              label="Needs attention"
              value={stats.failed_runs}
              note="failed or blocked gates"
              tone={stats.failed_runs ? "danger" : undefined}
              testid="stat-attention"
            />
            <StatCard
              label="Critical failures"
              value={stats.critical_failures}
              note="across stored runs"
              tone={stats.critical_failures ? "danger" : undefined}
              testid="stat-critical"
            />
            <StatCard label="Average score" value={`${stats.avg_score}%`} note="weighted by risk" testid="stat-avg-score" />
          </section>

          <Panel title="Needs attention" blurb={<>Failure-first queue, inspired by Cypress review flows and Playwright's shortest path to evidence.</>}>
            {!view.attention.length ? (
              <p className="quiet">No failed gates or critical failures in the latest runs.</p>
            ) : (
              <div className="attention-list">
                {view.attention.map((r) => (
                  <Link key={r.id} className="attention-item" data-testid="attention-row" to={`/runs/${r.id}`}>
                    <span className="mono">{r.short_id}</span>
                    <span>{r.agent_id}</span>
                    <StatusBadge status={r.status} />
                    <span>{r.failed} failed</span>
                    <span className={r.critical_failures ? "critical-count" : undefined}>
                      {r.critical_failures} critical
                    </span>
                  </Link>
                ))}
              </div>
            )}
          </Panel>

          <Panel title="Recent runs" blurb={<>Search, filter, and sort before opening a run.</>}>
            <RunsFilterBar filters={filters} agents={view.agents} labels={view.status_labels} />
            <DataTable
              empty="No runs match the current filters."
                caption="Recorded runs, with gate, score and evidence counts"
                rows={view.runs}
                rowKey={(r) => r.id}
                rowTestId="run-row"
                columns={[
                  {
                    key: "run",
                    header: "Run",
                    cell: (r) => (
                      <Link className="mono" to={`/runs/${r.id}`}>
                        {r.short_id}
                      </Link>
                    ),
                  },
                  {
                    key: "agent",
                    header: "Agent",
                    cell: (r) => (
                      <Link to={`/agents/${encodeURIComponent(r.agent_id)}`}>{r.agent_id}</Link>
                    ),
                  },
                  { key: "started", header: "Started", className: "mono", cell: (r) => r.started },
                  { key: "launched", header: "Launched by", cell: (r) => r.launched_by },
                  { key: "gate", header: "Gate", cell: (r) => <StatusBadge status={r.status} /> },
                  {
                    key: "score",
                    header: "Score",
                    cell: (r) => (
                      <>
                        <ScoreBar value={r.score_percent} label="Overall score" />{" "}
                        <span>{r.score_percent}%</span>
                      </>
                    ),
                  },
                  {
                    key: "evidence",
                    header: "Evidence",
                    cell: (r) => (
                      <>
                        <span className={r.critical_failures ? "critical-count" : undefined}>
                          {r.critical_failures}
                        </span>{" "}
                        critical, {r.failed} failed
                      </>
                    ),
                  },
                  {
                    key: "harness",
                    header: "Harness",
                    cell: (r) => <Link to={`/runs/${r.id}/harness`}>View</Link>,
                  },
                ]}
            />
          </Panel>
        </>
      )}
    </>
  );
}

function RunsFilterBar({
  filters,
  agents,
  labels,
}: {
  filters: { q: string; status: string; agent: string; sort: string };
  agents: string[];
  labels: Record<string, string>;
}) {
  const navigate = useNavigate();
  const [q, setQ] = useState(filters.q);
  // Keep the box in sync when navigation resets the filters.
  useEffect(() => setQ(filters.q), [filters.q]);

  const apply = (patch: Partial<typeof filters>) => {
    const next = new URLSearchParams({ ...filters, ...patch } as Record<string, string>);
    for (const [key, value] of [...next.entries()]) {
      if ((key === "q" && !value) || value === "all") next.delete(key);
    }
    const query = next.toString();
    navigate(query ? `?${query}` : "?");
  };

  return (
    <form
      className="filter-bar"
      onSubmit={(event) => {
        event.preventDefault();
        apply({ q });
      }}
    >
      <label>
        Search
        <input
          type="search"
          name="q"
          value={q}
          placeholder="Run or agent"
          autoComplete="off"
          onChange={(event) => setQ(event.target.value)}
        />
      </label>
      <label>
        Status
        <select name="status" value={filters.status} onChange={(e) => apply({ status: e.target.value })}>
          {Object.entries(labels).map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <label>
        Agent
        <select name="agent" value={filters.agent} onChange={(e) => apply({ agent: e.target.value })}>
          <option value="all">All agents</option>
          {agents.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
      </label>
      <label>
        Sort
        <select name="sort" value={filters.sort} onChange={(e) => apply({ sort: e.target.value })}>
          <option value="attention">Needs attention</option>
          <option value="score">Lowest score</option>
          <option value="agent">Agent</option>
        </select>
      </label>
      <Link className="button-secondary" to="/runs">
        Reset
      </Link>
    </form>
  );
}
