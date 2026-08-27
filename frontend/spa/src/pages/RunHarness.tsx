import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useView, Loading } from "../useView";
import { EmptyState, formatMs, PageHeader, ScoreBar, StatCard, StatusBadge } from "../ui";

interface AssertionJson {
  name: string;
  passed: boolean;
  detail: string | null;
}

interface Finding {
  step: number;
  test_id: string;
  category: string;
  risk: string;
  status: string;
  latency_ms: number | null;
  started: string;
  assertions: AssertionJson[];
  summary: string;
}

interface HarnessView {
  summary: {
    gate: string;
    overall_score: number;
    pass_rate: number;
    critical_failures: number;
    passed: number;
    total: number;
  };
  context: {
    agent: string;
    run_id: string;
    started: string;
    finished: string;
    categories: string[];
    assertions: string[];
    duration_ms: number | null;
  };
  memory: {
    total: number;
    passed: number;
    state_changes: number;
    results: { test_id: string; status: string }[];
  };
  skills: {
    name: string;
    category: string;
    assertions: string[];
    passed: number;
    total: number;
    score: number;
  }[];
  findings: Finding[];
}

function Icon({ children }: { children: React.ReactNode }) {
  return (
    <svg className="export-icon" aria-hidden="true" viewBox="0 0 24 24">
      {children}
    </svg>
  );
}

// A page outline with a format mark, so the menu reads as "a file of this kind".
const FileIcon = ({ mark }: { mark: React.ReactNode }) => (
  <Icon>
    <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
    <path d="M14 3v5h5" />
    {mark}
  </Icon>
);

const EXPORTS = [
  {
    fmt: "pdf",
    label: "PDF",
    note: "Print-ready report",
    icon: <FileIcon mark={<path d="M8 17v-4h1.5a1.5 1.5 0 0 1 0 3H8m5 1v-4h1.5a1.5 1.5 0 0 1 1.5 1.5v1a1.5 1.5 0 0 1-1.5 1.5z" />} />,
  },
  {
    fmt: "html",
    label: "HTML",
    note: "Styled web report",
    icon: <FileIcon mark={<path d="M9.5 13.5 7.5 15.5l2 2m5-4 2 2-2 2" />} />,
  },
  {
    fmt: "md",
    label: "Markdown",
    note: "Plain text summary",
    icon: <FileIcon mark={<path d="M7.5 17.5v-4l2 2.5 2-2.5v4m3-4v4m0 0 1.5-1.5m-1.5 1.5L13 16" />} />,
  },
  {
    fmt: "json",
    label: "JSON",
    note: "Full structured data",
    icon: <FileIcon mark={<path d="M10 13.5c-1.5 0-1.5 1.5-1.5 2s0 2-1.5 2m6-4c1.5 0 1.5 1.5 1.5 2s0 2 1.5 2" />} />,
  },
  {
    fmt: "junit",
    label: "JUnit XML",
    note: "For CI pipelines",
    icon: <FileIcon mark={<path d="M8 13.5 6.5 15.5 8 17.5m6-4 1.5 2-1.5 2m-3.5 1 2-6" />} />,
  },
] as const;

