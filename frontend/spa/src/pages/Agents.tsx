import { Link } from "react-router-dom";
import { useView, Loading } from "../useView";
import { EmptyState, LinkButton, PageHeader, ScoreBar, StatusBadge } from "../ui";
import { DataTable } from "../table";

interface AgentRow {
  agent: { id: string; target_type: string; created_at: string };
  latest: { status: string; score: { overall_score: number } } | null;
  run_count: number;
}

interface AgentsView {
  agent_rows: AgentRow[];
}

export function AgentsPage() {
  const { view, error } = useView<AgentsView>("/agents");

  if (error) return <EmptyState title="Could not load agents" body={error} />;
  if (!view) return <Loading />;

  return (
    <>
      <PageHeader
        eyebrow="Targets"
        title="Agents"
        subtitle="Each target keeps its own run history and latest pass/fail matrix."
        actions={
          <>
            <LinkButton href="/agents/register" testid="action-register-agent">
              Register Agent
            </LinkButton>
            <LinkButton href="/agents/connect" secondary>
              Run a Pack
            </LinkButton>
          </>
        }
      />
      {!view.agent_rows.length ? (
        <EmptyState
          title="No agents yet"
          body="Register an endpoint, or run a shipped pack, to record the first agent."
          actionLabel="Register Agent"
          actionHref="/agents/register"
        />
      ) : (
        <DataTable
          caption="Agents under test, with run counts and latest outcome"
          rows={view.agent_rows}
          rowKey={(row) => row.agent.id}
          columns={[
            {
              key: "agent",
              header: "Agent",
              cell: (row) => (
                <Link to={`/agents/${encodeAgentId(row.agent.id)}`}>{row.agent.id}</Link>
              ),
            },
            { key: "type", header: "Type", cell: (row) => row.agent.target_type },
            { key: "runs", header: "Runs", cell: (row) => row.run_count },
            {
              key: "status",
              header: "Latest status",
              cell: (row) => (row.latest ? <StatusBadge status={row.latest.status} /> : "-"),
            },
            {
              key: "score",
              header: "Latest score",
              cell: (row) => {
                if (!row.latest) return "-";
                const score = Math.floor(row.latest.score.overall_score * 100);
                return (
                  <>
                    <ScoreBar value={score} label="Latest score" /> {score}%
                  </>
                );
              },
            },
            {
              key: "seen",
              header: "First seen",
              className: "mono",
              cell: (row) => row.agent.created_at.slice(0, 10),
            },
          ]}
        />
      )}
    </>
  );
}

// Agent ids may be URL-shaped (e.g. "http://127.0.0.1:9911/"); keep their
// slashes as path segments, matching the server's {agent_id:path} converter.
export function encodeAgentId(id: string): string {
  return id.split("/").map(encodeURIComponent).join("/");
}
