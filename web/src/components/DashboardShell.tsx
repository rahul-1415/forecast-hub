import { FormEvent, ReactNode, useEffect, useMemo, useRef, useState } from "react";

import { getLocationSuggestions } from "../api/client";
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

export function DashboardShell({
  locations,
  activeLocation,
  setActiveLocation,
  addLocation,
  removeLocation,
  currentTemperatureC,
  currentTemperatureLoading,
  hourlyTemperatures24h,
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
        </header>
        <section className="hourly-slider-panel" aria-label="Hourly temperature forecast">
          <div className="hourly-slider-track">
            {hourlyTemperaturesLoading
              ? Array.from({ length: 10 }).map((_, index) => (
                  <article key={`hourly-loading-${index}`} className="hourly-item loading">
                    <span className="hourly-time">--</span>
                    <span className="hourly-temp">--°</span>
                  </article>
                ))
              : hourlyTemperatures24h.length === 0
                ? (
                  <article className="hourly-item">
                    <span className="hourly-time">No data</span>
                    <span className="hourly-temp">--°</span>
                  </article>
                  )
                : hourlyTemperatures24h.map((item, index) => (
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
                    </article>
                  ))}
          </div>
        </section>
        {children}
      </main>
    </div>
  );
}
