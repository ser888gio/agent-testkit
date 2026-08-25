import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError, apiGet, apiSend } from "../api";
import { useEffect } from "react";
import { EmptyState, PageHeader, ErrorNote } from "../ui";

interface RegisterOptions {
  sandboxes: string[];
}

const METHODS = ["POST", "GET"];

export function AgentRegisterPage() {
  const navigate = useNavigate();
  const [options, setOptions] = useState<RegisterOptions | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [values, setValues] = useState({
    target_id: "",
    endpoint: "",
    method: "POST",
    text_path: "$.text",
    sandbox: "",
  });

  useEffect(() => {
    apiGet<RegisterOptions>("/agents/register-options").then(setOptions);
  }, []);

  if (!options) return <EmptyState title="Loading" body="Fetching form options..." />;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await apiSend<{ agent_id: string }>("/agents/register", "POST", values);
      navigate(`/agents/${result.agent_id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Registration failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <p>
        <Link to="/agents">Back to agents</Link>
      </p>
      <PageHeader
        eyebrow="Agent setup"
        title="Register an agent"
        subtitle="Point agentaudit at an HTTP endpoint. The host you enter becomes the only address this target may be dialled at."
      />

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2>Endpoint</h2>
            <p>Registered targets can be profiled and run without adding a YAML file.</p>
          </div>
        </div>
        {error ? <ErrorNote message={error} /> : null}
        <form onSubmit={submit} className="test-form" data-testid="register-form">
          <label>
            Target id
            <input
              name="target_id"
              required
              value={values.target_id}
              onChange={(e) => setValues({ ...values, target_id: e.target.value })}
              placeholder="my-support-agent"
              data-testid="register-id"
            />
          </label>

          <label>
            Endpoint URL
            <input
              name="endpoint"
              type="url"
              required
              value={values.endpoint}
              onChange={(e) => setValues({ ...values, endpoint: e.target.value })}
              placeholder="https://agent.example.com/chat"
              data-testid="register-endpoint"
            />
          </label>

          <label>
            Method
            <select
              name="method"
              value={values.method}
              onChange={(e) => setValues({ ...values, method: e.target.value })}
            >
              {METHODS.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>

          <label>
            Response text path
            <input
              name="text_path"
              value={values.text_path}
              onChange={(e) => setValues({ ...values, text_path: e.target.value })}
            />
            <span className="quiet">Where the agent's reply lives in the JSON response.</span>
          </label>

          <label>
            Sandbox
            <select
              name="sandbox"
              value={values.sandbox}
              onChange={(e) => setValues({ ...values, sandbox: e.target.value })}
            >
              <option value="">None</option>
              {options.sandboxes.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <span className="quiet">Fake tools the agent is given. Required for action-safety tests.</span>
          </label>

          <button type="submit" disabled={busy} data-testid="register-submit">
            Register agent
          </button>
        </form>
      </section>
    </>
  );
}