function ExportMenu({ runId }: { runId: string }) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);

  // A menu that outlives a click elsewhere reads as stuck.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const href = (fmt: string) => `/api/runs/${encodeURIComponent(runId)}/export/${fmt}`;

  return (
    <div className="export-menu" ref={wrap}>
      <button
        type="button"
        data-testid="export-report"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <Icon>
          <path d="M12 3v12" />
          <path d="m7 10 5 5 5-5" />
          <path d="M5 21h14" />
        </Icon>
        Download report
        <Icon>
          <path d="m6 9 6 6 6-6" />
        </Icon>
      </button>
      {open ? (
        <div className="export-menu-list" role="menu">
          {EXPORTS.map(({ fmt, label, note, icon }) => (
            <a key={fmt} role="menuitem" href={href(fmt)} download onClick={() => setOpen(false)}>
              {icon}
              <span>
                <strong>{label}</strong>
                <small>{note}</small>
              </span>
            </a>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function RunHarnessPage() {
  const { runId = "" } = useParams();
  const { view, error } = useView<HarnessView>(`/runs/${encodeURIComponent(runId)}/harness`);

  if (error) return <EmptyState title="Harness not available" body={error} />;
  if (!view) return <Loading />;

  return (
    <>
      <p className="page-context">
        <Link to={`/runs/${runId}`}>
          Run <span className="mono">{runId.slice(0, 8)}</span>
        </Link>{" "}
        ·{" "}
        <Link to={`/agents/${encodeURIComponent(view.context.agent)}`}>{view.context.agent}</Link>
      </p>
      <PageHeader
        eyebrow="Page harness"
        title="Test Harness"
        subtitle="Inspect the environment, skills, memory and context, and the workflow recorded during this test run."
        actions={<ExportMenu runId={runId} />}
      />

      <section className="panel harness-status" aria-labelledby="harness-status-title">
        <div className="panel-header">
          <div>
            <h2 id="harness-status-title">Current Status</h2>
            <p id="run-status" aria-live="polite">
              Gate: {view.summary.gate}
            </p>
          </div>
          <StatusBadge status={view.summary.gate === "PASS" ? "passed" : "failed"} label={view.summary.gate} />
        </div>
        <div className="stat-grid">
          <StatCard label="Overall" value={`${view.summary.overall_score}%`} note="weighted score" testid="stat-overall" />
          <StatCard
            label="Pass Rate"
            value={`${view.summary.pass_rate}%`}
            note={`${view.summary.passed} of ${view.summary.total} tests`}
            testid="stat-pass-rate"
          />
          <StatCard
            label="Critical Findings"
            value={view.summary.critical_failures}
            note="blocks safety gate"
            tone={view.summary.critical_failures ? "danger" : undefined}
            testid="stat-critical-findings"
          />
          <StatCard label="Steps" value={view.findings.length} note="recorded workflow" testid="stat-steps" />
        </div>
      </section>

      <section className="detail-grid">
        <article className="panel">
          <div className="panel-header">
            <div>
              <h2>Harness Environment</h2>
              <p>Execution identity, timing, and coverage context.</p>
            </div>
          </div>
          <dl className="harness-meta">
            <div>
              <dt>Agent</dt>
              <dd>{view.context.agent}</dd>
            </div>
            <div>
              <dt>Run ID</dt>
              <dd className="mono">{view.context.run_id}</dd>
            </div>
            <div>
              <dt>Started</dt>
              <dd>{view.context.started}</dd>
            </div>
            <div>
              <dt>Finished</dt>
              <dd>{view.context.finished}</dd>
            </div>
            <div>
              <dt>Duration</dt>
              <dd>{view.context.duration_ms !== null ? formatMs(view.context.duration_ms) : "Unavailable"}</dd>
            </div>
            <div>
              <dt>Categories</dt>
              <dd>{view.context.categories.join(", ")}</dd>
            </div>
            <div>
              <dt>Assertions</dt>
              <dd>{view.context.assertions.join(", ")}</dd>
            </div>
          </dl>
        </article>

        <article className="panel">
          <div className="panel-header">
            <div>
              <h2>Skills</h2>
              <p>Capabilities exercised by this run.</p>
            </div>
          </div>
          <div className="skill-list">
            {view.skills.map((skill) => (
              <article key={skill.category} className="skill-card">
                <div>
                  <h3>{titleCase(skill.name)}</h3>
                  <p>
                    {skill.passed} of {skill.total} passed
                  </p>
                </div>
                <ScoreBar value={skill.score} label={`${skill.category} score`} />
                <small>{skill.assertions.join(", ")}</small>
              </article>
            ))}
          </div>
        </article>
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2>Memory &amp; Context</h2>
            <p>Memory/context probes and captured state changes. Agent-internal memory contents are not persisted.</p>
          </div>
        </div>
        <dl className="harness-meta harness-meta-summary">
          <div>
            <dt>Checks</dt>
            <dd>{view.memory.total}</dd>
          </div>
          <div>
            <dt>Passed</dt>
            <dd>
              {view.memory.passed} of {view.memory.total}
            </dd>
          </div>
          <div>
            <dt>State changes</dt>
            <dd>{view.memory.state_changes} captured</dd>
          </div>
        </dl>
        {view.memory.results.length ? (
          <ul className="memory-check-list">
            {view.memory.results.map((result) => (
              <li key={result.test_id}>
                <span className="mono">{result.test_id}</span>
                <StatusBadge status={result.status} />
              </li>
            ))}
          </ul>
        ) : (
          <p className="quiet memory-empty">No memory/context checks were included in this run.</p>
        )}
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2>Workflow / History</h2>
            <p>Chronological record of every test step and assertion outcome.</p>
          </div>
        </div>
        <ol className="finding-stream">
          {view.findings.map((finding) => (
            <li key={finding.test_id} className="finding-item">
              <div className="finding-main">
                <span className="mono">
                  Step {finding.step} · {finding.started}
                </span>
                <h3>{finding.test_id}</h3>
                <p>{finding.summary}</p>
              </div>
              <div className="finding-side">
                <StatusBadge status={finding.status} />
                <StatusBadge status={finding.risk} />
                <span>
                  {finding.latency_ms !== null ? formatMs(finding.latency_ms) : "no latency"}
                </span>
              </div>
              <ul className="assertion-list">
                {finding.assertions.map((assertion) => (
                  <li key={assertion.name} className={assertion.passed ? "pass" : "fail"}>
                    <strong>{assertion.name}</strong>
                    <span>{assertion.passed ? "pass" : `fail - ${assertion.detail}`}</span>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ol>
      </section>
    </>
  );
}

function titleCase(value: string): string {
  return value.replace(/\b\w/g, (c) => c.toUpperCase());
}
