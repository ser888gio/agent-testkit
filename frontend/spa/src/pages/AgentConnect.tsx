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

interface ConnectOptions {
  targets: string[];
  pack_roots: string[];
  default_target: string | null;
  default_pack: string | null;
  pack_tests: Record<string, PackCase[]>;
}

export function AgentConnectPage() {
  const navigate = useNavigate();
  const [options, setOptions] = useState<ConnectOptions | null>(null);
  const [target, setTarget] = useState("");
  const [pack, setPack] = useState("");
  // Only the selected pack's tests are offered: the form submits one pack.
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    apiGet<ConnectOptions>("/connect-options").then((data) => {
      setOptions(data);
      setTarget(data.default_target ?? data.targets[0] ?? "");
      setPack(data.default_pack ?? data.pack_roots[0] ?? "");
    });
  }, []);

  const cases = useMemo(() => options?.pack_tests[pack] ?? [], [options, pack]);

  if (!options) return <EmptyState title="Loading" body="Fetching run configuration..." />;
  if (!error && !options.targets.length && !options.pack_roots.length) {
    return (
      <>
        <PageHeader eyebrow="Agent setup" title="Connect an agent" />
        <EmptyState
          title="Connection inputs missing"
          body="Add a target config and at least one pack before running an agent."
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
      const result = await apiSend<{ job_id: string }>("/runs/enqueue", "POST", {
        target,
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
            Choose a target config and a test pack, then start the run. Results appear on Home when
            it finishes.
          </>
        }
      />

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2>Run configuration</h2>
            <p>
              Target configs come from <code>agentaudit/config</code>, packs from{" "}
              <code>agentaudit/packs</code>. Testing a new agent?{" "}
              <Link to="/agents/register">Register it by endpoint URL</Link> first.
            </p>
          </div>
        </div>
        {error ? <ErrorNote message={error} /> : null}
        <form onSubmit={submit} className="test-form" data-testid="connect-form">
          <label>
            Target config
            <select
              name="target"
              required
              value={target}
              onChange={(event) => setTarget(event.target.value)}
            >
              {options.targets.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>

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
