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

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSession outside SessionProvider");
  return session;
}
