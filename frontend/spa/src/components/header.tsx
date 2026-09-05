// Top app bar: sidebar toggle, search, theme toggle, notifications, account menu.

import { Link } from "react-router-dom";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { CircleHelp, LogOut, PanelLeft, Settings, UserRound } from "lucide-react";
import type { Session } from "../session";
import { CommandPalette } from "./CommandPalette";

function initials(session: Session): string {
  return session.email.slice(0, 2).toUpperCase();
}

function AccountMenu({ session }: { session: Session }) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button type="button" className="account-trigger" data-testid="account-menu">
          <span className="account-avatar" aria-hidden="true">
            {initials(session)}
          </span>
          <span className="account-name">{session.email}</span>
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content className="account-menu-list" align="end" sideOffset={8}>
          <DropdownMenu.Label className="account-menu-head">
            <strong>{session.email}</strong>
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
  collapsed,
  themeToggle,
}: {
  session: Session;
  onToggleNav: () => void;
  collapsed: boolean;
  themeToggle: React.ReactNode;
}) {
  return (
    <header className="app-header" data-testid="app-header">
      <button
        type="button"
        className="header-icon-button"
        data-testid="nav-toggle"
        aria-expanded={!collapsed}
        aria-controls="primary-nav"
        aria-label="Toggle navigation"
        onClick={onToggleNav}
      >
        <PanelLeft className="header-icon" aria-hidden="true" />
      </button>
      <CommandPalette />
      <div className="header-actions">
        {themeToggle}
        <AccountMenu session={session} />
      </div>
    </header>
  );
}
