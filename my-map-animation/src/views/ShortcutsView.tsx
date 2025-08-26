import * as React from 'react';
import {Map, Source, Layer, NavigationControl, FullscreenControl} from 'react-map-gl/mapbox';
import type {MapMouseEvent} from 'react-map-gl/mapbox';
import 'mapbox-gl/dist/mapbox-gl.css';
import { MAPBOX_TOKEN } from '../mapbox';

type Pair = [number, number];

const pointLayer: any = {
  id: 'nodes',
  type: 'circle',
  paint: {
    'circle-radius': [
      'case',
      ['get', 'pending'], 10,
      ['get', 'selected'], 9,
      8
    ],
    'circle-color': [
      'case',
      ['get', 'pending'], '#ff6b35',
      ['get', 'selected'], '#34d399',
      '#4285f4'
    ],
    'circle-stroke-width': 2,
    'circle-stroke-color': '#ffffff'
  }
};

const labelLayer: any = {
  id: 'node-labels',
  type: 'symbol',
  layout: {
    'text-field': [
      'case',
      ['get', 'pending'], ['get', 'idx'],
      ['get', 'selected'], ['get', 'idx'],
      ''
    ],
    'text-size': 10,
    'text-font': ['DIN Offc Pro Medium', 'Arial Unicode MS Bold'],
    'text-offset': [0, 0],
    'text-anchor': 'center'
  },
  paint: {
    'text-color': '#ffffff',
    'text-halo-color': '#000000',
    'text-halo-width': 1
  }
};

const pathLayer: any = {
  id: 'existing-path',
  type: 'line',
  paint: {
    'line-color': '#ffffff',
    'line-width': 2,
    'line-opacity': 0.8,
    'line-dasharray': [3, 3]
  }
};

const lineLayer: any = {
  id: 'shortcuts',
  type: 'line',
  paint: {
    'line-color': '#ff6b35',
    'line-width': 3
  }
};

