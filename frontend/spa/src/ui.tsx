// Shared UI primitives, ported one-for-one from the Jinja macros in
// templates/_components.html and the layout in base.html. Class names are the
// stylesheet's; the design contract lives in /static/style.css.

import { Link } from "react-router-dom";

export function StatusBadge({ status, label }: { status: string; label?: string }) {
  return (
    <span className={`badge badge-${status}`}>{label ?? status}</span>
  );
}

const RISK_BADGE: Record<string, string> = {
  low: "badge-low",
  medium: "badge-medium",
  high: "badge-high",
  critical: "badge-critical",
};

export function RiskBadge({ risk }: { risk: string }) {
  return <span className={`badge ${RISK_BADGE[risk] ?? ""}`}>{risk}</span>;
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
  return (
    <section className="empty-state" aria-live="polite">
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
