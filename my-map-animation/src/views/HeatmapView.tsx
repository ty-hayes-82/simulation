import * as React from 'react';
import {useEffect, useState} from 'react';
import {Map, Source, Layer, Popup} from 'react-map-gl/mapbox';
import 'mapbox-gl/dist/mapbox-gl.css';
import '../App.css';
import { MAPBOX_TOKEN } from '../mapbox';

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

const Legend = ({ minTime, maxTime }: { minTime: number, maxTime: number }) => (
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
      <span style={{ fontSize: '12px' }}>{minTime.toFixed(1)}</span>
      <div style={{
        width: '100px',
        height: '20px',
        background: 'linear-gradient(to right, #ffffff, #ff0000)',
        margin: '0 10px',
        border: '1px solid #ccc'
      }} />
      <span style={{ fontSize: '12px' }}>{maxTime.toFixed(1)}</span>
    </div>
  </div>
);

export default function HeatmapView() {
  const [config, setConfig] = useState<AppConfig>(DEFAULT_CONFIG);
  const [currentMapStyle, setCurrentMapStyle] = useState<string>('outdoors');
  const [holesGeojson, setHolesGeojson] = useState<any | null>(null);
  const [holesMinTime, setHolesMinTime] = useState<number>(0);
  const [holesMaxTime, setHolesMaxTime] = useState<number>(1);
  const [hoverInfo, setHoverInfo] = useState<{ lngLat: [number, number]; hole: number; avg: number; count: number } | null>(null);
  const [deliveryMetrics, setDeliveryMetrics] = useState<DeliveryMetrics | null>(null);
  const [bevCartMetrics, setBevCartMetrics] = useState<BevCartMetrics | null>(null);
  const [hasRunners, setHasRunners] = useState<boolean>(false);
  const [hasBevCart, setHasBevCart] = useState<boolean>(false);

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
        const response = await fetch(`${coordinatesDir}/simulation_metrics.json${cacheBuster}`);
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
  }, [config]);

  useEffect(() => {
    const loadHoles = async () => {
      const cacheBuster = `?t=${Date.now()}`;
      const primaryPath = (process.env.REACT_APP_HOLES_PATH && process.env.REACT_APP_HOLES_PATH.trim().length > 0)
        ? process.env.REACT_APP_HOLES_PATH
        : '/hole_delivery_times.geojson';
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
        try {
          const times: number[] = (gj.features || [])
            .filter((f: any) => f?.properties?.has_data)
            .map((f: any) => Number(f?.properties?.avg_time))
            .filter((x: any) => Number.isFinite(x));
          if (times.length > 0) {
            setHolesMinTime(Math.min(...times));
            setHolesMaxTime(Math.max(...times));
          } else {
            setHolesMinTime(0);
            setHolesMaxTime(1);
          }
        } catch {}
      } catch {}
    };
    loadHoles();
  }, []);

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
        initialViewState={{ latitude: 34.0405, longitude: -84.5955, zoom: 14 }}
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
                  ['interpolate', ['linear'], ['get', 'avg_time'], holesMinTime, '#ffffff', holesMaxTime, '#ff0000'],
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
      </div>
      {holesGeojson && <Legend minTime={holesMinTime} maxTime={holesMaxTime} />}
    </div>
  );
}


