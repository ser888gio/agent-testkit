// App shell: sidebar navigation, theme toggle, footer. Ported from
// templates/base.html; the nav icons and testids are kept identical.

import { useEffect, useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { useSession } from "./session";

const NAV = [
  {
    to: "/",
    testid: "nav-analytics",
    label: "Analytics",
    icon: (
      <>
        <path d="M3 3v18h18" />
        <path d="M7 15l4-5 3 3 5-7" />
      </>
    ),
  },
  {
    to: "/harness",
    testid: "nav-harness",
    label: "Harness",
    icon: (
      <>
        <path d="M4 17l6-5-6-5" />
        <path d="M12 19h8" />
      </>
    ),
  },
  {
    to: "/runs",
    testid: "nav-runs",
    label: "Runs",
    icon: (
      <>
        <path d="M4 5h16" />
        <path d="M4 12h16" />
        <path d="M4 19h16" />
        <path d="M8 5v14" />
      </>
    ),
  },
  {
    to: "/agents",
    testid: "nav-agents",
    label: "Agents",
    icon: (
      <>
        <path d="M12 8V4H8" />
        <rect width={16} height={12} x={4} y={8} rx={2} />
        <path d="M2 14h2" />
        <path d="M20 14h2" />
        <path d="M15 13v2" />
        <path d="M9 13v2" />
      </>
    ),
  },
  {
    to: "/tests",
    testid: "nav-tests",
    label: "Tests",
    icon: (
      <>
        <path d="M9 11l3 3L22 4" />
        <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
      </>
    ),
  },
  {
    to: "/generated",
    testid: "nav-generated",
    label: "Generated",
    icon: (
      <>
        <path d="M12 3v18" />
        <path d="M5 8l7-5 7 5" />
        <path d="M5 16l7 5 7-5" />
      </>
    ),
  },
  {
    to: "/settings",
    testid: "nav-settings",
    label: "Settings",
    icon: (
      <>
        <circle cx={12} cy={12} r={3.2} />
        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06A1.65 1.65 0 0 0 15 19.4a1.65 1.65 0 0 0-1 .6 1.65 1.65 0 0 0-.33 1.82 2 2 0 1 1-3.34 0A1.65 1.65 0 0 0 10 20a1.65 1.65 0 0 0-1-.6 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-.6-1 1.65 1.65 0 0 0-1.82-.33 2 2 0 1 1 0-3.34A1.65 1.65 0 0 0 4 10a1.65 1.65 0 0 0 .6-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-.6 1.65 1.65 0 0 0 .33-1.82 2 2 0 1 1 3.34 0A1.65 1.65 0 0 0 14 4a1.65 1.65 0 0 0 1 .6 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9c.14.32.35.6.6 1 .45.28 1 .5 1.82.33a2 2 0 1 1 0 3.34A1.65 1.65 0 0 0 20 14c-.25.4-.46.68-.6 1Z" />
      </>
    ),
  },
];

function NavIcon({ children }: { children: React.ReactNode }) {
  return (
    <svg className="nav-icon" aria-hidden="true" viewBox="0 0 24 24">
      {children}
    </svg>
  );
}

function ThemeToggle() {
  const [theme, setTheme] = useState<"light" | "dark">("dark");

  useEffect(() => {
    const set = document.documentElement.getAttribute("data-theme");
    if (set === "light" || set === "dark") {
      setTheme(set);
      return;
    }
    if (window.matchMedia("(prefers-color-scheme: light)").matches) setTheme("light");
  }, []);

  const toggle = () => {
    const next = theme === "light" ? "dark" : "light";
    document.documentElement.setAttribute("data-theme", next);
    try {
      localStorage.setItem("aa-theme", next);
    } catch {
      // Storage blocked: the theme still applies for this page view.
    }
    setTheme(next);
  };

  return (
    <button
      type="button"
      className="theme-toggle"
      data-testid="theme-toggle"
      aria-pressed={theme === "light"}
      aria-label={theme === "light" ? "Switch to dark theme" : "Switch to light theme"}
      title="Toggle light and dark theme"
      onClick={toggle}
    >
      <svg className="theme-icon theme-icon-dark" aria-hidden="true" viewBox="0 0 24 24">
        <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
      </svg>
      <svg className="theme-icon theme-icon-light" aria-hidden="true" viewBox="0 0 24 24">
        <circle cx={12} cy={12} r={4} />
        <path d="M12 2v2" />
        <path d="M12 20v2" />
        <path d="M4.9 4.9l1.4 1.4" />
        <path d="M17.7 17.7l1.4 1.4" />
        <path d="M2 12h2" />
        <path d="M20 12h2" />
        <path d="M4.9 19.1l1.4-1.4" />
        <path d="M17.7 6.3l1.4-1.4" />
      </svg>
    </button>
  );
}

export function Layout({ children }: { children: React.ReactNode }) {
  const session = useSession();
  const location = useLocation();
  // The mobile menu collapses via a checkbox in the old markup; state is the
  // same idea, reset on navigation so a route change closes it.
  const [menuOpen, setMenuOpen] = useState(false);
  useEffect(() => setMenuOpen(false), [location.pathname]);

  return (
    <>
      <a className="skip-link" href="#content">
        Skip to content
      </a>
      <div className="layout">
        <aside className="sidebar">
          <Link className="brand" to="/" aria-label="agentaudit runs">
            <span className="brand-mark" aria-hidden="true">
              AK
            </span>
            <span>agentaudit</span>
          </Link>
          <button
            type="button"
            className="nav-toggle-button"
            data-testid="nav-toggle"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((open) => !open)}
          >
            <NavIcon>
              <path d="M4 6h16" />
              <path d="M4 12h16" />
              <path d="M4 18h16" />
            </NavIcon>
            <span>Menu</span>
          </button>
          <nav
            aria-label="Primary"
            className={menuOpen ? "open" : undefined}
          >
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                data-testid={item.testid}
                className={({ isActive }) => (isActive ? "active" : undefined)}
              >
                <NavIcon>{item.icon}</NavIcon>
                <span>{item.label}</span>
              </NavLink>
            ))}
            {session.oidc_enabled ? <a href="/logout"><span>Sign out</span></a> : null}
          </nav>
        </aside>
        <main id="content" tabIndex={-1}>
          <ThemeToggle />
          {children}
          <footer className="site-footer" data-testid="site-footer">
            <p className="site-footer-brand">agentaudit</p>
            <p>
              Black-box testing and assurance for AI agents. Evidence produced here is technical
              evidence, not a CE marking or compliance determination.
            </p>
            <p className="quiet">
              © {new Date().getFullYear()} agentaudit · Apache-2.0 licensed
            </p>
          </footer>
        </main>
      </div>
    </>
  );
}
