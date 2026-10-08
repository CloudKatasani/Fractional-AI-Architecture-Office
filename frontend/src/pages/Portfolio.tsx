import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { PageHeader } from "../components/Layout";
import { DiscoveryTab } from "../components/portfolio/DiscoveryTab";
import { InventoryTab } from "../components/portfolio/InventoryTab";
import { LifecycleTab } from "../components/portfolio/LifecycleTab";
import { OverlapsTab } from "../components/portfolio/OverlapsTab";
import { SavingsTab } from "../components/portfolio/SavingsTab";
import { TimeTab } from "../components/portfolio/TimeTab";
import { Tabs, useTab } from "../components/ui";
import { useApp } from "../state/AppState";

const TABS = [
  { id: "inventory", label: "Inventory" },
  { id: "discovery", label: "Discovery" },
  { id: "overlaps", label: "Overlaps" },
  { id: "time", label: "TIME" },
  { id: "lifecycle", label: "Lifecycle" },
  { id: "savings", label: "Savings" },
];

export default function Portfolio() {
  const { tenantName } = useApp();
  const [tab, setTab] = useTab("inventory", "tab");
  const [params, setParams] = useSearchParams();

  // keep ?tab= in the URL so tabs are linkable (Dashboard tiles deep-link here)
  useEffect(() => {
    const t = params.get("tab");
    if (t && t !== tab && TABS.some((x) => x.id === t)) setTab(t);
  }, [params]);
  const change = (id: string) => {
    setTab(id);
    const p = new URLSearchParams(params);
    p.set("tab", id);
    setParams(p, { replace: true });
  };

  return (
    <div>
      <PageHeader
        title="Portfolio"
        subtitle={<>Application inventory, discovery, rationalization and savings for {tenantName}. Agent output is proposed until an owner or approver decides.</>}
      />
      <Tabs tabs={TABS} active={TABS.some((t) => t.id === tab) ? tab : "inventory"} onChange={change} />
      {(tab === "inventory" || !TABS.some((t) => t.id === tab)) && <InventoryTab />}
      {tab === "discovery" && <DiscoveryTab />}
      {tab === "overlaps" && <OverlapsTab />}
      {tab === "time" && <TimeTab />}
      {tab === "lifecycle" && <LifecycleTab />}
      {tab === "savings" && <SavingsTab />}
    </div>
  );
}
