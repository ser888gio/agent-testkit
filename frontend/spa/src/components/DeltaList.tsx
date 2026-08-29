export function DeltaList({ items, tone }: { items: string[]; tone?: "pass" | "fail" | "status-failed" | "status-passed" }) {
  if (!items.length) return <li className="quiet">none</li>;
  return (
    <>
      {items.map((t) => (
        <li key={t} className={tone}>
          {t}
        </li>
      ))}
    </>
  );
}
