import * as React from 'react';
import {useState, useEffect, useRef} from 'react';
import {Map} from 'react-map-gl/mapbox';
import type {LayerProps} from 'react-map-gl/mapbox';
import Papa from 'papaparse';
import 'mapbox-gl/dist/mapbox-gl.css';
import '../App.css';
import { MAPBOX_TOKEN } from '../mapbox';

interface Coordinate {
  golfer_id: string;
  latitude: number;
  longitude: number;
  timestamp: number;
  type: string;
  current_hole?: number;
}

interface EntityData {
  coordinates: Coordinate[];
  color: string;
  name: string;
  type: string;
}

type SmoothingData = {
  times: number[];
  lat: number[];
  lng: number[];
  dLat: number[];
  dLng: number[];
};

interface MapStyle {
  name: string;
  url: string;
  description: string;
  golfOptimized?: boolean;
}

interface EntityType {
  name: string;
  color: string;
  description: string;
}

interface SimulationInfo {
  id: string;
  name: string;
  filename: string;
  description: string;
}

interface SimulationManifest {
  simulations: SimulationInfo[];
  defaultSimulation: string;
}

interface AppConfig {
  data: {
    csvFileName: string;
    cartPathFileName: string;
    coordinatesDir: string;
  };
  animation: {
    speedMultiplier: number;
    defaultMapStyle: string;
    startingHour?: number;
    smoothing?: {
      enabled: boolean;
      easing: 'linear' | 'cubic' | 'quart' | 'sine' | 'adaptive' | 'pchip' | 'catmull-rom';
      frameRate?: number;
    };
  };
  mapStyles: { [key: string]: MapStyle };
  entityTypes: { [key: string]: EntityType };
  display: {
    golferTrails: { width: number; opacity: number };
    golferMarkers: { radius: number; strokeWidth: number; strokeColor: string; strokeOpacity: number };
  };
  golferColors: string[];
}

const DEFAULT_COLORS = [
  '#007cbf', '#ff6b6b', '#4ecdc4', '#45b7d1', 
  '#f9ca24', '#6c5ce7', '#a55eea', '#26de81',
  '#fd79a8', '#e17055', '#00b894', '#0984e3'
];

const createPointLayer = (id: string, color: string, config?: AppConfig): LayerProps => ({
  id: id,
  type: 'circle',
  paint: {
    'circle-radius': (config?.display.golferMarkers.radius ?? 9),
    'circle-color': color,
    'circle-stroke-width': config?.display.golferMarkers.strokeWidth || 3,
    'circle-stroke-color': config?.display.golferMarkers.strokeColor || '#ffffff',
    'circle-stroke-opacity': config?.display.golferMarkers.strokeOpacity || 0.8
  }
});

