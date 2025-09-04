import React, { useEffect, useMemo, useState } from 'react';
import { Card, Flex, Table, Text, HoverCard, Select } from '@radix-ui/themes';
import { useSimulation } from '../context/SimulationContext';
import { SimulationEntry } from '../lib/manifest';
import DeliveryMetricsDisplay from './DeliveryMetricsDisplay';



type LoadedMetrics = {
  deliveryMetrics?: {
    onTimePercentage?: number;
    onTimeRate?: number;
    [key: string]: any;
  };
  [key: string]: any;
};

const BLOCKING_VARIANTS = ['none', 'front', 'back', 'front_mid', 'front_back', 'front_mid_back'];

const HEADER_MAP: Record<string, string> = {
  'none': 'None',
  'front': '1-3',
  'back': '10-12',
  'front_mid': '1-6',
  'front_back': '1-3 & 10-12',
  'front_mid_back': '1-6 & 10-12',
};

type MetricType = 'onTime' | 'avgOrderTime' | 'p90OrderTime' | 'failedOrders' | 'revenue' | 'runnerUtilization';

const METRIC_OPTIONS = [
  { value: 'onTime', label: 'On-Time %' },
  { value: 'avgOrderTime', label: 'Avg Order Time' },
  { value: 'p90OrderTime', label: 'P90 Order Time' },
  { value: 'failedOrders', label: 'Failed Orders' },
  { value: 'revenue', label: 'Revenue' },
  { value: 'runnerUtilization', label: 'Runner Utilization %' },
] as const;

