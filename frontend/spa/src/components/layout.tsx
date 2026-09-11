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
  // The header button collapses the sidebar to an icon rail. Persisted so the
  // choice survives a reload, which is the whole point of a manual toggle.
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem("aa-sidebar") === "collapsed";
    } catch {
      return false;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem("aa-sidebar", collapsed ? "collapsed" : "open");
    } catch {
      // Storage blocked: the toggle still works for this page view.
    }
  }, [collapsed]);

  // Below the sidebar breakpoint it becomes an overlay; a route change closes
  // it so the destination is not hidden behind the nav.
  const [navOpen, setNavOpen] = useState(false);
  const navRef = useRef<HTMLElement>(null);

  useEffect(() => setNavOpen(false), [location.pathname]);

  // Escape closes the open menu and returns focus to the button that opened
  // it, which is otherwise lost somewhere in the collapsed nav.
  useEffect(() => {
    if (!navOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setNavOpen(false);
      document.querySelector<HTMLButtonElement>('[data-testid="nav-toggle"]')?.focus();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [navOpen]);

  return (
    <>
      <a className="skip-link" href="#content">
        Skip to content
      </a>
      <div className={`layout${collapsed ? " collapsed" : ""}`}>
        <aside className={`sidebar${navOpen ? " open" : ""}`}>
          <Link className="brand" to="/" aria-label="OKJUL runs">
            <span className="brand-mark" aria-hidden="true">
              OK
            </span>
            <span className="brand-name">OKJUL</span>
          </Link>
          <nav ref={navRef} id="primary-nav" aria-label="Primary">
            <p className="nav-section">Menu</p>
            {NAV.map(({ to, testid, label, Icon }) => (
              <NavLink
                key={to}
                to={to}
                end={to === "/"}
                data-testid={testid}
                title={label}
                className={({ isActive }) => (isActive ? "active" : undefined)}
              >
                <Icon className="nav-icon" aria-hidden="true" />
                <span className="nav-label">{label}</span>
              </NavLink>
            ))}
          </nav>
        </aside>
        {/* Click-catcher for the overlay sidebar on narrow viewports. */}
        {navOpen ? (
          <button
            type="button"
            className="sidebar-scrim"
            aria-label="Close navigation"
            onClick={() => setNavOpen(false)}
          />
        ) : null}
        <div className="shell">
          {/* App renders Loading until the session resolves, so this is set
              by the time Layout mounts; the context type is nullable. */}
          {session ? (
            <Header
              session={session}
              collapsed={collapsed}
              onToggleNav={() => {
                // One button, two jobs: it collapses the rail on desktop and
                // opens the overlay where the sidebar is off-canvas.
                if (window.matchMedia("(max-width: 920px)").matches) {
                  setNavOpen((open) => !open);
                } else {
                  setCollapsed((c) => !c);
                }
              }}
              themeToggle={<ThemeToggle />}
            />
          ) : null}
          <main id="content" tabIndex={-1}>
            {children}
            <footer className="site-footer" data-testid="site-footer">
              <p className="site-footer-brand">OKJUL</p>
              <p>
                Black-box testing and assurance for AI agents. Evidence produced here is technical
                evidence, not a CE marking or compliance determination.
              </p>
              <p className="quiet">
                &copy; {new Date().getFullYear()} OKJUL &middot; Apache-2.0 licensed
              </p>
            </footer>
          </main>
        </div>
      </div>
    </>
  );
}
