import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { apiSend } from "../api";
import { Loading, useView } from "../useView";
import {
  EmptyState,
  PageHeader,
  ScoreBar,
  shortDate,
  StatCard,
  StatusBadge,
} from "../ui";
import { encodeAgentId } from "./Agents";

interface RunRowView {
  id: string;
  short_id: string;
  started: string;
  status: string;
  score_percent: number;
  failed: number;
  critical_failures: number;
}

interface AgentDetailView {
  agent_id: string;
  runs: RunRowView[];
  matrix: Record<string, Record<string, string>>;
  latest_run_id: string | null;
  profile: {
    purpose: string;
    domain: string;
    interface: string;
    sandbox: string | null;
    risk_level: string;
    tool_classes: string[];
    side_effects: string[];
    notes: string[];
  } | null;
  profiled_at: string | null;
  capabilities: string[];
  registered: boolean;
  allowed_hosts: string[];
}

const CAPABILITY_NAMES = ["multi_turn", "tool_use", "structured_input", "sandbox"];

export function AgentDetailPage() {
  // The server route is /agents/{agent_id:path}; everything after "/agents/"
  // is the id.
  const location = useLocation();
  const agentId = decodeURIComponent(location.pathname.replace(/^\/agents\//, ""));
  const navigate = useNavigate();
  const { view, error, reload } = useView<AgentDetailView>(
    `/agents/${agentId.split("/").map(encodeURIComponent).join("/")}`,
  );
  const [hosts, setHosts] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (view) setHosts(view.allowed_hosts.join(", "));
  }, [view]);

  if (error) return <EmptyState title="Agent not available" body={error} />;
  if (!view) return <Loading />;

  const saveAllowlist = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    try {
      await apiSend(`/agents/${encodeAgentId(agentId)}/allowlist`, "POST", { allowed_hosts: hosts });
      reload();
    } catch (err) {
      window.alert(err instanceof Error ? err.message : "Save failed.");
    } finally {
      setBusy(false);
    }
  };

  const discover = async () => {
    setBusy(true);
    try {
      const result = await apiSend<{ job_id: string }>(
        `/agents/${encodeAgentId(agentId)}/discover`,
        "POST",
        {},
      );
      navigate(`/jobs/${result.job_id}`);
    } catch (err) {
      window.alert(err instanceof Error ? err.message : "Profiling failed.");
    } finally {
      setBusy(false);
    }
  };

  const failures = view.runs.filter((r) => r.status === "failed" || r.status === "error");
  const latest = view.runs[0];

  return (
    <>
      <p>
        <Link to="/agents">Back to agents</Link>
      </p>
      <PageHeader eyebrow="Agent detail" title={agentId} />

      <section className="panel" data-testid="agent-profile" aria-labelledby="profile-title">
        <div className="panel-header">
          <div>
            <h2 id="profile-title">Discovered profile</h2>
            <p>What probing the endpoint revealed, and therefore which tests are worth running.</p>
          </div>
          {view.registered ? (
            <button type="button" onClick={discover} disabled={busy} data-testid="discover-submit">
              {view.profile ? "Re-profile" : "Profile agent"}
            </button>
          ) : null}
        </div>
        {!view.registered ? (
          <p className="quiet" data-testid="profile-unregistered">
            This agent has run history but no registered target, so there is no endpoint to probe.
            Targets are registered when a run is launched from{" "}
            <Link to="/agents/connect">Connect an agent</Link>; runs started from the CLI record the
            agent only.
          </p>
        ) : !view.profile ? (
          <p className="quiet">
            Never profiled. Probing sends a few low-risk requests to the endpoint and records shapes
            only — never response text.
          </p>
        ) : (
          <>
            <dl className="harness-meta">
              <div>
                <dt>Purpose</dt>
                <dd>{view.profile.purpose || "not inferred"}</dd>
              </div>
              <div>
                <dt>Domain</dt>
                <dd>{view.profile.domain}</dd>
              </div>
              <div>
                <dt>Interface</dt>
                <dd>{view.profile.interface}</dd>
              </div>
              <div>
                <dt>Sandbox</dt>
                <dd>{view.profile.sandbox || "none declared"}</dd>
              </div>
              <div>
                <dt>Risk level</dt>
                <dd>
                  <StatusBadge status={view.profile.risk_level} />
                </dd>
              </div>
              <div>
                <dt>Profiled</dt>
                <dd>{shortDate(view.profiled_at ?? undefined)}</dd>
              </div>
            </dl>

            <h3>Capabilities</h3>
            <p className="quiet">
              A test whose requirement the agent cannot satisfy is excluded rather than run and
              failed.
            </p>
            <ul className="memory-check-list">
              {CAPABILITY_NAMES.map((name) => {
                const present = view.capabilities.includes(name);
                return (
                  <li key={name}>
                    <span className="mono">{name}</span>
                    <StatusBadge status={present ? "passed" : "skipped"} label={present ? "yes" : "no"} />
                  </li>
                );
              })}
            </ul>

            {view.profile.tool_classes.length || view.profile.side_effects.length ? (
              <>
                <h3>Attack surface</h3>
                <div className="matrix-row">
                  {view.profile.tool_classes.map((tool) => (
                    <span key={tool} className="badge badge-neutral">
                      {tool}
                    </span>
                  ))}
                  {view.profile.side_effects.map((effect) => (
                    <span key={effect} className="badge badge-failed">
                      {effect}
                    </span>
                  ))}
                </div>
              </>
            ) : null}

            {view.profile.notes.length ? (
              <>
                <h3>Discovery notes</h3>
                <ul className="finding-stream">
                  {view.profile.notes.map((note, i) => (
                    <li key={i} className="finding-item">
                      <div className="finding-main">
                        <p>{note}</p>
                      </div>
                    </li>
                  ))}
                </ul>
              </>
            ) : null}
          </>
        )}
      </section>

      {view.registered ? (
        <section className="panel" data-testid="agent-egress">
          <div className="panel-header">
            <div>
              <h2>Egress allowlist</h2>
              <p>Hosts this target may be dialled at. Empty means no egress is permitted.</p>
            </div>
          </div>
          <form onSubmit={saveAllowlist} className="test-form">
            <label>
              Allowed hosts
              <input
                name="allowed_hosts"
                value={hosts}
                onChange={(event) => setHosts(event.target.value)}
                placeholder="agent.example.com"
                data-testid="allowlist-input"
              />
              <span className="quiet">Comma or space separated. Workers refuse any host outside this list.</span>
            </label>
            <button type="submit" disabled={busy} data-testid="allowlist-submit">
              Save allowlist
            </button>
          </form>
        </section>
      ) : null}

      {view.runs.length ? (
        <section className="stat-grid">
          <StatCard label="Runs" value={view.runs.length} note="recorded for this agent" />
          <StatCard
            label="Latest gate"
            value={latest.status}
            note="most recent run"
            tone={latest.status === "failed" ? "danger" : undefined}
          />
          <StatCard label="Latest score" value={`${latest.score_percent}%`} note="weighted by risk" />
          <StatCard label="Attention runs" value={failures.length} note="failed or critical" />
        </section>
      ) : null}

      <section className="panel">
        <div className="panel-header">
          <h2>Run history</h2>
        </div>
        {!view.runs.length ? (
          <EmptyState title="No runs yet for this agent" body="Run a pack against this target to populate history." />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Run</th>
                  <th scope="col">Started</th>
                  <th scope="col">Gate</th>
                  <th scope="col">Score</th>
                  <th scope="col">Evidence</th>
                </tr>
              </thead>
              <tbody>
                {view.runs.map((rv) => (
                  <tr key={rv.id}>
                    <td data-label="Run">
                      <Link className="mono" to={`/runs/${rv.id}`}>
                        {rv.short_id}
                      </Link>
                    </td>
                    <td data-label="Started" className="mono">
                      {rv.started}
                    </td>
                    <td data-label="Gate">
                      <StatusBadge status={rv.status} />
                    </td>
                    <td data-label="Score">
                      <ScoreBar value={rv.score_percent} label="Run score" /> {rv.score_percent}%
                    </td>
                    <td data-label="Evidence">
                      {rv.failed} failed,{" "}
                      <span className={rv.critical_failures ? "critical-count" : undefined}>
                        {rv.critical_failures}
                      </span>{" "}
                      critical
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Latest pass/fail matrix</h2>
        </div>
        {!Object.keys(view.matrix).length ? (
          <p className="quiet">No matrix yet.</p>
        ) : (
          Object.entries(view.matrix).map(([cat, tests]) => (
            <div key={cat} className="matrix-row">
              <span className="cat">{cat}</span>
              {Object.entries(tests).map(([tid, status]) =>
                view.latest_run_id ? (
                  <Link key={tid} to={`/runs/${view.latest_run_id}/tests/${encodeURIComponent(tid)}`}>
                    <StatusBadge status={status} label={tid} />
                  </Link>
                ) : (
                  <StatusBadge key={tid} status={status} label={tid} />
                ),
              )}
            </div>
          ))
        )}
      </section>
    </>
  );
}
