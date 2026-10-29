import { Route, Routes } from "react-router-dom";
import { Shell } from "./components/Shell";
import { AuthProvider } from "./lib/auth";
import { AdminPage } from "./pages/AdminPage";
import { AgentDetail } from "./pages/AgentDetail";
import { Agents } from "./pages/Agents";
import { Boards } from "./pages/Boards";
import { ChatPage } from "./pages/ChatPage";
import { Dashboard } from "./pages/Dashboard";
import { DataSources } from "./pages/DataSources";
import { DeliveryChannels } from "./pages/DeliveryChannels";
import { Models } from "./pages/Models";
import { RunDetail } from "./pages/RunDetail";
import { Runs } from "./pages/Runs";
import { SecretProviders } from "./pages/SecretProviders";
import { SettingsPage } from "./pages/SettingsPage";
import { Wizard } from "./pages/Wizard";

export function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route element={<Shell />}>
          <Route index element={<Dashboard />} />
          <Route path="chat" element={<ChatPage />} />
          <Route path="boards" element={<Boards />} />
          <Route path="agents" element={<Agents />} />
          <Route path="agents/new" element={<Wizard />} />
          <Route path="agents/:id" element={<AgentDetail />} />
          <Route path="runs" element={<Runs />} />
          <Route path="runs/:id" element={<RunDetail />} />
          <Route path="datasources" element={<DataSources />} />
          <Route path="models" element={<Models />} />
          <Route path="secrets" element={<SecretProviders />} />
          <Route path="delivery" element={<DeliveryChannels />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="admin" element={<AdminPage />} />
        </Route>
      </Routes>
    </AuthProvider>
  );
}
