import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useRef } from "react";
import { useView, Loading } from "../useView";
import { EmptyState, LinkButton, PageHeader, StatusBadge } from "../ui";
import { DataTable } from "../table";

interface TestRow {
  test_id: string;
  pack_id: string | null;
  category: string | null;
  risk: string | null;
  run_count: number;
  latest_status: string | null;
  latest_run_id: string | null;
}

interface TestsView {
  tests: TestRow[];
  categories: string[];
  risks: string[];
  status_labels: Record<string, string>;
}

export function TestsPage() {
  const [params] = useSearchParams();
  const filters = {
    q: params.get("q") ?? "",
    status: params.get("status") ?? "all",
    risk: params.get("risk") ?? "all",
    category: params.get("category") ?? "all",
  };
  const { view, error } = useView<TestsView>("/tests", filters);

  if (error) return <EmptyState title="Could not load the library" body={error} />;
  if (!view) return <Loading />;

  return (
    <>
      <PageHeader
        eyebrow="Coverage library"
        title="Tests"
        subtitle="Search and triage distinct tests across recorded runs."
        actions={<LinkButton href="/tests/new" testid="define-test">Define Test</LinkButton>}
      />
      {!view.tests.length && !filters.q ? (
        <EmptyState
          title="No tests yet"
          body="Define one or run a pack to record results."
          actionLabel="Define a test"
          actionHref="/tests/new"
        />
      ) : (
        <section className="panel">
          <TestsFilterBar filters={filters} view={view} />
          <DataTable
            caption="Test library, with pack, risk and latest outcome"
            empty="No tests match the current filters."
            rows={view.tests}
            rowKey={(t) => `${t.pack_id ?? "-"}:${t.test_id}`}
            rowTestId="test-row"
            columns={[
              {
                key: "test",
                header: "Test",
                sort: (t) => t.test_id,
                cell: (t) =>
                  t.latest_run_id ? (
                    <Link to={`/runs/${t.latest_run_id}/tests/${encodeURIComponent(t.test_id)}`}>
                      {t.test_id}
                    </Link>
                  ) : (
                    t.test_id
                  ),
              },
              { key: "pack", header: "Pack", sort: (t) => t.pack_id ?? "Run history", cell: (t) => t.pack_id || "Run history" },
              { key: "category", header: "Category", sort: (t) => t.category ?? "", cell: (t) => t.category },
              {
                key: "risk",
                header: "Risk",
                sort: (t) => t.risk ?? "",
                cell: (t) => (t.risk ? <StatusBadge status={t.risk} /> : "-"),
              },
              { key: "runs", header: "Runs", sort: (t) => t.run_count, cell: (t) => t.run_count },
              {
                key: "latest",
                header: "Latest status",
                sort: (t) => t.latest_status ?? "",
                cell: (t) => (t.latest_status ? <StatusBadge status={t.latest_status} /> : "-"),
              },
            ]}
          />
        </section>
      )}
    </>
  );
}

function TestsFilterBar({
  filters,
  view,
}: {
  filters: { q: string; status: string; risk: string; category: string };
  view: TestsView;
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
