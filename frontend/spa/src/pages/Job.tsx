import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError, apiGet, apiSend } from "../api";
import { EmptyState, ErrorNote, PageHeader, Panel, Spinner } from "../components/ui";

interface JobView {
  id: string;
  target_id: string;
  pack_id: string;
  state: string;
  run_id: string | null;
  error: string | null;
  tests_done: number;
  tests_total: number;
  running: boolean;
  recent: { test_id: string; status: string }[];
  message: string;
  discovery: boolean;
}

// Polls /jobs/{id}/status every 2s while the job is live; the same cadence the
// old poll.js used. Backoff on failure so an offline worker does not spin.
function useJobPolling(jobId: string, onStatus: (status: JobView) => void) {
  useEffect(() => {
    let alive = true;
    let failures = 0;
    let timer: number | undefined;

    const tick = () => {
      apiGet<JobView>(`/jobs/${encodeURIComponent(jobId)}/status`)
        .then((status) => {
          failures = 0;
          if (!alive) return;
          onStatus(status);
          if (status.running) timer = window.setTimeout(tick, 2000);
        })
        .catch(() => {
          failures += 1;
          if (!alive) return;
          timer = window.setTimeout(tick, Math.min(10000, 2000 * failures));
        });
    };
    tick();
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);
}

export function JobPage() {
  const { jobId = "" } = useParams();
  const navigate = useNavigate();
  const [job, setJob] = useState<JobView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const [rerunError, setRerunError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const followedRun = useRef<string | null>(null);

  useEffect(() => {
    apiGet<JobView>(`/jobs/${encodeURIComponent(jobId)}`).then(setJob).catch((err: unknown) => {
      setError(err instanceof ApiError ? err.detail : "Request failed.");
    });
  }, [jobId]);

  useJobPolling(jobId, (status) => {
    setJob((current) => (current ? { ...current, ...status } : status));
    // A queued job has no run until the worker finishes one; follow it.
    if (!status.running && status.run_id && followedRun.current !== status.run_id) {
      followedRun.current = status.run_id;
      navigate(`/runs/${status.run_id}`);
    }
  });

  if (error) return <EmptyState title="Job not available" body={error} />;
  if (!job) return <EmptyState title="Loading" body="Fetching job..." />;

  const cancel = async () => {
    setBusy(true);
    setCancelError(null);
    try {
      await apiSend(`/jobs/${encodeURIComponent(jobId)}/cancel`, "POST", {});
      setJob({ ...job, running: false, state: "cancelled", message: "Cancelled" });
    } catch (err) {
      setCancelError(err instanceof ApiError ? err.detail : "Cancellation failed.");
    } finally {
      setBusy(false);
    }
  };

  const rerun = async () => {
    setBusy(true);
    setRerunError(null);
    try {
      const result = await apiSend<{ job_id: string }>(
        `/jobs/${encodeURIComponent(jobId)}/rerun`,
        "POST",
        {},
      );
      setJob(null);
      navigate(`/jobs/${result.job_id}`);
    } catch (err) {
      setRerunError(err instanceof ApiError ? err.detail : "Re-run failed.");
    } finally {
      setBusy(false);
    }
  };

  const percent =
    job.tests_total > 0 ? Math.round((job.tests_done / job.tests_total) * 100) : 0;

  return (
    <>
      <PageHeader
        eyebrow={job.discovery ? "Queued discovery" : "Queued run"}
        title={
          <>
            Job <span className="mono">{job.id.slice(0, 8)}</span>
          </>
        }
        subtitle={
          <>
            {job.target_id} · {job.discovery ? "profiling the endpoint" : job.pack_id}
          </>
        }
      />

      <Panel titleId="job-status-title" title="Current Status">
        <p id="run-status" aria-live="polite">
          {job.running ? <Spinner /> : null} {job.message || job.state}
        </p>

        {job.running ? (
          <button type="button" onClick={cancel} disabled={busy} data-testid="job-cancel-submit">
            Abort run
          </button>
        ) : (
          <button type="button" onClick={rerun} disabled={busy} data-testid="job-rerun-submit">
            {job.discovery ? "Re-profile" : "Re-run"}
          </button>
        )}
        {cancelError ? <ErrorNote message={cancelError} /> : null}
        {rerunError ? <ErrorNote message={rerunError} /> : null}

        {/* Live progress off the job row. A run is written once, when it
            finishes, so nothing here reads a half-written run. */}
        <div className="run-progress" data-testid="run-progress" hidden={job.tests_total === 0}>
          <div
            className="progress-meter"
            role="progressbar"
            aria-label="Tests completed"
            aria-valuemin={0}
            aria-valuenow={job.tests_done}
            aria-valuemax={job.tests_total}
          >
            <span className="progress-fill" style={{ width: `${percent}%` }} />
          </div>
          <ul className="progress-list">
            {[...job.recent].reverse().map((entry, i) => (
              <li key={`${entry.test_id}-${i}`}>
                <span className="mono">{entry.test_id}</span>
                <span className={`badge badge-${entry.status}`}>{entry.status}</span>
              </li>
            ))}
          </ul>
        </div>
        {job.run_id ? (
          <p>
            <Link to={`/runs/${job.run_id}`}>View the run</Link>
          </p>
        ) : null}
        {job.discovery ? (
          <p>
            <Link to={`/agents/${job.target_id.split("/").map(encodeURIComponent).join("/")}`}>
              View the agent profile
            </Link>
          </p>
        ) : null}
      </Panel>
    </>
  );
}
