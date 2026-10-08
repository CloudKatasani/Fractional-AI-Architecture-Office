import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import "./index.css";
import { Layout } from "./components/Layout";
import { AppStateProvider, useApp } from "./state/AppState";
import Dashboard from "./pages/Dashboard";
import Portfolio from "./pages/Portfolio";
import AIGovernance from "./pages/AIGovernance";
import AppArchitecture from "./pages/AppArchitecture";
import EnterpriseArchitecture from "./pages/EnterpriseArchitecture";
import DataArchitecture from "./pages/DataArchitecture";
import Copilot from "./pages/Copilot";
import Approvals from "./pages/Approvals";
import Audit from "./pages/Audit";
import GraphExplorer from "./pages/GraphExplorer";
import Agents from "./pages/Agents";
import IngestedSources from "./pages/IngestedSources";

function Routed() {
  const { tenant } = useApp();
  return (
    <Layout>
      <Routes key={tenant}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/portfolio" element={<Portfolio />} />
        <Route path="/ai-governance" element={<AIGovernance />} />
        <Route path="/application" element={<AppArchitecture />} />
        <Route path="/enterprise" element={<EnterpriseArchitecture />} />
        <Route path="/data" element={<DataArchitecture />} />
        <Route path="/copilot" element={<Copilot />} />
        <Route path="/approvals" element={<Approvals />} />
        <Route path="/audit" element={<Audit />} />
        <Route path="/graph" element={<GraphExplorer />} />
        <Route path="/agents" element={<Agents />} />
        <Route path="/sources" element={<IngestedSources />} />
      </Routes>
    </Layout>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <AppStateProvider>
        <Routed />
      </AppStateProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
