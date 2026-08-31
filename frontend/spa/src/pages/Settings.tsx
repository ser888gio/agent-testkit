import { Link } from "react-router-dom";
import { useView, Loading } from "../components/useView";
import { EmptyState, PageHeader, Panel } from "../components/ui";
import { Meta } from "../components/Meta";

interface LLMRole {
  configured: boolean;
  model?: string;
  endpoint?: string;
  api_key_env?: string | null;
  api_key_present?: boolean;
}

// A role reads as one line: the model, then whether its key actually resolves
// on this worker -- the distinction core/llm.py:describe is built to report.
function llmRole(role: LLMRole): React.ReactNode {
  if (!role.configured) return <span className="quiet">Not configured</span>;
  return (
    <span>
      <span className="mono">{role.model ?? "unnamed model"}</span>
      {role.api_key_env && !role.api_key_present ? (
        <span className="quiet"> · key {role.api_key_env} not set</span>
      ) : null}
    </span>
  );
}

interface SettingsView {
  settings: {
    db_path: string;
    package_dir: string;
    config_dir: string;
    packs_dir: string;
    auth_state: string;
    redaction_patterns: string[];
    egress_allow_local: boolean;
    llm: {
      source: string | null;
      error: string | null;
      attacker: LLMRole;
      judge: LLMRole;
    };
  };
  principal: {
    org_id: string;
    subject: string;
    email: string;
    roles: string[];
    auth_method: string;
  };
}

export function SettingsPage() {
  const { view, error } = useView<SettingsView>("/settings");

  if (error) return <EmptyState title="Could not load settings" body={error} />;
  if (!view) return <Loading />;
  const s = view.settings;

  return (
    <>
      <PageHeader
        eyebrow="Workspace"
        title="Settings"
        subtitle={
          <>
            Deployment-owned runtime configuration. These come from the environment the server and
            its workers were started with, so they are changed there, not here. Per-target settings
            that <em>are</em> editable live on each <Link to="/agents">agent's page</Link>.
          </>
        }
      />

      <section className="settings-grid">
        <Panel title="Storage" blurb="Where runs, agents, and test results are read from.">
          <Meta
            entries={[
              ["Database", <span className="mono">{s.db_path}</span>],
              ["Package Root", <span className="mono">{s.package_dir}</span>],
            ]}
          />
        </Panel>

        <Panel title="Run Inputs" blurb="Allowed local roots for targets and packs.">
          <Meta
            entries={[
              ["Configs", <span className="mono">{s.config_dir}</span>],
              ["Packs", <span className="mono">{s.packs_dir}</span>],
            ]}
          />
        </Panel>

        <Panel title="Security" blurb="State-changing routes require an admin session or bearer token.">
          <Meta
            entries={[
              ["Authentication", s.auth_state],
              [
                "Writable Routes",
                <>
                  Protected by session role plus <span className="mono">x-csrf-token</span>, or an
                  OIDC bearer token.
                </>,
              ],
            ]}
          />
        </Panel>

        <Panel
          title="Evidence & Redaction"
          blurb="What the harness masks before anything is persisted or displayed."
          testid="settings-redaction"
        >
          <Meta
            entries={[
              ["Built-in Masks", s.redaction_patterns.join(", ")],
              ["Mask Format", <span className="mono">«redacted:name»</span>],
              [
                "Scope",
                "Per-target policies add patterns and literals on top of the built-ins; they cannot remove them.",
              ],
              ["Defense in Depth", "Redaction runs in the runner and is re-applied on save."],
            ]}
          />
        </Panel>

        <Panel
          title="Egress"
          blurb="Where run traffic may go. Enforced worker-side, per target."
          testid="settings-egress"
        >
          <Meta
            entries={[
              [
                "Allow Local Endpoints",
                <>
                  {s.egress_allow_local ? "Enabled (development only)" : "Disabled"}{" "}
                  <span className="quiet">
                    Set by <span className="mono">AGENTAUDIT_EGRESS_ALLOW_LOCAL</span> in the
                    worker's environment. Deliberately not tenant-settable: a bypass you can toggle
                    from the UI is not a bypass fix.
                  </span>
                </>,
              ],
              [
                "Host Allowlist",
                <>
                  Editable per target on the <Link to="/agents">agent's page</Link>; workers refuse
                  hosts outside it.
                </>,
              ],
            ]}
          />
        </Panel>

        <Panel
          title="Attacker & Judge Models"
          blurb="The LLMs that write adaptive attack turns and decide whether one landed."
          testid="settings-llm"
        >
          <Meta
            entries={[
              ["Attacker", llmRole(s.llm.attacker)],
              ["Judge", llmRole(s.llm.judge)],
              [
                "Source",
                s.llm.error ? (
                  <span className="quiet">{s.llm.error}</span>
                ) : s.llm.source ? (
                  <span className="mono">{s.llm.source}</span>
                ) : (
                  <span className="quiet">
                    No config file. Copy{" "}
                    <span className="mono">agentaudit/llm.example.yaml</span> to{" "}
                    <span className="mono">llm.yaml</span>, or set{" "}
                    <span className="mono">AGENTAUDIT_LLM_CONFIG</span>.
                  </span>
                ),
              ],
              [
                "Keys",
                <>
                  The config file names an environment variable —{" "}
                  <span className="mono">api_key_ref: env://OPENAI_API_KEY</span> — and never holds
                  the key itself. The key is supplied to the server's environment, so it is never
                  committed, persisted, or returned by this API. Editing it here would mean storing
                  it here.
                </>,
              ],
            ]}
          />
        </Panel>

        <Panel title="Access" blurb="The principal this session acts as." testid="settings-access">
          <Meta
            entries={[
              ["Organization", <span className="mono">{view.principal.org_id}</span>],
              ["Subject", <span className="mono">{view.principal.subject}</span>],
              ["Email", view.principal.email],
              ["Roles", [...view.principal.roles].sort().join(", ")],
              ["Method", view.principal.auth_method],
            ]}
          />
        </Panel>

        <Panel title="Interface" blurb="Current dashboard navigation and polling behavior.">
          <Meta
            entries={[
              [
                "Sections",
                "Analytics, Harness, Runs, Agents, Tests, Generated, Settings",
              ],
              [
                "Polling",
                `Job status polls every two seconds while work is live; signed in as ${view.principal.subject}.`,
              ],
            ]}
          />
        </Panel>
      </section>
    </>
  );
}
