import { FormEvent, ReactNode, useEffect, useMemo, useState } from "react";

import { getLocationSuggestions } from "../api/client";
import type { LocationSuggestion } from "../types";

type DashboardShellProps = {
  locations: string[];
  activeLocation: string;
  setActiveLocation: (value: string) => void;
  addLocation: (value: string) => void;
  removeLocation: (value: string) => void;
  currentTemperatureC: number | null;
  currentTemperatureLoading: boolean;
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
  children,
}: DashboardShellProps) {
  const [locationInput, setLocationInput] = useState("");
  const [suggestions, setSuggestions] = useState<LocationSuggestion[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [suggestionsLoading, setSuggestionsLoading] = useState(false);

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
    <div className="app-shell">
      <aside className="sidebar">
        <h1 className="brand-title">ForecastHub</h1>
        <p className="brand-subtitle">Weather Intelligence Command Center</p>

        <form className="location-form" onSubmit={onSubmit}>
          <label htmlFor="location-input">Add location</label>
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
            placeholder="City name"
            autoComplete="off"
          />
          <button type="submit">Add</button>
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

        <section className="location-panel">
          <p className="location-panel-title">Locations</p>
          <div className="location-list">
            {locations.map((location) => (
              <div
                key={location}
                className={location === activeLocation ? "location-item-row active" : "location-item-row"}
              >
                <button type="button" className="location-item" onClick={() => setActiveLocation(location)}>
                  {location}
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
          <div>
            <p className="app-main-eyebrow">Selected Location</p>
            <h2 className="app-main-location">{activeLocation}</h2>
          </div>
          <p className="app-main-temperature">{displayTemperature}°C</p>
        </header>
        {children}
      </main>
    </div>
  );
}
