import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError, apiGet, apiSend } from "../api";
import { Breadcrumb, EmptyState, ErrorNote, PageHeader, Panel, Spinner } from "../components/ui";

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
  steps: { name: string; label: string; state: string; detail: string }[];
  message: string;
  discovery: boolean;
  created_at: string | null;
  started_at: string | null;
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

/** m:ss elapsed since `since`, or null when there is no usable timestamp. */
function useElapsed(since: string | null | undefined, live: boolean): string | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!live) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [live]);
  if (!since) return null;
  // Job timestamps carry an offset, but older rows may not; without a marker a
  // browser reads them as local time and the counter starts hours out.
  const started = Date.parse(/[Zz]|[+-]\d\d:?\d\d$/.test(since) ? since : `${since}Z`);
  if (Number.isNaN(started)) return null;
  const seconds = Math.max(0, Math.floor((now - started) / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
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
  const cancelRequested = useRef(false);

  useEffect(() => {
    apiGet<JobView>(`/jobs/${encodeURIComponent(jobId)}`).then(setJob).catch((err: unknown) => {
      setError(err instanceof ApiError ? err.detail : "Request failed.");
    });
  }, [jobId]);

  useJobPolling(jobId, (status) => {
    // Cancel is cooperative: the worker only notices between tests, so a poll
    // already in flight can still report running:true after Abort is clicked.
    // Keep showing "Cancelling..." rather than let it stomp the optimistic state.
    if (cancelRequested.current && status.running) return;
    setJob((current) => (current ? { ...current, ...status } : status));
    // A queued job has no run until the worker finishes one; follow it.
    if (!status.running && status.run_id && followedRun.current !== status.run_id) {
      followedRun.current = status.run_id;
      navigate(`/runs/${status.run_id}`);
    }
  });

  // Before the early returns below: hooks may not sit behind a conditional.
  // Queued jobs have no started_at yet, so fall back to when it was enqueued.
  const elapsed = useElapsed(job?.started_at ?? job?.created_at, job?.running ?? false);

  if (error) return <EmptyState title="Job not available" body={error} />;
  if (!job) return <EmptyState title="Loading" body="Fetching job..." />;

  const cancel = async () => {
    setBusy(true);
    setCancelError(null);
    try {
      await apiSend(`/jobs/${encodeURIComponent(jobId)}/cancel`, "POST", {});
      cancelRequested.current = true;
      setJob({ ...job, running: false, state: "cancelled", message: "Cancelling..." });
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
      <Breadcrumb items={[{ label: "Runs", href: "/runs" }, { label: `Job ${job.id.slice(0, 8)}` }]} />
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
          {/* A live job with no visible movement reads as a hung one. */}
          {elapsed ? <span className="job-elapsed mono">{elapsed}</span> : null}
        </p>

        {/* Pipeline left, live results right: the stepper is narrow, and the
            result list needs somewhere to grow once tests start landing. */}
        <div className="job-live">
          <div className="job-live-pipeline">
            {/* The stages before the first test result -- resolving the target,
                confirming the request shape, planning -- used to be one spinner.
                The worker names the stage it is in; ordering makes the rest. */}
            <ol className="stepper" data-testid="job-steps">
          {(job.steps ?? []).map((step, index) => (
            <li key={step.name} className={`step step-${step.state}`}>
              <span className="step-marker" aria-hidden="true">
                {step.state === "done" ? "✓" : index + 1}
              </span>
              <span className="step-body">
                <span className="step-label">{step.label}</span>
                {step.detail ? <span className="step-detail">{step.detail}</span> : null}
              </span>
            </li>
          ))}
        </ol>

        {/* Abort is secondary: destructive, and not the point of this page. */}
        {job.running ? (
          <button
            type="button"
            className="button-secondary"
            onClick={cancel}
            disabled={busy}
            data-testid="job-cancel-submit"
          >
            Abort run
          </button>
        ) : (
          <button type="button" onClick={rerun} disabled={busy} data-testid="job-rerun-submit">
            {job.discovery ? "Re-profile" : "Re-run"}
          </button>
        )}
        {cancelError ? <ErrorNote message={cancelError} /> : null}
        {rerunError ? <ErrorNote message={rerunError} /> : null}
          </div>

          {/* Live progress off the job row. A run is written once, when it
              finishes, so nothing here reads a half-written run. */}
          <div className="run-progress" data-testid="run-progress" hidden={job.tests_total === 0}>
            {/* At 0% a determinate bar is an empty rail, indistinguishable from
                a stalled one. Until the first test lands, show motion instead. */}
            <div
              className={`progress-meter${job.running && job.tests_done === 0 ? " progress-meter-waiting" : ""}`}
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
