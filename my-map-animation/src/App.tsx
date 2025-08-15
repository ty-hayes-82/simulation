import * as React from 'react';
import {useState, useEffect, useRef} from 'react';
import {Map, Source, Layer} from 'react-map-gl/mapbox';
import type {LayerProps} from 'react-map-gl/mapbox';
import Papa from 'papaparse';
import 'mapbox-gl/dist/mapbox-gl.css';
import './App.css';

// Replace with your Mapbox token
const MAPBOX_TOKEN = 'pk.eyJ1IjoidHloYXllc3N3b29wIiwiYSI6ImNtZHlvMWNtcTAzdncybHB5aDc1MXlxZzQifQ.PjiPgGDO2dqbcYhd-UFxmg';

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

// Removed unused CartPath interface

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
      easing: 'linear' | 'cubic' | 'quart' | 'sine' | 'adaptive';
      frameRate?: number; // Target FPS for interpolation
    };
  };
  mapStyles: { [key: string]: MapStyle };
  entityTypes: { [key: string]: EntityType };
  display: {
    cartPath: {
      color: string;
      width: number;
      opacity: number;
      dashArray: number[];
    };
    golferTrails: {
      width: number;
      opacity: number;
    };
    golferMarkers: {
      radius: number;
      strokeWidth: number;
      strokeColor: string;
      strokeOpacity: number;
    };
  };
  golferColors: string[];
}

// Default fallback colors (will be replaced by config)
const DEFAULT_COLORS = [
  '#007cbf', '#ff6b6b', '#4ecdc4', '#45b7d1', 
  '#f9ca24', '#6c5ce7', '#a55eea', '#26de81',
  '#fd79a8', '#e17055', '#00b894', '#0984e3'
];

// Point layers for each tracker
const createPointLayer = (id: string, color: string, config?: AppConfig): LayerProps => ({
  id: id,
  type: 'circle',
  paint: {
    'circle-radius': config?.display.golferMarkers.radius || 12,
    'circle-color': color,
    'circle-stroke-width': config?.display.golferMarkers.strokeWidth || 3,
    'circle-stroke-color': config?.display.golferMarkers.strokeColor || '#ffffff',
    'circle-stroke-opacity': config?.display.golferMarkers.strokeOpacity || 0.8
  }
});

// Removed unused layer functions since we're not showing paths or cart paths

// Easing functions for smooth animation
function easeInOutCubic(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
}

function easeOutQuart(t: number): number {
  return 1 - Math.pow(1 - t, 4);
}

function easeInOutSine(t: number): number {
  return -(Math.cos(Math.PI * t) - 1) / 2;
}

// Function to interpolate between two points for smooth animation
function interpolatePoint(point1: Coordinate, point2: Coordinate, t: number, easing: 'linear' | 'cubic' | 'quart' | 'sine' = 'cubic'): Coordinate {
  // Apply easing function to smooth the movement
  let easedT = t;
  switch (easing) {
    case 'cubic':
      easedT = easeInOutCubic(t);
      break;
    case 'quart':
      easedT = easeOutQuart(t);
      break;
    case 'sine':
      easedT = easeInOutSine(t);
      break;
    case 'linear':
    default:
      easedT = t;
      break;
  }

  return {
    golfer_id: point1.golfer_id,
    latitude: point1.latitude + (point2.latitude - point1.latitude) * easedT,
    longitude: point1.longitude + (point2.longitude - point1.longitude) * easedT,
    timestamp: point1.timestamp + (point2.timestamp - point1.timestamp) * t, // Keep timestamp linear for accurate timing
    type: point1.type,
    current_hole: point1.current_hole // Preserve hole information
  };
}

