import { Route, Routes, useLocation } from "react-router-dom";
import { Layout } from "./components/layout";
import { useSession } from "./session";
import { Loading } from "./components/useView";
import { AnalyticsPage } from "./pages/Analytics";
import { RunsPage } from "./pages/Runs";
import { RunDetailPage } from "./pages/RunDetail";
import { RunHarnessPage } from "./pages/RunHarness";
import { TestDetailPage } from "./pages/TestDetail";
import { AgentsPage } from "./pages/Agents";
import { AgentDetailPage } from "./pages/AgentDetail";
import { AgentRegisterPage } from "./pages/AgentRegister";
import { AgentConnectPage } from "./pages/AgentConnect";
import { TestsPage } from "./pages/Tests";
import { TestNewPage } from "./pages/TestNew";
import { GeneratedPage } from "./pages/Generated";
import { JobPage } from "./pages/Job";
import { ComparePage } from "./pages/Compare";
import { SettingsPage } from "./pages/Settings";
import { LandingPage } from "./pages/Landing";
import { EmptyState, PageHeader } from "./components/ui";
import { ToastProvider } from "./components/toast";

function NotFound() {
  return (
    <>
      <PageHeader eyebrow="Error" title="404" />
      <EmptyState title="Not found" body="The page you asked for does not exist." actionLabel="Back to dashboard" actionHref="/" />
    </>
  );
}

export function App() {
  const session = useSession();
  // The landing page is public, so it renders ahead of the session gate below
  // and outside <Layout>, which needs a session for the account menu.
  if (useLocation().pathname === "/welcome") return <LandingPage />;
  if (!session) {
    return (
      <div className="layout">
        <main id="content">
          <Loading />
        </main>
      </div>
    );
  }
  return (
    <ToastProvider>
      <Layout>
        <Routes>
        <Route path="/" element={<AnalyticsPage />} />
        <Route path="/runs" element={<RunsPage />} />
        <Route path="/runs/:runId" element={<RunDetailPage />} />
        <Route path="/runs/:runId/harness" element={<RunHarnessPage />} />
        <Route path="/runs/:runId/tests/:testId" element={<TestDetailPage />} />
        <Route path="/agents" element={<AgentsPage />} />
        {/* Agent ids may be URL-shaped and carry slashes; match the rest of
            the path exactly like the server's {agent_id:path} converter. */}
        <Route path="/agents/register" element={<AgentRegisterPage />} />
        <Route path="/agents/connect" element={<AgentConnectPage />} />
        <Route path="/agents/*" element={<AgentDetailPage />} />
        <Route path="/tests" element={<TestsPage />} />
        <Route path="/tests/new" element={<TestNewPage />} />
        <Route path="/generated" element={<GeneratedPage />} />
        <Route path="/jobs/:jobId" element={<JobPage />} />
        <Route path="/compare" element={<ComparePage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<NotFound />} />
        </Routes>
      </Layout>
    </ToastProvider>
  );
}
