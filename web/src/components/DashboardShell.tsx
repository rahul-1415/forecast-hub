import { FormEvent, ReactNode, useEffect, useMemo, useRef, useState } from "react";

import {
  getLocationSuggestions,
  getNotificationDeliveryLogs,
  sendNotificationTest,
  upsertNotificationSubscription,
} from "../api/client";
import { NumericSparkline } from "./NumericSparkline";
import type { LocationSuggestion } from "../types";
import { formatHourFromTimestamp, type TimeFormat } from "../utils/time";

type DashboardShellProps = {
  locations: string[];
  activeLocation: string;
  setActiveLocation: (value: string) => void;
  addLocation: (value: string) => void;
  removeLocation: (value: string) => void;
  currentTemperatureC: number | null;
  currentTemperatureLoading: boolean;
  hourlyTemperatures24h: { timestamp: string; temperature_c: number | null }[];
  customMlHourlyTemperatures: { timestamp: string; temperature_c: number | null }[];
  customMlNextHourTemperatureC: number | null;
  hourlyTemperaturesLoading: boolean;
  locationTemperatures: Record<string, number | null>;
  locationTemperatureLoading: Record<string, boolean>;
  themeMode: "dark" | "light";
  setThemeMode: (mode: "dark" | "light") => void;
  predictionSource: "open_meteo" | "custom_ml";
  setPredictionSource: (source: "open_meteo" | "custom_ml") => void;
  timeFormat: TimeFormat;
  setTimeFormat: (format: TimeFormat) => void;
  children: ReactNode;
};

type NotificationPreferences = {
  enabled: boolean;
  time: string;
  timezone: string;
  location: string;
  channel: "email" | "telegram" | "mobile";
  email: string;
  telegram: string;
  mobile: string;
  clothingStyle: "casual" | "business" | "sporty" | "outdoor";
  quietHoursEnabled: boolean;
  quietStart: string;
  quietEnd: string;
  includeOutfit: boolean;
  includeHealth: boolean;
  includeCommute: boolean;
};

const NOTIFICATION_PREFS_KEY = "fh_notification_preferences_v1";

