import { Navigate, Route, Routes } from "react-router-dom";
import { AppLayout } from "./components/AppLayout";
import { RequireAuth } from "./components/RequireAuth";
import { RequireAdmin } from "./components/RequireAdmin";
import { LoginPage } from "./pages/LoginPage";
import { UsersPage } from "./pages/UsersPage";
import { PromptListPage } from "./pages/PromptListPage";
import { PromptEditorPage } from "./pages/PromptEditorPage";
import { VersionHistoryPage } from "./pages/VersionHistoryPage";
import { PlaygroundPage } from "./pages/PlaygroundPage";
import { DashboardPage } from "./pages/DashboardPage";
import { RunsPage } from "./pages/RunsPage";
import { TracesPage } from "./pages/TracesPage";
import { ScanResultsPage } from "./pages/ScanResultsPage";
import { OverviewPage } from "./pages/OverviewPage";
import { DatasetListPage } from "./pages/DatasetListPage";
import { DatasetEditorPage } from "./pages/DatasetEditorPage";
import { BlockListPage } from "./pages/BlockListPage";
import { BlockDetailPage } from "./pages/BlockDetailPage";
import { BlockEditorPage } from "./pages/BlockEditorPage";

// Route table. /login is public; everything under the layout sits behind RequireAuth.
export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route element={<AppLayout />}>
          {/* Overview is the landing page; the prompt list moved under "Prompts" (Sprint 16c). */}
          <Route index element={<OverviewPage />} />
          <Route path="prompts" element={<PromptListPage />} />
          {/* Keep old /overview bookmarks working. */}
          <Route path="overview" element={<Navigate to="/" replace />} />
          <Route path="datasets" element={<DatasetListPage />} />
          <Route path="datasets/new" element={<DatasetEditorPage />} />
          <Route path="datasets/:name/edit" element={<DatasetEditorPage />} />
          <Route path="blocks" element={<BlockListPage />} />
          <Route path="blocks/new" element={<BlockEditorPage />} />
          <Route path="blocks/:name" element={<BlockDetailPage />} />
          <Route path="blocks/:name/versions/new" element={<BlockEditorPage />} />
          <Route path="prompts/new" element={<PromptEditorPage />} />
          <Route path="prompts/:name/edit" element={<PromptEditorPage />} />
          <Route path="prompts/:name/versions" element={<VersionHistoryPage />} />
          <Route path="prompts/:name/dashboard" element={<DashboardPage />} />
          <Route path="prompts/:name/traces" element={<TracesPage />} />
          <Route
            path="prompts/:name/versions/:versionNumber/playground"
            element={<PlaygroundPage />}
          />
          <Route
            path="prompts/:name/versions/:versionNumber/scan"
            element={<ScanResultsPage />}
          />
          <Route
            path="prompts/:name/versions/:versionNumber/runs"
            element={<RunsPage />}
          />
          {/* Admin-only sections: gated by role, not just hidden in nav (Sprint 16g). */}
          <Route element={<RequireAdmin />}>
            <Route path="users" element={<UsersPage />} />
          </Route>
        </Route>
      </Route>
    </Routes>
  );
}
