import { useState } from "react";
import { ApiError, apiSend } from "../api";
import { useView, Loading } from "../useView";
import { EmptyState, ErrorNote, PageHeader } from "../ui";

interface Candidate {
  id: string;
  promoted_id: string;
  category: string;
  risk: string;
  input: string;
  still_failing: boolean;
}

interface GeneratedView {
  candidates: Candidate[];
}

export function GeneratedPage() {
  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const { view, error, reload } = useView<GeneratedView>("/generated");

  const act = async (path: string, test_id: string) => {
    setBusyId(test_id);
    setActionError(null);
    try {
      await apiSend(path, "POST", { test_id });
      reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.detail : "Action failed.");
    } finally {
      setBusyId(null);
    }
  };

  if (error) return <EmptyState title="Could not load the review queue" body={error} />;
  if (!view) return <Loading />;

  return (
    <>
      <PageHeader
        eyebrow="Review queue"
        title="Generated tests"
        subtitle={
          <>
            Machine-authored attacks awaiting review. They run while provisional, then expire unless
            promoted. Promoting one adds it to the reviewed baseline and freezes its ID, which starts
            a fresh regression history for that test.
          </>
        }
      />
      {!view.candidates.length ? (
        <EmptyState
          title="Nothing to review"
          body="Run `agentaudit evolve` to generate candidate attacks."
        />
      ) : (
        <section className="panel">
          {actionError ? <ErrorNote message={actionError} /> : null}
          <table>
            <thead>
              <tr>
                <th scope="col">Test</th>
                <th scope="col">Category</th>
                <th scope="col">Risk</th>
                <th scope="col">Probe</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {view.candidates.map((c) => (
                <tr key={c.id} data-testid="generated-row">
                  <td>
                    <code>{c.id}</code>{" "}
                    {c.still_failing ? (
                      <span className="badge badge-failed" title="This test is currently catching a defect.">
                        catching a defect
                      </span>
                    ) : null}
                    <div className="quiet">
                      promotes to <code>{c.promoted_id}</code>
                    </div>
                  </td>
                  <td>{c.category}</td>
                  <td>{c.risk}</td>
                  <td className="truncate">{c.input}</td>
                  <td className="row-actions">
                    <button type="button" disabled={busyId === c.id} onClick={() => act("/generated/promote", c.id)} data-testid="promote">
                      Promote
                    </button>
                    <button
                      type="button"
                      className="button-secondary"
                      disabled={busyId === c.id}
                      onClick={() => act("/generated/reject", c.id)}
                      data-testid="reject"
                    >
                      Reject
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </>
  );
}
