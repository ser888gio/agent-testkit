import { Link } from "react-router-dom";
import { useView, Loading } from "../useView";
import { EmptyState, PageHeader } from "../ui";

interface SettingsView {
  settings: {
    db_path: string;
    package_dir: string;
    config_dir: string;
    packs_dir: string;
    auth_state: string;
    redaction_patterns: string[];
    egress_allow_local: boolean;
  };
  principal: {
    org_id: string;
    subject: string;
    email: string;
    roles: string[];
    auth_method: string;
  };
}

function Meta({ entries }: { entries: [string, React.ReactNode][] }) {
  return (
    <dl className="harness-meta">
      {entries.map(([key, value]) => (
        <div key={key}>
          <dt>{key}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function Panel({
  title,
  blurb,
  children,
  testid,
}: {
  title: string;
  blurb: string;
  children: React.ReactNode;
  testid?: string;
}) {
  return (
    <article className="panel" data-testid={testid}>
      <div className="panel-header">
        <div>
          <h2>{title}</h2>
          <p>{blurb}</p>
        </div>
      </div>
      {children}
    </article>
  );
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
