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

interface AppConfig {
  animation: {
    defaultMapStyle: string;
  };
  mapStyles: { [key: string]: MapStyle };
}

const DEFAULT_CONFIG: AppConfig = {
  animation: { defaultMapStyle: 'outdoors' },
  mapStyles: {
    'outdoors': { name: 'Golf Course Terrain Pro', url: 'mapbox://styles/mapbox/outdoors-v12', description: 'Perfect for golf - vivid hillshading shows elevation changes, natural features like water hazards, and soft contrasting colors highlight course terrain' },
    'light': { name: 'Scorecard View', url: 'mapbox://styles/mapbox/light-v11', description: 'Clean, minimal style perfect for course layout overview' },
    'satellite-streets': { name: 'Satellite with Streets', url: 'mapbox://styles/mapbox/satellite-streets-v12', description: 'Satellite imagery with roads and labels' }
  }
};

export default function HeatmapView() {
  const [config, setConfig] = useState<AppConfig>(DEFAULT_CONFIG);
  const [currentMapStyle, setCurrentMapStyle] = useState<string>('outdoors');
  const [holesGeojson, setHolesGeojson] = useState<any | null>(null);
  const [holesMinTime, setHolesMinTime] = useState<number>(0);
  const [holesMaxTime, setHolesMaxTime] = useState<number>(1);
  const [hoverInfo, setHoverInfo] = useState<{ lngLat: [number, number]; hole: number; avg: number; count: number } | null>(null);

  useEffect(() => {
    const loadConfig = async () => {
      try {
        const configPath = (process.env.REACT_APP_CONFIG_PATH && process.env.REACT_APP_CONFIG_PATH.trim().length > 0)
          ? process.env.REACT_APP_CONFIG_PATH
          : '/config.json';
        const resp = await fetch(`${configPath}?t=${Date.now()}`);
        const cfg: AppConfig = await resp.json();
        setConfig(cfg);
        // Prefer Golf Course Terrain Pro (outdoors) style by default for Heatmap view if available
        const preferred = (cfg.mapStyles && cfg.mapStyles['outdoors']) ? 'outdoors' : cfg.animation.defaultMapStyle;
        setCurrentMapStyle(preferred);
      } catch {}
    };
    loadConfig();
  }, []);

  useEffect(() => {
    const loadHoles = async () => {
      try {
        const holesPath = (process.env.REACT_APP_HOLES_PATH && process.env.REACT_APP_HOLES_PATH.trim().length > 0)
          ? process.env.REACT_APP_HOLES_PATH
          : '/hole_delivery_times.geojson';
        const resp = await fetch(`${holesPath}?t=${Date.now()}`);
        if (!resp.ok) return;
        const gj = await resp.json();
        setHolesGeojson(gj);
        try {
          const times: number[] = (gj.features || [])
            .filter((f: any) => f?.properties?.has_data)
            .map((f: any) => Number(f?.properties?.avg_time))
            .filter((x: any) => Number.isFinite(x));
          if (times.length > 0) {
            setHolesMinTime(Math.min(...times));
            setHolesMaxTime(Math.max(...times));
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
        mapStyle={(config.mapStyles[currentMapStyle]?.url) || (config.mapStyles[config.animation.defaultMapStyle]?.url)}
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
              'text-color': '#666666'
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
              'text-size': 32,
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
              'text-size': 14,
              'text-allow-overlap': true,
              'text-justify': 'center',
              'text-anchor': 'center'
            }}
            paint={{ 
              'text-color': [
                'case',
                ['>', ['get', 'avg_time'], (holesMinTime + holesMaxTime) / 2],
                '#ffffff',  // White text for darker red backgrounds
                '#333333'   // Dark text for lighter/white backgrounds
              ] as any
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
    </div>
  );
}


