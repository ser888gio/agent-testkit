// Top app bar: sidebar toggle, search, theme toggle, notifications, account menu.

import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { Bell, CircleHelp, LogOut, PanelLeft, Search, Settings, UserRound } from "lucide-react";
import type { Session } from "../session";

function SearchBox() {
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "k" || !(event.metaKey || event.ctrlKey)) return;
      event.preventDefault();
      inputRef.current?.focus();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="header-search">
      <Search className="header-search-icon" aria-hidden="true" />
      <input
        ref={inputRef}
        type="search"
        data-testid="header-search"
        placeholder="Search or type command..."
        aria-label="Search"
      />
      <kbd aria-hidden="true">⌘K</kbd>
    </div>
  );
}

function initials(session: Session): string {
  const name = session.subject || session.email;
  return name.slice(0, 2).toUpperCase();
}

function AccountMenu({ session }: { session: Session }) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button type="button" className="account-trigger" data-testid="account-menu">
          <span className="account-avatar" aria-hidden="true">
            {initials(session)}
          </span>
          <span className="account-name">{session.subject || session.email}</span>
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content className="account-menu-list" align="end" sideOffset={8}>
          <DropdownMenu.Label className="account-menu-head">
            <strong>{session.subject || session.email}</strong>
            <small>{session.email}</small>
          </DropdownMenu.Label>
          <DropdownMenu.Separator className="account-menu-rule" />
          <DropdownMenu.Item asChild>
            <Link to="/settings">
              <UserRound className="account-menu-icon" aria-hidden="true" />
              Edit profile
            </Link>
          </DropdownMenu.Item>
          <DropdownMenu.Item asChild>
            <Link to="/settings">
              <Settings className="account-menu-icon" aria-hidden="true" />
              Account settings
            </Link>
          </DropdownMenu.Item>
          <DropdownMenu.Item asChild>
            <a href="https://github.com/ser888gio/agent-testkit" target="_blank" rel="noreferrer">
              <CircleHelp className="account-menu-icon" aria-hidden="true" />
              Support
            </a>
          </DropdownMenu.Item>
          {session.oidc_enabled ? (
            <>
              <DropdownMenu.Separator className="account-menu-rule" />
              <DropdownMenu.Item asChild>
                <a href="/logout">
                  <LogOut className="account-menu-icon" aria-hidden="true" />
                  Sign out
                </a>
              </DropdownMenu.Item>
            </>
          ) : null}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

export function Header({
  session,
  onToggleNav,
  navOpen,
  themeToggle,
}: {
  session: Session;
  onToggleNav: () => void;
  navOpen: boolean;
  themeToggle: React.ReactNode;
}) {
  return (
    <header className="app-header" data-testid="app-header">
      <button
        type="button"
        className="header-icon-button"
        data-testid="nav-toggle"
        aria-expanded={navOpen}
        aria-controls="primary-nav"
        aria-label="Toggle navigation"
        onClick={onToggleNav}
      >
        <PanelLeft className="header-icon" aria-hidden="true" />
      </button>
      <SearchBox />
      <div className="header-actions">
        {themeToggle}
        <button
          type="button"
          className="header-icon-button has-dot"
          data-testid="header-notifications"
          aria-label="Notifications"
        >
          <Bell className="header-icon" aria-hidden="true" />
        </button>
        <AccountMenu session={session} />
      </div>
    </header>
  );
}
