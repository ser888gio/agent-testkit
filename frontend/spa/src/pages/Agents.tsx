import { Link } from "react-router-dom";
import { useView, Loading } from "../useView";
import { EmptyState, LinkButton, PageHeader, ScoreBar, StatusBadge } from "../ui";

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
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">Agent</th>
                <th scope="col">Type</th>
                <th scope="col">Runs</th>
                <th scope="col">Latest status</th>
                <th scope="col">Latest score</th>
                <th scope="col">First seen</th>
              </tr>
            </thead>
            <tbody>
              {view.agent_rows.map((row) => {
                const score = row.latest
                  ? Math.floor(row.latest.score.overall_score * 100)
                  : null;
                return (
                  <tr key={row.agent.id}>
                    <td data-label="Agent">
                      <Link to={`/agents/${encodeAgentId(row.agent.id)}`}>{row.agent.id}</Link>
                    </td>
                    <td data-label="Type">{row.agent.target_type}</td>
                    <td data-label="Runs">{row.run_count}</td>
                    {row.latest && score !== null ? (
                      <>
                        <td data-label="Latest status">
                          <StatusBadge status={row.latest.status} />
                        </td>
                        <td data-label="Latest score">
                          <ScoreBar value={score} label="Latest score" /> {score}%
                        </td>
                      </>
                    ) : (
                      <>
                        <td data-label="Latest status">-</td>
                        <td data-label="Latest score">-</td>
                      </>
                    )}
                    <td className="mono" data-label="First seen">
                      {row.agent.created_at.slice(0, 10)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

// Agent ids may be URL-shaped (e.g. "http://127.0.0.1:9911/"); keep their
// slashes as path segments, matching the server's {agent_id:path} converter.
export function encodeAgentId(id: string): string {
  return id.split("/").map(encodeURIComponent).join("/");
}