export default function BlockedHolesMatrix() {
  const { manifest, filters, setFilters, selectedCourseId } = useSimulation();
  const [metricsById, setMetricsById] = useState<Record<string, LoadedMetrics>>({});
  const [selectedMetric, setSelectedMetric] = useState<MetricType>('onTime');
  const [selectedMetric2, setSelectedMetric2] = useState<MetricType>('avgOrderTime');

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

      // Try to load aggregate metrics first; if unavailable, fall back to per-sim metrics files
      for (const [groupKey, groupSims] of Array.from(groups.entries())) {
        if (groupSims.length === 0) continue;
        const aggregatePath = `${groupKey}/@aggregate.json`;
        let aggregate: LoadedMetrics | null = null;
        try {
          const resp = await fetch(`/coordinates/${aggregatePath}?t=${Date.now()}`);
          if (resp.ok) {
            aggregate = (await resp.json()) as LoadedMetrics;
          }
        } catch (e) {
          // ignore; will fallback per-sim
        }

        if (aggregate) {
          for (const sim of groupSims) {
            next[sim.id] = aggregate;
          }
          continue;
        }

        // Fallback: load each simulation's metrics JSON individually
        for (const sim of groupSims) {
          const metricsFile = sim.metricsFilename || '';
          if (!metricsFile) continue;
          try {
            const resp = await fetch(`/coordinates/${metricsFile}?t=${Date.now()}`);
            if (!resp.ok) continue;
            const data = (await resp.json()) as LoadedMetrics;
            next[sim.id] = data;
          } catch (e) {
            // ignore failures; cell will show dash
          }
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

  const formatMetric = (metricType: MetricType, metrics?: LoadedMetrics): string => {
    if (!metrics) return '—';
    // Support both single run and aggregate formats
    const deliveryMetrics = metrics.deliveryMetrics || metrics;
    
    switch (metricType) {
      case 'onTime': {
        const pct = Number((deliveryMetrics.on_time_mean ?? deliveryMetrics.onTimePercentage ?? deliveryMetrics.onTimeRate ?? 0));
        // on_time_mean is a fraction, so multiply by 100
        const displayPct = deliveryMetrics.on_time_mean ? pct * 100 : pct;
        return Number.isFinite(displayPct) ? `${displayPct.toFixed(0)}%` : '—';
      }
      case 'avgOrderTime': {
        const time = Number(deliveryMetrics.avg_delivery_time_mean ?? deliveryMetrics.avgOrderTime ?? 0);
        return Number.isFinite(time) ? `${Math.round(time)}m` : '—';
      }
      case 'p90OrderTime': {
        const time = Number(deliveryMetrics.p90_mean ?? deliveryMetrics.deliveryCycleTimeP90 ?? 0);
        return Number.isFinite(time) ? `${Math.round(time)}m` : '—';
      }
      case 'failedOrders': {
        const failed = Number(deliveryMetrics.failed_mean ?? deliveryMetrics.failedDeliveries ?? deliveryMetrics.failedOrderCount ?? 0);
        return Number.isFinite(failed) ? failed.toString() : '—';
      }
      case 'revenue': {
        const revenue = Number(deliveryMetrics.revenue ?? 0);
        return Number.isFinite(revenue) ? `$${revenue.toFixed(0)}` : '—';
      }
      case 'runnerUtilization': {
        const util = Number(deliveryMetrics.runnerUtilizationPct ?? 0);
        return Number.isFinite(util) ? `${util.toFixed(0)}%` : '—';
      }
      default:
        return '—';
    }
  };



  const TooltipContent = ({ metrics }: { metrics?: LoadedMetrics }) => {
    const driveTimes = (metrics as any)?.avg_drive_time_per_hole;
    
    // Transform the metrics to match the expected format for DeliveryMetricsDisplay
    const deliveryMetrics = metrics ? {
      totalOrders: Number(metrics.deliveryMetrics?.orders ?? metrics.deliveryMetrics?.totalOrders ?? metrics.deliveryMetrics?.orderCount ?? 0),
      avgOrderTime: Number(metrics.deliveryMetrics?.avg_delivery_time_mean ?? metrics.deliveryMetrics?.avgOrderTime ?? 0),
      onTimePercentage: metrics.deliveryMetrics?.on_time_mean ? Number(metrics.deliveryMetrics.on_time_mean) * 100 : Number(metrics.deliveryMetrics?.onTimePercentage ?? metrics.deliveryMetrics?.onTimeRate ?? 0),
      failedDeliveries: Number(metrics.deliveryMetrics?.failed_mean ?? metrics.deliveryMetrics?.failedDeliveries ?? metrics.deliveryMetrics?.failedOrderCount ?? 0),
      deliveryCycleTimeP90: Number(metrics.deliveryMetrics?.p90_mean ?? metrics.deliveryMetrics?.deliveryCycleTimeP90 ?? 0),
      ordersPerRunnerHour: Number(metrics.deliveryMetrics?.oph_mean ?? metrics.deliveryMetrics?.ordersPerRunnerHour ?? 0),
      ...metrics.deliveryMetrics
    } : null;

    return (
      <Flex direction="column" gap="2">
        <DeliveryMetricsDisplay 
          deliveryMetrics={deliveryMetrics} 
          variant="tooltip" 
          showTitle={true} 
        />
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

  // Debug: Always show the table to troubleshoot visibility issues
  // if (runnerCounts.length === 0) return null;

  const selectedMetricLabel = METRIC_OPTIONS.find(option => option.value === selectedMetric)?.label || 'Metric';
  const selectedMetric2Label = METRIC_OPTIONS.find(option => option.value === selectedMetric2)?.label || 'Metric';

  // Debug info
  console.log('BlockedHolesMatrix Debug:', {
    manifestSims: manifest?.simulations?.length || 0,
    simsAfterCourseFilter: sims.length,
    selectedOrders,
    relevantSims: relevantSims.length,
    runnerCounts: runnerCounts.length,
    selectedCourseId
  });

  return (
    <Card style={{ position: 'absolute', bottom: 20, left: 20, zIndex: 20, background: 'rgba(255,255,255,0.95)' }}>
      <Flex direction="column" gap="1" p="1">
        <Flex justify="between" align="center" gap="3">
          <Text size="1" weight="bold" style={{ fontSize: '11px' }}>
            {selectedMetricLabel} | {selectedMetric2Label} by Blocked Holes (Orders: {selectedOrders})
          </Text>
          <Flex align="center" gap="1">
            <Select.Root value={selectedMetric} onValueChange={(value: MetricType) => setSelectedMetric(value)}>
              <Select.Trigger variant="soft" style={{ minWidth: '90px', fontSize: '11px', padding: '2px 6px' }}>
                {selectedMetricLabel}
              </Select.Trigger>
              <Select.Content>
                {METRIC_OPTIONS.map(option => (
                  <Select.Item key={option.value} value={option.value}>
                    {option.label}
                  </Select.Item>
                ))}
              </Select.Content>
            </Select.Root>
            <Select.Root value={selectedMetric2} onValueChange={(value: MetricType) => setSelectedMetric2(value)}>
              <Select.Trigger variant="soft" style={{ minWidth: '90px', fontSize: '11px', padding: '2px 6px' }}>
                {selectedMetric2Label}
              </Select.Trigger>
              <Select.Content>
                {METRIC_OPTIONS.map(option => (
                  <Select.Item key={option.value} value={option.value}>
                    {option.label}
                  </Select.Item>
                ))}
              </Select.Content>
            </Select.Root>
          </Flex>
        </Flex>
        <Table.Root size="1" variant="surface" layout="auto" style={{ fontSize: '11px' }}>
          <Table.Header>
            <Table.Row>
              <Table.ColumnHeaderCell />
              {BLOCKING_VARIANTS.map(variant => (
                <Table.ColumnHeaderCell key={variant} justify="center" style={{ borderLeft: '1px solid var(--gray-a6)' }}>{HEADER_MAP[variant] || variant}</Table.ColumnHeaderCell>
              ))}
            </Table.Row>
          </Table.Header>
          <Table.Body>
            {runnerCounts.length === 0 ? (
              <Table.Row>
                <Table.RowHeaderCell>No Data</Table.RowHeaderCell>
                {BLOCKING_VARIANTS.map(variant => (
                  <Table.Cell key={variant} justify="center">—</Table.Cell>
                ))}
              </Table.Row>
            ) : runnerCounts.map(r => (
              <Table.Row key={r}>
                <Table.RowHeaderCell>{r === 1 ? '1 Runner' : `${r} Runners`}</Table.RowHeaderCell>
                {BLOCKING_VARIANTS.map(variant => {
                  const sim = getSimFor(r, variant);
                  const metrics = sim ? metricsById[sim.id] : undefined;
                  const metric1Value = formatMetric(selectedMetric, metrics);
                  const metric2Value = formatMetric(selectedMetric2, metrics);
                  const label = `${metric1Value} | ${metric2Value}`;
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
