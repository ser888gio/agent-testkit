// Shared UI primitives. Class names are the stylesheet's; the design contract
// lives in ./style.css, which main.tsx imports so Vite owns it.

import { Link } from "react-router-dom";

// The tones the stylesheet actually defines. Callers pass server-provided
// strings -- statuses, risks, but also profile domains, interfaces and
// selection sources -- so anything outside this set is a legitimate value with
// no status colour, not a bug. Interpolating `badge-${status}` instead rendered
// those as invisible transparent pills.
export const BADGE_TONE: Record<string, string> = {
  passed: "badge-passed",
  pass: "badge-pass",
  low: "badge-low",
  failed: "badge-failed",
  fail: "badge-fail",
  critical: "badge-critical",
  error: "badge-error",
  high: "badge-high",
  skipped: "badge-skipped",
  medium: "badge-medium",
};

export function badgeClass(value: string): string {
  return `badge ${BADGE_TONE[value] ?? "badge-neutral"}`;
}

export function StatusBadge({ status, label }: { status: string; label?: string }) {
  return <span className={badgeClass(status)}>{label ?? status}</span>;
}

export function RiskBadge({ risk }: { risk: string }) {
  return <span className={badgeClass(risk)}>{risk}</span>;
}

// Score carries pass/fail signal, not brand color: red below 50, amber below 80.
export function ScoreBar({ value, label = "Score" }: { value: number; label?: string }) {
  const tone =
    value < 50 ? "var(--fail-text)" : value < 80 ? "var(--warn-text)" : "var(--pass-text)";
  return (
    <span
      className="score-bar"
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={value}
    >
      <span style={{ width: `${value}%`, ["--tone" as string]: tone }} />
    </span>
  );
}

export function StatCard({
  label,
  value,
  note,
  tone,
  testid,
}: {
  label: string;
  value: React.ReactNode;
  note?: string;
  tone?: "danger";
  testid?: string;
}) {
  return (
    <article
      className={`stat-card${tone ? ` stat-card-${tone}` : ""}`}
      data-testid={testid}
    >
      <span className="stat-label">{label}</span>
      <strong>{value}</strong>
      {note ? <span className="stat-note">{note}</span> : null}
    </article>
  );
}

export function EmptyState({
  title,
  body,
  actionLabel,
  actionHref,
}: {
  title: string;
  body: string;
  actionLabel?: string;
  actionHref?: string;
}) {
  // No aria-live: this mounts with its content already present, so the region
  // would not announce. See Loading in useView.tsx.
  return (
    <section className="empty-state">
      <h2>{title}</h2>
      <p>{body}</p>
      {actionLabel && actionHref ? (
        <LinkButton href={actionHref}>{actionLabel}</LinkButton>
      ) : null}
    </section>
  );
}

export function LinkButton({
  href,
  secondary,
  children,
  testid,
}: {
  href: string;
  secondary?: boolean;
  children: React.ReactNode;
  testid?: string;
}) {
  if (href.startsWith("/")) {
    return (
      <Link
        className={`button-link${secondary ? " button-secondary" : ""}`}
        to={href}
        data-testid={testid}
      >
        {children}
      </Link>
    );
  }
  return (
    <a
      className={`button-link${secondary ? " button-secondary" : ""}`}
      href={href}
      data-testid={testid}
    >
      {children}
    </a>
  );
}

export function PageHeader({
  eyebrow,
  title,
  subtitle,
  actions,
}: {
  eyebrow: string;
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <header className={`page-header${actions ? " page-header-actions" : ""}`}>
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        {subtitle ? <p className="page-subtitle">{subtitle}</p> : null}
      </div>
      {actions ? <div className="page-header-actions-group">{actions}</div> : null}
    </header>
  );
}

// The .panel + .panel-header markup appeared 39 times across 13 pages, always
// the same shape. Promoted out of Settings.tsx, where the only extraction lived.
export function Panel({
  title,
  blurb,
  actions,
  children,
  testid,
  titleId,
}: {
  title: React.ReactNode;
  blurb?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
  testid?: string;
  /** Wires <h2 id> to the section's aria-labelledby. */
  titleId?: string;
}) {
  return (
    <section
      className="panel"
      data-testid={testid}
      aria-labelledby={titleId}
    >
      <div className="panel-header">
        <div>
          <h2 id={titleId}>{title}</h2>
          {blurb ? <p>{blurb}</p> : null}
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}

// Structure follows shadcn's breadcrumb (nav > ol > li, aria-current on the
// last crumb): https://ui.shadcn.com/docs/components/base/breadcrumb
// Replaces the ad-hoc `<p className="page-context">` trail in RunHarness.tsx.
export function Breadcrumb({
  items,
}: {
  items: { label: React.ReactNode; href?: string }[];
}) {
  return (
    <nav aria-label="Breadcrumb" className="breadcrumb">
      <ol>
        {items.map((item, index) => {
          const isLast = index === items.length - 1;
          return (
            <li key={index}>
              {item.href && !isLast ? (
                <Link to={item.href}>{item.label}</Link>
              ) : (
                <span aria-current={isLast ? "page" : undefined}>{item.label}</span>
              )}
              {!isLast ? (
                <span className="breadcrumb-separator" aria-hidden="true">
                  /
                </span>
              ) : null}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

export function Spinner() {
  return <span className="spinner" aria-hidden="true" />;
}

export function ErrorNote({ message }: { message: string }) {
  return (
    <p className="form-error" role="alert">
      {message}
    </p>
  );
}

export function formatMs(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  return `${Math.round(value * 10) / 10} ms`;
}

export function shortDate(value: string | undefined): string {
  if (!value) return "";
  return value.slice(0, 16).replace("T", " ");
}
