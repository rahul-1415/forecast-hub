import { useEffect, useMemo, useState } from "react";

import { getOverview } from "./api/client";
import { DashboardShell } from "./components/DashboardShell";
import { AnomaliesPage } from "./pages/AnomaliesPage";
import { HealthPage } from "./pages/HealthPage";
import { OutfitPage } from "./pages/OutfitPage";
import { OverviewPage } from "./pages/OverviewPage";
import { PlanPage } from "./pages/PlanPage";
import type { OverviewResponse } from "./types";

export default function App() {
  const defaultLocations = [
    "Chicago",
    "New York",
    "Los Angeles",
    "Houston",
    "Phoenix",
    "Philadelphia",
    "San Antonio",
    "San Diego",
    "Dallas",
    "San Jose",
  ];
  const [locations, setLocations] = useState<string[]>(defaultLocations);
  const [activeLocation, setActiveLocation] = useState(defaultLocations[0]);
  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [overviewLoading, setOverviewLoading] = useState(true);
  const [overviewError, setOverviewError] = useState<string | null>(null);

  const location = useMemo(() => activeLocation.trim() || "Chicago", [activeLocation]);

  function addLocation(nextLocation: string) {
    const normalized = nextLocation.trim();
    if (!normalized) {
      return;
    }

    const exists = locations.some((existing) => existing.toLowerCase() === normalized.toLowerCase());
    if (!exists) {
      setLocations((prev) => [...prev, normalized]);
    }
    setActiveLocation(normalized);
  }

  function removeLocation(locationToRemove: string) {
    const target = locationToRemove.trim().toLowerCase();
    setLocations((previous) => {
      const next = previous.filter((item) => item.trim().toLowerCase() !== target);
      if (next.length === 0) {
        return previous;
      }
      setActiveLocation((current) => {
        if (current.trim().toLowerCase() === target) {
          return next[0];
        }
        return current;
      });
      return next;
    });
  }

  useEffect(() => {
    let mounted = true;
    setOverviewLoading(true);
    setOverviewError(null);

    getOverview(location)
      .then((response) => {
        if (!mounted) {
          return;
        }
        setOverview(response as OverviewResponse);
      })
      .catch((err: Error) => {
        if (!mounted) {
          return;
        }
        setOverviewError(err.message);
        setOverview(null);
      })
      .finally(() => {
        if (mounted) {
          setOverviewLoading(false);
        }
      });

    return () => {
      mounted = false;
    };
  }, [location]);

  return (
    <DashboardShell
      locations={locations}
      activeLocation={activeLocation}
      setActiveLocation={setActiveLocation}
      addLocation={addLocation}
      removeLocation={removeLocation}
      currentTemperatureC={overview?.current_temperature_c ?? null}
      currentTemperatureLoading={overviewLoading}
    >
      <div className="single-page">
        <OverviewPage data={overview} loading={overviewLoading} error={overviewError} />
        <PlanPage location={location} />
        <OutfitPage location={location} />
        <HealthPage location={location} />
        <AnomaliesPage location={location} />
      </div>
    </DashboardShell>
  );
}
