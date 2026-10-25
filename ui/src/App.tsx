import { Route, Routes } from "react-router-dom";
import { Shell } from "./components/Shell";
import { AgentDetail } from "./pages/AgentDetail";
import { Agents } from "./pages/Agents";
import { Dashboard } from "./pages/Dashboard";
import { DataSources } from "./pages/DataSources";
import { Models } from "./pages/Models";
import { RunDetail } from "./pages/RunDetail";
import { Runs } from "./pages/Runs";
import { SettingsPage } from "./pages/SettingsPage";
import { Wizard } from "./pages/Wizard";

export function App() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<Dashboard />} />
        <Route path="agents" element={<Agents />} />
        <Route path="agents/new" element={<Wizard />} />
        <Route path="agents/:id" element={<AgentDetail />} />
        <Route path="runs" element={<Runs />} />
        <Route path="runs/:id" element={<RunDetail />} />
        <Route path="datasources" element={<DataSources />} />
        <Route path="models" element={<Models />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
    </Routes>
  );
}
