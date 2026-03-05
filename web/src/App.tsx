import { Navigate, Route, Routes } from "react-router-dom";
import { useMemo, useState } from "react";

import { DashboardShell } from "./components/DashboardShell";
import { AnomaliesPage } from "./pages/AnomaliesPage";
import { HealthPage } from "./pages/HealthPage";
import { OutfitPage } from "./pages/OutfitPage";
import { OverviewPage } from "./pages/OverviewPage";
import { PlanPage } from "./pages/PlanPage";

export default function App() {
  const [locationInput, setLocationInput] = useState("Chicago");
  const location = useMemo(() => locationInput.trim() || "Chicago", [locationInput]);

  return (
    <DashboardShell location={locationInput} setLocation={setLocationInput}>
      <Routes>
        <Route path="/" element={<OverviewPage location={location} />} />
        <Route path="/plan-copilot" element={<PlanPage location={location} />} />
        <Route path="/outfit-packing" element={<OutfitPage location={location} />} />
        <Route path="/health-alerts" element={<HealthPage location={location} />} />
        <Route path="/anomalies" element={<AnomaliesPage location={location} />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </DashboardShell>
  );
}