export function DashboardShell({
  locations,
  activeLocation,
  setActiveLocation,
  addLocation,
  removeLocation,
  currentTemperatureC,
  currentTemperatureLoading,
  hourlyTemperatures24h,
  customMlHourlyTemperatures,
  customMlNextHourTemperatureC,
  hourlyTemperaturesLoading,
  locationTemperatures,
  locationTemperatureLoading,
  themeMode,
  setThemeMode,
  predictionSource,
  setPredictionSource,
  timeFormat,
  setTimeFormat,
  children,
}: DashboardShellProps) {
  const [locationInput, setLocationInput] = useState("");
  const [suggestions, setSuggestions] = useState<LocationSuggestion[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [suggestionsLoading, setSuggestionsLoading] = useState(false);
  const [showSettingsMenu, setShowSettingsMenu] = useState(false);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [showNotificationSetup, setShowNotificationSetup] = useState(false);
  const [notificationStatus, setNotificationStatus] = useState<string | null>(null);
  const [savedNotificationSubscriptionId, setSavedNotificationSubscriptionId] = useState<number | null>(null);
  const [notificationRequestPending, setNotificationRequestPending] = useState(false);
  const [notificationLogs, setNotificationLogs] = useState<
    { id: number; status: string; channel: string; destination: string; created_at: string; provider_message: string | null }[]
  >([]);
  const [notificationPreferences, setNotificationPreferences] = useState<NotificationPreferences>(() => {
    const defaults: NotificationPreferences = {
      enabled: true,
      time: "08:00",
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
      location: activeLocation,
      channel: "email",
      email: "",
      telegram: "",
      mobile: "",
      clothingStyle: "casual",
      quietHoursEnabled: true,
      quietStart: "22:00",
      quietEnd: "07:00",
      includeOutfit: true,
      includeHealth: true,
      includeCommute: true,
    };

    if (typeof window === "undefined") {
      return defaults;
    }

    try {
      const raw = window.localStorage.getItem(NOTIFICATION_PREFS_KEY);
      if (!raw) {
        return defaults;
      }
      const parsed = JSON.parse(raw) as Partial<NotificationPreferences>;
      return { ...defaults, ...parsed };
    } catch {
      return defaults;
    }
  });
  const settingsRef = useRef<HTMLDivElement | null>(null);
  const backgroundRef = useRef<HTMLDivElement | null>(null);

  const canDelete = locations.length > 1;
  const displayTemperature = useMemo(() => {
    if (currentTemperatureLoading) {
      return "--";
    }
    if (currentTemperatureC == null) {
      return "--";
    }
    return currentTemperatureC.toFixed(1);
  }, [currentTemperatureC, currentTemperatureLoading]);
  const sparklinePoints = useMemo(
    () =>
      hourlyTemperatures24h.map((item, index) => ({
        label: index === 0 ? "Now" : formatHourFromTimestamp(item.timestamp, timeFormat),
        value: item.temperature_c,
      })),
    [hourlyTemperatures24h, timeFormat],
  );
  const customMlValidTemperatures = useMemo(
    () =>
      customMlHourlyTemperatures
        .map((item) => item.temperature_c)
        .filter((value): value is number => value != null && Number.isFinite(value)),
    [customMlHourlyTemperatures],
  );
  const customMlNowTemperature = customMlHourlyTemperatures[0]?.temperature_c ?? null;
  const customMlMinTemperature =
    customMlValidTemperatures.length > 0 ? Math.min(...customMlValidTemperatures) : null;
  const customMlMaxTemperature =
    customMlValidTemperatures.length > 0 ? Math.max(...customMlValidTemperatures) : null;
  const customMlAverageTemperature =
    customMlValidTemperatures.length > 0
      ? customMlValidTemperatures.reduce((sum, value) => sum + value, 0) / customMlValidTemperatures.length
      : null;
  const customMlPointCount = customMlValidTemperatures.length;

  function formatModelTemp(value: number | null) {
    if (value == null) {
      return "--";
    }
    return `${value.toFixed(1)}°C`;
  }
  const nextHourDelta = useMemo(() => {
    const currentHour = hourlyTemperatures24h[0]?.temperature_c;
    const nextHour = hourlyTemperatures24h[1]?.temperature_c;
    if (currentHour == null || nextHour == null) {
      return null;
    }
    return nextHour - currentHour;
  }, [hourlyTemperatures24h]);
  const notificationPreview = useMemo(() => {
    const weatherBits: string[] = [];

    if (notificationPreferences.includeOutfit) {
      if (currentTemperatureC == null) {
        weatherBits.push("Check today's weather before choosing your outfit.");
      } else if (currentTemperatureC <= 5) {
        weatherBits.push("Wear a warm coat and insulated shoes.");
      } else if (currentTemperatureC <= 15) {
        weatherBits.push("A light jacket or layered outfit is recommended.");
      } else if (currentTemperatureC <= 25) {
        weatherBits.push("A breathable top with light layers should work.");
      } else {
        weatherBits.push("Wear lightweight clothes and stay cool.");
      }
    }

    if (notificationPreferences.includeCommute) {
      if (nextHourDelta == null) {
        weatherBits.push("Review commute conditions before leaving.");
      } else if (nextHourDelta >= 2) {
        weatherBits.push("Temperature is rising; lighter outerwear is fine.");
      } else if (nextHourDelta <= -2) {
        weatherBits.push("Temperature is dropping; carry an extra layer.");
      } else {
        weatherBits.push("Commute weather is fairly stable.");
      }
    }

    if (notificationPreferences.includeHealth) {
      if (currentTemperatureC != null && currentTemperatureC >= 30) {
        weatherBits.push("Hydrate early and avoid extended midday sun.");
      } else if (currentTemperatureC != null && currentTemperatureC <= 0) {
        weatherBits.push("Protect exposed skin from cold air.");
      } else {
        weatherBits.push("Keep hydration and comfort breaks in mind.");
      }
    }

    return weatherBits.slice(0, 3).join(" ");
  }, [currentTemperatureC, nextHourDelta, notificationPreferences.includeCommute, notificationPreferences.includeHealth, notificationPreferences.includeOutfit]);
  const selectedNotificationContact = useMemo(() => {
    if (notificationPreferences.channel === "email") {
      return notificationPreferences.email.trim() || "No email set";
    }
    if (notificationPreferences.channel === "telegram") {
      return notificationPreferences.telegram.trim() || "No Telegram handle set";
    }
    return notificationPreferences.mobile.trim() || "No mobile number set";
  }, [
    notificationPreferences.channel,
    notificationPreferences.email,
    notificationPreferences.mobile,
    notificationPreferences.telegram,
  ]);

  function updateNotificationPreference<K extends keyof NotificationPreferences>(
    key: K,
    value: NotificationPreferences[K],
  ) {
    setNotificationPreferences((previous) => ({ ...previous, [key]: value }));
  }

  function getNotificationDestination() {
    if (notificationPreferences.channel === "email") {
      return notificationPreferences.email.trim();
    }
    if (notificationPreferences.channel === "telegram") {
      return notificationPreferences.telegram.trim();
    }
    return notificationPreferences.mobile.trim();
  }

  async function upsertNotificationSubscriptionForCurrentPreferences() {
    const destination = getNotificationDestination();
    if (!destination) {
      throw new Error("Please add a valid contact for the selected channel.");
    }

    const channel = notificationPreferences.channel === "mobile" ? "sms" : notificationPreferences.channel;
    const row = await upsertNotificationSubscription({
      location_name: notificationPreferences.location,
      channel,
      destination,
      enabled: notificationPreferences.enabled,
      schedule_time: notificationPreferences.time,
      timezone: notificationPreferences.timezone,
      include_outfit: notificationPreferences.includeOutfit,
      include_health: notificationPreferences.includeHealth,
      include_plan: notificationPreferences.includeCommute,
      quiet_hours_enabled: notificationPreferences.quietHoursEnabled,
      quiet_start: notificationPreferences.quietStart,
      quiet_end: notificationPreferences.quietEnd,
      escalation_enabled: true,
    });
    setSavedNotificationSubscriptionId(row.id);
    return row.id;
  }

  async function sendTestNotification() {
    try {
      setNotificationRequestPending(true);
      setNotificationStatus(null);
      const subscriptionId =
        savedNotificationSubscriptionId ?? (await upsertNotificationSubscriptionForCurrentPreferences());
      await sendNotificationTest(subscriptionId, "normal");
      const logs = await getNotificationDeliveryLogs(10);
      setNotificationLogs(logs);
      setNotificationStatus("Test notification queued. Delivery logs will update after processing.");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to queue test notification.";
      setNotificationStatus(message);
    } finally {
      setNotificationRequestPending(false);
    }
  }

  async function saveNotificationPreferences() {
    try {
      setNotificationRequestPending(true);
      setNotificationStatus(null);
      await upsertNotificationSubscriptionForCurrentPreferences();
      const logs = await getNotificationDeliveryLogs(10);
      setNotificationLogs(logs);
      setNotificationStatus("Notification preferences saved to backend scheduler.");
      setShowNotificationSetup(false);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to save notification preferences.";
      setNotificationStatus(message);
    } finally {
      setNotificationRequestPending(false);
    }
  }

  useEffect(() => {
    const query = locationInput.trim();
    if (query.length < 2) {
      setSuggestions([]);
      setSuggestionsLoading(false);
      return;
    }

    let cancelled = false;
    setSuggestionsLoading(true);

    const timer = window.setTimeout(() => {
      getLocationSuggestions(query)
        .then((items) => {
          if (!cancelled) {
            setSuggestions(items);
          }
        })
        .catch(() => {
          if (!cancelled) {
            setSuggestions([]);
          }
        })
        .finally(() => {
          if (!cancelled) {
            setSuggestionsLoading(false);
          }
        });
    }, 220);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [locationInput]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    window.localStorage.setItem(NOTIFICATION_PREFS_KEY, JSON.stringify(notificationPreferences));
  }, [notificationPreferences]);

  useEffect(() => {
    if (!showNotificationSetup) {
      return;
    }

    let cancelled = false;
    getNotificationDeliveryLogs(10)
      .then((logs) => {
        if (!cancelled) {
          setNotificationLogs(logs);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setNotificationLogs([]);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [showNotificationSetup]);

  useEffect(() => {
    if (!locations.includes(notificationPreferences.location)) {
      setNotificationPreferences((previous) => ({
        ...previous,
        location: activeLocation,
      }));
    }
  }, [activeLocation, locations, notificationPreferences.location]);

  useEffect(() => {
    function handleOutsideClick(event: MouseEvent) {
      if (!settingsRef.current) {
        return;
      }
      if (!settingsRef.current.contains(event.target as Node)) {
        setShowSettingsMenu(false);
      }
    }

    document.addEventListener("mousedown", handleOutsideClick);
    return () => {
      document.removeEventListener("mousedown", handleOutsideClick);
    };
  }, []);

  useEffect(() => {
    const background = backgroundRef.current;
    if (!background) {
      return;
    }

    let frameId = 0;
    let targetX = 0;
    let targetY = 0;
    let currentX = 0;
    let currentY = 0;

    function updatePointerOffset() {
      currentX += (targetX - currentX) * 0.08;
      currentY += (targetY - currentY) * 0.08;
      background?.style.setProperty("--pointer-x", currentX.toFixed(3));
      background?.style.setProperty("--pointer-y", currentY.toFixed(3));

      if (Math.abs(targetX - currentX) > 0.001 || Math.abs(targetY - currentY) > 0.001) {
        frameId = window.requestAnimationFrame(updatePointerOffset);
        return;
      }

      frameId = 0;
    }

    function queueUpdate() {
      if (!frameId) {
        frameId = window.requestAnimationFrame(updatePointerOffset);
      }
    }

    function handlePointerMove(event: PointerEvent) {
      targetX = (event.clientX / window.innerWidth - 0.5) * 2;
      targetY = (event.clientY / window.innerHeight - 0.5) * 2;
      queueUpdate();
    }

    function handlePointerLeave() {
      targetX = 0;
      targetY = 0;
      queueUpdate();
    }

    window.addEventListener("pointermove", handlePointerMove, { passive: true });
    window.addEventListener("pointerleave", handlePointerLeave);

    return () => {
      if (frameId) {
        window.cancelAnimationFrame(frameId);
      }
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerleave", handlePointerLeave);
    };
  }, []);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    addLocation(locationInput);
    setLocationInput("");
    setShowSuggestions(false);
    setSuggestions([]);
  }

  function onPickSuggestion(suggestion: LocationSuggestion) {
    addLocation(suggestion.name);
    setLocationInput("");
    setShowSuggestions(false);
    setSuggestions([]);
  }

  return (
    <div className={isSidebarCollapsed ? "app-shell sidebar-collapsed" : "app-shell"}>
      <div className="space-background" ref={backgroundRef} aria-hidden="true">
        <span className="starfield starfield-far" />
        <span className="starfield starfield-mid" />
        <span className="starfield starfield-near" />
        <div className="shooting-stars-layer">
          <span className="shooting-star shooting-star-1" />
          <span className="shooting-star shooting-star-2" />
          <span className="shooting-star shooting-star-3" />
          <span className="shooting-star shooting-star-4" />
          <span className="shooting-star shooting-star-5" />
          <span className="shooting-star shooting-star-6" />
          <span className="shooting-star shooting-star-7" />
          <span className="shooting-star shooting-star-8" />
        </div>
      </div>

      <header className="top-nav">
        <div className="top-nav-left">
          <button
            type="button"
            className="icon-chip"
            aria-label={isSidebarCollapsed ? "Open sidebar" : "Hide sidebar"}
            aria-expanded={!isSidebarCollapsed}
            onClick={() => setIsSidebarCollapsed((previous) => !previous)}
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M4 7h16M4 12h16M4 17h16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>
          <button
            type="button"
            className="brand-home-button"
            onClick={() => window.location.reload()}
            aria-label="Refresh Forecast Hub"
          >
            <img className="brand-logo-icon-sidebar" src="/logo.png" alt="ForecastHub icon" />
            <h1 className="brand-title">Forecast Hub</h1>
          </button>
        </div>

        <form className="top-search-form" onSubmit={onSubmit}>
          <div className="menu-location-controls">
            <input
              id="location-input"
              value={locationInput}
              onChange={(event) => {
                setLocationInput(event.target.value);
                setShowSuggestions(true);
              }}
              onFocus={() => setShowSuggestions(true)}
              onBlur={() => {
                window.setTimeout(() => setShowSuggestions(false), 100);
              }}
              placeholder="Search City"
              autoComplete="off"
            />
            <button type="submit">Add</button>
          </div>
          {showSuggestions && locationInput.trim().length >= 2 ? (
            <div className="location-suggestions">
              {suggestionsLoading ? <p className="suggestion-status">Searching...</p> : null}
              {!suggestionsLoading && suggestions.length === 0 ? (
                <p className="suggestion-status">No suggestions found.</p>
              ) : null}
              {!suggestionsLoading
                ? suggestions.map((suggestion) => (
                    <button
                      key={suggestion.label}
                      type="button"
                      className="suggestion-item"
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={() => onPickSuggestion(suggestion)}
                    >
                      {suggestion.label}
                    </button>
                  ))
                : null}
            </div>
          ) : null}
        </form>

        <div className="top-nav-right">
          <div className="model-source-toggle">
            <button
              type="button"
              className={predictionSource === "open_meteo" ? "source-button active" : "source-button"}
              onClick={() => setPredictionSource("open_meteo")}
            >
              Open-Meteo
            </button>
            <button
              type="button"
              className={predictionSource === "custom_ml" ? "source-button active" : "source-button"}
              onClick={() => setPredictionSource("custom_ml")}
            >
              Custom ML
            </button>
          </div>

          <button
            type="button"
            className="notification-setup-button"
            onClick={() => {
              setNotificationStatus(null);
              setShowNotificationSetup(true);
            }}
          >
            Setup Notification
          </button>

          <div className="header-settings" ref={settingsRef}>
            <button
              type="button"
              className="settings-icon-button"
              aria-label="Open settings"
              aria-expanded={showSettingsMenu}
              onClick={() => setShowSettingsMenu((previous) => !previous)}
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M19.14 12.94a7.98 7.98 0 0 0 .06-.94c0-.32-.02-.63-.06-.94l2.03-1.58a.5.5 0 0 0 .12-.65l-1.92-3.32a.5.5 0 0 0-.61-.22l-2.39.96a7.4 7.4 0 0 0-1.63-.94l-.36-2.54a.5.5 0 0 0-.5-.43h-3.84a.5.5 0 0 0-.5.43l-.36 2.54c-.57.22-1.12.53-1.63.94l-2.39-.96a.5.5 0 0 0-.61.22L2.71 8.83a.5.5 0 0 0 .12.65L4.86 11a7.98 7.98 0 0 0-.06.94c0 .32.02.63.06.94l-2.03 1.58a.5.5 0 0 0-.12.65l1.92 3.32c.13.22.39.31.61.22l2.39-.96c.5.4 1.05.72 1.63.94l.36 2.54c.04.24.25.43.5.43h3.84c.25 0 .46-.19.5-.43l.36-2.54c.57-.22 1.12-.53 1.63-.94l2.39.96c.22.09.48 0 .61-.22l1.92-3.32a.5.5 0 0 0-.12-.65l-2.03-1.58ZM12 15.5A3.5 3.5 0 1 1 12 8.5a3.5 3.5 0 0 1 0 7Z" />
              </svg>
            </button>

            {showSettingsMenu ? (
              <div className="settings-dropdown">
                <p className="header-settings-label">Settings</p>
                <div className="theme-slider-row">
                  <span>Light Mode</span>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={themeMode === "light"}
                    className={themeMode === "light" ? "theme-slider active" : "theme-slider"}
                    onClick={() => setThemeMode(themeMode === "dark" ? "light" : "dark")}
                  >
                    <span className="theme-slider-thumb" />
                  </button>
                </div>

                <div className="time-format-row">
                  <span>Time Format</span>
                  <div className="time-format-toggle" role="radiogroup" aria-label="Time format">
                    <button
                      type="button"
                      role="radio"
                      aria-checked={timeFormat === "12h"}
                      className={timeFormat === "12h" ? "time-format-button active" : "time-format-button"}
                      onClick={() => setTimeFormat("12h")}
                    >
                      12h
                    </button>
                    <button
                      type="button"
                      role="radio"
                      aria-checked={timeFormat === "24h"}
                      className={timeFormat === "24h" ? "time-format-button active" : "time-format-button"}
                      onClick={() => setTimeFormat("24h")}
                    >
                      24h
                    </button>
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        </div>
      </header>

      <aside className="sidebar">

        <section className="location-panel">
          <h2 className="location-panel-title" style={{ textAlign: "center" }}>Locations</h2>
          <div className="location-list">
            {locations.map((location) => (
              <div
                key={location}
                className={location === activeLocation ? "location-item-row active" : "location-item-row"}
              >
                <button type="button" className="location-item" onClick={() => setActiveLocation(location)}>
                  <span className="location-item-name">{location}</span>
                  <span className="location-item-temp">
                    {locationTemperatureLoading[location]
                      ? "--°C"
                      : locationTemperatures[location] == null
                        ? "--°C"
                        : `${locationTemperatures[location]?.toFixed(1)}°C`}
                  </span>
                </button>
                <button
                  type="button"
                  className="location-delete"
                  onClick={() => removeLocation(location)}
                  disabled={!canDelete}
                  aria-label={`Delete ${location}`}
                  title={canDelete ? `Delete ${location}` : "At least one location is required"}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        </section>
      </aside>

      <main className="content">
        <header className="app-main-header">
          <p className="app-main-eyebrow">My Location</p>
          <h2 className="app-main-location">{activeLocation}</h2>
          <p className="app-main-temperature">{displayTemperature}°C</p>
          {nextHourDelta != null ? (
            <p className={nextHourDelta > 0 ? "app-main-delta up" : nextHourDelta < 0 ? "app-main-delta down" : "app-main-delta flat"}>
              {nextHourDelta > 0 ? "↑" : nextHourDelta < 0 ? "↓" : "→"} {Math.abs(nextHourDelta).toFixed(1)}° next hour
            </p>
          ) : null}
        </header>
        {predictionSource === "custom_ml" ? (
          <section className="custom-ml-panel" aria-label="Custom ML model outputs">
            <div className="custom-ml-panel-header">
              <h3>Custom ML Model Output</h3>
              <p className="custom-ml-panel-note">Model-only values (Open-Meteo excluded)</p>
            </div>
            <div className="custom-ml-metrics">
              <article className="custom-ml-metric">
                <span className="custom-ml-metric-label">Current (Model)</span>
                <span className="custom-ml-metric-value">{formatModelTemp(customMlNowTemperature)}</span>
              </article>
              <article className="custom-ml-metric">
                <span className="custom-ml-metric-label">Next Hour (Model)</span>
                <span className="custom-ml-metric-value">{formatModelTemp(customMlNextHourTemperatureC)}</span>
              </article>
              <article className="custom-ml-metric">
                <span className="custom-ml-metric-label">24h Min (Model)</span>
                <span className="custom-ml-metric-value">{formatModelTemp(customMlMinTemperature)}</span>
              </article>
              <article className="custom-ml-metric">
                <span className="custom-ml-metric-label">24h Max (Model)</span>
                <span className="custom-ml-metric-value">{formatModelTemp(customMlMaxTemperature)}</span>
              </article>
              <article className="custom-ml-metric">
                <span className="custom-ml-metric-label">24h Avg (Model)</span>
                <span className="custom-ml-metric-value">{formatModelTemp(customMlAverageTemperature)}</span>
              </article>
              <article className="custom-ml-metric">
                <span className="custom-ml-metric-label">Model Points</span>
                <span className="custom-ml-metric-value">{customMlPointCount}</span>
              </article>
            </div>
            {!hourlyTemperaturesLoading && customMlPointCount === 0 ? (
              <p className="custom-ml-empty-note">
                No loadable ML model output found. Trigger `train-model` to refresh model artifacts.
              </p>
            ) : null}
          </section>
        ) : null}
        <section className="hourly-slider-panel" aria-label="Hourly temperature forecast">
          <div className="hourly-slider-track">
            {hourlyTemperaturesLoading
              ? Array.from({ length: 10 }).map((_, index) => (
                  <article key={`hourly-loading-${index}`} className="hourly-item loading">
                    <span className="hourly-time">--</span>
                    <span className="hourly-temp">--°</span>
                    <span className="hourly-delta">--</span>
                  </article>
                ))
              : hourlyTemperatures24h.length === 0
                ? (
                  <article className="hourly-item">
                    <span className="hourly-time">No data</span>
                    <span className="hourly-temp">--°</span>
                    <span className="hourly-delta">--</span>
                  </article>
                  )
                : hourlyTemperatures24h.map((item, index) => {
                    const previousTemperature = index > 0 ? hourlyTemperatures24h[index - 1]?.temperature_c : null;
                    const hourlyDelta =
                      index > 0 && item.temperature_c != null && previousTemperature != null
                        ? item.temperature_c - previousTemperature
                        : null;
                    const hourlyDeltaClass =
                      hourlyDelta == null
                        ? "hourly-delta"
                        : hourlyDelta > 0
                          ? "hourly-delta up"
                          : hourlyDelta < 0
                            ? "hourly-delta down"
                            : "hourly-delta flat";
                    return (
                    <article
                      key={`${item.timestamp}-${index}`}
                      className={index === 0 ? "hourly-item current" : "hourly-item"}
                    >
                      <span className="hourly-time">
                        {index === 0 ? "Now" : formatHourFromTimestamp(item.timestamp, timeFormat)}
                      </span>
                      <span className="hourly-temp">
                        {item.temperature_c == null ? "--°" : `${Math.round(item.temperature_c)}°`}
                      </span>
                      <span className={hourlyDeltaClass}>
                        {index === 0
                          ? "Base"
                          : hourlyDelta == null
                            ? "--"
                            : `${hourlyDelta > 0 ? "↑" : hourlyDelta < 0 ? "↓" : "→"} ${Math.abs(hourlyDelta).toFixed(1)}°`}
                      </span>
                    </article>
                    );
                  })}
          </div>
        </section>
        <section className="sparkline-panel" aria-label="24-hour temperature trend">
          <div className="sparkline-header">
            <h3>24h Temperature Trend</h3>
            {nextHourDelta != null ? (
              <p className={nextHourDelta > 0 ? "sparkline-delta up" : nextHourDelta < 0 ? "sparkline-delta down" : "sparkline-delta flat"}>
                {nextHourDelta > 0 ? "↑" : nextHourDelta < 0 ? "↓" : "→"} {Math.abs(nextHourDelta).toFixed(1)}° vs now
              </p>
            ) : null}
          </div>
          {hourlyTemperaturesLoading ? <p className="status-text">Loading trend...</p> : <NumericSparkline points={sparklinePoints} unit="°C" />}
        </section>
        {children}
      </main>

      {showNotificationSetup ? (
        <div
          className="notification-modal-backdrop"
          onClick={() => setShowNotificationSetup(false)}
          role="presentation"
        >
          <section
            className="notification-modal"
            role="dialog"
            aria-modal="true"
            aria-label="Setup Notification"
            onClick={(event) => event.stopPropagation()}
          >
            <header className="notification-modal-header">
              <h3>Setup Notification</h3>
              <button
                type="button"
                className="notification-modal-close"
                onClick={() => setShowNotificationSetup(false)}
                aria-label="Close setup notification"
              >
                ×
              </button>
            </header>

            <p className="notification-modal-note">
              Enter email, Telegram, or mobile contact and choose where daily personalized recommendations should be sent.
            </p>

            <div className="notification-form-grid">
              <label className="notification-field checkbox">
                <input
                  type="checkbox"
                  checked={notificationPreferences.enabled}
                  onChange={(event) => updateNotificationPreference("enabled", event.target.checked)}
                />
                <span>Enable daily notifications</span>
              </label>

              <label className="notification-field">
                <span>Daily time</span>
                <input
                  type="time"
                  value={notificationPreferences.time}
                  onChange={(event) => updateNotificationPreference("time", event.target.value)}
                />
              </label>

              <label className="notification-field">
                <span>Timezone</span>
                <input
                  type="text"
                  value={notificationPreferences.timezone}
                  onChange={(event) => updateNotificationPreference("timezone", event.target.value)}
                />
              </label>

              <label className="notification-field">
                <span>Location</span>
                <select
                  value={notificationPreferences.location}
                  onChange={(event) => updateNotificationPreference("location", event.target.value)}
                >
                  {locations.map((location) => (
                    <option key={location} value={location}>
                      {location}
                    </option>
                  ))}
                </select>
              </label>

              <label className="notification-field">
                <span>Delivery channel</span>
                <select
                  value={notificationPreferences.channel}
                  onChange={(event) =>
                    updateNotificationPreference(
                      "channel",
                      event.target.value as NotificationPreferences["channel"],
                    )
                  }
                >
                  <option value="email">Email</option>
                  <option value="telegram">Telegram</option>
                  <option value="mobile">Mobile (SMS)</option>
                </select>
              </label>

              <label className="notification-field">
                <span>Email contact</span>
                <input
                  type="email"
                  value={notificationPreferences.email}
                  onChange={(event) => updateNotificationPreference("email", event.target.value)}
                  placeholder="you@example.com"
                />
              </label>

              <label className="notification-field">
                <span>Telegram contact</span>
                <input
                  type="text"
                  value={notificationPreferences.telegram}
                  onChange={(event) => updateNotificationPreference("telegram", event.target.value)}
                  placeholder="@username"
                />
              </label>

              <label className="notification-field">
                <span>Mobile contact</span>
                <input
                  type="tel"
                  value={notificationPreferences.mobile}
                  onChange={(event) => updateNotificationPreference("mobile", event.target.value)}
                  placeholder="+1 555 000 0000"
                />
              </label>

              <label className="notification-field">
                <span>Clothing style</span>
                <select
                  value={notificationPreferences.clothingStyle}
                  onChange={(event) =>
                    updateNotificationPreference(
                      "clothingStyle",
                      event.target.value as NotificationPreferences["clothingStyle"],
                    )
                  }
                >
                  <option value="casual">Casual</option>
                  <option value="business">Business</option>
                  <option value="sporty">Sporty</option>
                  <option value="outdoor">Outdoor</option>
                </select>
              </label>

              <label className="notification-field checkbox">
                <input
                  type="checkbox"
                  checked={notificationPreferences.quietHoursEnabled}
                  onChange={(event) => updateNotificationPreference("quietHoursEnabled", event.target.checked)}
                />
                <span>Enable quiet hours</span>
              </label>

              <label className="notification-field">
                <span>Quiet start</span>
                <input
                  type="time"
                  value={notificationPreferences.quietStart}
                  onChange={(event) => updateNotificationPreference("quietStart", event.target.value)}
                  disabled={!notificationPreferences.quietHoursEnabled}
                />
              </label>

              <label className="notification-field">
                <span>Quiet end</span>
                <input
                  type="time"
                  value={notificationPreferences.quietEnd}
                  onChange={(event) => updateNotificationPreference("quietEnd", event.target.value)}
                  disabled={!notificationPreferences.quietHoursEnabled}
                />
              </label>

              <div className="notification-field notification-toggles">
                <span>Include recommendations</span>
                <label className="checkbox">
                  <input
                    type="checkbox"
                    checked={notificationPreferences.includeOutfit}
                    onChange={(event) => updateNotificationPreference("includeOutfit", event.target.checked)}
                  />
                  <span>Outfit + packing</span>
                </label>
                <label className="checkbox">
                  <input
                    type="checkbox"
                    checked={notificationPreferences.includeHealth}
                    onChange={(event) => updateNotificationPreference("includeHealth", event.target.checked)}
                  />
                  <span>Health alerts</span>
                </label>
                <label className="checkbox">
                  <input
                    type="checkbox"
                    checked={notificationPreferences.includeCommute}
                    onChange={(event) => updateNotificationPreference("includeCommute", event.target.checked)}
                  />
                  <span>Commute tips</span>
                </label>
              </div>
            </div>

            <section className="notification-preview">
              <p className="notification-preview-label">Preview</p>
              <p className="notification-preview-title">
                Forecast Hub · {notificationPreferences.location} · {notificationPreferences.time}
              </p>
              <p className="notification-preview-contact">
                {notificationPreferences.channel.toUpperCase()} · {selectedNotificationContact}
              </p>
              <p className="notification-preview-body">{notificationPreview}</p>
            </section>

            {notificationStatus ? <p className="notification-status">{notificationStatus}</p> : null}

            {notificationLogs.length > 0 ? (
              <section className="notification-log-panel">
                <p className="notification-preview-label">Recent Delivery Logs</p>
                <ul className="notification-log-list">
                  {notificationLogs.slice(0, 5).map((log) => (
                    <li key={log.id}>
                      <span>{log.channel.toUpperCase()} · {log.destination}</span>
                      <span>{log.status}</span>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            <footer className="notification-modal-actions">
              <button type="button" onClick={sendTestNotification} disabled={notificationRequestPending}>
                {notificationRequestPending ? "Queuing..." : "Send Test"}
              </button>
              <button type="button" className="primary" onClick={saveNotificationPreferences} disabled={notificationRequestPending}>
                {notificationRequestPending ? "Saving..." : "Save"}
              </button>
            </footer>
          </section>
        </div>
      ) : null}
    </div>
  );
}
