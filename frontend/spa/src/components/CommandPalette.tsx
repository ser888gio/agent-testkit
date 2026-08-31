// Global search: jump to a run, agent, or test from anywhere.

import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bot, ListChecks, Rows3 } from "lucide-react";
import { apiGet } from "../api";
import { encodeAgentId } from "../pages/Agents";

interface Hit {
  key: string;
  group: "Runs" | "Agents" | "Tests";
  label: string;
  detail: string;
  to: string;
}

const GROUP_ICON = { Runs: Rows3, Agents: Bot, Tests: ListChecks } as const;

// Per group, so one busy noun cannot crowd the others out of the list.
const PER_GROUP = 5;

interface RunHit {
  id: string;
  short_id: string;
  agent_id: string;
  status: string;
}
interface AgentHit {
  agent: { id: string; target_type: string };
  run_count: number;
}
interface TestHit {
  test_id: string;
  category: string | null;
  latest_run_id: string | null;
}

// /api/runs and /api/tests filter on `q` server-side; /api/agents takes no
// query param and returns every row, so that one is matched here.
async function search(q: string): Promise<Hit[]> {
  const [runs, agents, tests] = await Promise.all([
    apiGet<{ runs: RunHit[] }>("/runs", { q }),
    apiGet<{ agent_rows: AgentHit[] }>("/agents"),
    apiGet<{ tests: TestHit[] }>("/tests", { q }),
  ]);

  const needle = q.toLowerCase();
  return [
    ...runs.runs.slice(0, PER_GROUP).map((r) => ({
      key: `run:${r.id}`,
      group: "Runs" as const,
      label: r.short_id || r.id,
      detail: `${r.agent_id} · ${r.status}`,
      to: `/runs/${r.id}`,
    })),
    ...agents.agent_rows
      .filter((a) => a.agent.id.toLowerCase().includes(needle))
      .slice(0, PER_GROUP)
      .map((a) => ({
        key: `agent:${a.agent.id}`,
        group: "Agents" as const,
        label: a.agent.id,
        detail: `${a.agent.target_type} · ${a.run_count} run(s)`,
        to: `/agents/${encodeAgentId(a.agent.id)}`,
      })),
    ...tests.tests.slice(0, PER_GROUP).map((t) => ({
      key: `test:${t.test_id}`,
      group: "Tests" as const,
      label: t.test_id,
      detail: t.category ?? "uncategorised",
      // A test is only viewable through the run that exercised it; without one
      // there is no detail page, so fall back to the filtered library.
      to: t.latest_run_id
        ? `/runs/${t.latest_run_id}/tests/${encodeURIComponent(t.test_id)}`
        : `/tests?q=${encodeURIComponent(t.test_id)}`,
    })),
  ];
}

export function CommandPalette() {
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[]>([]);
  const [active, setActive] = useState(0);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "k" || !(event.metaKey || event.ctrlKey)) return;
      event.preventDefault();
      inputRef.current?.focus();
      inputRef.current?.select();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  // Debounced so a typed word is one round trip, not one per keystroke. The
  // stale-response guard matters more than the delay: three endpoints race
  // per query, and an earlier slow reply must not overwrite a later fast one.
  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) {
      setHits([]);
      return;
    }
    let live = true;
    const timer = window.setTimeout(() => {
      search(term)
        .then((found) => {
          if (!live) return;
          setHits(found);
          setActive(0);
        })
        .catch(() => {
          // A failed lookup shows as "no matches"; the pages themselves
          // surface real API errors.
          if (live) setHits([]);
        });
    }, 200);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [q]);

  const grouped = useMemo(() => {
    const order: Hit["group"][] = ["Runs", "Agents", "Tests"];
    return order
      .map((group) => ({ group, items: hits.filter((h) => h.group === group) }))
      .filter((g) => g.items.length > 0);
  }, [hits]);

  const go = (hit: Hit) => {
    setQ("");
    setHits([]);
    setOpen(false);
    inputRef.current?.blur();
    navigate(hit.to);
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "Escape") {
      setOpen(false);
      inputRef.current?.blur();
      return;
    }
    if (!hits.length) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((i) => (i + 1) % hits.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((i) => (i - 1 + hits.length) % hits.length);
    } else if (event.key === "Enter") {
      event.preventDefault();
      go(hits[active]);
    }
  };

  const showResults = open && q.trim().length >= 2;

  return (
    <div className="header-search">
      <svg className="header-search-icon" viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="11" cy="11" r="7" />
        <path d="m20 20-3.5-3.5" />
      </svg>
      <input
        ref={inputRef}
        type="search"
        data-testid="header-search"
        placeholder="Search runs, agents, tests..."
        aria-label="Search runs, agents and tests"
        role="combobox"
        aria-expanded={showResults}
        aria-controls="header-search-results"
        aria-autocomplete="list"
        autoComplete="off"
        value={q}
        onChange={(event) => {
          setQ(event.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        // Blur closes the list, but not before a click on a result lands.
        onBlur={() => window.setTimeout(() => setOpen(false), 150)}
        onKeyDown={onKeyDown}
      />
      <kbd aria-hidden="true">⌘K</kbd>
      {showResults ? (
        <div className="header-search-results" id="header-search-results" role="listbox">
          {grouped.length === 0 ? (
            <p className="header-search-empty">No matches for “{q.trim()}”</p>
          ) : (
            grouped.map(({ group, items }) => {
              const Icon = GROUP_ICON[group];
              return (
                <div key={group} className="header-search-group">
                  <p className="header-search-group-label">{group}</p>
                  {items.map((hit) => (
                    <button
                      key={hit.key}
                      type="button"
                      role="option"
                      aria-selected={hits[active]?.key === hit.key}
                      className={hits[active]?.key === hit.key ? "active" : undefined}
                      // mousedown, not click: blur would close the list first.
                      onMouseDown={(event) => {
                        event.preventDefault();
                        go(hit);
                      }}
                      onMouseEnter={() => setActive(hits.indexOf(hit))}
                    >
                      <Icon className="header-search-hit-icon" aria-hidden="true" />
                      <span>
                        <strong>{hit.label}</strong>
                        <small>{hit.detail}</small>
                      </span>
                    </button>
                  ))}
                </div>
              );
            })
          )}
        </div>
      ) : null}
    </div>
  );
}
