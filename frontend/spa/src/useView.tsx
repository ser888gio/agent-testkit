import { useCallback, useEffect, useState } from "react";
import { ApiError, apiGet } from "./api";

// One fetch per page: the JSON API returns the whole view model the Jinja
// template used to receive, so pages render from a single response object.
export function useView<T>(path: string, params?: Record<string, string>) {
  const [view, setView] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const key = params ? JSON.stringify(params) : "";

  useEffect(() => {
    let alive = true;
    setView(null);
    setError(null);
    apiGet<T>(path, params)
      .then((data) => {
        if (alive) setView(data);
      })
      .catch((err: unknown) => {
        if (!alive) return;
        if (err instanceof ApiError) setError(err.detail);
        else setError("Request failed.");
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, key, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { view, error, reload };
}

export function Loading({ label = "Loading..." }: { label?: string }) {
  return (
    <p className="quiet" aria-live="polite">
      <span className="spinner" aria-hidden="true" /> {label}
    </p>
  );
}
