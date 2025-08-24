import React, { useEffect, useMemo, useState } from 'react';
import { Flex, Text, Select, Card, Slider, Separator, CheckboxGroup } from '@radix-ui/themes';
import { useSimulation } from '../context/SimulationContext';
import { useLocation } from 'react-router-dom';
import { distinctRunnerCounts, distinctOrderCounts } from '../lib/manifest';
import { secondsSince7amToClock } from '../lib/format';

export default function TopBarControls() {
  const { manifest, selectedSim, selectedCourseId, setSelectedCourseId, filters, setFilters, timelineMinutes, setTimelineMinutes, timelineMaxMinutes, baselineTimestampSeconds, isSliderControlled, setIsSliderControlled, animationSpeed, setAnimationSpeed } = useSimulation();
  // Workaround for typing issue on CheckboxGroup.Root accepting children
  const CheckboxRoot: any = (CheckboxGroup as any).Root;
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

  return (
    <Card style={{ position: 'absolute', top: 20, left: 20, zIndex: 20, background: 'rgba(255,255,255,0.95)', minWidth: '320px' }}>
      <Flex direction="column" gap="3" p="4">
        {/* Simulation Controls */}
        <Flex direction="column" gap="3">
          <Text size="3" weight="bold">Simulation Controls</Text>
          {/* Course Selector */}
          <Flex align="center" gap="2">
            <Text size="2" weight="medium" style={{ minWidth: '60px' }}>Course:</Text>
            <Select.Root 
              value={selectedCourseId || 'pinetree_country_club'}
              onValueChange={(value) => setSelectedCourseId(value)}
            >
              <Select.Trigger style={{ flex: 1 }} />
              <Select.Content>
                {/* Default to Pinetree if none found */}
                {((manifest?.courses && manifest.courses.length > 0) ? manifest.courses : [
                  { id: 'pinetree_country_club', name: 'Pinetree Country Club' }
                ]).map(c => (
                  <Select.Item key={c.id} value={c.id}>{c.name}</Select.Item>
                ))}
              </Select.Content>
            </Select.Root>
          </Flex>
          
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

          {/* --- Start: Blocked Holes Controls --- */}
          <Flex direction="column" gap="2">
            <Text size="2" weight="medium">Block Holes</Text>
            <CheckboxRoot 
              value={
                [
                  filters.blockFront ? 'front' : '',
                  filters.blockMid ? 'mid' : '',
                  filters.blockBack ? 'back' : ''
                ].filter(Boolean)
              }
              onValueChange={(v: string[]) => {
                setFilters({
                  ...filters,
                  blockFront: v.includes('front'),
                  blockMid: v.includes('mid'),
                  blockBack: v.includes('back'),
                });
              }}
              name="blockedHoles" 
              variant="soft" 
              size="2"
            >
              <Flex direction="column" gap="2">
                <Text as="label" size="2">
                  <Flex gap="2"><CheckboxGroup.Item value="front" /> 1–3</Flex>
                </Text>
                <Text as="label" size="2">
                  <Flex gap="2"><CheckboxGroup.Item value="mid" /> 4–6</Flex>
                </Text>
                <Text as="label" size="2">
                  <Flex gap="2"><CheckboxGroup.Item value="back" /> 10–12</Flex>
                </Text>
              </Flex>
            </CheckboxRoot>
          </Flex>
          {/* --- End: Blocked Holes Controls --- */}

          {!isHeatmap && (
            <>
              <Separator size="2" />
              <Flex direction="column" gap="3">
                <Text size="2" weight="medium">Animation Speed</Text>
                <Slider
                  value={[animationSpeed]}
                  onValueChange={(val) => setAnimationSpeed(val[0])}
                  min={1}
                  max={400}
                  step={1}
                  style={{ width: '100%' }}
                />
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


