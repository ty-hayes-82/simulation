import * as React from 'react';
import {useState, useEffect, useRef} from 'react';
import {Map, Source, Layer} from 'react-map-gl/mapbox';
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

// createPointLayer helper kept previously is unused; removing to satisfy linter

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
  // timestamps are in minutes; convert to seconds for m/s
  const timeDiff = (point2.timestamp - point1.timestamp) * 60;
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
  trackersData, isLoading, center
}: {
  trackersData: EntityData[];
  isLoading: boolean;
  center: [number, number];
}) {
  const totalWaypoints = trackersData.reduce((sum, tracker) => sum + tracker.coordinates.length, 0);
  return (
    <div style={{ position: 'absolute', top: 0, right: 0, maxWidth: 340, background: '#fff', boxShadow: '0 2px 4px rgba(0,0,0,0.3)', padding: '12px 24px', margin: 20, fontSize: 13, lineHeight: 1.5, color: '#6b6b76', outline: 'none', borderRadius: 4 }}>
      <h3 style={{ margin: '0 0 12px 0', color: '#333', textTransform: 'uppercase' }}>Path Animation Tracker</h3>
      {isLoading ? (<p>Loading tracker coordinates...</p>) : (
        <>
          <p style={{ margin: '0 0 8px 0' }}>Following path with {totalWaypoints} total waypoints</p>
          <p style={{ margin: '0 0 8px 0', fontSize: 12 }}>Center: ({center[1].toFixed(4)}, {center[0].toFixed(4)})</p>
        </>
      )}
    </div>
  );
}

