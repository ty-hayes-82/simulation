import * as React from 'react';
import { Route, Routes, NavLink } from 'react-router-dom';
import AnimationView from './views/AnimationView';
import HeatmapView from './views/HeatmapView';

export default function App() {
  return (
    <div style={{ width: '100vw', height: '100vh' }}>
      <div style={{ position: 'absolute', top: 0, left: 0, zIndex: 10, background: 'rgba(255,255,255,0.92)', padding: '6px 10px', margin: 10, borderRadius: 6, boxShadow: '0 2px 4px rgba(0,0,0,0.2)' }}>
        <nav style={{ display: 'flex', gap: 12, alignItems: 'center', fontFamily: 'Inter, system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif', fontSize: 13, lineHeight: 1.4 }}>
          <NavLink
            to="/animation"
            style={(args: { isActive: boolean }) => ({
              fontWeight: 600,
              color: args.isActive ? '#1f4d8f' : '#2e2e2e',
              textDecoration: 'none'
            })}
          >
            Animation
          </NavLink>
          <NavLink
            to="/heatmap"
            style={(args: { isActive: boolean }) => ({
              fontWeight: 600,
              color: args.isActive ? '#1f4d8f' : '#2e2e2e',
              textDecoration: 'none'
            })}
          >
            Heatmap
          </NavLink>
        </nav>
      </div>
      <Routes>
        <Route path="/" element={<AnimationView />} />
        <Route path="/animation" element={<AnimationView />} />
        <Route path="/heatmap" element={<HeatmapView />} />
      </Routes>
    </div>
  );
}