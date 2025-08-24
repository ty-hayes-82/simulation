import React, { useEffect, useMemo, useState } from 'react';
import { Flex, Text, Select, Card, Slider, Separator } from '@radix-ui/themes';
import { useSimulation } from '../context/SimulationContext';
import { useLocation } from 'react-router-dom';
import { distinctRunnerCounts, distinctOrderCounts } from '../lib/manifest';

export default function TopBarControls() {
  const { manifest, selectedSim, filters, setFilters, timelineMinutes, setTimelineMinutes, timelineMaxMinutes, baselineTimestampSeconds, isSliderControlled, setIsSliderControlled } = useSimulation();
  const [animationSpeed, setAnimationSpeed] = useState([1]);
  const location = useLocation();
  const isHeatmap = (location.pathname || '').toLowerCase().includes('/heatmap');
  const runnerOptions = useMemo(() => distinctRunnerCounts(manifest || { simulations: [] }), [manifest]);
  const orderOptions = useMemo(() => distinctOrderCounts(manifest || { simulations: [] }), [manifest]);

  const currentRunnersValue = useMemo(() => {
    const val = filters.runners ?? (runnerOptions[0] || 1);
    return runnerOptions.includes(val) ? val : (runnerOptions[0] || 1);
  }, [filters.runners, runnerOptions]);

  const currentOrdersValue = useMemo(() => {
    const fallback = orderOptions[0] ?? 1;
    const val = filters.orders ?? fallback;
    return orderOptions.includes(val) ? val : fallback;
  }, [filters.orders, orderOptions]);

  const secondsSince7amToClock = (totalSeconds: number): string => {
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
    <Card style={{ position: 'absolute', top: 20, left: 20, zIndex: 20, background: 'rgba(255,255,255,0.95)', minWidth: '320px' }}>
      <Flex direction="column" gap="3" p="4">
        {/* Simulation Controls */}
        <Flex direction="column" gap="3">
          <Text size="3" weight="bold">Simulation Controls</Text>
          
          <Flex align="center" gap="2">
            <Text size="2" weight="medium" style={{ minWidth: '60px' }}>Runners:</Text>
            <Select.Root 
              value={currentRunnersValue.toString()} 
              onValueChange={(value) => setFilters({ ...filters, runners: Number(value) })}
            >
              <Select.Trigger style={{ flex: 1 }} />
              <Select.Content>
                {runnerOptions.map(count => (
                  <Select.Item key={count} value={count.toString()}>
                    {count} {count === 1 ? 'Runner' : 'Runners'}
                  </Select.Item>
                ))}
              </Select.Content>
            </Select.Root>
          </Flex>

          <Flex align="center" gap="2">
            <Text size="2" weight="medium" style={{ minWidth: '60px' }}>Orders:</Text>
            <Select.Root 
              value={currentOrdersValue.toString()} 
              onValueChange={(value) => setFilters({ ...filters, orders: Number(value) })}
            >
              <Select.Trigger style={{ flex: 1 }} />
              <Select.Content>
                {orderOptions.map(count => (
                  <Select.Item key={count} value={count.toString()}>
                    {count} Orders
                  </Select.Item>
                ))}
              </Select.Content>
            </Select.Root>
          </Flex>

          {!isHeatmap && (
            <>
              <Separator size="2" />
              <Flex direction="column" gap="2">
                <Text size="2" weight="medium">Animation Speed: {animationSpeed[0].toFixed(1)}x</Text>
                <Flex align="center" gap="2">
                  <Text size="1" color="gray">0.5x</Text>
                  <Slider
                    value={animationSpeed}
                    onValueChange={setAnimationSpeed}
                    min={0.5}
                    max={3}
                    step={0.1}
                    style={{ flex: 1 }}
                  />
                  <Text size="1" color="gray">3x</Text>
                </Flex>
              </Flex>

              <Separator size="2" />

              {/* Time Slider */}
              <Flex direction="column" gap="2">
                <Text size="2" weight="medium">Time: {secondsSince7amToClock(baselineTimestampSeconds + timelineMinutes * 60)}</Text>
                <Flex align="center" gap="2">
                  <Text size="1" color="gray">{secondsSince7amToClock(baselineTimestampSeconds)}</Text>
                  <Slider
                    value={[timelineMinutes]}
                    onValueChange={(val) => {
                      setIsSliderControlled(true);
                      setTimelineMinutes(val[0]);
                    }}
                    onValueCommit={(val) => {
                      // User finished scrubbing; keep the time and signal resume
                      setTimelineMinutes(val[0]);
                      setIsSliderControlled(false);
                    }}
                    min={0}
                    max={Math.max(0, timelineMaxMinutes)}
                    step={0.1}
                    style={{ flex: 1 }}
                  />
                  <Text size="1" color="gray">{secondsSince7amToClock(baselineTimestampSeconds + Math.max(0, timelineMaxMinutes) * 60)}</Text>
                </Flex>
              </Flex>
            </>
          )}

          {/* Selected Simulation display removed */}
        </Flex>
      </Flex>
    </Card>
  );
}


