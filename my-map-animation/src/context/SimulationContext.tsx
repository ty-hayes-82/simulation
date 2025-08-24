import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { SimulationEntry, SimulationManifest } from '../lib/manifest';
import { loadManifest, selectBestMatch } from '../lib/manifest';

type Filters = { runners?: number; orders?: number };

// Add ViewState type
type ViewState = {
  latitude: number;
  longitude: number;
  zoom: number;
};

type SimulationContextValue = {
  manifest: SimulationManifest | null;
  selectedSim: SimulationEntry | null;
  selectedId: string | null;
  filters: Filters;
  setFilters: (f: Filters) => void;
  setSelectedId: (id: string) => void;
  refreshManifest: () => Promise<void>;
  // Timeline controls (minutes-based scrubbing)
  timelineMinutes: number;
  setTimelineMinutes: (m: number) => void;
  timelineMaxMinutes: number;
  setTimelineMaxMinutes: (m: number) => void;
  baselineTimestampSeconds: number;
  setBaselineTimestampSeconds: (s: number) => void;
  // Slider control state: true while user is scrubbing
  isSliderControlled: boolean;
  setIsSliderControlled: (v: boolean) => void;
  // Shared map view state
  viewState: ViewState;
  setViewState: (vs: ViewState) => void;
  // Animation timestamp preservation
  savedAnimationTimestamp: number | null;
  setSavedAnimationTimestamp: (timestamp: number | null) => void;
};

const SimulationContext = createContext<SimulationContextValue | undefined>(undefined);

// Default starting view
const INITIAL_VIEW_STATE: ViewState = {
  latitude: 34.0405,
  longitude: -84.5955,
  zoom: 14,
};

export function SimulationProvider({ children }: { children: React.ReactNode }) {
  const [manifest, setManifest] = useState<SimulationManifest | null>(null);
  const [filters, setFilters] = useState<Filters>({ runners: 1, orders: 20 });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // Timeline state shared across views/controls
  const [timelineMinutes, setTimelineMinutes] = useState<number>(0);
  const [timelineMaxMinutes, setTimelineMaxMinutes] = useState<number>(0);
  const [baselineTimestampSeconds, setBaselineTimestampSeconds] = useState<number>(0);
  const [isSliderControlled, setIsSliderControlled] = useState<boolean>(false);
  // Shared map view state
  const [viewState, setViewState] = useState<ViewState>(INITIAL_VIEW_STATE);
  // Animation timestamp preservation
  const [savedAnimationTimestamp, setSavedAnimationTimestamp] = useState<number | null>(null);

  // Load manifest on mount
  const refreshManifest = useCallback(async () => {
    const m = await loadManifest();
    setManifest(m);
  }, []);

  useEffect(() => { refreshManifest(); }, [refreshManifest]);

  // Sync ?sim= from URL on load
  useEffect(() => {
    const sp = new URLSearchParams(window.location.search);
    const urlSim = sp.get('sim');
    if (urlSim) setSelectedId(urlSim);
  }, []);

  // Resolve selected simulation by id or best match to filters
  const selectedSim: SimulationEntry | null = useMemo(() => {
    if (!manifest || (manifest.simulations || []).length === 0) return null;
    const byId = selectedId ? manifest.simulations.find(s => s.id === selectedId) || null : null;
    if (byId) return byId;
    const fallbackId = manifest.defaultSimulation;
    return selectBestMatch(manifest, filters, fallbackId);
  }, [manifest, selectedId, filters]);

  // Persist selection to URL when id changes
  useEffect(() => {
    if (selectedSim?.id) {
      const sp = new URLSearchParams(window.location.search);
      sp.set('sim', selectedSim.id);
      const newUrl = `${window.location.pathname}?${sp.toString()}`;
      if (newUrl !== window.location.href) window.history.replaceState(null, '', newUrl);
    }
  }, [selectedSim?.id]);

  // When filters change, clear explicit selection so filters drive the choice
  useEffect(() => {
    // Only clear if a different sim would be chosen by filters
    if (manifest && (manifest.simulations || []).length > 0) {
      const byFilters = selectBestMatch(manifest, filters, manifest.defaultSimulation);
      if (byFilters && byFilters.id !== selectedId) {
        setSelectedId(null);
      }
    } else {
      setSelectedId(null);
    }
  }, [filters, manifest]);

  const value = useMemo<SimulationContextValue>(() => ({
    manifest,
    selectedSim,
    selectedId: selectedSim?.id || selectedId,
    filters,
    setFilters,
    setSelectedId,
    refreshManifest,
    timelineMinutes,
    setTimelineMinutes,
    timelineMaxMinutes,
    setTimelineMaxMinutes,
    baselineTimestampSeconds,
    setBaselineTimestampSeconds,
    isSliderControlled,
    setIsSliderControlled,
    viewState,
    setViewState,
    savedAnimationTimestamp,
    setSavedAnimationTimestamp,
  }), [
    manifest,
    selectedSim,
    selectedId,
    filters,
    timelineMinutes,
    timelineMaxMinutes,
    baselineTimestampSeconds,
    isSliderControlled,
    viewState,
    savedAnimationTimestamp,
  ]);

  return (
    <SimulationContext.Provider value={value}>{children}</SimulationContext.Provider>
  );
}

export function useSimulation(): SimulationContextValue {
  const ctx = useContext(SimulationContext);
  if (!ctx) throw new Error('useSimulation must be used within SimulationProvider');
  return ctx;
}


