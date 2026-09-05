import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, apiGet, apiSend } from "../api";
import { Breadcrumb, EmptyState, ErrorNote, PageHeader, Panel } from "../components/ui";

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
  attack_transforms: AttackTransform[];
}

interface AttackTransform {
  name: string;
  family: string;
  description: string;
  recommended: boolean;
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
  const [timeoutMinutes, setTimeoutMinutes] = useState("");
  // Each name adds one mutated variant per planned test, so the run grows by
  // roughly (1 + count) x. Empty means the pack runs as written.
  const [transforms, setTransforms] = useState<Set<string>>(new Set());
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
      // Preselected so an unfamiliar user gets broad attack-class coverage
      // without having to judge 20 names; every one stays unticked-able.
      setTransforms(
        new Set(data.attack_transforms.filter((t) => t.recommended).map((t) => t.name)),
      );
    });
  }, []);

  const cases = useMemo(() => options?.pack_tests[pack] ?? [], [options, pack]);

  // Transforms grouped into the families the API orders them by, so the form
  // renders sections without hardcoding a family list of its own.
  const families = useMemo(() => {
    const groups = new Map<string, AttackTransform[]>();
    for (const transform of options?.attack_transforms ?? []) {
      const group = groups.get(transform.family) ?? [];
      group.push(transform);
      groups.set(transform.family, group);
    }
    return [...groups];
  }, [options]);

  // What the run will actually contain. A selection narrows the pack, so the
  // base is the chosen tests when there are any -- the same arithmetic the
  // worker's expansion does, not the whole-pack guess the old blurb made.
  const baseCount = selected.size || cases.length;
  const runCount = baseCount * (transforms.size + 1);
  const urlMode = target === URL_OPTION;
  const hasTargets = Boolean(
    options && (options.targets.length || options.registered_targets.length),
  );

  if (!options) return <EmptyState title="Loading" body="Fetching run configuration..." />;
  if (!error && !hasTargets && !options.pack_roots.length) {
    return (
      <>
        <Breadcrumb items={[{ label: "Runs", href: "/runs" }, { label: "Connect" }]} />
        <PageHeader eyebrow="Agent setup" title="Connect an agent" />
        <EmptyState
          title="Connection inputs missing"
          body="Register an agent by endpoint URL and add at least one pack before running."
        />
      </>
    );
  }

  const toggleTransform = (name: string) => {
    setTransforms((current) => {
      const next = new Set(current);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

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
        timeout_seconds: timeoutMinutes ? Number(timeoutMinutes) * 60 : null,
        attack_transforms: [...transforms],
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
      <Breadcrumb items={[{ label: "Runs", href: "/runs" }, { label: "Connect" }]} />
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

      <Panel title="Run configuration" blurb={<>Pick a registered agent or a shipped target config, choose a test pack from{" "}
              <code>agentaudit/packs</code>, then start the run. Agent deployed somewhere new?{" "}
              Select <em>other endpoint URL</em> and paste its address.</>}>
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

          <label>
            Time limit <span className="quiet">(optional)</span>
            <input
              type="number"
              name="timeout-minutes"
              min={1}
              max={1440}
              step={1}
              placeholder="no limit"
              value={timeoutMinutes}
              onChange={(event) => setTimeoutMinutes(event.target.value)}
              data-testid="connect-timeout"
            />
            <small className="quiet">
              Minutes the run may take before it is stopped. Tests already sent to the agent
              still finish, and whatever ran is kept as partial evidence.
            </small>
          </label>

          <details className="test-picker" data-testid="attack-picker">
            <summary>
              Generate attack variants{" "}
              <span className="quiet">
                {transforms.size
                  ? `(${transforms.size} selected)`
                  : "(optional — the pack runs as written)"}
              </span>
            </summary>

            {/* Cost first: selecting transforms multiplies the run, and that is
                the thing a user most needs to see before ticking more. */}
            <p className="attack-cost" data-testid="attack-cost">
              {transforms.size ? (
                <>
                  <strong>
                    {baseCount} test{baseCount === 1 ? "" : "s"} → {runCount} to run
                  </strong>{" "}
                  <span className="quiet">
                    ({transforms.size} transform{transforms.size === 1 ? "" : "s"} adds one
                    variant each)
                  </span>
                </>
              ) : (
                <span className="quiet">
                  {baseCount} test{baseCount === 1 ? "" : "s"} run as written.
                </span>
              )}
            </p>
            {runCount > 100 ? (
              <p className="attack-warning" data-testid="attack-warning">
                A run this size takes a while. Consider setting a time limit above.
              </p>
            ) : null}

            {families.map(([family, items]) => (
              <fieldset className="test-picker-group" key={family}>
                <legend>{family}</legend>
                <ul className="test-picker-list">
                  {items.map((transform) => (
                    <li key={transform.name}>
                      <label>
                        <input
                          type="checkbox"
                          checked={transforms.has(transform.name)}
                          onChange={() => toggleTransform(transform.name)}
                        />
                        <span className="mono">{transform.name}</span>
                        {transform.recommended ? (
                          <span className="badge badge-passed">recommended</span>
                        ) : null}
                        <span className="quiet">{transform.description}</span>
                      </label>
                    </li>
                  ))}
                </ul>
              </fieldset>
            ))}
          </details>

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
      </Panel>
    </>
  );
}
