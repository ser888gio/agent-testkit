// App shell: top header, sidebar navigation, footer.

import { useEffect, useRef, useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import {
  Bot,
  ChartLine,
  ListChecks,
  Moon,
  Rows3,
  Settings as SettingsIcon,
  Shuffle,
  Sun,
  type LucideIcon,
} from "lucide-react";
import { useSession } from "../session";
import { Header } from "./header";

// testids are asserted as string literals against this source file by
// tests/test_web.py::test_spa_source_keeps_nav_and_action_hooks. Keep them
// spelled out here rather than computed.
const NAV: { to: string; testid: string; label: string; Icon: LucideIcon }[] = [
  { to: "/", testid: "nav-analytics", label: "Analytics", Icon: ChartLine },
  { to: "/runs", testid: "nav-runs", label: "Runs", Icon: Rows3 },
  { to: "/agents", testid: "nav-agents", label: "Agents", Icon: Bot },
  { to: "/tests", testid: "nav-tests", label: "Tests", Icon: ListChecks },
  { to: "/generated", testid: "nav-generated", label: "Generated", Icon: Shuffle },
  { to: "/settings", testid: "nav-settings", label: "Settings", Icon: SettingsIcon },
];

function ThemeToggle() {
  const [theme, setTheme] = useState<"light" | "dark">("dark");

  useEffect(() => {
    // The boot script in index.html always stamps an explicit theme, so this
    // only has to read it back.
    const set = document.documentElement.getAttribute("data-theme");
    if (set === "light" || set === "dark") setTheme(set);
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

  const Icon = theme === "light" ? Moon : Sun;
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
      <Icon className="theme-icon" aria-hidden="true" />
    </button>
  );
}

export function Layout({ children }: { children: React.ReactNode }) {
  const session = useSession();
  const location = useLocation();
  // Below the sidebar breakpoint the nav collapses behind a button. Reset on
  // navigation so a route change closes it.
  const [menuOpen, setMenuOpen] = useState(false);
  const navRef = useRef<HTMLElement>(null);

  useEffect(() => setMenuOpen(false), [location.pathname]);

  // Escape closes the open menu and returns focus to the button that opened
  // it, which is otherwise lost somewhere in the collapsed nav.
  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setMenuOpen(false);
      document.querySelector<HTMLButtonElement>('[data-testid="nav-toggle"]')?.focus();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [menuOpen]);

  return (
    <>
      <a className="skip-link" href="#content">
        Skip to content
      </a>
      {/* App renders Loading until the session resolves, so this is set by
          the time Layout mounts; the context type is nullable regardless. */}
      {session ? (
        <Header
          session={session}
          navOpen={menuOpen}
          onToggleNav={() => setMenuOpen((open) => !open)}
          themeToggle={<ThemeToggle />}
        />
      ) : null}
      <div className="layout">
        <aside className="sidebar">
          <Link className="brand" to="/" aria-label="agentaudit runs">
            <span className="brand-mark" aria-hidden="true">
              AK
            </span>
            <span>agentaudit</span>
          </Link>
          <nav
            ref={navRef}
            id="primary-nav"
            aria-label="Primary"
            className={menuOpen ? "open" : undefined}
          >
            {NAV.map(({ to, testid, label, Icon }) => (
              <NavLink
                key={to}
                to={to}
                end={to === "/"}
                data-testid={testid}
                className={({ isActive }) => (isActive ? "active" : undefined)}
              >
                <Icon className="nav-icon" aria-hidden="true" />
                <span>{label}</span>
              </NavLink>
            ))}
            {session?.oidc_enabled ? <a href="/logout"><span>Sign out</span></a> : null}
          </nav>
        </aside>
        <main id="content" tabIndex={-1}>
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
