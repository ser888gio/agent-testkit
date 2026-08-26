import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError, apiGet, apiSend } from "../api";
import { EmptyState, ErrorNote, PageHeader } from "../ui";

interface PackCase {
  id: string;
  description: string;
  category: string;
  risk: string;
}

interface RegisteredTarget {
  id: string;
  name: string;
}

interface ConnectOptions {
  targets: string[];
  registered_targets: RegisteredTarget[];
  pack_roots: string[];
  default_target: string | null;
  default_pack: string | null;
  pack_tests: Record<string, PackCase[]>;
}

// Sentinel option that switches the form to endpoint-URL mode.
const URL_OPTION = "__endpoint-url__";

export function AgentConnectPage() {
  const navigate = useNavigate();
  const [options, setOptions] = useState<ConnectOptions | null>(null);
  const [target, setTarget] = useState("");
  const [endpointUrl, setEndpointUrl] = useState("");
  const [newAgentId, setNewAgentId] = useState("");
  const [pack, setPack] = useState("");
  // Only the selected pack's tests are offered: the form submits one pack.
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    apiGet<ConnectOptions>("/connect-options").then((data) => {
      setOptions(data);
      setTarget(
        data.default_target ??
          data.registered_targets[0]?.id ??
          data.targets[0] ??
          URL_OPTION,
      );
      setPack(data.default_pack ?? data.pack_roots[0] ?? "");
    });
  }, []);

  const cases = useMemo(() => options?.pack_tests[pack] ?? [], [options, pack]);
  const urlMode = target === URL_OPTION;
  const hasTargets = Boolean(
    options && (options.targets.length || options.registered_targets.length),
  );

  if (!options) return <EmptyState title="Loading" body="Fetching run configuration..." />;
  if (!error && !hasTargets && !options.pack_roots.length) {
    return (
      <>
        <PageHeader eyebrow="Agent setup" title="Connect an agent" />
        <EmptyState
          title="Connection inputs missing"
          body="Register an agent by endpoint URL and add at least one pack before running."
        />
      </>
    );
  }

  const toggle = (id: string) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      let targetId = target;
      if (urlMode) {
        // Register first so the run has a target row to resolve; the enqueue
        // endpoint then accepts the id like any registered agent.
        await apiSend<{ agent_id: string }>("/agents/register", "POST", {
          target_id: newAgentId,
          endpoint: endpointUrl,
        });
        targetId = newAgentId;
      }
      const result = await apiSend<{ job_id: string }>("/runs/enqueue", "POST", {
        target: targetId,
        packs: pack,
        test_ids: [...selected],
      });
      navigate(`/jobs/${result.job_id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not queue the run.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <p>
        <Link to="/runs">Back to runs</Link>
      </p>
      <PageHeader
        eyebrow="Agent setup"
        title="Connect an agent"
        subtitle={
          <>
            Pick an agent (registered or shipped) and a test pack, then start the run. Results
            appear on Home when it finishes.
          </>
        }
      />

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2>Run configuration</h2>
            <p>
              Pick a registered agent or a shipped target config, choose a test pack from{" "}
              <code>agentaudit/packs</code>, then start the run. Agent deployed somewhere new?{" "}
              Select <em>other endpoint URL</em> and paste its address.
            </p>
          </div>
        </div>
        {error ? <ErrorNote message={error} /> : null}
        <form onSubmit={submit} className="test-form" data-testid="connect-form">
          <label>
            Agent
            <select
              name="target"
              required
              value={target}
              onChange={(event) => setTarget(event.target.value)}
            >
              {options.registered_targets.length ? (
                <optgroup label="Registered agents">
                  {options.registered_targets.map((t) => (
                    <option key={`reg:${t.id}`} value={t.id}>
                      {t.name === t.id ? t.id : `${t.name} (${t.id})`}
                    </option>
                  ))}
                </optgroup>
              ) : null}
              {options.targets.length ? (
                <optgroup label="Shipped configs">
                  {options.targets.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </optgroup>
              ) : null}
              <option value={URL_OPTION}>other endpoint URL…</option>
            </select>
          </label>

          {urlMode ? (
            <>
              <label>
                Endpoint URL
                <input
                  type="url"
                  name="endpoint"
                  required
                  placeholder="https://agent.example.com/chat"
                  value={endpointUrl}
                  onChange={(event) => setEndpointUrl(event.target.value)}
                  data-testid="connect-endpoint"
                />
              </label>
              <label>
                Agent id
                <input
                  type="text"
                  name="agent-id"
                  required
                  placeholder="my-agent"
                  value={newAgentId}
                  onChange={(event) => setNewAgentId(event.target.value)}
                  data-testid="connect-agent-id"
                />
              </label>
            </>
          ) : null}

          <label>
            Test pack
            <select
              name="packs"
              required
              value={pack}
              onChange={(event) => {
                setPack(event.target.value);
                // Uncheck what is no longer offered, so switching packs cannot
                // submit a stale selection the server must reject.
                setSelected(new Set());
              }}
            >
              {options.pack_roots.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </label>

          <details className="test-picker" data-testid="test-picker">
            <summary>
              Choose specific tests{" "}
              <span className="quiet">(optional — the whole pack runs by default)</span>
            </summary>
            <fieldset className="test-picker-group">
              <legend className="mono">{pack}</legend>
              {!cases.length ? (
                <p className="quiet">No YAML-backed tests in this pack.</p>
              ) : (
                <ul className="test-picker-list">
                  {cases.map((testCase) => (
                    <li key={testCase.id}>
                      <label>
                        <input
                          type="checkbox"
                          checked={selected.has(testCase.id)}
                          onChange={() => toggle(testCase.id)}
                        />
                        <span className="mono">{testCase.id}</span>
                        <span className="quiet">
                          {testCase.category} · {testCase.risk}
                        </span>
                      </label>
                      {testCase.description ? (
                        // Native title tooltip: no popover library.
                        <span
                          className="test-info"
                          tabIndex={0}
                          title={testCase.description}
                          aria-label={testCase.description}
                        >
                          i
                        </span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )}
            </fieldset>
          </details>

          <button type="submit" disabled={busy} data-testid="connect-submit">
            Run Tests
          </button>
        </form>
      </section>
    </>
  );
}
