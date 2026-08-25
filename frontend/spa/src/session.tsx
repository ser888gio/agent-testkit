import { createContext, useContext, useEffect, useState } from "react";
import { apiGet, setCsrfToken } from "./api";

export interface Session {
  org_id: string;
  subject: string;
  email: string;
  roles: string[];
  auth_method: string;
  admin: boolean;
  oidc_enabled: boolean;
}

const SessionContext = createContext<Session | null>(null);

// The same `null` means both "outside the provider" and "still fetching
// /api/session"; callers render a loading state until it resolves.
export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  useEffect(() => {
    apiGet<Session & { csrf_token: string }>("/session").then((s) => {
      setCsrfToken(s.csrf_token);
      setSession(s);
    });
    // 401 inside apiGet redirects to /login; nothing else to do here.
  }, []);
  return <SessionContext.Provider value={session}>{children}</SessionContext.Provider>;
}

export function useSession(): Session | null {
  return useContext(SessionContext);
}