// Function to convert timestamp to time of day with starting hour offset
function timestampToTimeOfDay(timestamp: number, startingHour: number = 0): string {
  // Since timestamps are now "seconds within the hour", we need to:
  // 1. Get the hour offset from timestamp (how many hours have passed)
  // 2. Add it to the starting hour
  // 3. Get minutes and seconds within the current hour
  
  const totalHours = Math.floor(timestamp / 3600);
  const currentHour = (startingHour + totalHours) % 24; // Handle day rollover
  const minutes = Math.floor((timestamp % 3600) / 60);
  const seconds = Math.floor(timestamp % 60);
  
  // Format as HH:MM:SS
  return `${currentHour.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
}

// Function to get current position along the path based on elapsed time with smooth interpolation
function getPositionOnPath(coordinates: Coordinate[], elapsedTime: number, easing: 'linear' | 'cubic' | 'quart' | 'sine' = 'cubic'): Coordinate | null {
  if (coordinates.length === 0) {
    return null;
  }
  
  if (coordinates.length === 1) {
    return coordinates[0];
  }

  // Find the appropriate segment based on elapsed time
  for (let i = 0; i < coordinates.length - 1; i++) {
    const current = coordinates[i];
    const next = coordinates[i + 1];
    
    if (elapsedTime >= current.timestamp && elapsedTime <= next.timestamp) {
      // Interpolate between current and next point with easing
      const segmentDuration = next.timestamp - current.timestamp;
      const segmentProgress = segmentDuration > 0 ? (elapsedTime - current.timestamp) / segmentDuration : 0;
      return interpolatePoint(current, next, segmentProgress, easing);
    }
  }
  
  // If we're past the last timestamp, return the last position
  if (elapsedTime >= coordinates[coordinates.length - 1].timestamp) {
    return coordinates[coordinates.length - 1];
  }
  
  // If we're before the first timestamp, return null (golfer hasn't started)
  return null;
}

// Function to calculate velocity between two points for adaptive smoothing
function calculateVelocity(point1: Coordinate, point2: Coordinate): number {
  const timeDiff = point2.timestamp - point1.timestamp;
  if (timeDiff <= 0) return 0;
  
  // Calculate distance using Haversine formula for more accurate distance
  const lat1 = point1.latitude * Math.PI / 180;
  const lat2 = point2.latitude * Math.PI / 180;
  const deltaLat = (point2.latitude - point1.latitude) * Math.PI / 180;
  const deltaLng = (point2.longitude - point1.longitude) * Math.PI / 180;
  
  const a = Math.sin(deltaLat / 2) * Math.sin(deltaLat / 2) +
            Math.cos(lat1) * Math.cos(lat2) *
            Math.sin(deltaLng / 2) * Math.sin(deltaLng / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  const distance = 6371000 * c; // Earth's radius in meters
  
  return distance / timeDiff; // meters per second
}

// Function to get adaptive easing based on velocity
function getAdaptiveEasing(velocity: number): 'linear' | 'cubic' | 'quart' | 'sine' {
  // Use different easing based on velocity
  if (velocity > 10) return 'linear'; // Fast movement - linear for accuracy
  if (velocity > 5) return 'cubic';   // Medium movement - smooth cubic
  if (velocity > 1) return 'quart';   // Slow movement - gentle quart
  return 'sine';                      // Very slow movement - smooth sine
}

// Compute monotone piecewise cubic Hermite (PCHIP-like) tangents
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
    if (slopes[i - 1] * slopes[i] <= 0) {
      m[i] = 0;
    } else {
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
  // Find segment index
  let i = 0;
  for (; i < n - 1; i++) {
    if (time <= times[i + 1]) break;
  }
  const t0 = times[i];
  const t1 = times[i + 1];
  const h = Math.max(1e-9, t1 - t0);
  const s = (time - t0) / h;
  const lat = hermiteInterpolate(data.lat[i], data.lat[i + 1], data.dLat[i], data.dLat[i + 1], h, s);
  const lng = hermiteInterpolate(data.lng[i], data.lng[i + 1], data.dLng[i], data.dLng[i + 1], h, s);
  return { lat, lng };
}

// Function to calculate bounding box and appropriate zoom from coordinates
function calculateBounds(entitiesData: EntityData[]) {
  const allCoordinates = entitiesData.flatMap(e => e.coordinates);
  
  if (allCoordinates.length === 0) {
    return { center: [0, 0] as [number, number], zoom: 2 };
  }

  const lats = allCoordinates.map(c => c.latitude);
  const lngs = allCoordinates.map(c => c.longitude);
  
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  const minLng = Math.min(...lngs);
  const maxLng = Math.max(...lngs);
  
  const centerLat = (minLat + maxLat) / 2;
  const centerLng = (minLng + maxLng) / 2;
  
  // Calculate zoom based on coordinate spread
  const latSpread = maxLat - minLat;
  const lngSpread = maxLng - minLng;
  const maxSpread = Math.max(latSpread, lngSpread);
  
  // Dynamic zoom calculation based on coordinate spread
  let zoom = 10;
  if (maxSpread < 0.001) zoom = 18;        // Very tight area
  else if (maxSpread < 0.01) zoom = 16;    // Small area
  else if (maxSpread < 0.1) zoom = 14;     // Medium area  
  else if (maxSpread < 1) zoom = 12;       // Large area
  else zoom = 10;                          // Very large area
  
  return {
    center: [centerLng, centerLat] as [number, number],
    zoom: zoom
  };
}

// Control Panel Component
function ControlPanel({ 
  trackersData, 
  isLoading,
  center,
  elapsedTime,
  currentTimeOfDay,
  originalMinTimestamp,
  trackerPositions,
  config,
  currentMapStyle,
  onMapStyleChange,
  simulations,
  currentSimulation,
  onSimulationChange,
  isLoadingSimulations,
  onSmoothingChange
}: {
  trackersData: EntityData[];
  isLoading: boolean;
  center: [number, number];
  elapsedTime: number;
  currentTimeOfDay: string;
  originalMinTimestamp: number;
  trackerPositions: { [key: string]: Coordinate | null };
  config: AppConfig;
  currentMapStyle: string;
  onMapStyleChange: (style: string) => void;
  simulations: SimulationInfo[];
  currentSimulation: string;
  onSimulationChange: (simulationId: string) => void;
  isLoadingSimulations: boolean;
  onSmoothingChange?: (smoothing: { enabled: boolean; easing: 'linear' | 'cubic' | 'quart' | 'sine' | 'adaptive' }) => void;
}) {
  const totalWaypoints = trackersData.reduce((sum, tracker) => sum + tracker.coordinates.length, 0);
  
  return (
    <div style={{
      position: 'absolute',
      top: 0,
      right: 0,
      maxWidth: 340,
      background: '#fff',
      boxShadow: '0 2px 4px rgba(0,0,0,0.3)',
      padding: '12px 24px',
      margin: 20,
      fontSize: 13,
      lineHeight: 1.5,
      color: '#6b6b76',
      outline: 'none',
      borderRadius: 4
    }}>
      <h3 style={{ margin: '0 0 12px 0', color: '#333', textTransform: 'uppercase' }}>
        Path Animation Tracker
      </h3>
      
      {isLoading ? (
        <p>Loading tracker coordinates...</p>
      ) : (
        <>
          <p style={{ margin: '0 0 8px 0' }}>
            Following path with {totalWaypoints} total waypoints
          </p>
          <p style={{ margin: '0 0 8px 0', fontSize: 12 }}>
            Center: ({center[1].toFixed(4)}, {center[0].toFixed(4)})
          </p>
          <p style={{ margin: '0 0 12px 0', fontSize: 14, fontWeight: 'bold', color: '#2c5aa0' }}>
            Current Time: {currentTimeOfDay}
          </p>

          <div style={{ marginBottom: 12 }}>
            <label style={{ fontSize: 12, fontWeight: 'bold', display: 'block', marginBottom: 4 }}>
              Simulation:
            </label>
            <select 
              value={currentSimulation} 
              onChange={(e) => onSimulationChange(e.target.value)}
              disabled={isLoadingSimulations}
              style={{ 
                fontSize: 11, 
                padding: '2px 4px', 
                width: '100%',
                border: '1px solid #ccc',
                borderRadius: 2,
                backgroundColor: isLoadingSimulations ? '#f5f5f5' : 'white'
              }}
            >
              {simulations.map((sim) => (
                <option key={sim.id} value={sim.id} title={sim.description}>
                  {sim.name}
                </option>
              ))}
            </select>
            <div style={{ fontSize: 10, color: '#666', marginTop: 4, fontStyle: 'italic' }}>
              {simulations.find(s => s.id === currentSimulation)?.description || 'Loading simulations...'}
            </div>
          </div>

          <div style={{ marginBottom: 12 }}>
            <label style={{ fontSize: 12, fontWeight: 'bold', display: 'block', marginBottom: 4 }}>
              Map Style:
            </label>
            <select 
              value={currentMapStyle} 
              onChange={(e) => onMapStyleChange(e.target.value)}
              style={{ 
                fontSize: 11, 
                padding: '2px 4px', 
                width: '100%',
                border: '1px solid #ccc',
                borderRadius: 2
              }}
            >
              <optgroup label="🏌️ Golf Optimized">
                {Object.entries(config.mapStyles)
                  .filter(([, style]) => style.golfOptimized)
                  .map(([key, style]) => (
                    <option key={key} value={key} title={style.description}>
                      {style.name}
                    </option>
                  ))}
              </optgroup>
              <optgroup label="📍 General Maps">
                {Object.entries(config.mapStyles)
                  .filter(([, style]) => !style.golfOptimized)
                  .map(([key, style]) => (
                    <option key={key} value={key} title={style.description}>
                      {style.name}
                    </option>
                  ))}
              </optgroup>
            </select>
            <div style={{ fontSize: 10, color: '#666', marginTop: 4, fontStyle: 'italic' }}>
              {config.mapStyles[currentMapStyle]?.description}
            </div>
          </div>

          {onSmoothingChange && (
            <div style={{ marginBottom: 12 }}>
              <label style={{ fontSize: 12, fontWeight: 'bold', display: 'block', marginBottom: 4 }}>
                Movement Smoothing:
              </label>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                <input
                  type="checkbox"
                  checked={config.animation.smoothing?.enabled ?? true}
                  onChange={(e) => onSmoothingChange({
                    enabled: e.target.checked,
                    easing: config.animation.smoothing?.easing ?? 'adaptive'
                  })}
                  style={{ margin: 0 }}
                />
                <span style={{ fontSize: 11 }}>Enable Smoothing</span>
              </div>
              {config.animation.smoothing?.enabled && (
                <select 
                  value={config.animation.smoothing?.easing ?? 'adaptive'}
                  onChange={(e) => onSmoothingChange({
                    enabled: true,
                    easing: e.target.value as 'linear' | 'cubic' | 'quart' | 'sine' | 'adaptive'
                  })}
                  style={{ 
                    fontSize: 11, 
                    padding: '2px 4px', 
                    width: '100%',
                    border: '1px solid #ccc',
                    borderRadius: 2
                  }}
                >
                  <option value="adaptive">Adaptive (Recommended)</option>
                  <option value="cubic">Cubic (Smooth)</option>
                  <option value="sine">Sine (Gentle)</option>
                  <option value="quart">Quart (Moderate)</option>
                  <option value="linear">Linear (Precise)</option>
                </select>
              )}
              <div style={{ fontSize: 10, color: '#666', marginTop: 4, fontStyle: 'italic' }}>
                {config.animation.smoothing?.easing === 'adaptive' 
                  ? 'Automatically adjusts based on movement speed'
                  : config.animation.smoothing?.easing === 'cubic'
                  ? 'Smooth acceleration and deceleration'
                  : config.animation.smoothing?.easing === 'sine'
                  ? 'Very gentle, natural movement'
                  : config.animation.smoothing?.easing === 'quart'
                  ? 'Moderate smoothing with slight easing'
                  : 'Precise linear movement between points'
                }
              </div>
            </div>
          )}
          
          {trackersData.map((tracker) => {
            const position = trackerPositions[tracker.name];
            const status = position ? 'Active' : (elapsedTime >= tracker.coordinates[0]?.timestamp ? 'Finished' : 'Waiting');
            const entityType = config.entityTypes[tracker.type];
            
            // Find current hole information
            let currentHole = null;
            if (position) {
              // Find the closest coordinate by timestamp (normalized coordinates already have adjusted timestamps)
              const targetTime = elapsedTime;
              let closestCoord = null;
              let minTimeDiff = Infinity;
              
              for (const coord of tracker.coordinates) {
                const timeDiff = Math.abs(coord.timestamp - targetTime);
                if (timeDiff < minTimeDiff) {
                  minTimeDiff = timeDiff;
                  closestCoord = coord;
                }
              }
              
              currentHole = closestCoord?.current_hole;
            }
            
            return (
              <div key={tracker.name} style={{ marginBottom: 8, fontSize: 12 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
                  <div style={{ 
                    width: 12, 
                    height: 12, 
                    borderRadius: '50%', 
                    backgroundColor: tracker.color,
                    border: '2px solid #fff',
                    boxShadow: '0 1px 2px rgba(0,0,0,0.2)'
                  }}></div>
                  <span style={{ fontWeight: 'bold', textTransform: 'capitalize' }}>{tracker.name}:</span>
                  <span style={{ color: '#666', fontSize: 11 }}>({entityType?.name || tracker.type})</span>
                  <span>{status}</span>
                </div>
                {currentHole && (
                  <div style={{ marginLeft: 18, fontSize: 11, color: '#2c5aa0', fontWeight: 'bold' }}>
                    Currently at Hole {currentHole}
                  </div>
                )}
              </div>
            );
          })}
          
          <div style={{ fontSize: 11, marginTop: 12, paddingTop: 12, borderTop: '1px solid #eee' }}>
            <p style={{ margin: 0 }}>
              Trackers follow paths with satellite imagery showing terrain, roads, and water features.
              Colored lines show complete paths, small dots mark waypoints, large dots show current positions.
            </p>
          </div>
        </>
      )}
    </div>
  );
}

// Default configuration (fallback)
const DEFAULT_CONFIG: AppConfig = {
  data: {
    csvFileName: '/golfer_coordinates.csv',
    cartPathFileName: '/cart_paths.geojson',
    coordinatesDir: '/coordinates'
  },
  animation: {
    speedMultiplier: 250,
    defaultMapStyle: 'satellite-streets',
    smoothing: {
      enabled: true,
      easing: 'adaptive',
      frameRate: 60
    }
  },
  mapStyles: {
    'satellite-streets': {
      name: 'Satellite with Streets',
      url: 'mapbox://styles/mapbox/satellite-streets-v12',
      description: 'Satellite imagery with roads and labels'
    }
  },
  entityTypes: {
    'golfer': { name: 'Golfer', color: '#007cbf', description: 'Golf players' },
    'bev-cart': { name: 'Beverage Cart', color: '#ff6b6b', description: 'Beverage service' },
    'runner': { name: 'Runner', color: '#FF8B00', description: 'Runners on course' }
  },
  display: {
    cartPath: { color: '#888888', width: 1.5, opacity: 0.6, dashArray: [3, 3] },
    golferTrails: { width: 2, opacity: 0.6 },
    golferMarkers: { radius: 12, strokeWidth: 3, strokeColor: '#ffffff', strokeOpacity: 0.8 }
  },
  golferColors: DEFAULT_COLORS
};

export default function App() {
  const [config, setConfig] = useState<AppConfig>(DEFAULT_CONFIG);
  const [currentMapStyle, setCurrentMapStyle] = useState<string>('satellite-streets');
  const [trackersData, setTrackersData] = useState<EntityData[]>([]);
  const [trackerPositions, setTrackerPositions] = useState<{ [key: string]: Coordinate | null }>({});
  const [isLoading, setIsLoading] = useState(true);
  const [pathBounds, setPathBounds] = useState({ center: [0, 0] as [number, number], zoom: 2 });
  const [elapsedTime, setElapsedTime] = useState(0);
  const [currentTimeOfDay, setCurrentTimeOfDay] = useState<string>('00:00:00');
  const [originalMinTimestamp, setOriginalMinTimestamp] = useState<number>(0);
  const [animationStartTime, setAnimationStartTime] = useState<number | null>(null);
  
  // Map and animation refs (to avoid per-frame React re-renders)
  const mapRef = useRef<any>(null);
  const sourcesCacheRef = useRef<{ [sourceId: string]: any }>({});
  const lastUiUpdateRef = useRef<number>(0);
  const uiUpdateIntervalMs = 200; // throttle UI updates to 5 fps
  const smoothingCacheRef = useRef<{ [name: string]: SmoothingData }>({});
  
  // Simulation-related state
  const [simulations, setSimulations] = useState<SimulationInfo[]>([]);
  const [currentSimulation, setCurrentSimulation] = useState<string>('');
  const [isLoadingSimulations, setIsLoadingSimulations] = useState(true);

  // Load configuration from JSON file
  useEffect(() => {
    const loadConfig = async () => {
      try {
        // Add cache-busting parameter to ensure fresh data every time
        const cacheBuster = `?t=${Date.now()}`;
        const response = await fetch(`/config.json${cacheBuster}`);
        const configData: AppConfig = await response.json();
        setConfig(configData);
        setCurrentMapStyle(configData.animation.defaultMapStyle);
        console.log('Configuration loaded successfully');
      } catch (error) {
        console.error('Error loading configuration, using defaults:', error);
      }
    };

    loadConfig();
  }, []);

  // Load simulation manifest
  useEffect(() => {
    const loadSimulations = async () => {
      try {
        // Add cache-busting parameter to ensure fresh data every time
        const cacheBuster = `?t=${Date.now()}`;
        const response = await fetch(`${config.data.coordinatesDir}/manifest.json${cacheBuster}`);
        if (response.ok) {
          const manifest: SimulationManifest = await response.json();

          setSimulations(manifest.simulations);

          // Prefer defaultSimulation if provided and present; otherwise first simulation
          const defaultId = manifest.defaultSimulation;
          const hasDefault = defaultId && manifest.simulations.some(s => s.id === defaultId);
          if (hasDefault) {
            setCurrentSimulation(defaultId);
          } else if (manifest.simulations.length > 0) {
            setCurrentSimulation(manifest.simulations[0].id);
          } else {
            setCurrentSimulation('');
          }
          console.log(`Simulation manifest loaded successfully. Found ${manifest.simulations.length} simulations.`);
        } else {
          // Fallback to single file mode
          console.log('No simulation manifest found, using single file mode');
          const fallbackSimulations = [{
            id: 'default',
            name: 'Default Simulation',
            filename: 'golfer_coordinates.csv',
            description: 'Single simulation file'
          }];
          setSimulations(fallbackSimulations);
          setCurrentSimulation('default');
        }
        setIsLoadingSimulations(false);
      } catch (error) {
        console.error('Error loading simulations, using fallback:', error);
        // Fallback to single file mode
        const fallbackSimulations = [{
          id: 'default',
          name: 'Default Simulation',
          filename: 'golfer_coordinates.csv',
          description: 'Single simulation file'
        }];
        setSimulations(fallbackSimulations);
        setCurrentSimulation('default');
        setIsLoadingSimulations(false);
      }
    };

    loadSimulations();
  }, [config]);

  // Cart path loading removed since we're not displaying them

  // Load coordinates from CSV file
  useEffect(() => {
    if (!currentSimulation || isLoadingSimulations) return;
    
    const loadCoordinates = async () => {
      setIsLoading(true);
      setAnimationStartTime(null); // Reset animation
      
      try {
        // Determine the CSV file path
        const selectedSim = simulations.find(s => s.id === currentSimulation);
        let csvPath: string;
        
        if (selectedSim && selectedSim.id !== 'default') {
          csvPath = `${config.data.coordinatesDir}/${selectedSim.filename}`;
        } else {
          csvPath = config.data.csvFileName;
        }
        
        // Add cache-busting parameter to ensure fresh data every time
        const cacheBuster = `?t=${Date.now()}`;
        const csvPathWithCache = `${csvPath}${cacheBuster}`;
        console.log(`Loading coordinates from: ${csvPath}`);
        const response = await fetch(csvPathWithCache);
        const csvText = await response.text();
        
        Papa.parse(csvText, {
          header: true,
          skipEmptyLines: true,
          complete: (results) => {
            console.log('CSV parsing results:', {
              totalRows: results.data?.length,
              hasData: results.data && results.data.length > 0
            });
            
            const coords = results.data
              .map((row: any, index: number) => {
                // More flexible column mapping
                const coord = {
                  golfer_id: row.id || row.golfer_id || row.type || `entity_${index}`,
                  latitude: parseFloat(row.latitude),
                  longitude: parseFloat(row.longitude),
                  timestamp: parseFloat(row.timestamp),
                  type: row.type || 'golfer',
                  current_hole: row.current_hole || row.hole ? parseInt(row.current_hole || row.hole) : undefined
                };
                
                return coord;
              })
              .filter((coord: Coordinate) => 
                !isNaN(coord.latitude) && !isNaN(coord.longitude) && !isNaN(coord.timestamp)
              );
            
            // Group coordinates by tracker ID
            const trackerGroups = coords.reduce((acc: { [key: string]: Coordinate[] }, coord) => {
              if (!acc[coord.golfer_id]) {
                acc[coord.golfer_id] = [];
              }
              acc[coord.golfer_id].push(coord);
              return acc;
            }, {});
            
            // Find the minimum timestamp across all coordinates to normalize
            const allTimestamps = coords.map(c => c.timestamp);
            const minTimestamp = Math.min(...allTimestamps);
            const maxTimestamp = Math.max(...allTimestamps);
            setOriginalMinTimestamp(minTimestamp);
            console.log(`Normalizing timestamps - original range: ${minTimestamp} to ${maxTimestamp}`);
            console.log(`Starting time of day: ${timestampToTimeOfDay(minTimestamp, config.animation.startingHour || 0)}`);
            console.log(`Duration: ${maxTimestamp - minTimestamp} seconds (${((maxTimestamp - minTimestamp)/60).toFixed(1)} minutes)`);
            
            // Create tracker data with colors based on entity type and normalized timestamps
            const trackersArray: EntityData[] = Object.entries(trackerGroups).map(([trackerId, coordinates]) => {
              const sortedCoords = coordinates
                .sort((a, b) => a.timestamp - b.timestamp)
                .map(coord => ({
                  ...coord,
                  timestamp: coord.timestamp - minTimestamp // Normalize timestamps to start from 0
                }));
              const entityType = sortedCoords[0]?.type || 'golfer';
              const typeConfig = config.entityTypes[entityType];
              
              // Create a better display name for the entity
              const displayName = trackerId === entityType ? 
                (typeConfig?.name || entityType) : 
                trackerId;
              
              // Log entity details
              console.log(`Entity ${trackerId}: ${sortedCoords.length} coordinates, ` + 
                         `original time ${coordinates[0]?.timestamp} to ${coordinates[coordinates.length-1]?.timestamp}, ` +
                         `normalized time 0 to ${sortedCoords[sortedCoords.length-1]?.timestamp}, ` +
                         `starting hole: ${sortedCoords[0]?.current_hole}`);
              
              return {
                name: displayName,
                coordinates: sortedCoords,
                type: entityType,
                color: typeConfig?.color || config.golferColors[0] // Use entity type color or fallback
              };
            });
            
            setTrackersData(trackersArray);

            // Precompute PCHIP smoothing data per tracker for perfectly smooth motion
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
            
            // Calculate bounds from all coordinates
            const bounds = calculateBounds(trackersArray);
            setPathBounds(bounds);
            
            setIsLoading(false);
            console.log(`Loaded ${trackersArray.length} trackers with ${coords.length} total waypoints`);
            console.log(`Path bounds: center (${bounds.center[1]}, ${bounds.center[0]}), zoom ${bounds.zoom}`);
          },
          error: (error: any) => {
            console.error('Error parsing CSV:', error);
        console.error('Make sure the CSV file has the required columns: golfer_id, latitude, longitude, timestamp, type');
            setIsLoading(false);
          }
        });
      } catch (error) {
        console.error('Error loading CSV file:', error);
        console.error('Make sure the file exists at:', config.data.csvFileName);
        setIsLoading(false);
      }
    };

    loadCoordinates();
  }, [config, currentSimulation, simulations, isLoadingSimulations]);

  // Animation logic for all trackers
  useEffect(() => {
    if (isLoading || trackersData.length === 0) return;

    // Set animation start time on first load
    if (animationStartTime === null) {
      setAnimationStartTime(Date.now());
      return;
    }

    const animate = () => {
      const currentTime = Date.now();
      const realElapsed = (currentTime - animationStartTime) / 1000; // Real seconds elapsed
      const simulatedElapsed = realElapsed * config.animation.speedMultiplier;
      
      // Imperatively update map sources for per-frame smoothness
      const map = mapRef.current?.getMap?.();
      const newPositions: { [key: string]: Coordinate | null } = {};
      
      trackersData.forEach((tracker) => {
        // Determine easing type based on configuration
        let easing: 'linear' | 'cubic' | 'quart' | 'sine' = 'cubic';
        
        if (config.animation.smoothing?.enabled) {
          if (config.animation.smoothing.easing === 'adaptive') {
            // Find current segment for velocity calculation
            for (let i = 0; i < tracker.coordinates.length - 1; i++) {
              const current = tracker.coordinates[i];
              const next = tracker.coordinates[i + 1];
              
              if (simulatedElapsed >= current.timestamp && simulatedElapsed <= next.timestamp) {
                const velocity = calculateVelocity(current, next);
                easing = getAdaptiveEasing(velocity);
                break;
              }
            }
          } else {
            easing = config.animation.smoothing.easing;
          }
        }
        
        let position = getPositionOnPath(tracker.coordinates, simulatedElapsed, easing);
        
        // If smoothing is enabled, override with PCHIP-interpolated position for perfectly smooth motion
        if (config.animation.smoothing?.enabled) {
          const data = smoothingCacheRef.current[tracker.name];
          if (data) {
            const p = getPchipPosition(data, simulatedElapsed);
            if (p) {
              position = {
                golfer_id: tracker.name,
                latitude: p.lat,
                longitude: p.lng,
                timestamp: simulatedElapsed,
                type: tracker.type,
                current_hole: undefined
              };
            }
          }
        }
        newPositions[tracker.name] = position;
        
        // Update underlying Mapbox source directly
        if (map && position) {
          const sourceId = `tracker-${tracker.name}`;
          const src: any = map.getSource(sourceId);
          if (src && typeof src.setData === 'function') {
            src.setData({
              type: 'Feature',
              geometry: {
                type: 'Point',
                coordinates: [position.longitude, position.latitude]
              }
            });
          }
        }
      });
      
      // Throttle UI state updates to reduce React re-render frequency
      if (!lastUiUpdateRef.current || (currentTime - lastUiUpdateRef.current) >= uiUpdateIntervalMs) {
        lastUiUpdateRef.current = currentTime;
        setTrackerPositions(newPositions);
        setElapsedTime(Math.floor(simulatedElapsed));
        const currentTimestamp = originalMinTimestamp + simulatedElapsed;
        setCurrentTimeOfDay(timestampToTimeOfDay(currentTimestamp, config.animation.startingHour || 0));
      }
      
      // Continue the animation loop
      requestAnimationFrame(animate);
    };

    const animationId = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(animationId);
  }, [isLoading, trackersData, animationStartTime, config, originalMinTimestamp]);

  // Handle group change - removed since we no longer have groups

  // Handle simulation change
  const handleSimulationChange = (simulationId: string) => {
    setCurrentSimulation(simulationId);
    console.log(`Switching to simulation: ${simulationId}`);
  };

  // Handle smoothing change
  const handleSmoothingChange = (smoothing: { enabled: boolean; easing: 'linear' | 'cubic' | 'quart' | 'sine' | 'adaptive' }) => {
    setConfig(prevConfig => ({
      ...prevConfig,
      animation: {
        ...prevConfig.animation,
        smoothing: {
          ...prevConfig.animation.smoothing,
          ...smoothing
        }
      }
    }));
    console.log(`Smoothing updated:`, smoothing);
  };

  // Calculate initial viewport based on the path bounds
  const getInitialViewState = () => {
    if (isLoading || (pathBounds.center[0] === 0 && pathBounds.center[1] === 0)) {
      return {
        latitude: 0,
        longitude: 0,
        zoom: 2
      };
    }

    return {
      latitude: pathBounds.center[1],
      longitude: pathBounds.center[0],
      zoom: pathBounds.zoom
    };
  };

  if (isLoading) {
    return (
      <div style={{ 
        display: 'flex', 
        justifyContent: 'center', 
        alignItems: 'center', 
        height: '100vh',
        fontSize: 18,
        color: '#666'
      }}>
        Loading tracker coordinates...
      </div>
    );
  }

  if (trackersData.length === 0) {
    return (
      <div style={{ 
        display: 'flex', 
        justifyContent: 'center', 
        alignItems: 'center', 
        height: '100vh',
        fontSize: 18,
        color: '#666',
        textAlign: 'center'
      }}>
        <div>
          <p>No tracker coordinates found in CSV file.</p>
          <p>Make sure your CSV file has 'golfer_id', 'latitude', 'longitude', 'timestamp', and 'type' columns.</p>
          <p>CSV file location: {config.data.csvFileName}</p>
        </div>
      </div>
    );
  }

  return (
    <div style={{ width: '100vw', height: '100vh' }}>
      <Map
        ref={mapRef}
        initialViewState={getInitialViewState()}
        mapStyle={(config.mapStyles[currentMapStyle]?.url) || (config.mapStyles[config.animation.defaultMapStyle]?.url)}
        mapboxAccessToken={MAPBOX_TOKEN}
        terrain={{ source: 'mapbox-dem', exaggeration: 1.5 }}
      >
        {/* Cart paths removed - cleaner view focusing on golfer animations */}
        
        {/* Golfer trail paths removed - showing only current positions */}
        
        {/* Animated points for each tracker */}
        {trackersData.map((tracker) => {
          // Initialize each source once; data will be updated imperatively per frame
          const initial = tracker.coordinates[0] || null;
          if (!initial) return null;
          return (
            <Source key={`tracker-${tracker.name}`} id={`tracker-${tracker.name}`} type="geojson" data={{
              type: 'Feature',
              properties: {},
              geometry: {
                type: 'Point',
                coordinates: [initial.longitude, initial.latitude]
              }
            }}>
              <Layer {...createPointLayer(`tracker-${tracker.name}`, tracker.color, config)} />
            </Source>
          );
        })}
      </Map>
      
      <ControlPanel 
        trackersData={trackersData}
        isLoading={isLoading}
        center={pathBounds.center}
        elapsedTime={elapsedTime}
        currentTimeOfDay={currentTimeOfDay}
        originalMinTimestamp={originalMinTimestamp}
        trackerPositions={trackerPositions}
        config={config}
        currentMapStyle={currentMapStyle}
        onMapStyleChange={setCurrentMapStyle}
        simulations={simulations}
        currentSimulation={currentSimulation}
        onSimulationChange={handleSimulationChange}
        isLoadingSimulations={isLoadingSimulations}
        onSmoothingChange={handleSmoothingChange}
      />
    </div>
  );
}