function catmullRom(p0: number, p1: number, p2: number, p3: number, t: number): number {
  const t2 = t * t;
  const t3 = t2 * t;
  return 0.5 * (
    (2 * p1) +
    (-p0 + p2) * t +
    (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 +
    (-p0 + 3 * p1 - 3 * p2 + p3) * t3
  );
}

function easeInOutCubic(t: number): number { return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; }
function easeOutQuart(t: number): number { return 1 - Math.pow(1 - t, 4); }
function easeInOutSine(t: number): number { return -(Math.cos(Math.PI * t) - 1) / 2; }

function interpolatePoint(point1: Coordinate, point2: Coordinate, t: number, easing: 'linear' | 'cubic' | 'quart' | 'sine' = 'cubic'): Coordinate {
  let easedT = t;
  switch (easing) {
    case 'cubic': easedT = easeInOutCubic(t); break;
    case 'quart': easedT = easeOutQuart(t); break;
    case 'sine': easedT = easeInOutSine(t); break;
    case 'linear': default: easedT = t; break;
  }
  return {
    golfer_id: point1.golfer_id,
    latitude: point1.latitude + (point2.latitude - point1.latitude) * easedT,
    longitude: point1.longitude + (point2.longitude - point1.longitude) * easedT,
    timestamp: point1.timestamp + (point2.timestamp - point1.timestamp) * t,
    type: point1.type,
    current_hole: point1.current_hole
  };
}

function timestampToTimeOfDay(timestamp: number, startingHour: number = 0): string {
  const totalHours = Math.floor(timestamp / 3600);
  const currentHour = (startingHour + totalHours) % 24;
  const minutes = Math.floor((timestamp % 3600) / 60);
  const seconds = Math.floor(timestamp % 60);
  return `${currentHour.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
}

function getPositionOnPath(coordinates: Coordinate[], elapsedTime: number, easing: 'linear' | 'cubic' | 'quart' | 'sine' = 'cubic'): Coordinate | null {
  if (coordinates.length === 0) return null;
  if (coordinates.length === 1) return coordinates[0];
  for (let i = 0; i < coordinates.length - 1; i++) {
    const current = coordinates[i];
    const next = coordinates[i + 1];
    if (elapsedTime >= current.timestamp && elapsedTime <= next.timestamp) {
      const segmentDuration = next.timestamp - current.timestamp;
      const segmentProgress = segmentDuration > 0 ? (elapsedTime - current.timestamp) / segmentDuration : 0;
      return interpolatePoint(current, next, segmentProgress, easing);
    }
  }
  if (elapsedTime >= coordinates[coordinates.length - 1].timestamp) return coordinates[coordinates.length - 1];
  return null;
}

function calculateVelocity(point1: Coordinate, point2: Coordinate): number {
  const timeDiff = point2.timestamp - point1.timestamp;
  if (timeDiff <= 0) return 0;
  const lat1 = point1.latitude * Math.PI / 180;
  const lat2 = point2.latitude * Math.PI / 180;
  const deltaLat = (point2.latitude - point1.latitude) * Math.PI / 180;
  const deltaLng = (point2.longitude - point1.longitude) * Math.PI / 180;
  const a = Math.sin(deltaLat / 2) * Math.sin(deltaLat / 2) + Math.cos(lat1) * Math.cos(lat2) * Math.sin(deltaLng / 2) * Math.sin(deltaLng / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  const distance = 6371000 * c;
  return distance / timeDiff;
}

function getAdaptiveEasing(velocity: number): 'linear' | 'cubic' | 'quart' | 'sine' {
  if (velocity > 10) return 'linear';
  if (velocity > 5) return 'cubic';
  if (velocity > 1) return 'quart';
  return 'sine';
}

function computePchipTangents(values: number[], times: number[]): number[] {
  const n = values.length;
  if (n <= 2) {
    const s = n === 2 ? (values[1] - values[0]) / Math.max(1e-9, (times[1] - times[0])) : 0;
    return n === 2 ? [s, s] : [0];
  }
  const h: number[] = new Array(n - 1);
  const slopes: number[] = new Array(n - 1);
  for (let i = 0; i < n - 1; i++) {
    h[i] = Math.max(1e-9, times[i + 1] - times[i]);
    slopes[i] = (values[i + 1] - values[i]) / h[i];
  }
  const m: number[] = new Array(n);
  m[0] = slopes[0];
  m[n - 1] = slopes[n - 2];
  for (let i = 1; i < n - 1; i++) {
    if (slopes[i - 1] * slopes[i] <= 0) m[i] = 0; else {
      const w1 = 2 * h[i] + h[i - 1];
      const w2 = h[i] + 2 * h[i - 1];
      m[i] = (w1 + w2) / (w1 / slopes[i - 1] + w2 / slopes[i]);
    }
  }
  return m;
}

function hermiteInterpolate(v0: number, v1: number, m0: number, m1: number, h: number, s: number): number {
  const s2 = s * s;
  const s3 = s2 * s;
  const h00 = 2 * s3 - 3 * s2 + 1;
  const h10 = s3 - 2 * s2 + s;
  const h01 = -2 * s3 + 3 * s2;
  const h11 = s3 - s2;
  return h00 * v0 + h10 * h * m0 + h01 * v1 + h11 * h * m1;
}

function getPchipPosition(data: SmoothingData, time: number): { lat: number; lng: number } | null {
  const times = data.times;
  const n = times.length;
  if (n === 0) return null;
  if (n === 1) return { lat: data.lat[0], lng: data.lng[0] };
  if (time <= times[0]) return { lat: data.lat[0], lng: data.lng[0] };
  if (time >= times[n - 1]) return { lat: data.lat[n - 1], lng: data.lng[n - 1] };
  let i = 0;
  for (; i < n - 1; i++) if (time <= times[i + 1]) break;
  const t0 = times[i];
  const t1 = times[i + 1];
  const h = Math.max(1e-9, t1 - t0);
  const s = (time - t0) / h;
  const lat = hermiteInterpolate(data.lat[i], data.lat[i + 1], data.dLat[i], data.dLat[i + 1], h, s);
  const lng = hermiteInterpolate(data.lng[i], data.lng[i + 1], data.dLng[i], data.dLng[i + 1], h, s);
  return { lat, lng };
}

function getCatmullRomPositionOnPath(coordinates: Coordinate[], elapsedTime: number): Coordinate | null {
  if (coordinates.length < 2) {
    return coordinates.length === 1 ? coordinates[0] : null;
  }

  let i = -1;
  // Find the current segment
  for (let j = 0; j < coordinates.length - 1; j++) {
    if (elapsedTime >= coordinates[j].timestamp && elapsedTime <= coordinates[j + 1].timestamp) {
      i = j;
      break;
    }
  }

  if (i === -1) {
    if (elapsedTime < coordinates[0].timestamp) return coordinates[0];
    return coordinates[coordinates.length - 1];
  }
  
  const p1 = coordinates[i];
  const p2 = coordinates[i + 1];
  const p0 = i > 0 ? coordinates[i - 1] : p1;
  const p3 = i < coordinates.length - 2 ? coordinates[i + 2] : p2;

  const segmentDuration = p2.timestamp - p1.timestamp;
  const t = segmentDuration > 0 ? (elapsedTime - p1.timestamp) / segmentDuration : 0;

  const lat = catmullRom(p0.latitude, p1.latitude, p2.latitude, p3.latitude, t);
  const lng = catmullRom(p0.longitude, p1.longitude, p2.longitude, p3.longitude, t);

  return {
    golfer_id: p1.golfer_id,
    latitude: lat,
    longitude: lng,
    timestamp: elapsedTime,
    type: p1.type,
    current_hole: p1.current_hole,
  };
}

function calculateBounds(entitiesData: EntityData[]) {
  const allCoordinates = entitiesData.flatMap(e => e.coordinates);
  if (allCoordinates.length === 0) return { center: [0, 0] as [number, number], zoom: 2 };
  const lats = allCoordinates.map(c => c.latitude);
  const lngs = allCoordinates.map(c => c.longitude);
  const minLat = Math.min(...lats); const maxLat = Math.max(...lats);
  const minLng = Math.min(...lngs); const maxLng = Math.max(...lngs);
  const centerLat = (minLat + maxLat) / 2; const centerLng = (minLng + maxLng) / 2;
  const latSpread = maxLat - minLat; const lngSpread = maxLng - minLng; const maxSpread = Math.max(latSpread, lngSpread);
  let zoom = 10; if (maxSpread < 0.001) zoom = 18; else if (maxSpread < 0.01) zoom = 16; else if (maxSpread < 0.1) zoom = 14; else if (maxSpread < 1) zoom = 12; else zoom = 10;
  return { center: [centerLng, centerLat] as [number, number], zoom };
}

function ControlPanel({ 
  trackersData, isLoading, center, elapsedTime, currentTimeOfDay, originalMinTimestamp, trackerPositions
}: {
  trackersData: EntityData[];
  isLoading: boolean;
  center: [number, number];
  elapsedTime: number;
  currentTimeOfDay: string;
  originalMinTimestamp: number;
  trackerPositions: { [key: string]: Coordinate | null };
}) {
  const totalWaypoints = trackersData.reduce((sum, tracker) => sum + tracker.coordinates.length, 0);
  return (
    <div style={{ position: 'absolute', top: 0, right: 0, maxWidth: 340, background: '#fff', boxShadow: '0 2px 4px rgba(0,0,0,0.3)', padding: '12px 24px', margin: 20, fontSize: 13, lineHeight: 1.5, color: '#6b6b76', outline: 'none', borderRadius: 4 }}>
      <h3 style={{ margin: '0 0 12px 0', color: '#333', textTransform: 'uppercase' }}>Path Animation Tracker</h3>
      {isLoading ? (<p>Loading tracker coordinates...</p>) : (
        <>
          <p style={{ margin: '0 0 8px 0' }}>Following path with {totalWaypoints} total waypoints</p>
          <p style={{ margin: '0 0 8px 0', fontSize: 12 }}>Center: ({center[1].toFixed(4)}, {center[0].toFixed(4)})</p>
          <p style={{ margin: '0 0 12px 0', fontSize: 14, fontWeight: 'bold', color: '#2c5aa0' }}>Current Time: {currentTimeOfDay}</p>
        </>
      )}
    </div>
  );
}

const DEFAULT_CONFIG: AppConfig = {
  data: { csvFileName: '/golfer_coordinates.csv', cartPathFileName: '/cart_paths.geojson', coordinatesDir: '/coordinates' },
  animation: { speedMultiplier: 250, defaultMapStyle: 'satellite-streets', smoothing: { enabled: true, easing: 'catmull-rom', frameRate: 60 } },
  mapStyles: { 'satellite-streets': { name: 'Satellite with Streets', url: 'mapbox://styles/mapbox/satellite-streets-v12', description: 'Satellite imagery with roads and labels' } },
  entityTypes: { 'golfer': { name: 'Golfer', color: '#007cbf', description: 'Golf players' }, 'bev-cart': { name: 'Beverage Cart', color: '#ff6b6b', description: 'Beverage service' }, 'runner': { name: 'Runner', color: '#FF8B00', description: 'Runners on course' }},
  display: { golferTrails: { width: 2, opacity: 0.6 }, golferMarkers: { radius: 9, strokeWidth: 3, strokeColor: '#ffffff', strokeOpacity: 0.8 } },
  golferColors: DEFAULT_COLORS
};

export default function AnimationView() {
  const [config, setConfig] = useState<AppConfig>(DEFAULT_CONFIG);
  const [currentMapStyle, setCurrentMapStyle] = useState<string>('satellite-streets');
  const [trackersData, setTrackersData] = useState<EntityData[]>([]);
  const [trackerPositions, setTrackerPositions] = useState<{ [key: string]: Coordinate | null }>({});
  const [isLoading, setIsLoading] = useState(true);
  const [pathBounds, setPathBounds] = useState({ center: [0, 0] as [number, number], zoom: 2 });
  const [elapsedTime, setElapsedTime] = useState(0);
  const [currentTimeOfDay, setCurrentTimeOfDay] = useState<string>('00:00:00');
  const [originalMinTimestamp, setOriginalMinTimestamp] = useState<number>(0);
  const [animationDuration, setAnimationDuration] = useState<number>(0);
  // Animation timing is integrated incrementally to allow live speed changes without jumps
  const [animationStartTime, setAnimationStartTime] = useState<number | null>(0); // retained for backward-compat but not used
  const [sourcesReady, setSourcesReady] = useState<boolean>(false);
  const mapRef = useRef<any>(null);
  const lastUiUpdateRef = useRef<number>(0);
  const uiUpdateIntervalMs = 200;
  const smoothingCacheRef = useRef<{ [name: string]: SmoothingData }>({});
  const sourcesInitializedRef = useRef<boolean>(false);
  const initialSourceDataRef = useRef<{ [sourceId: string]: any }>({});
  // Live speed control
  const [speedMultiplier, setSpeedMultiplier] = useState<number>(DEFAULT_CONFIG.animation.speedMultiplier);
  const speedRef = useRef<number>(DEFAULT_CONFIG.animation.speedMultiplier);
  const simulatedElapsedRef = useRef<number>(0);
  const lastRealTimeSecRef = useRef<number>(0);

  useEffect(() => {
    const loadConfig = async () => {
      try {
        const cacheBuster = `?t=${Date.now()}`;
        const response = await fetch(`/config.json${cacheBuster}`);
        const configData: AppConfig = await response.json();
        setConfig(configData);
        setCurrentMapStyle(configData.animation.defaultMapStyle);
        if (typeof configData.animation?.speedMultiplier === 'number' && isFinite(configData.animation.speedMultiplier)) {
          setSpeedMultiplier(configData.animation.speedMultiplier);
          speedRef.current = configData.animation.speedMultiplier;
        }
      } catch (error) {
        // use defaults
      }
    };
    loadConfig();
  }, []);

  useEffect(() => {
    const loadSimulations = async () => {
      try {
        const cacheBuster = `?t=${Date.now()}`;
        const response = await fetch(`${config.data.coordinatesDir}/manifest.json${cacheBuster}`);
        let csvPath = config.data.csvFileName;
        if (response.ok) {
          const manifest: SimulationManifest = await response.json();
          const defaultId = manifest.defaultSimulation || manifest.simulations[0]?.id;
          const selected = manifest.simulations.find(s => s.id === defaultId);
          if (selected) csvPath = `${config.data.coordinatesDir}/${selected.filename}`;
        }
        const csvPathWithCache = `${csvPath}?t=${Date.now()}`;
        const csvResp = await fetch(csvPathWithCache);
        const csvText = await csvResp.text();
        Papa.parse(csvText, {
          header: true,
          skipEmptyLines: true,
          complete: (results) => {
            const coords = results.data
              .map((row: any, index: number) => ({
                golfer_id: row.id || row.golfer_id || row.type || `entity_${index}`,
                latitude: parseFloat(row.latitude),
                longitude: parseFloat(row.longitude),
                timestamp: parseFloat(row.timestamp),
                type: row.type || 'golfer',
                current_hole: row.current_hole || row.hole ? parseInt(row.current_hole || row.hole) : undefined
              }))
              .filter((coord: Coordinate) => !isNaN(coord.latitude) && !isNaN(coord.longitude) && !isNaN(coord.timestamp));
            const trackerGroups = coords.reduce((acc: { [key: string]: Coordinate[] }, coord) => {
              if (!acc[coord.golfer_id]) acc[coord.golfer_id] = [];
              acc[coord.golfer_id].push(coord);
              return acc;
            }, {});
            const allTimestamps = coords.map(c => c.timestamp);
            const minTimestamp = Math.min(...allTimestamps);
            const maxTimestamp = Math.max(...allTimestamps);
            const duration = maxTimestamp - minTimestamp;
            setOriginalMinTimestamp(minTimestamp);
            setAnimationDuration(duration);
            const trackersArray: EntityData[] = Object.entries(trackerGroups).map(([trackerId, coordinates]) => {
              const sortedCoords = coordinates
                .sort((a, b) => a.timestamp - b.timestamp)
                .map(coord => ({ ...coord, timestamp: coord.timestamp - minTimestamp }));
              const entityType = sortedCoords[0]?.type || 'golfer';
              return { name: trackerId, coordinates: sortedCoords, type: entityType, color: config.entityTypes[entityType]?.color || config.golferColors[0] };
            });
            setTrackersData(trackersArray);
            const newSmoothingCache: { [name: string]: SmoothingData } = {};
            for (const tracker of trackersArray) {
              const times = tracker.coordinates.map(c => c.timestamp);
              const lat = tracker.coordinates.map(c => c.latitude);
              const lng = tracker.coordinates.map(c => c.longitude);
              const dLat = computePchipTangents(lat, times);
              const dLng = computePchipTangents(lng, times);
              newSmoothingCache[tracker.name] = { times, lat, lng, dLat, dLng };
            }
            smoothingCacheRef.current = newSmoothingCache;
            const bounds = calculateBounds(trackersArray);
            setPathBounds(bounds);
            setIsLoading(false);
            setSourcesReady(false);
          },
          error: () => setIsLoading(false)
        });
      } catch {
        setIsLoading(false);
      }
    };
    loadSimulations();
  }, [config]);

  useEffect(() => {
    if (isLoading || trackersData.length === 0) return;
    const initializeSources = () => {
      const map = mapRef.current?.getMap?.();
      if (!map || sourcesInitializedRef.current) {
        // Even if sources are not initialized, allow animation to proceed
        setSourcesReady(true);
        return;
      }
      trackersData.forEach((tracker) => {
        const sourceId = `tracker-${tracker.name}`;
        const initial = tracker.coordinates[0];
        if (!initial) return;
        const initialData = { type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [initial.longitude, initial.latitude] } };
        initialSourceDataRef.current[sourceId] = initialData;
        if (!map.getSource(sourceId)) {
          map.addSource(sourceId, { type: 'geojson', data: initialData });
          if (!map.getLayer(sourceId)) {
            const layerConfig = createPointLayer(sourceId, tracker.color, config);
            map.addLayer({ ...layerConfig, source: sourceId });
            setTimeout(() => { try { if (map.getLayer(sourceId)) { map.moveLayer(sourceId); } } catch {} }, 100);
          }
        }
      });
      sourcesInitializedRef.current = true;
      setSourcesReady(true);
    };
    if (mapRef.current?.getMap?.()?.isStyleLoaded?.()) initializeSources(); else {
      const map = mapRef.current?.getMap?.();
      if (map) { map.on('styledata', initializeSources); return () => map.off('styledata', initializeSources); }
    }
  }, [trackersData, config, isLoading]);

  useEffect(() => {
    if (isLoading || trackersData.length === 0) return;
    if (!animationStartTime) { setAnimationStartTime(Date.now()); return; }
    const animate = () => {
      const currentTime = Date.now();
      const realElapsed = (currentTime - animationStartTime) / 1000;
      const simulatedElapsed = realElapsed * config.animation.speedMultiplier;
      const map = mapRef.current?.getMap?.();
      const newPositions: { [key: string]: Coordinate | null } = {};
      
      trackersData.forEach((tracker) => {
        let position: Coordinate | null = null;
        const smoothingConfig = config.animation.smoothing;

        if (smoothingConfig?.enabled) {
          switch (smoothingConfig.easing) {
            case 'catmull-rom':
              position = getCatmullRomPositionOnPath(tracker.coordinates, simulatedElapsed);
              break;
            case 'pchip': {
              const data = smoothingCacheRef.current[tracker.name];
              if (data) {
                const p = getPchipPosition(data, simulatedElapsed);
                if (p) {
                  position = { golfer_id: tracker.name, latitude: p.lat, longitude: p.lng, timestamp: simulatedElapsed, type: tracker.type };
                }
              }
              break;
            }
            case 'adaptive': {
              let easing: 'linear' | 'cubic' | 'quart' | 'sine' = 'cubic';
              for (let i = 0; i < tracker.coordinates.length - 1; i++) {
                const current = tracker.coordinates[i];
                const next = tracker.coordinates[i + 1];
                if (simulatedElapsed >= current.timestamp && simulatedElapsed <= next.timestamp) {
                  const velocity = calculateVelocity(current, next);
                  easing = getAdaptiveEasing(velocity);
                  break;
                }
              }
              position = getPositionOnPath(tracker.coordinates, simulatedElapsed, easing);
              break;
            }
            default:
              position = getPositionOnPath(tracker.coordinates, simulatedElapsed, smoothingConfig.easing as any);
          }
        }

        if (!position) {
            position = getPositionOnPath(tracker.coordinates, simulatedElapsed, 'linear');
        }

        newPositions[tracker.name] = position;
        if (map && position) {
          const sourceId = `tracker-${tracker.name}`;
          const src: any = map.getSource(sourceId);
          if (src && typeof src.setData === 'function') {
            src.setData({ type: 'Feature', geometry: { type: 'Point', coordinates: [position.longitude, position.latitude] } });
          }
        }
      });
      
      if (!lastUiUpdateRef.current || (currentTime - lastUiUpdateRef.current) >= uiUpdateIntervalMs) {
        lastUiUpdateRef.current = currentTime;
        setTrackerPositions(newPositions);
        setElapsedTime(Math.floor(simulatedElapsed));
        const currentSimulationTimestamp = originalMinTimestamp + simulatedElapsed;
        setCurrentTimeOfDay(timestampToTimeOfDay(currentSimulationTimestamp, config.animation.startingHour || 0));
      }
      requestAnimationFrame(animate);
    };
    const animationId = requestAnimationFrame(animate);
    const currentMapRef = mapRef.current;
    return () => {
      cancelAnimationFrame(animationId);
      if (sourcesInitializedRef.current) {
        const map = currentMapRef?.getMap?.();
        if (map) {
          trackersData.forEach((tracker) => {
            const sourceId = `tracker-${tracker.name}`;
            try { if (map.getLayer(sourceId)) map.removeLayer(sourceId); if (map.getSource(sourceId)) map.removeSource(sourceId); } catch {}
          });
        }
        sourcesInitializedRef.current = false;
      }
      // Reset integrator on unmount/reload of animation loop
      lastRealTimeSecRef.current = 0;
      simulatedElapsedRef.current = 0;
    };
  }, [isLoading, trackersData, config, originalMinTimestamp, sourcesReady]);

  // Keep ref in sync for animation loop without re-creating it
  useEffect(() => { speedRef.current = speedMultiplier; }, [speedMultiplier]);

  const getInitialViewState = () => {
    if (isLoading || (pathBounds.center[0] === 0 && pathBounds.center[1] === 0)) {
      return { latitude: 0, longitude: 0, zoom: 2 };
    }
    return { latitude: pathBounds.center[1], longitude: pathBounds.center[0], zoom: pathBounds.zoom };
  };

  if (isLoading) return (<div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh', fontSize: 18, color: '#666' }}>Loading tracker coordinates...</div>);
  if (trackersData.length === 0) return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh', fontSize: 18, color: '#666', textAlign: 'center' }}>
      <div>
        <p>No tracker coordinates found in CSV file.</p>
        <p>Make sure your CSV file has 'golfer_id', 'latitude', 'longitude', 'timestamp', and 'type' columns.</p>
      </div>
    </div>
  );

  return (
    <div style={{ width: '100vw', height: '100vh' }}>
      {/* Speed control panel */}
      <div style={{ position: 'absolute', top: 56, left: 10, zIndex: 11, background: 'rgba(255,255,255,0.95)', padding: '8px 10px', borderRadius: 6, boxShadow: '0 2px 4px rgba(0,0,0,0.2)', minWidth: 260 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <label htmlFor="speed-slider" style={{ fontSize: 12, color: '#333', minWidth: 70 }}>Speed</label>
          <input
            id="speed-slider"
            type="range"
            min={25}
            max={1000}
            step={25}
            value={speedMultiplier}
            onChange={(e) => setSpeedMultiplier(Number(e.target.value))}
            style={{ width: 140 }}
          />
          <span style={{ fontSize: 12, color: '#333', width: 44, textAlign: 'right' }}>{(speedMultiplier).toFixed(0)}x</span>
        </div>
      </div>
      <Map
        ref={mapRef}
        initialViewState={getInitialViewState()}
        mapStyle={(config.mapStyles[currentMapStyle]?.url) || (config.mapStyles[config.animation.defaultMapStyle]?.url)}
        mapboxAccessToken={MAPBOX_TOKEN}
        terrain={{ source: 'mapbox-dem', exaggeration: 1.5 }}
      >
        {/* Animated points sources are added imperatively */}
      </Map>
      <ControlPanel 
        trackersData={trackersData}
        isLoading={isLoading}
        center={pathBounds.center}
        elapsedTime={elapsedTime}
        currentTimeOfDay={currentTimeOfDay}
        originalMinTimestamp={originalMinTimestamp}
        trackerPositions={trackerPositions}
      />
    </div>
  );
}


