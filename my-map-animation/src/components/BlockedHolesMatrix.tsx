import React, { useEffect, useMemo, useState } from 'react';
import { Card, Flex, Table, Text, HoverCard } from '@radix-ui/themes';
import { useSimulation } from '../context/SimulationContext';
import { SimulationEntry } from '../lib/manifest';



type LoadedMetrics = {
  deliveryMetrics?: {
    onTimePercentage?: number;
    onTimeRate?: number;
    [key: string]: any;
  };
  [key: string]: any;
};

const BLOCKING_VARIANTS = ['none', 'front', 'mid', 'back', 'front_mid', 'front_back', 'mid_back', 'front_mid_back'];

const HEADER_MAP: Record<string, string> = {
  'none': 'None',
  'front': '1-3',
  'mid': '4-6',
  'back': '10-12',
  'front_mid': '1-6',
  'front_back': '1-3 & 10-12',
  'mid_back': '4-6 & 10-12',
  'front_mid_back': '1-6 & 10-12',
};

export default function BlockedHolesMatrix() {
  const { manifest, filters, setFilters, selectedCourseId } = useSimulation();
  const [metricsById, setMetricsById] = useState<Record<string, LoadedMetrics>>({});

  // Filter simulations by selected course first
  const sims = useMemo(() => {
    if (!manifest?.simulations) return [];
    return selectedCourseId
      ? manifest.simulations.filter(s => (s.courseId || '') === selectedCourseId)
      : manifest.simulations;
  }, [manifest?.simulations, selectedCourseId]);

  const selectedOrders = filters.orders;

  const relevantSims = useMemo(() => {
    return sims.filter(s => s.meta?.orders === selectedOrders);
  }, [sims, selectedOrders]);

  const runnerCounts: number[] = useMemo(() => {
    const s = new Set<number>();
    for (const sim of relevantSims) {
      const n = sim.meta?.runners;
      if (typeof n === 'number' && Number.isFinite(n)) s.add(n);
    }
    return Array.from(s).sort((a, b) => a - b);
  }, [relevantSims]);

  useEffect(() => {
    let cancelled = false;
    const loadAll = async () => {
      const next: Record<string, LoadedMetrics> = {};
      // Group simulations by their parent directory, which corresponds to a variant group
      const groups = new Map<string, SimulationEntry[]>();
      for (const sim of relevantSims) {
        // Parse simulation ID to construct output directory path
        // Format: {course_id}__{pass_name}__orders_{orders:03d}__runners_{runners}__{variant}
        const parts = sim.id.split('__');
        if (parts.length >= 5) {
          const [courseId, passName, ordersPart, runnersPart] = parts;
          const key = `${courseId}/${passName}/${ordersPart}/${runnersPart}`;
          if (!groups.has(key)) groups.set(key, []);
          groups.get(key)!.push(sim);
        }
      }

      for (const [groupKey, groupSims] of Array.from(groups.entries())) {
        if (groupSims.length === 0) continue;
        const aggregatePath = `${groupKey}/@aggregate.json`;

        try {
          const resp = await fetch(`/coordinates/${aggregatePath}?t=${Date.now()}`);
          if (!resp.ok) continue;
          const data = (await resp.json()) as LoadedMetrics;
          // Store the aggregated data for each sim in the group
          for (const sim of groupSims) {
            next[sim.id] = data;
          }
        } catch (e) {
          console.error(`Failed to load aggregate metrics from ${aggregatePath}:`, e);
        }
      }

      if (!cancelled) setMetricsById(next);
    };
    if (relevantSims.length > 0) loadAll();
    return () => { cancelled = true; };
  }, [relevantSims]);

  const getSimFor = (runners: number, variantKey: string): SimulationEntry | undefined => {
    return relevantSims.find(s => s.meta?.runners === runners && s.variantKey === variantKey);
  }

  const formatOnTime = (metrics?: LoadedMetrics): string => {
    if (!metrics) return '—';
    // Support both single run and aggregate formats
    const deliveryMetrics = metrics.deliveryMetrics || metrics;
    const pct = Number((deliveryMetrics.on_time_mean ?? deliveryMetrics.onTimePercentage ?? deliveryMetrics.onTimeRate ?? 0));
    // on_time_mean is a fraction, so multiply by 100
    const displayPct = deliveryMetrics.on_time_mean ? pct * 100 : pct;
    return Number.isFinite(displayPct) ? `${displayPct.toFixed(0)}%` : '—';
  };

  const buildTooltipData = (metrics?: LoadedMetrics): { label: string, value: string }[] => {
    if (!metrics) return [];
    const dm: any = metrics.deliveryMetrics || metrics;
    const onTime = Number(dm.on_time_mean ?? dm.onTimePercentage ?? dm.onTimeRate ?? 0);
    const displayOnTime = dm.on_time_mean ? onTime * 100 : onTime;

    return [
      { label: 'Orders', value: `${Number(dm.orders ?? dm.totalOrders ?? dm.orderCount ?? 0)}` },
      { label: 'Runs', value: `${Number(dm.runs ?? 1)}` },
      { label: 'Avg On-Time %', value: `${Number.isFinite(displayOnTime) ? displayOnTime.toFixed(0) : '—'}%` },
      { label: 'Avg Failed', value: `${(Number(dm.failed_mean ?? dm.failedDeliveries ?? dm.failedOrderCount ?? 0) * 100).toFixed(1)}%` },
      { label: 'Avg Order Time', value: `${Number(dm.avg_delivery_time_mean ?? dm.avgOrderTime ?? 0).toFixed(1)}m` },
      { label: 'Avg P90 Cycle', value: `${Number(dm.p90_mean ?? dm.deliveryCycleTimeP90 ?? 0).toFixed(1)}m` },
      { label: 'Avg OPH', value: `${Number(dm.oph_mean ?? dm.ordersPerRunnerHour ?? 0).toFixed(1)}` },
    ];
  };

  const TooltipContent = ({ metrics }: { metrics?: LoadedMetrics }) => {
    const data = buildTooltipData(metrics);
    const driveTimes = (metrics as any)?.avg_drive_time_per_hole;

    if (data.length === 0) {
      return <Text as="div" size="2">No metrics available</Text>;
    }
    return (
      <Flex direction="column" gap="2">
        <div style={{ display: 'grid', gridTemplateColumns: 'auto auto', gap: '4px 12px', alignItems: 'center' }}>
          {data.map(({ label, value }) => (
            <React.Fragment key={label}>
              <Text size="2" style={{ justifySelf: 'start' }}>{label}:</Text>
              <Text size="2" weight="bold" style={{ justifySelf: 'end' }}>{value}</Text>
            </React.Fragment>
          ))}
        </div>
        {driveTimes && Object.keys(driveTimes).length > 0 && (
          <Flex direction="column" gap="1" mt="2">
            <Text size="2" weight="bold">Avg Drive Time by Hole (min)</Text>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(60px, 1fr))', gap: '4px 8px' }}>
              {Object.entries(driveTimes).map(([hole, time]) => (
                <Flex key={hole} gap="1" justify="between">
                  <Text size="1">H{hole}:</Text>
                  <Text size="1" weight="bold">{(Number(time) / 60).toFixed(1)}</Text>
                </Flex>
              ))}
            </div>
          </Flex>
        )}
      </Flex>
    );
  };

  const variantToBlockedHoles = (variant: string) => {
    const blockFront = variant.includes('front');
    const blockMid = variant.includes('mid');
    const blockBack = variant.includes('back');
    return { blockFront, blockMid, blockBack };
  };

  const getCurrentVariant = () => {
    const { blockFront, blockMid, blockBack } = filters;
    const parts = [];
    if (blockFront) parts.push('front');
    if (blockMid) parts.push('mid');
    if (blockBack) parts.push('back');
    return parts.length > 0 ? parts.join('_') : 'none';
  };

  const handleCellClick = (variant: string, runners: number) => {
    const blockedHoles = variantToBlockedHoles(variant);
    setFilters({
      ...filters,
      runners,
      ...blockedHoles
    });
  };

  if (runnerCounts.length === 0) return null;

  return (
    <Card style={{ position: 'absolute', bottom: 20, left: 20, zIndex: 20, background: 'rgba(255,255,255,0.95)' }}>
      <Flex direction="column" gap="2" p="3">
        <Text size="2" weight="bold" style={{ alignSelf: 'center' }}>On-Time % by Blocked Holes (Orders: {selectedOrders})</Text>
        <Table.Root size="1" variant="surface" layout="auto">
          <Table.Header>
            <Table.Row>
              <Table.ColumnHeaderCell />
              {BLOCKING_VARIANTS.map(variant => (
                <Table.ColumnHeaderCell key={variant} justify="center" style={{ borderLeft: '1px solid var(--gray-a6)' }}>{HEADER_MAP[variant] || variant}</Table.ColumnHeaderCell>
              ))}
            </Table.Row>
          </Table.Header>
          <Table.Body>
            {runnerCounts.map(r => (
              <Table.Row key={r}>
                <Table.RowHeaderCell>{r === 1 ? '1 Runner' : `${r} Runners`}</Table.RowHeaderCell>
                {BLOCKING_VARIANTS.map(variant => {
                  const sim = getSimFor(r, variant);
                  const metrics = sim ? metricsById[sim.id] : undefined;
                  const label = formatOnTime(metrics);
                  const currentVariant = getCurrentVariant();
                  const isSelected = currentVariant === variant && filters.runners === r;
                  return (
                    <Table.Cell 
                      key={`${r}-${variant}`} 
                      justify="center" 
                      style={{ 
                        borderLeft: '1px solid var(--gray-a6)',
                        cursor: sim ? 'pointer' : 'default',
                        background: isSelected ? 'rgba(0,128,255,0.15)' : undefined
                      }}
                      onClick={() => sim && handleCellClick(variant, r)}
                    >
                      <HoverCard.Root>
                        <HoverCard.Trigger>
                          <Text weight={isSelected ? 'bold' : 'regular'}>{label}</Text>
                        </HoverCard.Trigger>
                        <HoverCard.Content size="2" maxWidth="340px">
                          <TooltipContent metrics={metrics} />
                        </HoverCard.Content>
                      </HoverCard.Root>
                    </Table.Cell>
                  );
                })}
              </Table.Row>
            ))}
          </Table.Body>
        </Table.Root>

      </Flex>
    </Card>
  );
}
