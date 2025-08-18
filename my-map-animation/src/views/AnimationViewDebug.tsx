import * as React from 'react';
import {useState, useEffect} from 'react';
import Papa from 'papaparse';

interface Coordinate {
  golfer_id: string;
  latitude: number;
  longitude: number;
  timestamp: number;
  type: string;
  current_hole?: number;
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

interface DebugState {
  loading: boolean;
  manifestLoaded: boolean;
  csvLoaded: boolean;
  coordinates: Coordinate[];
  errors: string[];
  manifest?: SimulationManifest;
  csvPath?: string;
  rawCsvLength?: number;
  validCoordinates?: number;
}

export default function AnimationViewDebug() {
  const [debugInfo, setDebugInfo] = useState<DebugState>({
    loading: true,
    manifestLoaded: false,
    csvLoaded: false,
    coordinates: [],
    errors: []
  });

  useEffect(() => {
    const loadDebugData = async () => {
      const errors: string[] = [];
      let manifest: SimulationManifest | undefined = undefined;
      let coordinates: Coordinate[] = [];

      try {
        // Try to load manifest
        const cacheBuster = `?t=${Date.now()}`;
        const manifestResponse = await fetch(`/coordinates/manifest.json${cacheBuster}`);
        if (manifestResponse.ok) {
          manifest = await manifestResponse.json();
          setDebugInfo((prev: DebugState) => ({ ...prev, manifestLoaded: true, manifest }));
        } else {
          errors.push(`Manifest fetch failed: ${manifestResponse.status} ${manifestResponse.statusText}`);
        }
      } catch (error) {
        errors.push(`Manifest error: ${error}`);
      }

      try {
        // Try to load CSV
        let csvPath = '/coordinates.csv';
        if (manifest && manifest.defaultSimulation) {
          const selected = manifest.simulations.find((s: SimulationInfo) => s.id === manifest!.defaultSimulation);
          if (selected) {
            csvPath = `/coordinates/${selected.filename}`;
          }
        }

        const csvResponse = await fetch(`${csvPath}?t=${Date.now()}`);
        if (csvResponse.ok) {
          const csvText = await csvResponse.text();
          
          // Parse CSV
          Papa.parse(csvText, {
            header: true,
            skipEmptyLines: true,
            complete: (results: Papa.ParseResult<any>) => {
              console.log('CSV Parse Results:', results);
              
              coordinates = results.data
                .map((row: any, index: number): Coordinate => ({
                  golfer_id: row.id || row.golfer_id || row.type || `entity_${index}`,
                  latitude: parseFloat(row.latitude),
                  longitude: parseFloat(row.longitude),
                  timestamp: parseFloat(row.timestamp),
                  type: row.type || 'golfer',
                  current_hole: row.current_hole || row.hole ? parseInt(row.current_hole || row.hole) : undefined
                }))
                .filter((coord: Coordinate) => !isNaN(coord.latitude) && !isNaN(coord.longitude) && !isNaN(coord.timestamp));

              console.log('Parsed coordinates:', coordinates.length, coordinates.slice(0, 5));
              
              setDebugInfo((prev: DebugState) => ({ 
                ...prev, 
                csvLoaded: true, 
                coordinates, 
                errors,
                csvPath,
                rawCsvLength: results.data.length,
                validCoordinates: coordinates.length
              }));
            },
            error: (error: any) => {
              errors.push(`CSV parse error: ${error}`);
              setDebugInfo((prev: DebugState) => ({ ...prev, errors, loading: false }));
            }
          });
        } else {
          errors.push(`CSV fetch failed: ${csvResponse.status} ${csvResponse.statusText}`);
        }
      } catch (error) {
        errors.push(`CSV load error: ${error}`);
      }

      setDebugInfo((prev: DebugState) => ({ ...prev, loading: false, errors }));
    };

    loadDebugData();
  }, []);

  return (
    <div style={{ padding: 20, fontFamily: 'monospace', fontSize: 14 }}>
      <h2>Animation Debug Information</h2>
      
      <h3>Loading Status</h3>
      <p>Loading: {debugInfo.loading ? 'YES' : 'NO'}</p>
      <p>Manifest Loaded: {debugInfo.manifestLoaded ? 'YES' : 'NO'}</p>
      <p>CSV Loaded: {debugInfo.csvLoaded ? 'YES' : 'NO'}</p>
      
      {debugInfo.manifest && (
        <div>
          <h3>Manifest Info</h3>
          <p>Default Simulation: {debugInfo.manifest.defaultSimulation}</p>
          <p>Available Simulations: {debugInfo.manifest.simulations?.length || 0}</p>
          {debugInfo.manifest.simulations && debugInfo.manifest.simulations.map((sim: any) => (
            <div key={sim.id} style={{ marginLeft: 20 }}>
              <p>• {sim.name} ({sim.filename}) - {sim.description}</p>
            </div>
          ))}
        </div>
      )}
      
      {debugInfo.csvPath && (
        <div>
          <h3>CSV Info</h3>
          <p>CSV Path: {debugInfo.csvPath}</p>
          <p>Raw CSV Rows: {debugInfo.rawCsvLength}</p>
          <p>Valid Coordinates: {debugInfo.validCoordinates}</p>
        </div>
      )}
      
      {debugInfo.coordinates.length > 0 && (
        <div>
          <h3>Sample Coordinates</h3>
          {debugInfo.coordinates.slice(0, 5).map((coord: Coordinate, index: number) => (
            <div key={index} style={{ marginLeft: 20, fontSize: 12 }}>
              <p>{coord.golfer_id}: {coord.latitude}, {coord.longitude} @ {coord.timestamp}s ({coord.type})</p>
            </div>
          ))}
          
          <h3>Coordinate Stats</h3>
          <p>Total Points: {debugInfo.coordinates.length}</p>
          <p>Time Range: {Math.min(...debugInfo.coordinates.map(c => c.timestamp))} - {Math.max(...debugInfo.coordinates.map(c => c.timestamp))} seconds</p>
          <p>Lat Range: {Math.min(...debugInfo.coordinates.map(c => c.latitude)).toFixed(6)} - {Math.max(...debugInfo.coordinates.map(c => c.latitude)).toFixed(6)}</p>
          <p>Lng Range: {Math.min(...debugInfo.coordinates.map(c => c.longitude)).toFixed(6)} - {Math.max(...debugInfo.coordinates.map(c => c.longitude)).toFixed(6)}</p>
        </div>
      )}
      
      {debugInfo.errors.length > 0 && (
        <div>
          <h3>Errors</h3>
          {debugInfo.errors.map((error: string, index: number) => (
            <p key={index} style={{ color: 'red' }}>{error}</p>
          ))}
        </div>
      )}
    </div>
  );
}
