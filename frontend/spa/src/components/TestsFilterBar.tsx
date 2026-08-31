import { useRef } from "react";
import { Link, useNavigate } from "react-router-dom";

export function TestsFilterBar({
  filters,
  view,
}: {
  filters: { q: string; status: string; risk: string; category: string };
  view: { categories: string[]; risks: string[]; status_labels: Record<string, string> };
}) {
  const navigate = useNavigate();
  const timer = useRef<number | undefined>(undefined);

  const apply = (patch: Partial<typeof filters>) => {
    const next = new URLSearchParams({ ...filters, ...patch });
    for (const [key, value] of [...next.entries()]) {
      if (!value || value === "all") next.delete(key);
    }
    const query = next.toString();
    navigate(query ? `?${query}` : "?");
  };

  return (
    <form
      className="filter-bar"
      onSubmit={(event) => {
        event.preventDefault();
        apply({});
      }}
    >
      <label>
        Search
        <input
          type="search"
          name="q"
          defaultValue={filters.q}
          placeholder="Test ID or category"
          autoComplete="off"
          onChange={(event) => {
            window.clearTimeout(timer.current);
            const value = event.target.value;
            timer.current = window.setTimeout(() => apply({ q: value }), 350);
          }}
        />
      </label>
      <label>
        Status
        <select value={filters.status} onChange={(e) => apply({ status: e.target.value })}>
          {Object.entries(view.status_labels).map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <label>
        Risk
        <select value={filters.risk} onChange={(e) => apply({ risk: e.target.value })}>
          <option value="all">All risks</option>
          {view.risks.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
      </label>
      <label>
        Category
        <select value={filters.category} onChange={(e) => apply({ category: e.target.value })}>
          <option value="all">All categories</option>
          {view.categories.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </label>
      <Link className="button-secondary" to="/tests">
        Reset
      </Link>
    </form>
  );
}
