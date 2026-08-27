import { Route, Routes } from "react-router-dom";
import { Layout } from "./layout";
import { useSession } from "./session";
import { Loading } from "./useView";
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
import { EmptyState, PageHeader } from "./ui";

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
  );
}
