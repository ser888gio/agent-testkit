import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

export function RunsFilterBar({
  filters,
  agents,
  labels,
}: {
  filters: { q: string; status: string; agent: string; sort: string };
  agents: string[];
  labels: Record<string, string>;
}) {
  const navigate = useNavigate();
  const [q, setQ] = useState(filters.q);
  // Keep the box in sync when navigation resets the filters.
  useEffect(() => setQ(filters.q), [filters.q]);

  const apply = (patch: Partial<typeof filters>) => {
    const next = new URLSearchParams({ ...filters, ...patch } as Record<string, string>);
    for (const [key, value] of [...next.entries()]) {
      if ((key === "q" && !value) || value === "all") next.delete(key);
    }
    const query = next.toString();
    navigate(query ? `?${query}` : "?");
  };

  return (
    <form
      className="filter-bar"
      onSubmit={(event) => {
        event.preventDefault();
        apply({ q });
      }}
    >
      <label>
        Search
        <input
          type="search"
          name="q"
          value={q}
          placeholder="Run or agent"
          autoComplete="off"
          onChange={(event) => setQ(event.target.value)}
        />
      </label>
      <label>
        Status
        <select name="status" value={filters.status} onChange={(e) => apply({ status: e.target.value })}>
          {Object.entries(labels).map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <label>
        Agent
        <select name="agent" value={filters.agent} onChange={(e) => apply({ agent: e.target.value })}>
          <option value="all">All agents</option>
          {agents.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
      </label>
      <label>
        Sort
        <select name="sort" value={filters.sort} onChange={(e) => apply({ sort: e.target.value })}>
          <option value="attention">Needs attention</option>
          <option value="score">Lowest score</option>
          <option value="agent">Agent</option>
        </select>
      </label>
      <Link className="button-secondary" to="/runs">
        Reset
      </Link>
    </form>
  );
}
