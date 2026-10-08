import { setUrlParam } from "../components/arch/common";
import { BoardPack, CapabilityHeatMap, GoalsLinkage, ImpactAnalysis, InvestmentAlignment, Roadmaps } from "../components/arch/EaTabs";
import { PageHeader } from "../components/Layout";
import { Tabs, useTab } from "../components/ui";
import { useApp } from "../state/AppState";

const TABS = [
  { id: "capabilities", label: "Capability heat map" },
  { id: "goals", label: "Goals → capabilities → projects" },
  { id: "investment", label: "Investment alignment" },
  { id: "roadmap", label: "Roadmap scenarios" },
  { id: "impact", label: "Impact analysis" },
  { id: "board", label: "Board pack" },
];

export default function EnterpriseArchitecture() {
  const { tenantName } = useApp();
  const [tab, setTab] = useTab("capabilities", "tab");
  const change = (t: string) => {
    setTab(t);
    setUrlParam("tab", t);
  };
  return (
    <div className="[&_button]:whitespace-nowrap">
      <PageHeader
        title="Enterprise Architecture"
        subtitle={`${tenantName} — capabilities, strategy traceability, investment alignment, roadmaps and impact analysis.`}
      />
      <Tabs tabs={TABS} active={tab} onChange={change} />
      {tab === "capabilities" && <CapabilityHeatMap />}
      {tab === "goals" && <GoalsLinkage />}
      {tab === "investment" && <InvestmentAlignment />}
      {tab === "roadmap" && <Roadmaps />}
      {tab === "impact" && <ImpactAnalysis />}
      {tab === "board" && <BoardPack />}
    </div>
  );
}
