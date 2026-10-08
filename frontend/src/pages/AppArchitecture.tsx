import { Adrs, Apis, Debt, Drift, PatternAdvisor } from "../components/arch/AppTabs";
import { setUrlParam } from "../components/arch/common";
import { DesignReviews } from "../components/arch/DesignReviews";
import { ThreatModels } from "../components/arch/ThreatModels";
import { PageHeader } from "../components/Layout";
import { Tabs, useTab } from "../components/ui";
import { useApp } from "../state/AppState";

const TABS = [
  { id: "designs", label: "Design reviews" },
  { id: "adrs", label: "ADRs" },
  { id: "drift", label: "Drift" },
  { id: "apis", label: "APIs" },
  { id: "debt", label: "Tech debt" },
  { id: "threats", label: "Threat models" },
  { id: "patterns", label: "Pattern advisor" },
];

export default function AppArchitecture() {
  const { tenantName } = useApp();
  const [tab, setTab] = useTab("designs", "tab");
  const change = (t: string) => {
    setTab(t);
    setUrlParam("tab", t);
  };
  return (
    <div className="[&_button]:whitespace-nowrap">
      <PageHeader
        title="Application Architecture"
        subtitle={`${tenantName} — design reviews against standards, ADRs from discussions, drift, APIs, tech debt and threat models.`}
      />
      <Tabs tabs={TABS} active={tab} onChange={change} />
      {tab === "designs" && <DesignReviews />}
      {tab === "adrs" && <Adrs />}
      {tab === "drift" && <Drift />}
      {tab === "apis" && <Apis />}
      {tab === "debt" && <Debt />}
      {tab === "threats" && <ThreatModels />}
      {tab === "patterns" && <PatternAdvisor />}
    </div>
  );
}
