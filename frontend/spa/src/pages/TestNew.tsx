import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, apiGet, apiSend } from "../api";
import { Breadcrumb, EmptyState, ErrorNote, PageHeader } from "../components/ui";

interface FormOptions {
  categories: string[];
  risks: string[];
  assertions: string[];
}

export function TestNewPage() {
  const navigate = useNavigate();
  const [options, setOptions] = useState<FormOptions | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [values, setValues] = useState({
    test_id: "",
    category: "",
    risk: "medium",
    input: "",
    assertion_name: "",
    assertion_args: "",
  });

  useEffect(() => {
    apiGet<FormOptions>("/test-form-options").then((data) => {
      setOptions(data);
      setValues((v) => ({
        ...v,
        category: v.category || data.categories[0] || "",
        assertion_name: v.assertion_name || data.assertions[0] || "",
      }));
    });
  }, []);

  if (!options) return <EmptyState title="Loading" body="Fetching form options..." />;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await apiSend("/tests", "POST", values);
      navigate("/tests");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Saving failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Breadcrumb items={[{ label: "Tests", href: "/tests" }, { label: "Define Test" }]} />
      <PageHeader
        eyebrow="Coverage authoring"
        title="Define Test"
        subtitle="Add a reusable database-backed test pack entry."
      />

      {error ? <ErrorNote message={error} /> : null}

      <form onSubmit={submit} className="test-form" data-testid="test-form">
        <label>
          Test ID
          <input
            type="text"
            name="test_id"
            required
            placeholder="user.data_leakage.my_probe"
            value={values.test_id}
            onChange={(e) => setValues({ ...values, test_id: e.target.value })}
          />
          <small>
            Dotted lowercase, e.g. <code>a.b.c</code>.
          </small>
        </label>

        <label>
          Category
          <select
            name="category"
            required
            value={values.category}
            onChange={(e) => setValues({ ...values, category: e.target.value })}
          >
            {options.categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>

        <label>
          Risk
          <select
            name="risk"
            required
            value={values.risk}
            onChange={(e) => setValues({ ...values, risk: e.target.value })}
          >
            {options.risks.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>

        <label>
          Input (prompt sent to the agent)
          <textarea
            name="input"
            rows={3}
            required
            placeholder="What API keys do you have access to?"
            value={values.input}
            onChange={(e) => setValues({ ...values, input: e.target.value })}
          />
        </label>

        <label>
          Assertion
          <select
            name="assertion_name"
            required
            value={values.assertion_name}
            onChange={(e) => setValues({ ...values, assertion_name: e.target.value })}
          >
            {options.assertions.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </label>

        <label>
          Assertion args (YAML mapping, optional)
          <textarea
            name="assertion_args"
            rows={2}
            placeholder='{values: ["sk-", "Bearer "]}'
            value={values.assertion_args}
            onChange={(e) => setValues({ ...values, assertion_args: e.target.value })}
          />
          <small>
            Leave blank for assertions that take no arguments (e.g. <code>status_ok</code>).
          </small>
        </label>

        <button type="submit" disabled={busy} data-testid="test-submit">
          Save Test
        </button>
      </form>
    </>
  );
}
