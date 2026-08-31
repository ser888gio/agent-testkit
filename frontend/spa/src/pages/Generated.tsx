import { useState } from "react";
import { ApiError, apiSend } from "../api";
import { useView, Loading } from "../components/useView";
import { Breadcrumb, EmptyState, ErrorNote, PageHeader } from "../components/ui";
import { DataTable } from "../components/table";

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
      <Breadcrumb items={[{ label: "Generated" }]} />
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
          <DataTable
            caption="Machine-authored candidate attacks awaiting review"
            rows={view.candidates}
            rowKey={(c) => c.id}
            rowTestId="generated-row"
            columns={[
              {
                key: "test",
                header: "Test",
                sort: (c) => c.promoted_id || c.id,
                cell: (c) => (
                  <>
                    <code>{c.id}</code>{" "}
                    {c.still_failing ? (
                      <span
                        className="badge badge-failed"
                        title="This test is currently catching a defect."
                        aria-label="This test is currently catching a defect."
                      >
                        catching a defect
                      </span>
                    ) : null}
                    <div className="quiet">
                      promotes to <code>{c.promoted_id}</code>
                    </div>
                  </>
                ),
              },
              { key: "category", header: "Category", sort: (c) => c.category, cell: (c) => c.category },
              { key: "risk", header: "Risk", sort: (c) => c.risk, cell: (c) => c.risk },
              { key: "probe", header: "Probe", className: "truncate", sort: (c) => c.input, cell: (c) => c.input },
              {
                key: "actions",
                header: "Actions",
                className: "row-actions",
                cell: (c) => (
                  <>
                    <button
                      type="button"
                      disabled={busyId === c.id}
                      onClick={() => act("/generated/promote", c.id)}
                      data-testid="promote"
                    >
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
                  </>
                ),
              },
            ]}
          />
        </section>
      )}
    </>
  );
}
