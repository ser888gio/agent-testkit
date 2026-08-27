import { Link, useParams } from "react-router-dom";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { ChevronDown, Download } from "lucide-react";
import { useView, Loading } from "../useView";
import { EmptyState, formatMs, PageHeader, Panel, ScoreBar, StatCard, StatusBadge } from "../ui";

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

// Radix owns the menu behaviour. The hand-rolled version declared role="menu"
// and role="menuitem" but implemented only outside-click and Escape -- no arrow
// keys, no focus trap, no focus return to the trigger. Announcing the menu
// pattern to a screen reader and then not providing it is worse than not
// announcing it, since the user is told to expect keys that do nothing.
function ExportMenu({ runId }: { runId: string }) {
  const href = (fmt: string) => `/api/runs/${encodeURIComponent(runId)}/export/${fmt}`;

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button type="button" data-testid="export-report" className="export-menu-trigger">
          <Download className="export-icon" aria-hidden="true" />
          Download report
          <ChevronDown className="export-icon" aria-hidden="true" />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          className="export-menu-list"
          aria-label="Report formats"
          align="end"
          sideOffset={6}
        >
          {EXPORTS.map(({ fmt, label, note, icon }) => (
            <DropdownMenu.Item key={fmt} asChild>
              <a href={href(fmt)} download>
                {icon}
                <span>
                  <strong>{label}</strong>
                  <small>{note}</small>
                </span>
              </a>
            </DropdownMenu.Item>
          ))}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
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
        <Panel title="Harness Environment" blurb={<>Execution identity, timing, and coverage context.</>}>
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
        </Panel>

        <Panel title="Skills" blurb={<>Capabilities exercised by this run.</>}>
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
        </Panel>
      </section>

      <Panel title="Memory &amp; Context" blurb={<>Memory/context probes and captured state changes. Agent-internal memory contents are not persisted.</>}>
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
      </Panel>

      <Panel title="Workflow / History" blurb={<>Chronological record of every test step and assertion outcome.</>}>
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
      </Panel>
    </>
  );
}

function titleCase(value: string): string {
  return value.replace(/\b\w/g, (c) => c.toUpperCase());
}
