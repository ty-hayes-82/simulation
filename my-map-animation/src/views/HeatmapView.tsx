import * as React from 'react';
import {useEffect, useState} from 'react';
import {Map, Source, Layer, Popup} from 'react-map-gl/mapbox';
import 'mapbox-gl/dist/mapbox-gl.css';
import '../App.css';
import { MAPBOX_TOKEN } from '../mapbox';
import { useSimulation } from '../context/SimulationContext';
import DeliveryMetricsGrid from '../components/DeliveryMetricsGrid';

interface MapStyle {
  name: string;
  url: string;
  description: string;
}

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
  runnerUtilizationPct?: number;
}

interface BevCartMetrics {
  totalOrders: number;
  totalGroupsPassed: number;
  avgOrderValue: number;
  totalDeliveryOrdersPlaced: number;
  revenuePerBevcartHour: number;
}

interface AppConfig {
  data?: {
    coordinatesDir?: string;
  };
  animation: {
    defaultMapStyle: string;
  };
  mapStyles: { [key: string]: MapStyle };
}

const DEFAULT_CONFIG: AppConfig = {
  data: { coordinatesDir: '/coordinates' },
  animation: { defaultMapStyle: 'outdoors' },
  mapStyles: {
    'outdoors': { name: 'Golf Course Terrain Pro', url: 'mapbox://styles/mapbox/outdoors-v12', description: 'Perfect for golf - vivid hillshading shows elevation changes, natural features like water hazards, and soft contrasting colors highlight course terrain' },
    'light': { name: 'Scorecard View', url: 'mapbox://styles/mapbox/light-v11', description: 'Clean, minimal style perfect for course layout overview' },
    'satellite-streets': { name: 'Satellite with Streets', url: 'mapbox://styles/mapbox/satellite-streets-v12', description: 'Satellite imagery with roads and labels' }
  }
};

const Legend = () => (
  <div style={{
    position: 'absolute',
    bottom: 20,
    right: 20,
    background: 'rgba(255, 255, 255, 0.9)',
    padding: '10px',
    borderRadius: '5px',
    boxShadow: '0 0 10px rgba(0, 0, 0, 0.2)',
    zIndex: 10
  }}>
    <div style={{ marginBottom: '5px', fontWeight: 'bold', fontSize: '12px' }}>Avg Delivery Time (min)</div>
    <div style={{ display: 'flex', alignItems: 'center' }}>
      <span style={{ fontSize: '12px' }}>0</span>
      <div style={{
        width: '100px',
        height: '20px',
        background: 'linear-gradient(to right, #ffffff, #ff0000)',
        margin: '0 10px',
        border: '1px solid #ccc'
      }} />
      <span style={{ fontSize: '12px' }}>10+</span>
    </div>
  </div>
);

