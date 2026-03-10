import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { getOverview } from "./api/client";
import { DashboardShell } from "./components/DashboardShell";
import { AnomaliesPage } from "./pages/AnomaliesPage";
import { HealthPage } from "./pages/HealthPage";
import { OutfitPage } from "./pages/OutfitPage";
import { OverviewPage } from "./pages/OverviewPage";
import { PlanPage } from "./pages/PlanPage";
import type { OverviewResponse } from "./types";
import type { TimeFormat } from "./utils/time";

type ThemeMode = "dark" | "light";
type PredictionSource = "open_meteo" | "custom_ml";

function normalizeLocationKey(location: string) {
  return location.trim().toLowerCase();
}

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
  const [themeMode, setThemeMode] = useState<ThemeMode>(() => {
    const saved = window.localStorage.getItem("fh_theme_mode");
    return saved === "light" ? "light" : "dark";
  });
  const [predictionSource, setPredictionSource] = useState<PredictionSource>("open_meteo");
  const [timeFormat, setTimeFormat] = useState<TimeFormat>(() => {
    const saved = window.localStorage.getItem("fh_time_format");
    return saved === "24h" ? "24h" : "12h";
  });
  const [overviewByLocation, setOverviewByLocation] = useState<Record<string, OverviewResponse | null>>({});
  const [overviewLoadingByLocation, setOverviewLoadingByLocation] = useState<Record<string, boolean>>({});
  const [overviewErrorByLocation, setOverviewErrorByLocation] = useState<Record<string, string | null>>({});
  const locationsRef = useRef<string[]>(defaultLocations);
  const previousLocationKeysRef = useRef<Set<string>>(new Set());

  const location = useMemo(() => activeLocation.trim() || "Chicago", [activeLocation]);
  const activeLocationKey = useMemo(() => normalizeLocationKey(location), [location]);
  const activeOverview = overviewByLocation[activeLocationKey] ?? null;
  const activeOverviewLoading = overviewLoadingByLocation[activeLocationKey] ?? true;
  const activeOverviewError = overviewErrorByLocation[activeLocationKey] ?? null;
  const openMeteoHourlyTemperatures = activeOverview?.hourly_temperatures_24h ?? [];
  const customMlHourlyTemperatures = activeOverview?.hourly_temperatures_24h_custom_model ?? [];
  const customMlHasValues = customMlHourlyTemperatures.some((item) => item.temperature_c != null);
  const activeHourlyTemperatures24h =
    predictionSource === "custom_ml" && customMlHasValues
      ? customMlHourlyTemperatures
      : openMeteoHourlyTemperatures;
  const activeHeaderTemperature = useMemo(() => {
    if (predictionSource === "custom_ml") {
      if (customMlHasValues) {
        return customMlHourlyTemperatures[0]?.temperature_c ?? null;
      }
      return (
        activeOverview?.next_hour_temperature_custom_model_c ??
        activeOverview?.next_hour_temperature_prediction_c ??
        activeOverview?.current_temperature_c ??
        null
      );
    }
    return activeOverview?.current_temperature_c ?? null;
  }, [activeOverview, customMlHasValues, customMlHourlyTemperatures, predictionSource]);

  const locationTemperatures = useMemo(() => {
    return Object.fromEntries(
      locations.map((item) => {
        const key = normalizeLocationKey(item);
        return [item, overviewByLocation[key]?.current_temperature_c ?? null];
      }),
    );
  }, [locations, overviewByLocation]);

  const locationTemperatureLoading = useMemo(() => {
    return Object.fromEntries(
      locations.map((item) => {
        const key = normalizeLocationKey(item);
        return [item, overviewLoadingByLocation[key] ?? false];
      }),
    );
  }, [locations, overviewLoadingByLocation]);

  function addLocation(nextLocation: string) {
    const normalized = nextLocation.trim();
    if (!normalized) {
      return;
    }

    setLocations((previous) => {
      const exists = previous.some((existing) => existing.toLowerCase() === normalized.toLowerCase());
      if (exists) {
        return previous;
      }
      return [...previous, normalized];
    });
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

  const fetchOverviewForLocation = useCallback((locationName: string) => {
    const key = normalizeLocationKey(locationName);
    setOverviewLoadingByLocation((previous) => ({ ...previous, [key]: true }));
    setOverviewErrorByLocation((previous) => ({ ...previous, [key]: null }));

    getOverview(locationName)
      .then((response) => {
        const stillTracked = locationsRef.current.some(
          (existingLocation) => normalizeLocationKey(existingLocation) === key,
        );
        if (!stillTracked) {
          return;
        }
        setOverviewByLocation((previous) => ({ ...previous, [key]: response as OverviewResponse }));
      })
      .catch((err: Error) => {
        const stillTracked = locationsRef.current.some(
          (existingLocation) => normalizeLocationKey(existingLocation) === key,
        );
        if (!stillTracked) {
          return;
        }
        setOverviewErrorByLocation((previous) => ({ ...previous, [key]: err.message }));
        setOverviewByLocation((previous) => ({ ...previous, [key]: null }));
      })
      .finally(() => {
        const stillTracked = locationsRef.current.some(
          (existingLocation) => normalizeLocationKey(existingLocation) === key,
        );
        if (!stillTracked) {
          return;
        }
        setOverviewLoadingByLocation((previous) => ({ ...previous, [key]: false }));
      });
  }, []);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", themeMode);
    window.localStorage.setItem("fh_theme_mode", themeMode);
  }, [themeMode]);

  useEffect(() => {
    window.localStorage.setItem("fh_time_format", timeFormat);
  }, [timeFormat]);

  useEffect(() => {
    locationsRef.current = locations;

    const allowedKeys = new Set(locations.map((item) => normalizeLocationKey(item)));
    setOverviewByLocation((previous) =>
      Object.fromEntries(Object.entries(previous).filter(([key]) => allowedKeys.has(key))),
    );
    setOverviewLoadingByLocation((previous) =>
      Object.fromEntries(Object.entries(previous).filter(([key]) => allowedKeys.has(key))),
    );
    setOverviewErrorByLocation((previous) =>
      Object.fromEntries(Object.entries(previous).filter(([key]) => allowedKeys.has(key))),
    );

    const previousKeys = previousLocationKeysRef.current;
    const addedLocations = locations.filter((item) => !previousKeys.has(normalizeLocationKey(item)));
    addedLocations.forEach((locationName) => {
      if (normalizeLocationKey(locationName) !== normalizeLocationKey(activeLocation)) {
        fetchOverviewForLocation(locationName);
      }
    });

    previousLocationKeysRef.current = allowedKeys;
  }, [activeLocation, fetchOverviewForLocation, locations]);

  useEffect(() => {
    const key = normalizeLocationKey(activeLocation);
    const hasNonNullData = overviewByLocation[key] != null;
    const isLoading = overviewLoadingByLocation[key] ?? false;
    if (!hasNonNullData && !isLoading) {
      fetchOverviewForLocation(activeLocation);
    }
  }, [activeLocation, fetchOverviewForLocation]);

  useEffect(() => {
    const intervalId = window.setInterval(() => {
      locationsRef.current.forEach((locationName) => {
        fetchOverviewForLocation(locationName);
      });
    }, 60 * 60 * 1000);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [fetchOverviewForLocation]);

  return (
    <DashboardShell
      locations={locations}
      activeLocation={activeLocation}
      setActiveLocation={setActiveLocation}
      addLocation={addLocation}
      removeLocation={removeLocation}
      currentTemperatureC={activeHeaderTemperature}
      currentTemperatureLoading={activeOverviewLoading}
      hourlyTemperatures24h={activeHourlyTemperatures24h}
      customMlHourlyTemperatures={customMlHourlyTemperatures}
      customMlNextHourTemperatureC={activeOverview?.next_hour_temperature_custom_model_c ?? null}
      hourlyTemperaturesLoading={activeOverviewLoading}
      locationTemperatures={locationTemperatures}
      locationTemperatureLoading={locationTemperatureLoading}
      themeMode={themeMode}
      setThemeMode={setThemeMode}
      predictionSource={predictionSource}
      setPredictionSource={setPredictionSource}
      timeFormat={timeFormat}
      setTimeFormat={setTimeFormat}
    >
      <div className="single-page">
        <OverviewPage
          data={activeOverview}
          loading={activeOverviewLoading}
          error={activeOverviewError}
          predictionSource={predictionSource}
          timeFormat={timeFormat}
        />
        <PlanPage location={location} timeFormat={timeFormat} />
        <OutfitPage location={location} timeFormat={timeFormat} />
        <HealthPage location={location} timeFormat={timeFormat} />
        <AnomaliesPage location={location} timeFormat={timeFormat} />
      </div>
    </DashboardShell>
  );
}
