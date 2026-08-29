import { useCallback, useEffect, useState } from "react";
import { ApiError, apiGet } from "../api";

// One fetch per page: the JSON API returns the whole view model the React
// pages use, so pages render from a single response object.
export function useView<T>(path: string, params?: Record<string, string>) {
  const [view, setView] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);
  const key = params ? JSON.stringify(params) : "";

  useEffect(() => {
    let alive = true;
    // The previous view stays on screen while the next one loads. Blanking it
    // here meant every navigation -- including back/forward and each debounced
    // keystroke in a filter box -- flashed a full-page loading state over
    // content that was about to be replaced by something nearly identical.
    setLoading(true);
    setError(null);
    apiGet<T>(path, params)
      .then((data) => {
        if (!alive) return;
        setView(data);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (!alive) return;
        setError(err instanceof ApiError ? err.detail : "Request failed.");
        setLoading(false);
      });
    return () => {
      // Cleared on every dep change, not just unmount, so a slow response for
      // a stale path can never overwrite a newer one.
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, key, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { view, error, loading, reload };
}

// No aria-live: this mounts already populated, and a live region inserted with
// its content is generally not announced. Claiming coverage that does not fire
// is worse than not claiming it.
export function Loading({ label = "Loading..." }: { label?: string }) {
  return (
    <p className="quiet">
      <span className="spinner" aria-hidden="true" /> {label}
    </p>
  );
}
