import { useEffect, useState } from "react";
import { ApiError, apiGet, apiSend } from "../api";
import { Breadcrumb, EmptyState, ErrorNote, PageHeader, Panel } from "../components/ui";

const ROLES = [
  {
    key: "attacker" as const,
    title: "Attacker model",
    blurb: "Writes the adaptive attack turns that probe your agent.",
  },
  {
    key: "judge" as const,
    title: "Judge model",
    blurb: "Decides whether an attack turn actually landed.",
  },
];

type Role = (typeof ROLES)[number]["key"];

// Clicking one fills the URL only. The model list is deliberately not here: it
// changes weekly per provider, and a stale dropdown is worse than a text field.
const PRESETS = [
  {
    name: "OpenRouter",
    endpoint: "https://openrouter.ai/api/v1/chat/completions",
    model: "openai/gpt-4o-mini",
    keys: "openrouter.ai/keys",
  },
  {
    name: "OpenAI",
    endpoint: "https://api.openai.com/v1/chat/completions",
    model: "gpt-4o-mini",
    keys: "platform.openai.com/api-keys",
  },
  {
    name: "Groq",
    endpoint: "https://api.groq.com/openai/v1/chat/completions",
    model: "llama-3.3-70b-versatile",
    keys: "console.groq.com/keys",
  },
];

interface StoredRole {
  endpoint: string;
  model: string;
  api_key_set: boolean;
}

interface SettingsView {
  llm: Partial<Record<Role, StoredRole>>;
  default_endpoint: string;
}

// The key is write-only: the server returns `api_key_set`, never the value, so
// an empty field means "leave the stored key alone" rather than "clear it".
interface Draft {
  endpoint: string;
  model: string;
  api_key: string;
}

const EMPTY: Draft = { endpoint: "", model: "", api_key: "" };

export function SettingsPage() {
  const [view, setView] = useState<SettingsView | null>(null);
  const [drafts, setDrafts] = useState<Record<Role, Draft>>({ attacker: EMPTY, judge: EMPTY });
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    apiGet<SettingsView>("/settings")
      .then((data) => {
        setView(data);
        setDrafts({
          attacker: toDraft(data.llm.attacker),
          judge: toDraft(data.llm.judge),
        });
      })
      .catch((err: unknown) =>
        setError(err instanceof ApiError ? err.detail : "Could not load settings."),
      );
  }, []);

  if (error && !view) return <EmptyState title="Could not load settings" body={error} />;
  if (!view) return <EmptyState title="Loading" body="Fetching settings..." />;

  const set = (role: Role, field: keyof Draft, value: string) => {
    setDrafts((d) => ({ ...d, [role]: { ...d[role], [field]: value } }));
    setSaved(false);
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = Object.fromEntries(
        ROLES.map(({ key }) => [key, toBody(drafts[key], view.default_endpoint)]),
      );
      const result = await apiSend<{ llm: SettingsView["llm"] }>("/settings/llm", "PUT", body);
      setView({ ...view, llm: result.llm });
      setDrafts({
        attacker: toDraft(result.llm.attacker),
        judge: toDraft(result.llm.judge),
      });
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not save settings.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Breadcrumb items={[{ label: "Settings" }]} />
      <PageHeader
        eyebrow="Workspace"
        title="Settings"
        subtitle="Bring your own model. These credentials are used only to run your audits; leave a role blank to turn it off."
      />

      <Panel
        title="Getting a key"
        blurb="agentaudit talks the OpenAI chat-completions format, so any provider that speaks it works."
      >
        <p>
          The quickest route is <strong>OpenRouter</strong>, which fronts most models behind one
          key. Sign up at <span className="mono">openrouter.ai</span>, create a key under{" "}
          <span className="mono">openrouter.ai/keys</span>, then paste it below with the base URL{" "}
          <span className="mono">https://openrouter.ai/api/v1/chat/completions</span> and a model
          name such as <span className="mono">openai/gpt-4o-mini</span> or{" "}
          <span className="mono">anthropic/claude-sonnet-4</span> — OpenRouter model names are
          always <span className="mono">vendor/model</span>.
        </p>
        <p className="quiet">
          Going direct to a vendor works the same way, and so does a local server (Ollama, vLLM,
          LiteLLM) if you point the base URL at it and leave the key blank. Use the buttons on each
          role below to fill in a provider's URL.
        </p>
      </Panel>

      {error ? <ErrorNote message={error} /> : null}
      {saved ? <p className="quiet">Saved.</p> : null}

      <form onSubmit={submit} className="settings-grid" data-testid="llm-form">
        {ROLES.map(({ key, title, blurb }) => (
          <Panel key={key} title={title} blurb={blurb} testid={`settings-${key}`}>
            <div className="test-form">
              <p className="quiet">
                Fill from:{" "}
                {PRESETS.map((preset) => (
                  <button
                    key={preset.name}
                    type="button"
                    className="button-secondary"
                    onClick={() => {
                      set(key, "endpoint", preset.endpoint);
                      if (!drafts[key].model.trim()) set(key, "model", preset.model);
                    }}
                  >
                    {preset.name}
                  </button>
                ))}
              </p>

              <label>
                API base URL
                <input
                  type="url"
                  value={drafts[key].endpoint}
                  onChange={(e) => set(key, "endpoint", e.target.value)}
                  placeholder={view.default_endpoint}
                  data-testid={`${key}-endpoint`}
                />
                <span className="quiet">Any OpenAI-compatible chat-completions endpoint.</span>
              </label>

              <label>
                Model name
                <input
                  value={drafts[key].model}
                  onChange={(e) => set(key, "model", e.target.value)}
                  placeholder="gpt-4o-mini"
                  data-testid={`${key}-model`}
                />
              </label>

              <label>
                API key reference
                <input
                  autoComplete="off"
                  value={drafts[key].api_key}
                  onChange={(e) => set(key, "api_key", e.target.value)}
                  placeholder={
                    view.llm[key]?.api_key_set ? "Stored — leave blank to keep" : "${OPENAI_API_KEY}"
                  }
                  data-testid={`${key}-key`}
                />
                <span className="quiet">
                  The name of an environment variable your operator has provisioned on the
                  worker, written as ${"${VAR}"}. Keys themselves are never stored here. Blank
                  is fine for a local model server that needs no key.
                </span>
              </label>
            </div>
          </Panel>
        ))}

        <button type="submit" disabled={busy} data-testid="llm-save">
          {busy ? "Saving..." : "Save"}
        </button>
      </form>
    </>
  );
}

function toDraft(role: StoredRole | undefined): Draft {
  return role ? { endpoint: role.endpoint, model: role.model, api_key: "" } : EMPTY;
}

// A role with no model name is off. The endpoint falls back to the default so a
// user who only knows their model name does not have to look the URL up.
function toBody(draft: Draft, defaultEndpoint: string) {
  if (!draft.model.trim()) return null;
  return {
    endpoint: draft.endpoint.trim() || defaultEndpoint,
    model: draft.model.trim(),
    api_key: draft.api_key || null,
  };
}
