import * as React from 'react';
import { Route, Routes, NavLink, useLocation } from 'react-router-dom';
import { Theme, Card, Flex, Text } from '@radix-ui/themes';
import AnimationView from './views/AnimationView';
import AnimationViewDebug from './views/AnimationViewDebug';
import HeatmapView from './views/HeatmapView';
import { SimulationProvider } from './context/SimulationContext';
import TopBarControls from './components/TopBarControls';
import SimulationTable from './components/SimulationTable';
import ViewSwitcher from './components/ViewSwitcher';
import SimulationMatrix from './components/SimulationMatrix';
import { useSimulation } from './context/SimulationContext';

function SimulationTimePanel() {
  const { baselineTimestampSeconds, timelineMinutes } = useSimulation();
  const toClock = (totalSeconds: number): string => {
    if (!Number.isFinite(totalSeconds) || totalSeconds <= 0) return '--:--';
    const total = Math.max(0, Math.floor(totalSeconds));
    const hoursSinceStart = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const hour24 = (7 + hoursSinceStart) % 24;
    const period = hour24 >= 12 ? 'PM' : 'AM';
    const hour12 = (hour24 % 12) === 0 ? 12 : (hour24 % 12);
    return `${hour12}:${minutes.toString().padStart(2, '0')} ${period}`;
  };
  return (
    <div style={{ position: 'absolute', top: 64, left: '50%', transform: 'translateX(-50%)', zIndex: 20 }}>
      <div style={{ background: 'rgba(255,255,255,0.9)', padding: '8px 12px', borderRadius: 6, textAlign: 'center', border: '1px solid rgba(0,0,0,0.08)' }}>
        <div style={{ fontSize: 18, fontWeight: 600, color: '#333', fontFamily: 'monospace' }}>
          {toClock(baselineTimestampSeconds + timelineMinutes * 60)}
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const location = useLocation();
  const isHeatmap = (location.pathname || '').toLowerCase().includes('/heatmap');
  return (
    <Theme accentColor="blue" grayColor="slate" radius="medium" scaling="100%">
      <SimulationProvider>
        <div style={{ width: '100vw', height: '100vh' }}>
          <ViewSwitcher />
          {!isHeatmap && <SimulationTimePanel />}
          <TopBarControls />
          <SimulationMatrix />
          <Routes>
            <Route path="/" element={<AnimationView />} />
            <Route path="/animation" element={<AnimationView />} />
            <Route path="/debug" element={<AnimationViewDebug />} />
            <Route path="/heatmap" element={<HeatmapView />} />
            <Route path="/table" element={
              <div style={{ padding: '80px 20px 20px', height: '100vh', overflow: 'auto' }}>
                <SimulationTable />
              </div>
            } />
          </Routes>
        </div>
      </SimulationProvider>
    </Theme>
  );
}