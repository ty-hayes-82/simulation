import React, { useEffect, useMemo, useState } from 'react';
import { Card, Flex, Table, Text, HoverCard } from '@radix-ui/themes';
import { useSimulation } from '../context/SimulationContext';
import { SimulationEntry } from '../lib/manifest';

const StaticBlockedHolesTable = () => {
  const headers = ['None', '1-3', '4-6', '10-12', '1-6', '1-3 & 10-12', '4-6 & 10-12', '1-6 & 10-12'];
  const rowData = ['35%', '32%', '54%', '33%', '41%', '38%', '50%', '63%'];

  return (
    <Flex direction="column" gap="2" mt="1">
      <Text size="2" weight="bold" style={{ alignSelf: 'center' }}>On-Time % by Blocked Holes (Orders: 20)</Text>
      <Table.Root size="1" variant="surface" layout="auto">
        <Table.Header>
          <Table.Row>
            <Table.ColumnHeaderCell />
            {headers.map(header => (
              <Table.ColumnHeaderCell key={header} justify="center" style={{ borderLeft: '1px solid var(--gray-a6)' }}>{header}</Table.ColumnHeaderCell>
            ))}
          </Table.Row>
        </Table.Header>
        <Table.Body>
          <Table.Row>
            <Table.RowHeaderCell>1 Runner</Table.RowHeaderCell>
            {rowData.map((data, index) => (
              <Table.Cell key={index} justify="center" style={{ borderLeft: '1px solid var(--gray-a6)' }}>
                {data}
              </Table.Cell>
            ))}
          </Table.Row>
        </Table.Body>
      </Table.Root>
    </Flex>
  );
};

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
  const { manifest, filters, setFilters } = useSimulation();
  const [metricsById, setMetricsById] = useState<Record<string, LoadedMetrics>>({});

  const sims = manifest?.simulations || [];
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
      for (const sim of relevantSims) {
        if (!sim.metricsFilename) continue;
        try {
          const resp = await fetch(`/coordinates/${sim.metricsFilename}?t=${Date.now()}`);
          if (!resp.ok) continue;
          const data = (await resp.json()) as LoadedMetrics;
          next[sim.id] = data;
        } catch {}
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
    if (!metrics || !metrics.deliveryMetrics) return '—';
    const dm = metrics.deliveryMetrics || {};
    const pct = Number((dm.onTimePercentage ?? dm.onTimeRate ?? 0));
    return Number.isFinite(pct) ? `${pct.toFixed(0)}%` : '—';
  };

  const buildTooltipData = (metrics?: LoadedMetrics): { label: string, value: string }[] => {
    if (!metrics || !metrics.deliveryMetrics) return [];
    const dm: any = metrics.deliveryMetrics || {};
    const onTime = Number(dm.onTimePercentage ?? dm.onTimeRate ?? 0);
    return [
      { label: 'Orders', value: `${Number(dm.totalOrders ?? dm.orderCount ?? 0)}` },
      { label: 'Revenue', value: `$${Number(dm.revenue ?? 0).toFixed(0)}` },
      { label: 'Avg Order Time', value: `${Number(dm.avgOrderTime ?? 0).toFixed(1)}m` },
      { label: 'On-Time %', value: `${Number.isFinite(onTime) ? onTime.toFixed(0) : '—'}%` },
      { label: 'Failed', value: `${Number(dm.failedDeliveries ?? dm.failedOrderCount ?? 0)}` },
      { label: 'Queue Wait', value: `${Number(dm.queueWaitAvg ?? 0).toFixed(1)}m` },
      { label: 'P90 Cycle', value: `${Number(dm.deliveryCycleTimeP90 ?? 0).toFixed(1)}m` },
      { label: 'Orders / Runner-Hr', value: `${Number(dm.ordersPerRunnerHour ?? 0).toFixed(1)}` },
      { label: 'Revenue / Runner-Hr', value: `$${Number(dm.revenuePerRunnerHour ?? 0).toFixed(0)}` },
    ];
  };

  const TooltipContent = ({ metrics }: { metrics?: LoadedMetrics }) => {
    const data = buildTooltipData(metrics);
    if (data.length === 0) {
      return <Text as="div" size="2">No metrics available</Text>;
    }
    return (
      <div style={{ display: 'grid', gridTemplateColumns: 'auto auto', gap: '4px 12px', alignItems: 'center' }}>
        {data.map(({ label, value }) => (
          <React.Fragment key={label}>
            <Text size="2" style={{ justifySelf: 'start' }}>{label}:</Text>
            <Text size="2" weight="bold" style={{ justifySelf: 'end' }}>{value}</Text>
          </React.Fragment>
        ))}
      </div>
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
        <StaticBlockedHolesTable />
      </Flex>
    </Card>
  );
}
