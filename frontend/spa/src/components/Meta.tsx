export function Meta({ entries }: { entries: [string, React.ReactNode][] }) {
  return (
    <dl className="harness-meta">
      {entries.map(([key, value]) => (
        <div key={key}>
          <dt>{key}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}
