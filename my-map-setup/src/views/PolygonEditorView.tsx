import * as React from 'react';
import {Map, Source, Layer, NavigationControl, FullscreenControl} from 'react-map-gl/mapbox';
import 'mapbox-gl/dist/mapbox-gl.css';
import '@mapbox/mapbox-gl-draw/dist/mapbox-gl-draw.css';
import { MAPBOX_TOKEN } from '../mapbox';
import { useCourse } from '../context/CourseContext';

const polygonLayer: any = {
  id: 'holes-fill',
  type: 'fill',
  paint: {
    'fill-color': '#34d399',
    'fill-opacity': 0.2,
  },
};

const polygonLineLayer: any = {
  id: 'holes-line',
  type: 'line',
  paint: {
    'line-color': '#34d399',
    'line-width': 2,
  },
};

export default function PolygonEditorView() {
  const { selectedCourse } = useCourse();
  const [geoJson, setGeoJson] = React.useState(null);

  React.useEffect(() => {
    if (selectedCourse) {
      const url = `/${selectedCourse.id}/holes_geofenced.geojson`;
      fetch(url)
        .then(res => res.json())
        .then(data => setGeoJson(data))
        .catch(() => setGeoJson(null));
    } else {
      setGeoJson(null);
    }
  }, [selectedCourse]);

  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <Map
        initialViewState={{ longitude: -78.36, latitude: 38.01, zoom: 14 }}
        mapStyle="mapbox://styles/mapbox/satellite-streets-v12"
        mapboxAccessToken={MAPBOX_TOKEN}
        style={{ width: '100%', height: '100%' }}
      >
        <NavigationControl position="top-right" />
        <FullscreenControl position="top-right" />

        {geoJson && (
          <Source id="holes" type="geojson" data={geoJson}>
            <Layer {...polygonLayer} />
            <Layer {...polygonLineLayer} />
          </Source>
        )}
      </Map>
    </div>
  );
}
