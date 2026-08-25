import { Link } from "react-router-dom";
import { useView, Loading } from "../useView";
import { EmptyState, PageHeader, ScoreBar, StatusBadge } from "../ui";

type HarnessRow = {
  id: string;
  short_id: string;
  agent_id: string;
  started: string;
  status: string;
  score_percent: number;
  total: number;
};

export function HarnessIndexPage() {
  const { view, error } = useView<{ harnesses: HarnessRow[] }>("/harnesses");

  if (error) return <EmptyState title="Could not load harnesses" body={error} />;
  if (!view) return <Loading />;

  return (
    <>
      <PageHeader
        eyebrow="Page harness"
        title="Test Harnesses"
        subtitle="One harness per recorded run: the environment it executed in, the skills it exercised, and the workflow it produced. Open one to inspect or export it."
      />
      {!view.harnesses.length ? (
        <EmptyState
          title="No harness data yet"
          body="Run a test pack to populate the harness environment and workflow history."
          actionLabel="View runs"
          actionHref="/runs"
        />
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">Harness</th>
                <th scope="col">Agent</th>
                <th scope="col">Started</th>
                <th scope="col">Gate</th>
                <th scope="col">Score</th>
                <th scope="col">Steps</th>
              </tr>
            </thead>
            <tbody>
              {view.harnesses.map((h) => (
                <tr key={h.id} data-testid="harness-row">
                  <td data-label="Harness">
                    <Link className="mono" to={`/runs/${h.id}/harness`}>
                      {h.short_id}
                    </Link>
                  </td>
                  <td data-label="Agent">
                    <Link to={`/agents/${h.agent_id.split("/").map(encodeURIComponent).join("/")}`}>
                      {h.agent_id}
                    </Link>
                  </td>
                  <td data-label="Started" className="mono">
                    {h.started}
                  </td>
                  <td data-label="Gate">
                    <StatusBadge status={h.status} />
                  </td>
                  <td data-label="Score">
                    <ScoreBar value={h.score_percent} label="Harness score" /> {h.score_percent}%
                  </td>
                  <td data-label="Steps">{h.total}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