export default function ShortcutsView() {
  const [pairs, setPairs] = React.useState<Pair[]>([]);
  const [pending, setPending] = React.useState<number | null>(null);
  const [bbox, setBbox] = React.useState<[number, number, number, number] | null>(null);

  const nodesUrl = React.useMemo(() => process.env.PUBLIC_URL + '/holes_connected.geojson', []);
  const courseUrl = React.useMemo(() => process.env.PUBLIC_URL + '/course_polygon.geojson', []);

  const onClick = (e: MapMouseEvent) => {
    const features = e.features || [];
    const node = features.find((f: any) => f.layer && (f.layer.id === 'nodes' || f.layer.id === 'node-labels'));
    if (!node) return;
    const idx = Number(node.properties?.idx);
    if (!Number.isFinite(idx)) return;
    if (pending == null) {
      setPending(idx);
    } else if (pending !== idx) {
      const a = Math.min(pending, idx);
      const b = Math.max(pending, idx);
      setPairs(prev => (prev.some(p => p[0] === a && p[1] === b) ? prev : [...prev, [a, b]]));
      setPending(null);
    }
  };



  const [nodePositions, setNodePositions] = React.useState<Record<number, [number, number]>>({});
  const [originalGeoJson, setOriginalGeoJson] = React.useState<any>(null);

  // Load node positions to draw lines
  React.useEffect(() => {
    fetch(nodesUrl).then(r => r.json()).then((gj) => {
      const pos: Record<number, [number, number]> = {};
      const coords: [number, number][] = [];
      for (const f of gj.features || []) {
        if (f.geometry?.type === 'Point' && f.properties?.idx != null) {
          const idx = Number(f.properties.idx);
          const [x, y] = f.geometry.coordinates as [number, number];
          pos[idx] = [x, y];
          coords.push([x, y]);
        }
      }
      setNodePositions(pos);
      setOriginalGeoJson(gj);
      if (coords.length) {
        const xs = coords.map(c => c[0]);
        const ys = coords.map(c => c[1]);
        setBbox([Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)]);
      }
    });
  }, [nodesUrl]);

  // Create existing path data (sequential order: 0→1→2→3...→239→0)
  const pathData = React.useMemo(() => {
    if (!nodePositions || Object.keys(nodePositions).length === 0) {
      return { type: 'FeatureCollection', features: [] };
    }
    
    const indices = Object.keys(nodePositions).map(Number).sort((a, b) => a - b);
    const features = [];
    
    // Connect nodes in sequential order: 0→1→2→3...
    for (let i = 0; i < indices.length - 1; i++) {
      const currentIdx = indices[i];
      const nextIdx = indices[i + 1];
      
      // Only connect if they are truly consecutive (e.g., 1→2, 2→3, not 1→5)
      if (nextIdx === currentIdx + 1) {
        const A = nodePositions[currentIdx];
        const B = nodePositions[nextIdx];
        
        if (A && B) {
          features.push({
            type: 'Feature',
            properties: { from: currentIdx, to: nextIdx },
            geometry: { type: 'LineString', coordinates: [A, B] }
          });
        }
      }
    }
    
    // Close the loop: connect last node back to first (if they exist)
    const firstIdx = Math.min(...indices);
    const lastIdx = Math.max(...indices);
    const firstPos = nodePositions[firstIdx];
    const lastPos = nodePositions[lastIdx];
    
    if (firstPos && lastPos && firstIdx !== lastIdx) {
      features.push({
        type: 'Feature',
        properties: { from: lastIdx, to: firstIdx },
        geometry: { type: 'LineString', coordinates: [lastPos, firstPos] }
      });
    }
    
    return { type: 'FeatureCollection', features } as any;
  }, [nodePositions]);

  // Create dynamic nodes data with selection states
  const nodesData = React.useMemo(() => {
    if (!originalGeoJson) return { type: 'FeatureCollection' as const, features: [] };
    
    const selectedIndices = new Set(pairs.flat());
    
    const features = originalGeoJson.features.map((feature: any) => {
      const idx = feature.properties?.idx;
      const isSelected = selectedIndices.has(idx);
      const isPending = pending === idx;
      
      return {
        ...feature,
        properties: {
          ...feature.properties,
          selected: isSelected,
          pending: isPending
        }
      };
    });
    
    return { type: 'FeatureCollection' as const, features };
  }, [originalGeoJson, pairs, pending]);

  // Update line coords when pairs change
  const linesData = React.useMemo(() => {
    const features = pairs.map(([a, b]) => {
      const A = nodePositions[a];
      const B = nodePositions[b];
      return {
        type: 'Feature',
        properties: { a, b },
        geometry: { type: 'LineString', coordinates: (A && B) ? [A, B] : [] }
      } as any;
    });
    return { type: 'FeatureCollection', features } as any;
  }, [pairs, nodePositions]);

  const exportCsv = () => {
    const csv = pairs.map(([a, b]) => `${a}-${b}`).join(',');
    navigator.clipboard.writeText(csv).catch(() => {});
    alert('Copied to clipboard: ' + csv);
  };

  const removeLast = () => setPairs(p => p.slice(0, -1));
  const clearAll = () => setPairs([]);



  return (
    <div style={{ width: '100vw', height: '100vh', position: 'relative' }}>
      <div style={{ position: 'absolute', top: 64, left: 12, zIndex: 10 }}>
        <div style={{ background: 'rgba(255,255,255,0.95)', padding: 8, borderRadius: 6, boxShadow: '0 1px 4px rgba(0,0,0,0.15)' }}>
          <div style={{ fontSize: 12, marginBottom: 4 }}>
            Click two nodes to create shortcuts. White dashed lines show existing path.
            {pending != null && (<span style={{ marginLeft: 6 }}>Pending first: {pending}</span>)}
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <button onClick={exportCsv}>Copy CSV</button>
            <button onClick={removeLast}>Undo</button>
            <button onClick={clearAll}>Clear</button>
          </div>
          {!!pairs.length && (
            <div style={{ marginTop: 6, fontFamily: 'monospace', fontSize: 12 }}>
              {pairs.map(([a, b]) => `${a}-${b}`).join(', ')}
            </div>
          )}
        </div>
      </div>
      <Map
        initialViewState={{ longitude: -84.469878, latitude: 38.027532, zoom: 15 }}
        mapStyle="mapbox://styles/mapbox/satellite-streets-v12"
        mapboxAccessToken={MAPBOX_TOKEN}
        interactiveLayerIds={["nodes", "node-labels"]}
        onClick={onClick}
        style={{ width: '100%', height: '100%' }}
      >
        <NavigationControl position="top-right" />
        <FullscreenControl position="top-right" />

        <Source id="course" type="geojson" data={courseUrl}>
          <Layer id="course-fill" type="fill" paint={{ 'fill-color': '#1e90ff', 'fill-opacity': 0.08 }} />
          <Layer id="course-line" type="line" paint={{ 'line-color': '#1e90ff', 'line-width': 2 }} />
        </Source>

        <Source id="existing-path" type="geojson" data={pathData}>
          <Layer {...pathLayer} />
        </Source>

        <Source id="nodes" type="geojson" data={nodesData}>
          <Layer {...pointLayer} />
          <Layer {...labelLayer} />
        </Source>

        <Source id="shortcuts" type="geojson" data={linesData}>
          <Layer {...lineLayer} />
        </Source>
      </Map>
    </div>
  );
}


