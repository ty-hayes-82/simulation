import React from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { SegmentedControl } from '@radix-ui/themes';

export default function ViewSwitcher() {
  const navigate = useNavigate();
  const location = useLocation();

  const currentValue = () => {
    if (location.pathname.startsWith('/heatmap')) return 'heatmap';
    if (location.pathname.startsWith('/shortcuts')) return 'shortcuts';
    return 'animation';
  };

  const handleValueChange = (value: string) => {
    navigate(`/${value}`);
  };

  return (
    <div style={{ position: 'absolute', top: 20, left: '50%', transform: 'translateX(-50%)', zIndex: 20 }}>
      <SegmentedControl.Root value={currentValue()} onValueChange={handleValueChange}>
        <SegmentedControl.Item value="animation">Animation</SegmentedControl.Item>
        <SegmentedControl.Item value="heatmap">Heatmap</SegmentedControl.Item>
      </SegmentedControl.Root>
    </div>
  );
}