const DEFAULT_CONFIG: AppConfig = {
  data: { csvFileName: '/golfer_coordinates.csv', cartPathFileName: '/cart_paths.geojson', coordinatesDir: '/coordinates' },
  animation: { speedMultiplier: 200, defaultMapStyle: 'satellite-streets', smoothing: { enabled: true, easing: 'catmull-rom', frameRate: 60 } },
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
  const [originalMinTimestamp, setOriginalMinTimestamp] = useState<number>(0);
  const [animationDuration, setAnimationDuration] = useState<number>(0);
  const [availableSimulations, setAvailableSimulations] = useState<SimulationInfo[]>([]);
  const [selectedSimulationId, setSelectedSimulationId] = useState<string | null>(null);
  // Animation timing is integrated incrementally to allow live speed changes without jumps
  const [animationStartTime, setAnimationStartTime] = useState<number | null>(null); // retained for backward-compat but not used
  const [sourcesReady, setSourcesReady] = useState<boolean>(false);
  const [styleReady, setStyleReady] = useState<boolean>(false);
  const mapRef = useRef<any>(null);
  const lastUiUpdateRef = useRef<number>(0);
  const uiUpdateIntervalMs = 200;
  // Smoothing cache not needed for linear interpolation example-style animation
  const sourcesInitializedRef = useRef<boolean>(false);
  // removed unused initialSourceDataRef to satisfy linter
  const trackersGeoJsonRef = useRef<any>({ type: 'FeatureCollection', features: [] });
  const styleReadyRef = useRef<boolean>(false);
  // Fixed optimal speed for smooth animation
  const speedMultiplier = DEFAULT_CONFIG.animation.speedMultiplier;
  const speedRef = useRef<number>(DEFAULT_CONFIG.animation.speedMultiplier);
  const simulatedElapsedRef = useRef<number>(0);
  const lastRealTimeSecRef = useRef<number>(0);
  // Easing selection state
  const [currentEasing, setCurrentEasing] = useState<'linear' | 'cubic' | 'quart' | 'sine' | 'catmull-rom'>('catmull-rom');

  useEffect(() => {
    const loadConfig = async () => {
      try {
        const cacheBuster = `?t=${Date.now()}`;
        const response = await fetch(`/config.json${cacheBuster}`);
        const configData: AppConfig = await response.json();
        setConfig(configData);
        setCurrentMapStyle(configData.animation.defaultMapStyle);
        if (typeof configData.animation?.speedMultiplier === 'number' && isFinite(configData.animation.speedMultiplier)) {
          speedRef.current = configData.animation.speedMultiplier;
        }
      } catch (error) {
        // use defaults
      }
    };
    loadConfig();
  }, []);

  // Load manifest and expose simulations for selection
  useEffect(() => {
    const loadManifest = async () => {
      try {
        const cacheBuster = `?t=${Date.now()}`;
        const response = await fetch(`${config.data.coordinatesDir}/manifest.json${cacheBuster}`);
        if (response.ok) {
          const manifest: SimulationManifest = await response.json();
          setAvailableSimulations(manifest.simulations || []);
          const defaultId = manifest.defaultSimulation || manifest.simulations[0]?.id || null;
          setSelectedSimulationId(defaultId);
        } else {
          // Fallback: use single CSV path from config
          setAvailableSimulations([{ id: 'single', name: 'Single CSV', filename: config.data.csvFileName.replace(`${config.data.coordinatesDir}/`, ''), description: '' } as any]);
          setSelectedSimulationId('single');
        }
      } catch {
        // ignore
      }
    };
    loadManifest();
  }, [config]);

  // Load coordinates for the selected simulation
  useEffect(() => {
    const loadSelectedSimulation = async () => {
      if (!selectedSimulationId) return;
      try {
        const selected = availableSimulations.find(s => s.id === selectedSimulationId);
        const filename = selected ? selected.filename : config.data.csvFileName.replace(`${config.data.coordinatesDir}/`, '');
        const csvPath = `${config.data.coordinatesDir}/${filename}`;
        const csvResp = await fetch(`${csvPath}?t=${Date.now()}`);
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
            const duration = (maxTimestamp - minTimestamp) / 60; // minutes
            setOriginalMinTimestamp(minTimestamp);
            setAnimationDuration(duration);
            const trackersArray: EntityData[] = Object.entries(trackerGroups).map(([trackerId, coordinates]) => {
              const sortedCoords = coordinates
                .sort((a, b) => a.timestamp - b.timestamp)
                .map(coord => ({ ...coord, timestamp: (coord.timestamp - minTimestamp) / 60 })); // minutes
              let filteredCoords = sortedCoords;
              if (sortedCoords[0]?.type === 'golfer') {
                filteredCoords = sortedCoords.filter((_, index) => index % 3 === 0);
              }
              const entityType = filteredCoords[0]?.type || 'golfer';
              return { name: trackerId, coordinates: filteredCoords, type: entityType, color: config.entityTypes[entityType]?.color || config.golferColors[0] };
            });
            setTrackersData(trackersArray);
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
    loadSelectedSimulation();
  }, [selectedSimulationId, availableSimulations, config]);

  useEffect(() => {
    if (!styleReady || isLoading || trackersData.length === 0 || sourcesInitializedRef.current) return;
    // Build initial FeatureCollection with first point of each tracker, include color for data-driven styling
    const features: any[] = [];
    trackersData.forEach(tracker => {
      const p = tracker.coordinates[0];
      if (!p) return;
      features.push({
        type: 'Feature',
        properties: { id: tracker.name, color: tracker.color },
        geometry: { type: 'Point', coordinates: [p.longitude, p.latitude] }
      });
    });
    trackersGeoJsonRef.current = { type: 'FeatureCollection', features };
    sourcesInitializedRef.current = true;
    setSourcesReady(true);
  }, [isLoading, trackersData, styleReady]);

  // Simple animation loop matching react-map-gl example
  useEffect(() => {
    if (isLoading || trackersData.length === 0) return;
    
    let animationId: number;
    let startTime = Date.now();
    
    const animate = () => {
      const elapsed = (Date.now() - startTime) * speedMultiplier / 1000; // seconds
      const elapsedMinutes = elapsed / 60; // convert to minutes
      
      const map = mapRef.current?.getMap?.();
      if (!map) {
        animationId = requestAnimationFrame(animate);
        return;
      }
      
      const features: any[] = [];
      
             trackersData.forEach((tracker) => {
         let position: Coordinate | null;
         if (currentEasing === 'catmull-rom') {
           position = getCatmullRomPositionOnPath(tracker.coordinates, elapsedMinutes);
         } else {
           position = getPositionOnPath(tracker.coordinates, elapsedMinutes, currentEasing);
         }
         if (position) {
           features.push({
             type: 'Feature',
             properties: { id: tracker.name, color: tracker.color },
             geometry: { type: 'Point', coordinates: [position.longitude, position.latitude] }
           });
         }
       });
      
      // Update GeoJSON source
      const source = map.getSource('trackers');
      if (source && typeof source.setData === 'function') {
        source.setData({ type: 'FeatureCollection', features });
      }
      
      setElapsedTime(elapsedMinutes);
      animationId = requestAnimationFrame(animate);
    };
    
    animationId = requestAnimationFrame(animate);
    
    return () => {
      if (animationId) {
        cancelAnimationFrame(animationId);
      }
    };
  }, [isLoading, trackersData, speedMultiplier, currentEasing]);



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
      {/* Easing Control Panel */}
      <div style={{ position: 'absolute', top: 56, left: 10, zIndex: 11, background: 'rgba(255,255,255,0.95)', padding: '8px 10px', borderRadius: 6, boxShadow: '0 2px 4px rgba(0,0,0,0.2)', minWidth: 220 }}>
        {/* Simulation selector */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
          <label htmlFor="sim-select" style={{ fontSize: 12, color: '#333', minWidth: 70 }}>Simulation</label>
          <select
            id="sim-select"
            value={selectedSimulationId || ''}
            onChange={(e) => setSelectedSimulationId(e.target.value)}
            style={{ width: 280, padding: '4px', borderRadius: 4, border: '1px solid #ccc', fontSize: 12 }}
          >
            {availableSimulations.map((sim) => (
              <option key={sim.id} value={sim.id}>{sim.name}</option>
            ))}
          </select>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <label htmlFor="easing-select" style={{ fontSize: 12, color: '#333', minWidth: 70 }}>Easing</label>
          <select
            id="easing-select"
            value={currentEasing}
            onChange={(e) => setCurrentEasing(e.target.value as 'linear' | 'cubic' | 'quart' | 'sine' | 'catmull-rom')}
            style={{ width: 140, padding: '4px', borderRadius: 4, border: '1px solid #ccc', fontSize: 12 }}
          >
            <option value="linear">Linear</option>
            <option value="cubic">Cubic</option>
            <option value="quart">Quart</option>
            <option value="sine">Sine</option>
            <option value="catmull-rom">Catmull-Rom</option>
          </select>
        </div>
      </div>
      <Map
        ref={mapRef}
        initialViewState={getInitialViewState()}
        mapStyle={(config.mapStyles[currentMapStyle]?.url) || (config.mapStyles[config.animation.defaultMapStyle]?.url)}
        mapboxAccessToken={MAPBOX_TOKEN}
        reuseMaps
        onLoad={(e) => {
          // Ensure DEM source exists before enabling terrain
          try {
            const map = e.target as any;
            if (!map.getSource('mapbox-dem')) {
              map.addSource('mapbox-dem', {
                type: 'raster-dem',
                url: 'mapbox://mapbox.mapbox-terrain-dem-v1',
                tileSize: 512,
                maxzoom: 14
              });
            }
            map.setTerrain({ source: 'mapbox-dem', exaggeration: 1.5 });
          } catch {}
          styleReadyRef.current = true;
          setStyleReady(true);
        }}
      >
        {/* Declarative source/layer for trackers; data updated imperatively each frame for performance */}
        {sourcesReady && (
          <Source id="trackers" type="geojson" data={trackersGeoJsonRef.current}>
            <Layer
              id="trackers-points"
              type="circle"
              paint={{
                'circle-radius': (config?.display.golferMarkers.radius ?? 9),
                'circle-color': ['get', 'color'],
                'circle-stroke-width': config?.display.golferMarkers.strokeWidth || 3,
                'circle-stroke-color': config?.display.golferMarkers.strokeColor || '#ffffff',
                'circle-stroke-opacity': config?.display.golferMarkers.strokeOpacity || 0.8
              }}
            />
          </Source>
        )}
      </Map>
      <ControlPanel 
        trackersData={trackersData}
        isLoading={isLoading}
        center={pathBounds.center}
      />
    </div>
  );
}


