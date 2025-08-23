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

// Removed SimulationInfo and SimulationManifest interfaces - no longer needed

interface DeliveryMetrics {
  orderCount: number;
  revenue: number;
  avgOrderTime: number;
  onTimeRate: number;
  failedOrderCount: number;
  queueWaitAvg: number;
  deliveryCycleTimeP90: number;
  ordersPerRunnerHour: number;
  revenuePerRunnerHour: number;
}

interface BevCartMetrics {
  totalOrders: number;
  totalGroupsPassed: number;
  avgOrderValue: number;
  totalDeliveryOrdersPlaced: number;
  revenuePerBevcartHour: number;
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

function formatSimulationTime(elapsedMinutes: number, startingHour: number = 9): string {
  // Round to nearest minute
  const roundedMinutes = Math.floor(elapsedMinutes);
  const totalHours = Math.floor(roundedMinutes / 60);
  const currentHour = (startingHour + totalHours) % 24;
  const minutes = Math.floor(roundedMinutes % 60);
  return `${currentHour.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}`;
}

// Render HH:MM clock for absolute seconds since 7:00 AM baseline
function secondsSince7amToClock(totalSeconds: number): string {
  const total = Math.max(0, Math.floor(totalSeconds));
  const hoursSinceStart = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  // Convert to 24h clock relative to 7:00 AM baseline
  const hour24 = (7 + hoursSinceStart) % 24;
  const period = hour24 >= 12 ? 'PM' : 'AM';
  const hour12 = (hour24 % 12) === 0 ? 12 : (hour24 % 12);
  return `${hour12}:${minutes.toString().padStart(2, '0')} ${period}`;
}

function getPositionOnPath(coordinates: Coordinate[], elapsedTime: number, easing: 'linear' | 'cubic' | 'quart' | 'sine' = 'cubic'): Coordinate | null {
  if (coordinates.length === 0) return null;
  if (coordinates.length === 1) return coordinates[0];
  
  // elapsedTime is in minutes from animation loop, convert to seconds for timestamp matching
  const elapsedSeconds = elapsedTime * 60;
  
  for (let i = 0; i < coordinates.length - 1; i++) {
    const current = coordinates[i];
    const next = coordinates[i + 1];
    if (elapsedSeconds >= current.timestamp && elapsedSeconds <= next.timestamp) {
      const segmentDuration = next.timestamp - current.timestamp;
      const segmentProgress = segmentDuration > 0 ? (elapsedSeconds - current.timestamp) / segmentDuration : 0;
      return interpolatePoint(current, next, segmentProgress, easing);
    }
  }
  if (elapsedSeconds >= coordinates[coordinates.length - 1].timestamp) return coordinates[coordinates.length - 1];
  if (elapsedSeconds < coordinates[0].timestamp) return coordinates[0];
  return null;
}

function calculateVelocity(point1: Coordinate, point2: Coordinate): number {
  // timestamps are in seconds already
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

  // elapsedTime is in minutes from animation loop, convert to seconds for timestamp matching
  const elapsedSeconds = elapsedTime * 60;

  let i = -1;
  // Find the current segment
  for (let j = 0; j < coordinates.length - 1; j++) {
    if (elapsedSeconds >= coordinates[j].timestamp && elapsedSeconds <= coordinates[j + 1].timestamp) {
      i = j;
      break;
    }
  }

  if (i === -1) {
    if (elapsedSeconds < coordinates[0].timestamp) return coordinates[0];
    return coordinates[coordinates.length - 1];
  }
  
  const p1 = coordinates[i];
  const p2 = coordinates[i + 1];
  const p0 = i > 0 ? coordinates[i - 1] : p1;
  const p3 = i < coordinates.length - 2 ? coordinates[i + 2] : p2;

  const segmentDuration = p2.timestamp - p1.timestamp;
  const t = segmentDuration > 0 ? (elapsedSeconds - p1.timestamp) / segmentDuration : 0;

  const lat = catmullRom(p0.latitude, p1.latitude, p2.latitude, p3.latitude, t);
  const lng = catmullRom(p0.longitude, p1.longitude, p2.longitude, p3.longitude, t);

  return {
    golfer_id: p1.golfer_id,
    latitude: lat,
    longitude: lng,
    timestamp: elapsedSeconds,
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
  trackersData, isLoading, center, timestamp, deliveryMetrics, bevCartMetrics, hasRunners, hasBevCart
}: {
  trackersData: EntityData[];
  isLoading: boolean;
  center: [number, number];
  timestamp: string;
  deliveryMetrics?: DeliveryMetrics | null;
  bevCartMetrics?: BevCartMetrics | null;
  hasRunners?: boolean;
  hasBevCart?: boolean;
}) {
  const totalWaypoints = trackersData.reduce((sum, tracker) => sum + tracker.coordinates.length, 0);
  
  return (
    <div style={{ position: 'absolute', top: 0, right: 0, maxWidth: 340, background: '#fff', boxShadow: '0 2px 4px rgba(0,0,0,0.3)', padding: '12px 20px', margin: 20, fontSize: 12, lineHeight: 1.4, color: '#6b6b76', outline: 'none', borderRadius: 4 }}>
      {/* Timestamp Display */}
      <div style={{ textAlign: 'center', marginBottom: 16, padding: '8px 12px', background: '#f8f9fa', borderRadius: 4, border: '1px solid #e9ecef' }}>
        <div style={{ fontSize: 18, fontWeight: 600, color: '#333', fontFamily: 'monospace' }}>
          {timestamp}
        </div>
        <div style={{ fontSize: 10, color: '#666', marginTop: 2 }}>
          Simulation Time
        </div>
      </div>

      {isLoading ? (
        <p>Loading simulation data...</p>
      ) : (
        <>
                     {/* Delivery Runner Metrics */}
           {hasRunners && deliveryMetrics && (
             <div style={{ marginBottom: 16 }}>
               <h4 style={{ margin: '0 0 8px 0', color: '#333', fontSize: 14, fontWeight: 600, textTransform: 'uppercase', borderBottom: '1px solid #e9ecef', paddingBottom: 4 }}>
                 Delivery Metrics
               </h4>
               <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px 12px', fontSize: 13 }}>
                 <div>Order Count: <strong>{(deliveryMetrics as any).totalOrders ?? deliveryMetrics.orderCount ?? 0}</strong></div>
                 <div>Revenue: <strong>${(deliveryMetrics.revenue ?? 0).toFixed(0)}</strong></div>
                 <div>Avg Order Time: <strong>{(deliveryMetrics.avgOrderTime ?? 0).toFixed(1)}m</strong></div>
                 <div>On-Time %: <strong>{((deliveryMetrics as any).onTimePercentage ?? deliveryMetrics.onTimeRate ?? 0).toFixed(1)}%</strong></div>
                 <div>Failed Orders: <strong>{(deliveryMetrics as any).failedDeliveries ?? deliveryMetrics.failedOrderCount ?? 0}</strong></div>
                 <div>Queue Wait: <strong>{(deliveryMetrics.queueWaitAvg ?? 0).toFixed(1)}m</strong></div>
                 <div>Cycle Time (P90): <strong>{(deliveryMetrics.deliveryCycleTimeP90 ?? 0).toFixed(1)}m</strong></div>
                 <div>Orders/Runner-Hr: <strong>{(deliveryMetrics.ordersPerRunnerHour ?? 0).toFixed(1)}</strong></div>
                 <div style={{ gridColumn: 'span 2' }}>Revenue/Runner-Hr: <strong>${(deliveryMetrics.revenuePerRunnerHour ?? 0).toFixed(0)}</strong></div>
               </div>
             </div>
           )}

                     {/* Bev-Cart Metrics */}
           {hasBevCart && bevCartMetrics && (
             <div style={{ marginBottom: 16 }}>
               <h4 style={{ margin: '0 0 8px 0', color: '#333', fontSize: 14, fontWeight: 600, textTransform: 'uppercase', borderBottom: '1px solid #e9ecef', paddingBottom: 4 }}>
                 Bev-Cart Metrics
               </h4>
               <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px 12px', fontSize: 13 }}>
                 <div>Total Orders: <strong>{bevCartMetrics.totalOrders ?? 0}</strong></div>
                 <div>Groups Passed: <strong>{bevCartMetrics.totalGroupsPassed ?? 0}</strong></div>
                 <div>Avg Order Value: <strong>${(bevCartMetrics.avgOrderValue ?? 0).toFixed(0)}</strong></div>
                 <div>Delivery Orders: <strong>{bevCartMetrics.totalDeliveryOrdersPlaced ?? 0}</strong></div>
                 <div style={{ gridColumn: 'span 2' }}>Revenue/Bevcart-Hr: <strong>${(bevCartMetrics.revenuePerBevcartHour ?? 0).toFixed(0)}</strong></div>
               </div>
             </div>
           )}

          {/* Technical Info */}
          <div style={{ borderTop: '1px solid #e9ecef', paddingTop: 8, fontSize: 10, color: '#999' }}>
          </div>
        </>
      )}
    </div>
  );
}

function ColorLegend({
  config
}: {
  config: AppConfig;
}) {
  const legendItems = [
    { type: 'golfer', name: 'Golfer', color: '#007cbf' },
    { type: 'bev-cart', name: 'Beverage Cart', color: '#FF0000' },
    { type: 'runner', name: 'Runner', color: '#FF8B00' }
  ];

  return (
    <div style={{ 
      position: 'absolute', 
      bottom: 20, 
      left: 20, 
      background: 'rgba(255,255,255,0.95)', 
      padding: '12px 16px', 
      borderRadius: 6, 
      boxShadow: '0 2px 4px rgba(0,0,0,0.2)',
      fontSize: 13,
      fontFamily: 'Inter, system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif'
    }}>
      <h4 style={{ margin: '0 0 8px 0', color: '#333', fontSize: 12, fontWeight: 600, textTransform: 'uppercase' }}>
        Entity Types
      </h4>
      {legendItems.map((item) => (
        <div key={item.type} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
          <div style={{
            width: 12,
            height: 12,
            borderRadius: '50%',
            backgroundColor: item.color,
            border: '2px solid #ffffff',
            boxShadow: '0 1px 2px rgba(0,0,0,0.2)'
          }} />
          <span style={{ color: '#333', fontSize: 12 }}>{item.name}</span>
        </div>
      ))}
    </div>
  );
}



const DEFAULT_CONFIG: AppConfig = {
  data: { csvFileName: '/golfer_coordinates.csv', cartPathFileName: '/cart_paths.geojson', coordinatesDir: '/coordinates' },
  animation: { speedMultiplier: 150, defaultMapStyle: 'outdoors-v12', smoothing: { enabled: true, easing: 'catmull-rom', frameRate: 60 } },
  mapStyles: { 
    'satellite-streets': { name: 'Satellite with Streets', url: 'mapbox://styles/mapbox/satellite-streets-v12', description: 'Satellite imagery with roads and labels' },
    'streets-v12': { name: 'Streets', url: 'mapbox://styles/mapbox/streets-v12', description: 'Detailed street map with buildings' },
    'outdoors-v12': { name: 'Outdoors', url: 'mapbox://styles/mapbox/outdoors-v12', description: 'Terrain and outdoor recreation' },
    'light-v11': { name: 'Light', url: 'mapbox://styles/mapbox/light-v11', description: 'Clean, minimal design' },
    'dark-v11': { name: 'Dark', url: 'mapbox://styles/mapbox/dark-v11', description: 'Dark theme with subtle details' },
    'satellite-v9': { name: 'Satellite', url: 'mapbox://styles/mapbox/satellite-v9', description: 'Pure satellite imagery' }
  },
  entityTypes: { 'golfer': { name: 'Golfer', color: '#007cbf', description: 'Golf players' }, 'bev-cart': { name: 'Beverage Cart', color: '#ff6b6b', description: 'Beverage service' }, 'runner': { name: 'Runner', color: '#FF8B00', description: 'Runners on course' }},
  display: { golferTrails: { width: 2, opacity: 1 }, golferMarkers: { radius: 7, strokeWidth: 2, strokeColor: '#ffffff', strokeOpacity: 0.8 } },
  golferColors: DEFAULT_COLORS
};

export default function AnimationView() {
  const [config, setConfig] = useState<AppConfig>(DEFAULT_CONFIG);
  const [currentMapStyle, setCurrentMapStyle] = useState<string>(DEFAULT_CONFIG.animation.defaultMapStyle);
  const [trackersData, setTrackersData] = useState<EntityData[]>([]);
  const [trackerPositions, setTrackerPositions] = useState<{ [key: string]: Coordinate | null }>({});
  const [isLoading, setIsLoading] = useState(true);
  const [pathBounds, setPathBounds] = useState({ center: [0, 0] as [number, number], zoom: 2 });
  const [elapsedTime, setElapsedTime] = useState(0);
  const [displayedTimestamp, setDisplayedTimestamp] = useState<string>('00:00');
  const [originalMinTimestamp, setOriginalMinTimestamp] = useState<number>(0);
  const [animationDuration, setAnimationDuration] = useState<number>(0);
  
  // Timer slider state
  const [isSliderControlled, setIsSliderControlled] = useState<boolean>(false);
  const [sliderTime, setSliderTime] = useState<number>(0);
  const [sliderMaxTime, setSliderMaxTime] = useState<number>(0);
  
  // Metrics loaded from simulation
  const [deliveryMetrics, setDeliveryMetrics] = useState<DeliveryMetrics | null>(null);
  const [bevCartMetrics, setBevCartMetrics] = useState<BevCartMetrics | null>(null);
  const [hasRunners, setHasRunners] = useState<boolean>(false);
  const [hasBevCart, setHasBevCart] = useState<boolean>(false);
  // Simplified - no need for simulation selection since we only have one simulation
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
  // Speed control for smooth animation without resets
  const speedRef = useRef<number>(150);
  const [currentSpeed, setCurrentSpeed] = useState<number>(150);
  const simulatedElapsedRef = useRef<number>(0);
  const lastRealTimeSecRef = useRef<number>(0);
  // Easing selection state
  const [currentEasing, setCurrentEasing] = useState<'linear' | 'cubic' | 'quart' | 'sine' | 'catmull-rom'>('catmull-rom');
  
  // Animation timing refs for smooth transitions
  const animationStartTimeRef = useRef<number>(0);
  const animationOffsetRef = useRef<number>(0);

  useEffect(() => {
    const loadConfig = async () => {
      try {
        const cacheBuster = `?t=${Date.now()}`;
        const configPath = (process.env.REACT_APP_CONFIG_PATH && process.env.REACT_APP_CONFIG_PATH.trim().length > 0)
          ? process.env.REACT_APP_CONFIG_PATH
          : '/config.json';
        const response = await fetch(`${configPath}${cacheBuster}`);
        // Gracefully handle non-OK responses
        const loaded: any = response.ok ? await response.json() : {};
        // Deep-merge with defaults to tolerate course-style configs
        const safeConfig: AppConfig = {
          ...DEFAULT_CONFIG,
          ...(loaded || {}),
          data: { ...DEFAULT_CONFIG.data, ...(loaded?.data || {}) },
          animation: { ...DEFAULT_CONFIG.animation, ...(loaded?.animation || {}) },
          mapStyles: { ...DEFAULT_CONFIG.mapStyles, ...(loaded?.mapStyles || {}) },
          entityTypes: { ...DEFAULT_CONFIG.entityTypes, ...(loaded?.entityTypes || {}) },
          display: { ...DEFAULT_CONFIG.display, ...(loaded?.display || {}) },
          golferColors: Array.isArray(loaded?.golferColors) && loaded.golferColors.length > 0 ? loaded.golferColors : DEFAULT_CONFIG.golferColors,
        };
        setConfig(safeConfig);
        setCurrentMapStyle(safeConfig.animation.defaultMapStyle);
        if (typeof safeConfig.animation?.speedMultiplier === 'number' && isFinite(safeConfig.animation.speedMultiplier)) {
          speedRef.current = safeConfig.animation.speedMultiplier;
          setCurrentSpeed(safeConfig.animation.speedMultiplier);
        }
      } catch (error) {
        // Keep defaults on any error
      }
    };
    loadConfig();
  }, []);

  // Load coordinates directly from the single simulation
  useEffect(() => {
    const loadCoordinates = async () => {
      try {
        const coordinatesDir = (config as any)?.data?.coordinatesDir || DEFAULT_CONFIG.data.coordinatesDir;
        const csvPath = `${coordinatesDir}/coordinates.csv`;
        const csvResp = await fetch(`${csvPath}?t=${Date.now()}`);
        const csvText = await csvResp.text();
        Papa.parse(csvText, {
          header: true,
          skipEmptyLines: true,
          complete: (results) => {
            const rawRows: any[] = results.data as any[];
            // Normalize and filter rows
            const normalizedRows = rawRows
              .map((row: any) => {
                const rawType = String(row.type || '').toLowerCase();
                let normType = rawType;
                if (rawType === 'bev_cart' || rawType === 'beverage_cart' || rawType === 'bevcart') {
                  normType = 'bev-cart';
                }
                if (rawType === '') {
                  // Default heuristics: infer type from id when possible
                  const idLower = String(row.id || row.golfer_id || '').toLowerCase();
                  if (idLower.includes('runner')) normType = 'runner';
                  else if (idLower.includes('golfer')) normType = 'golfer';
                }
                // Drop unsupported utility rows (e.g., timeline)
                if (normType === 'timeline') {
                  return null;
                }
                const latitude = parseFloat(row.latitude);
                const longitude = parseFloat(row.longitude);
                const timestamp = parseFloat(row.timestamp);
                const holeStr = (row.current_hole ?? row.hole);
                const parsedHole = typeof holeStr === 'string' ? parseInt(holeStr, 10) : (Number.isFinite(holeStr) ? Number(holeStr) : undefined);
                return {
                  golfer_id: row.id || row.golfer_id || normType || `entity_${Math.random().toString(36).slice(2)}`,
                  latitude,
                  longitude,
                  timestamp,
                  type: normType || 'golfer',
                  current_hole: Number.isFinite(parsedHole) ? (parsedHole as number) : undefined
                } as Coordinate;
              })
              .filter((coord: Coordinate | null) => !!coord)
              .map((coord) => coord as Coordinate)
              .filter((coord: Coordinate) => !isNaN(coord.latitude) && !isNaN(coord.longitude) && !isNaN(coord.timestamp));

            const trackerGroups = normalizedRows.reduce((acc: { [key: string]: Coordinate[] }, coord) => {
              if (!acc[coord.golfer_id]) acc[coord.golfer_id] = [];
              acc[coord.golfer_id].push(coord);
              return acc;
            }, {});
            // Anchor animation start to the first golfer tee time when available
            const golferTimestamps = normalizedRows
              .filter((c: any) => c.type === 'golfer')
              .map((c: any) => c.timestamp);
            const timestampsForStart = golferTimestamps.length
              ? golferTimestamps
              : normalizedRows.map((c: any) => c.timestamp);
            const minTimestamp = Math.min(...timestampsForStart);
            const maxTimestamp = Math.max(...normalizedRows.map((c: any) => c.timestamp));
            const duration = (maxTimestamp - minTimestamp); // keep in seconds
            setOriginalMinTimestamp(minTimestamp);
            setAnimationDuration(duration / 60); // convert to minutes only for UI display
            
            // Set slider time range: start from first tee time, end 5 hours after last tee time
            setSliderTime(0); // Start at beginning
            setSliderMaxTime((duration + (5 * 3600)) / 60); // Add 5 hours to duration, convert to minutes
            
            // Initialize animation timing refs
            animationStartTimeRef.current = Date.now();
            animationOffsetRef.current = 0;
            
            const trackersArray: EntityData[] = Object.entries(trackerGroups)
              .map(([trackerId, coordinates]) => {
                const sortedCoords = coordinates
                  .sort((a, b) => a.timestamp - b.timestamp)
                  .map(coord => ({ ...coord, timestamp: (coord.timestamp - minTimestamp) })); // keep in seconds, just normalize to start at 0
                let filteredCoords = sortedCoords;
                if (sortedCoords[0]?.type === 'golfer') {
                  // Only show golfers from when they tee off (hole >= 1) until they finish
                  const teeOffIndex = sortedCoords.findIndex(coord => 
                    coord.current_hole !== undefined && coord.current_hole >= 1
                  );
                  const finishIndex = sortedCoords.length - 1 - [...sortedCoords].reverse().findIndex((coord: Coordinate) => 
                    coord.current_hole !== undefined && coord.current_hole >= 1
                  );

                  if (teeOffIndex !== -1 && finishIndex !== -1 && teeOffIndex <= finishIndex) {
                    // Start from tee-off (hole 1+) and end at last hole, apply sampling
                    filteredCoords = sortedCoords.slice(teeOffIndex, finishIndex + 1).filter((_, index) => index % 3 === 0);
                  } else {
                    // This golfer never teed off or has no valid coordinates
                    filteredCoords = [];
                  }
                }
                const entityType = filteredCoords[0]?.type || sortedCoords[0]?.type || 'golfer';
                return { name: trackerId, coordinates: filteredCoords, type: entityType, color: config.entityTypes[entityType]?.color || config.golferColors[0] };
              })
              .filter((e) => e.coordinates.length > 0); // Drop empty trackers entirely
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
    loadCoordinates();
  }, [config]);

  // Load simulation metrics
  useEffect(() => {
    const loadMetrics = async () => {
      try {
        const cacheBuster = `?t=${Date.now()}`;
        const response = await fetch(`${config.data.coordinatesDir}/simulation_metrics.json${cacheBuster}`);
        if (!response.ok) {
          console.log('No simulation metrics found, using defaults');
          return;
        }
        
        const metricsData = await response.json();
        
        setHasRunners(metricsData.hasRunners || false);
        setHasBevCart(metricsData.hasBevCart || false);
        
        if (metricsData.deliveryMetrics) {
          setDeliveryMetrics(metricsData.deliveryMetrics);
        }
        
        if (metricsData.bevCartMetrics) {
          setBevCartMetrics(metricsData.bevCartMetrics);
        }
        
        console.log('Loaded simulation metrics:', metricsData);
      } catch (error) {
        console.error('Error loading simulation metrics:', error);
        // Set defaults if metrics loading fails
        setHasRunners(false);
        setHasBevCart(false);
      }
    };

    if (config.data?.coordinatesDir) {
      loadMetrics();
    }
  }, [config]);

  useEffect(() => {
    if (!styleReady || isLoading || trackersData.length === 0 || sourcesInitializedRef.current) return;
    // Build initial FeatureCollection with first point of each tracker, include color for data-driven styling
    const features: any[] = [];
    trackersData.forEach(tracker => {
      const p = tracker.coordinates[0];
      if (!p) return;
      features.push({
        type: 'Feature',
        properties: { id: tracker.name, color: tracker.color, type: tracker.type },
        geometry: { type: 'Point', coordinates: [p.longitude, p.latitude] }
      });
    });
    trackersGeoJsonRef.current = { type: 'FeatureCollection', features };
    sourcesInitializedRef.current = true;
    setSourcesReady(true);
  }, [isLoading, trackersData, styleReady]);

    // Animation loop with continuous timing (no resets)
  useEffect(() => {
    if (isLoading || trackersData.length === 0) return;
    
    let animationId: number;
    let lastTimestampUpdate = 0; // Track when we last updated timestamp to avoid constant updates
    
    const animate = () => {
      let elapsed: number;
      let elapsedMinutes: number;
      
      if (isSliderControlled) {
        // Use slider time when controlled by user
        elapsedMinutes = sliderTime;
        elapsed = sliderTime * 60; // convert to seconds
      } else {
        // Normal automatic animation with offset for smooth transitions
        const currentTime = Date.now();
        const realElapsed = (currentTime - animationStartTimeRef.current) * speedRef.current / 1000; // seconds
        elapsedMinutes = (realElapsed + animationOffsetRef.current) / 60; // convert to minutes
        
        // Update slider position during automatic playback
        setSliderTime(elapsedMinutes);
      }
      
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
            properties: { id: tracker.name, color: tracker.color, type: tracker.type },
            geometry: { type: 'Point', coordinates: [position.longitude, position.latitude] }
          });
        }
      });
      
      // Update GeoJSON source
      const source = map.getSource('trackers');
      if (source && typeof source.setData === 'function') {
        source.setData({ type: 'FeatureCollection', features });
      }
      
      // Update the displayed timestamp only every few seconds to prevent constant rerenders
      const now = Date.now();
      if (now - lastTimestampUpdate > 2000) { // Update every 2 seconds instead of every frame
        // Display actual clock time based on the current slider position - use same calculation as clock update
        const absoluteSeconds = (originalMinTimestamp || 0) + (sliderTime * 60);
        const newClock = secondsSince7amToClock(absoluteSeconds);
        setDisplayedTimestamp(newClock);
        lastTimestampUpdate = now;
      }
      
      setElapsedTime(elapsedMinutes);
      
      // Only continue animation loop if not slider controlled
      if (!isSliderControlled) {
        animationId = requestAnimationFrame(animate);
      }
    };
    
    if (!isSliderControlled) {
      animationId = requestAnimationFrame(animate);
    } else {
      // For slider control, run once to update positions
      animate();
    }
    
    return () => {
      if (animationId) {
        cancelAnimationFrame(animationId);
      }
    };
  }, [isLoading, trackersData, currentEasing, originalMinTimestamp, isSliderControlled, sliderTime]);

  // Update clock display immediately when slider changes
  useEffect(() => {
    if (originalMinTimestamp !== 0) {
      // Calculate time consistently: slider time is in minutes, convert to seconds and add to original timestamp
      const absoluteSeconds = originalMinTimestamp + (sliderTime * 60);
      const newClock = secondsSince7amToClock(absoluteSeconds);
      setDisplayedTimestamp(newClock);
      
      // Debug logging to understand time calculations
      console.log('Time Debug:', {
        sliderTime,
        sliderTimeMinutes: sliderTime,
        sliderTimeSeconds: sliderTime * 60,
        originalMinTimestamp,
        absoluteSeconds,
        newClock,
        expectedTime: `${Math.floor(sliderTime / 60)}:${Math.floor(sliderTime % 60).toString().padStart(2, '0')}`
      });
    }
  }, [sliderTime, originalMinTimestamp]);

  // Cleanup terrain when component unmounts or map style changes
  useEffect(() => {
    return () => {
      const map = mapRef.current?.getMap?.();
      if (map) {
        try {
          // Remove terrain first to avoid the undefined source error
          if (map.getTerrain()) {
            map.setTerrain(null);
          }
          // Then remove the source if it exists
          if (map.getSource('mapbox-dem')) {
            map.removeSource('mapbox-dem');
          }
        } catch (error) {
          console.warn('Error during terrain cleanup:', error);
        }
      }
    };
  }, [currentMapStyle]); // Also cleanup when map style changes



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
      {/* Animation Control Panel */}
      <div style={{ position: 'absolute', top: 56, left: 10, zIndex: 11, background: 'rgba(255,255,255,0.95)', padding: '12px', borderRadius: 6, boxShadow: '0 2px 4px rgba(0,0,0,0.2)', minWidth: 280 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {/* Timer Slider */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <label htmlFor="timer-slider" style={{ fontSize: 12, color: '#333', minWidth: 70, fontWeight: 600 }}>Timer</label>
              <input
                id="timer-slider"
                type="range"
                min="0"
                max={sliderMaxTime}
                step="0.1"
                value={sliderTime}
                onChange={(e) => {
                  const newTime = parseFloat(e.target.value);
                  setSliderTime(newTime);
                  // When timer changes, update animation timing for smooth transition
                  animationOffsetRef.current = newTime * 60; // convert to seconds
                  animationStartTimeRef.current = Date.now();
                  setIsSliderControlled(false); // Auto-play when timer is changed
                }}
                style={{ flex: 1 }}
              />
              <span style={{ fontSize: 11, color: '#666', minWidth: 30 }}>
                {secondsSince7amToClock(originalMinTimestamp + (sliderTime * 60))}
              </span>
            </div>
          </div>
          
          {/* Speed Control */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <label htmlFor="speed-control" style={{ fontSize: 12, color: '#333', minWidth: 70 }}>Speed</label>
            <input
              id="speed-control"
              type="range"
              min="0.1"
              max="300"
              step="1"
              value={currentSpeed}
              onChange={(e) => {
                const newSpeed = parseFloat(e.target.value);
                speedRef.current = newSpeed;
                setCurrentSpeed(newSpeed);
                // When speed changes, maintain current position for smooth transition
                animationOffsetRef.current = sliderTime * 60; // convert to seconds
                animationStartTimeRef.current = Date.now();
                setIsSliderControlled(false); // Auto-play when speed is changed
              }}
              style={{ flex: 1 }}
            />
            <span style={{ fontSize: 11, color: '#666', minWidth: 30 }}>{currentSpeed.toFixed(1)}x</span>
          </div>
          
          {/* Map Style Selection */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <label htmlFor="map-style-select" style={{ fontSize: 12, color: '#333', minWidth: 70 }}>Map Style</label>
            <select
              id="map-style-select"
              value={currentMapStyle}
              onChange={(e) => setCurrentMapStyle(e.target.value)}
              style={{ flex: 1, padding: '4px', borderRadius: 4, border: '1px solid #ccc', fontSize: 12 }}
            >
              {Object.entries(config.mapStyles).map(([key, style]) => (
                <option key={key} value={key}>
                  {style.name}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>
      <Map
        ref={mapRef}
        initialViewState={getInitialViewState()}
        mapStyle={config.mapStyles[currentMapStyle]?.url || config.mapStyles[config.animation.defaultMapStyle]?.url}
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
          } catch (error) {
            console.warn('Failed to set up terrain:', error);
          }
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
                'circle-radius': ['case',
                  ['==', ['get', 'type'], 'runner'],
                  (config?.display.golferMarkers.radius ?? 9) * 1.125,
                  ['==', ['get', 'type'], 'golfer'],
                  (config?.display.golferMarkers.radius ?? 9) * 0.75,
                  (config?.display.golferMarkers.radius ?? 9)
                ],
                'circle-color': ['get', 'color'],
                'circle-stroke-width': config?.display.golferMarkers.strokeWidth || 1.5,
                'circle-stroke-color': config?.display.golferMarkers.strokeColor || '#ffffff',
                'circle-stroke-opacity': config?.display.golferMarkers.strokeOpacity || 0.8,
                // @ts-ignore - circle-sort-key is a valid Mapbox property for layer ordering but may not be in older type definitions
                'circle-sort-key': ['case',
                  ['==', ['get', 'type'], 'runner'], 3,
                  ['==', ['get', 'type'], 'bev-cart'], 2,
                  1
                ]
              }}
            />
          </Source>
        )}
      </Map>
      <ControlPanel 
        trackersData={trackersData}
        isLoading={isLoading}
        center={pathBounds.center}
        timestamp={displayedTimestamp}
        deliveryMetrics={deliveryMetrics}
        bevCartMetrics={bevCartMetrics}
        hasRunners={hasRunners}
        hasBevCart={hasBevCart}
      />
      <ColorLegend config={config} />
    </div>
  );
}