export default function HeatmapView() {
  const { selectedSim, viewState, setViewState } = useSimulation();
  const [config, setConfig] = useState<AppConfig>(DEFAULT_CONFIG);
  const [currentMapStyle, setCurrentMapStyle] = useState<string>('outdoors');
  const [holesGeojson, setHolesGeojson] = useState<any | null>(null);

  const [hoverInfo, setHoverInfo] = useState<{ lngLat: [number, number]; hole: number; avg: number; count: number } | null>(null);
  const [deliveryMetrics, setDeliveryMetrics] = useState<DeliveryMetrics | null>(null);
  const [bevCartMetrics, setBevCartMetrics] = useState<BevCartMetrics | null>(null);
  const [hasRunners, setHasRunners] = useState<boolean>(false);
  const [hasBevCart, setHasBevCart] = useState<boolean>(false);
  // Derived fallbacks when not present in metrics JSON
  const [derivedRevenue, setDerivedRevenue] = useState<number | null>(null);
  const [derivedUtilPct, setDerivedUtilPct] = useState<number | null>(null);

  useEffect(() => {
    const loadConfig = async () => {
      try {
        const configPath = (process.env.REACT_APP_CONFIG_PATH && process.env.REACT_APP_CONFIG_PATH.trim().length > 0)
          ? process.env.REACT_APP_CONFIG_PATH
          : '/config.json';
        const resp = await fetch(`${configPath}?t=${Date.now()}`);
        const cfg: Partial<AppConfig> = await resp.json();
        // Merge with defaults to ensure required keys exist (match AnimationView tolerance)
        const merged: AppConfig = {
          ...DEFAULT_CONFIG,
          ...(cfg || {}),
          data: { ...DEFAULT_CONFIG.data, ...(cfg?.data || {}) },
          animation: { ...DEFAULT_CONFIG.animation, ...(cfg?.animation || {}) },
          mapStyles: { ...DEFAULT_CONFIG.mapStyles, ...(cfg?.mapStyles || {}) }
        } as AppConfig;
        setConfig(merged);
        // Prefer Golf Course Terrain Pro (outdoors) if available, otherwise use configured default, finally fallback to DEFAULT_CONFIG
        const preferred = (merged.mapStyles?.['outdoors'])
          ? 'outdoors'
          : (merged.animation?.defaultMapStyle || DEFAULT_CONFIG.animation.defaultMapStyle);
        setCurrentMapStyle(preferred);
      } catch {}
    };
    loadConfig();
  }, []);

  // Load simulation metrics to match AnimationView
  useEffect(() => {
    const loadMetrics = async () => {
      try {
        const cacheBuster = `?t=${Date.now()}`;
        const coordinatesDir = (config?.data?.coordinatesDir) || '/coordinates';
        const metricsFile = (selectedSim?.metricsFilename) || 'simulation_metrics.json';
        const response = await fetch(`${coordinatesDir}/${metricsFile}${cacheBuster}`);
        if (!response.ok) {
          return;
        }
        const metricsData = await response.json();
        setHasRunners(Boolean(metricsData.hasRunners));
        setHasBevCart(Boolean(metricsData.hasBevCart));
        if (metricsData.deliveryMetrics) setDeliveryMetrics(metricsData.deliveryMetrics);
        if (metricsData.bevCartMetrics) setBevCartMetrics(metricsData.bevCartMetrics);
      } catch {}
    };
    loadMetrics();
  }, [config, selectedSim?.metricsFilename]);

  useEffect(() => {
    const loadHoles = async () => {
      const cacheBuster = `?t=${Date.now()}`;
      let primaryPath = (process.env.REACT_APP_HOLES_PATH && process.env.REACT_APP_HOLES_PATH.trim().length > 0)
        ? process.env.REACT_APP_HOLES_PATH
        : '/hole_delivery_times.geojson';
      // If per-sim geojson exists, prefer it
      if (selectedSim?.holeDeliveryGeojson) {
        primaryPath = `/coordinates/${selectedSim.holeDeliveryGeojson}`;
      }
      const fallbackPath = '/hole_delivery_times_debug.geojson';
      try {
        // Try primary first
        let resp = await fetch(`${primaryPath}${cacheBuster}`);
        let gj: any | null = null;
        if (resp.ok) {
          gj = await resp.json();
        }
        // If primary failed or has no data, try fallback
        const hasAnyData = (gj?.features || []).some((f: any) => Boolean(f?.properties?.has_data));
        if (!resp.ok || !hasAnyData) {
          const fb = await fetch(`${fallbackPath}${cacheBuster}`);
          if (fb.ok) {
            gj = await fb.json();
          }
        }
        if (!gj) return;
        setHolesGeojson(gj);
      } catch {}
    };
    loadHoles();
  }, [selectedSim?.holeDeliveryGeojson, selectedSim?.id]);

  // Also load CSV for derived metrics calculation (reuses AnimationView path conventions)
  useEffect(() => {
    const loadCsvForDerived = async () => {
      try {
        const coordinatesDir = (config?.data?.coordinatesDir) || '/coordinates';
        const csvFile = selectedSim?.filename || 'coordinates.csv';
        const csvResp = await fetch(`${coordinatesDir}/${csvFile}?t=${Date.now()}`);
        if (!csvResp.ok) return;
        const csvText = await csvResp.text();
        const rows: any[] = [];
        try {
          const PapaAny: any = (window as any).Papa;
          if (PapaAny && typeof PapaAny.parse === 'function') {
            const result = PapaAny.parse(csvText, { header: true, skipEmptyLines: true });
            rows.push(...(result.data || []));
          }
        } catch {}
        // Fallback simplistic parser if Papa not on window
        if (rows.length === 0) {
          const lines = csvText.split(/\r?\n/).filter(Boolean);
          const header = (lines.shift() || '').split(',');
          for (const line of lines) {
            const vals = line.split(',');
            const obj: any = {};
            header.forEach((h, i) => obj[h.trim()] = vals[i]);
            rows.push(obj);
          }
        }
        // Derived revenue: maximum cumulative total_revenue across rows
        let maxRevenue = 0;
        for (const row of rows) {
          const val = parseFloat(row.total_revenue ?? row.totalRevenue ?? '');
          if (Number.isFinite(val)) maxRevenue = Math.max(maxRevenue, val);
        }
        setDerivedRevenue(Number.isFinite(maxRevenue) ? maxRevenue : 0);

        // Derived utilization from runner tracks
        const grouped: Record<string, any[]> = {};
        for (const r of rows) {
          const id = String(r.id || '').trim();
          if (!id) continue;
          if (!grouped[id]) grouped[id] = [];
          grouped[id].push(r);
        }
        const isRunner = (id: string, type: string) => (String(type || '').toLowerCase() === 'runner') || id.toLowerCase().includes('runner');
        const toNum = (x: any) => parseFloat(x);
        const toCoord = (r: any) => ({
          latitude: toNum(r.latitude),
          longitude: toNum(r.longitude),
          timestamp: toNum(r.timestamp)
        });
        let totalShiftSeconds = 0;
        let movingSeconds = 0;
        for (const [id, arr] of Object.entries(grouped)) {
          const type = arr[0]?.type;
          if (!isRunner(id, type)) continue;
          const coords = arr.map(toCoord).filter(c => Number.isFinite(c.latitude) && Number.isFinite(c.longitude) && Number.isFinite(c.timestamp)).sort((a, b) => a.timestamp - b.timestamp);
          if (coords.length < 2) continue;
          totalShiftSeconds += Math.max(0, coords[coords.length - 1].timestamp - coords[0].timestamp);
          for (let i = 0; i < coords.length - 1; i++) {
            const p1 = coords[i];
            const p2 = coords[i + 1];
            const timeDiff = Math.max(0, p2.timestamp - p1.timestamp);
            if (timeDiff <= 0) continue;
            const lat1 = p1.latitude * Math.PI / 180;
            const lat2 = p2.latitude * Math.PI / 180;
            const dLat = (p2.latitude - p1.latitude) * Math.PI / 180;
            const dLng = (p2.longitude - p1.longitude) * Math.PI / 180;
            const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLng / 2) ** 2;
            const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
            const distance = 6371000 * c;
            if (distance >= 2) movingSeconds += timeDiff;
          }
        }
        const util = totalShiftSeconds > 0 ? (movingSeconds / totalShiftSeconds) * 100 : 0;
        setDerivedUtilPct(util);
      } catch {}
    };
    loadCsvForDerived();
  }, [config?.data?.coordinatesDir, selectedSim?.filename]);

  // Merge derived values into displayed metrics
  useEffect(() => {
    if (!hasRunners) return;
    if (derivedRevenue == null && derivedUtilPct == null) return;
    setDeliveryMetrics((prev) => {
      const dm: any = { ...(prev || {}) };
      const existingRevenue = Number(dm.revenue ?? 0);
      if (!(Number.isFinite(existingRevenue) && existingRevenue > 0) && Number.isFinite(derivedRevenue)) {
        dm.revenue = derivedRevenue ?? 0;
      }
      if (Number.isFinite(derivedUtilPct)) dm.runnerUtilizationPct = derivedUtilPct;
      return dm as DeliveryMetrics;
    });
  }, [derivedRevenue, derivedUtilPct, hasRunners]);

  return (
    <div style={{ width: '100vw', height: '100vh' }}>
      {/* Map style selector */}
      <div style={{ position: 'absolute', top: 56, left: 10, zIndex: 11, background: 'rgba(255,255,255,0.95)', padding: '8px 10px', borderRadius: 6, boxShadow: '0 2px 4px rgba(0,0,0,0.2)' }}>
        <label htmlFor="basemap-select" style={{ fontSize: 12, color: '#333', marginRight: 8 }}>Base map:</label>
        <select
          id="basemap-select"
          value={currentMapStyle}
          onChange={(e) => setCurrentMapStyle(e.target.value)}
          style={{ fontSize: 12, padding: '4px 6px' }}
        >
          {Object.entries(config.mapStyles || {}).map(([key, style]) => (
            <option key={key} value={key}>{style?.name || key}</option>
          ))}
        </select>
      </div>
      <Map
        initialViewState={viewState}
        viewState={viewState as any}
        onMove={evt => setViewState(evt.viewState)}
        mapStyle={
          config.mapStyles?.[currentMapStyle]?.url
          || config.mapStyles?.[config.animation?.defaultMapStyle || 'outdoors']?.url
          || DEFAULT_CONFIG.mapStyles['outdoors'].url
        }
        mapboxAccessToken={MAPBOX_TOKEN}
        interactiveLayerIds={["holes-fill"] as any}
        onMouseMove={(evt: any) => {
          const f = evt.features && evt.features.find((x: any) => x.layer && x.layer.id === 'holes-fill');
          if (f && f.properties && f.properties.has_data) {
            const hole = Number(f.properties.hole);
            const avg = Number(f.properties.avg_time);
            const count = Number(f.properties.count);
            const { lng, lat } = evt.lngLat || {};
            if (Number.isFinite(hole) && Number.isFinite(avg) && Number.isFinite(lng) && Number.isFinite(lat)) {
              setHoverInfo({ lngLat: [lng, lat], hole, avg, count });
            }
          } else {
            setHoverInfo(null);
          }
        }}
        onMouseLeave={() => setHoverInfo(null)}
      >
        {holesGeojson && (
          <Source id="holes" type="geojson" data={holesGeojson}>
            <Layer
              id="holes-fill"
              type="fill"
              paint={{
                'fill-color': [
                  'case',
                  ['==', ['get', 'has_data'], true],
                  [
                    'interpolate', ['linear'],
                    // Clamp avg_time to [0,10] for consistent color scaling
                    ['max', 0, ['min', 10, ['to-number', ['get', 'avg_time']]]],
                    0, '#ffffff',
                    2, '#ffe6e6',
                    4, '#ffcccc',
                    6, '#ff6666',
                    8, '#ff3333',
                    10, '#ff0000'
                  ],
                  'rgba(0,0,0,0)'
                ],
                'fill-opacity': [
                  'case',
                  ['==', ['get', 'has_data'], true], 0.6,
                  0.2
                ],
                'fill-outline-color': '#333333'
              }}
              layout={{ 'visibility': 'visible' }}
            />
            <Layer
              id="holes-no-data"
              type="line"
              filter={['==', ['get', 'has_data'], false] as any}
              paint={{ 'line-color': '#aaaaaa', 'line-width': 1, 'line-dasharray': [1, 2] }}
              layout={{ 'visibility': 'visible' }}
            />
          </Source>
        )}
        {holesGeojson && (
          <Layer
            id="holes-circle-border"
            source="holes"
            type="symbol"
            filter={['>', ['get', 'count'], 0] as any}
            layout={{
              'text-field': '●',
              'text-size': 36,
              'text-allow-overlap': true,
              'text-justify': 'center',
              'text-anchor': 'center'
            }}
            paint={{ 
              'text-color': '#333333'
            }}
          />
        )}
        {holesGeojson && (
          <Layer
            id="holes-circles"
            source="holes"
            type="symbol"
            filter={['>', ['get', 'count'], 0] as any}
            layout={{
              'text-field': '●',
              'text-size': 34,
              'text-allow-overlap': true,
              'text-justify': 'center',
              'text-anchor': 'center'
            }}
            paint={{ 
              'text-color': '#ffffff'
            }}
          />
        )}
        {holesGeojson && (
          <Layer
            id="holes-labels"
            source="holes"
            type="symbol"
            filter={['>', ['get', 'count'], 0] as any}
            layout={{
              'text-field': ['to-string', ['get', 'count']] as any,
              'text-size': 11,
              'text-allow-overlap': true,
              'text-justify': 'center',
              'text-anchor': 'center'
            }}
            paint={{ 
              'text-color': '#000000'
            }}
          />
        )}
        {hoverInfo && (
          <Popup longitude={hoverInfo.lngLat[0]} latitude={hoverInfo.lngLat[1]} closeButton={false} closeOnClick={false} anchor="top" style={{ pointerEvents: 'none' }}>
            <div style={{ fontSize: 12 }}>
              <div><strong>Hole {hoverInfo.hole}</strong></div>
              <div>Avg drive: {hoverInfo.avg.toFixed(1)} min</div>
              <div>Orders: {hoverInfo.count}</div>
            </div>
          </Popup>
        )}
      </Map>
      {/* Metrics panel - mirrored from AnimationView ControlPanel (sizing and layout) */}
      <div style={{ position: 'absolute', top: 0, right: 0, maxWidth: 340, background: '#fff', boxShadow: '0 2px 4px rgba(0,0,0,0.3)', padding: '12px 20px', margin: 20, fontSize: 12, lineHeight: 1.4, color: '#6b6b76', outline: 'none', borderRadius: 4 }}>
        {/* Delivery Runner Metrics */}
        {hasRunners && deliveryMetrics && (
          <DeliveryMetricsGrid deliveryMetrics={deliveryMetrics} />
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
      </div>
      {holesGeojson && <Legend />}
    </div>
  );
}


