import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { ChevronDown, Download } from "lucide-react";

function Icon({ children }: { children: React.ReactNode }) {
  return (
    <svg className="export-icon" aria-hidden="true" viewBox="0 0 24 24">
      {children}
    </svg>
  );
}

// A page outline with a format mark, so the menu reads as "a file of this kind".
const FileIcon = ({ mark }: { mark: React.ReactNode }) => (
  <Icon>
    <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
    <path d="M14 3v5h5" />
    {mark}
  </Icon>
);

const EXPORTS = [
  {
    fmt: "pdf",
    label: "PDF",
    note: "Print-ready report",
    icon: <FileIcon mark={<path d="M8 17v-4h1.5a1.5 1.5 0 0 1 0 3H8m5 1v-4h1.5a1.5 1.5 0 0 1 1.5 1.5v1a1.5 1.5 0 0 1-1.5 1.5z" />} />,
  },
  {
    fmt: "html",
    label: "HTML",
    note: "Styled web report",
    icon: <FileIcon mark={<path d="M9.5 13.5 7.5 15.5l2 2m5-4 2 2-2 2" />} />,
  },
  {
    fmt: "md",
    label: "Markdown",
    note: "Plain text summary",
    icon: <FileIcon mark={<path d="M7.5 17.5v-4l2 2.5 2-2.5v4m3-4v4m0 0 1.5-1.5m-1.5 1.5L13 16" />} />,
  },
  {
    fmt: "json",
    label: "JSON",
    note: "Full structured data",
    icon: <FileIcon mark={<path d="M10 13.5c-1.5 0-1.5 1.5-1.5 2s0 2-1.5 2m6-4c1.5 0 1.5 1.5 1.5 2s0 2 1.5 2" />} />,
  },
  {
    fmt: "junit",
    label: "JUnit XML",
    note: "For CI pipelines",
    icon: <FileIcon mark={<path d="M8 13.5 6.5 15.5 8 17.5m6-4 1.5 2-1.5 2m-3.5 1 2-6" />} />,
  },
] as const;

// Radix owns the menu behaviour. The hand-rolled version declared role="menu"
// and role="menuitem" but implemented only outside-click and Escape -- no arrow
// keys, no focus trap, no focus return to the trigger. Announcing the menu
// pattern to a screen reader and then not providing it is worse than not
// announcing it, since the user is told to expect keys that do nothing.
export function ExportMenu({ runId }: { runId: string }) {
  const href = (fmt: string) => `/api/runs/${encodeURIComponent(runId)}/export/${fmt}`;

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button type="button" data-testid="export-report" className="export-menu-trigger">
          <Download className="export-icon" aria-hidden="true" />
          Download report
          <ChevronDown className="export-icon" aria-hidden="true" />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          className="export-menu-list"
          aria-label="Report formats"
          align="end"
          sideOffset={6}
        >
          {EXPORTS.map(({ fmt, label, note, icon }) => (
            <DropdownMenu.Item key={fmt} asChild>
              <a href={href(fmt)} download>
                {icon}
                <span>
                  <strong>{label}</strong>
                  <small>{note}</small>
                </span>
              </a>
            </DropdownMenu.Item>
          ))}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
