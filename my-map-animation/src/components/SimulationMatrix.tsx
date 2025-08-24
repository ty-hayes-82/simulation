import React, { useEffect, useMemo, useState } from 'react';
import { Card, Flex, Table, Text, HoverCard } from '@radix-ui/themes';
import { useSimulation } from '../context/SimulationContext';

type LoadedMetrics = {
  hasRunners?: boolean;
  hasBevCart?: boolean;
  deliveryMetrics?: any;
  bevCartMetrics?: any;
};

export default function SimulationMatrix() {
  const { manifest, filters, setFilters } = useSimulation();
  const [metricsById, setMetricsById] = useState<Record<string, LoadedMetrics>>({});

  const sims = manifest?.simulations || [];

  const runnerCounts: number[] = useMemo(() => {
    const s = new Set<number>();
    for (const sim of sims) {
      const n = sim.meta?.runners;
      if (typeof n === 'number' && Number.isFinite(n)) s.add(n);
    }
    return Array.from(s).sort((a, b) => a - b);
  }, [sims]);

  const orderCounts: number[] = useMemo(() => {
    const s = new Set<number>();
    for (const sim of sims) {
      const n = sim.meta?.orders;
      if (typeof n === 'number' && Number.isFinite(n)) s.add(n);
    }
    return Array.from(s).sort((a, b) => a - b);
  }, [sims]);

  useEffect(() => {
    let cancelled = false;
    const loadAll = async () => {
      const next: Record<string, LoadedMetrics> = {};
      for (const sim of sims) {
        const metricsFile = sim.metricsFilename || 'simulation_metrics.json';
        try {
          const resp = await fetch(`/coordinates/${metricsFile}?t=${Date.now()}`);
          if (!resp.ok) continue;
          const data = (await resp.json()) as LoadedMetrics;
          next[sim.id] = data;
        } catch {}
      }
      if (!cancelled) setMetricsById(next);
    };
    if (sims.length > 0) loadAll();
    return () => { cancelled = true; };
  }, [sims]);

  const getSimFor = (runners: number, orders: number) =>
    sims.find(s => (s.meta?.runners ?? NaN) === runners && (s.meta?.orders ?? NaN) === orders);

  const formatOnTime = (metrics?: LoadedMetrics): string => {
    if (!metrics || !metrics.deliveryMetrics) return '—';
    const dm: any = metrics.deliveryMetrics || {};
    const pct = Number((dm.onTimePercentage ?? dm.onTimeRate ?? 0));
    if (!Number.isFinite(pct)) return '—';
    return `${pct.toFixed(1)}%`;
  };

  const buildTooltipText = (metrics?: LoadedMetrics): string => {
    if (!metrics || !metrics.deliveryMetrics) return 'No metrics available';
    const dm: any = metrics.deliveryMetrics || {};
    const onTime = Number(dm.onTimePercentage ?? dm.onTimeRate ?? 0);
    const lines = [
      `Orders: ${Number(dm.totalOrders ?? dm.orderCount ?? 0)}`,
      `Revenue: $${Number(dm.revenue ?? 0).toFixed(0)}`,
      `Avg Order Time: ${Number(dm.avgOrderTime ?? 0).toFixed(1)}m`,
      `On-Time %: ${Number.isFinite(onTime) ? onTime.toFixed(1) : '—'}%`,
      `Failed: ${Number(dm.failedDeliveries ?? dm.failedOrderCount ?? 0)}`,
      `Queue Wait: ${Number(dm.queueWaitAvg ?? 0).toFixed(1)}m`,
      `P90 Cycle: ${Number(dm.deliveryCycleTimeP90 ?? 0).toFixed(1)}m`,
      `Orders / Runner-Hr: ${Number(dm.ordersPerRunnerHour ?? 0).toFixed(1)}`,
      `Revenue / Runner-Hr: $${Number(dm.revenuePerRunnerHour ?? 0).toFixed(0)}`,
    ];
    return lines.join('\n');
  };

  if (runnerCounts.length === 0 || orderCounts.length === 0) return null;

  return (
    <div style={{ position: 'absolute', bottom: 20, right: 20, zIndex: 25 }}>
      <Card variant="surface">
        <Flex direction="column" gap="2" p="3">
          <Text size="2" weight="bold" style={{ alignSelf: 'center' }}>On-Time %</Text>
          <Table.Root size="2" variant="surface" layout="auto">
            <Table.Header>
              <Table.Row>
                <Table.ColumnHeaderCell style={{ borderRight: '1px solid var(--gray-5)' }} />
                <Table.ColumnHeaderCell
                  colSpan={orderCounts.length}
                  justify="center"
                  style={{ borderLeft: '1px solid var(--gray-5)', borderRight: '1px solid var(--gray-5)' }}
                >
                  Total Orders
                </Table.ColumnHeaderCell>
              </Table.Row>
              <Table.Row>
                <Table.ColumnHeaderCell style={{ borderRight: '1px solid var(--gray-5)' }} />
                {orderCounts.map((o, idx) => (
                  <Table.ColumnHeaderCell
                    key={o}
                    justify="center"
                    style={{ borderLeft: '1px solid var(--gray-5)', ...(idx === orderCounts.length - 1 ? { borderRight: '1px solid var(--gray-5)' } : {}) }}
                  >
                    {o}
                  </Table.ColumnHeaderCell>
                ))}
              </Table.Row>
            </Table.Header>
            <Table.Body>
              {runnerCounts.map(r => (
                <Table.Row key={r}>
                  <Table.RowHeaderCell justify="start" style={{ borderRight: '1px solid var(--gray-5)' }}>{r === 1 ? '1 Runner' : `${r} Runners`}</Table.RowHeaderCell>
                  {orderCounts.map((o, idx) => {
                    const sim = getSimFor(r, o);
                    const m = sim ? metricsById[sim.id] : undefined;
                    const label = formatOnTime(m);
                    const tip = buildTooltipText(m);
                    const isActive = (filters.runners === r && filters.orders === o);
                    return (
                      <Table.Cell
                        key={`${r}-${o}`}
                        justify="center"
                        style={{
                          cursor: sim ? 'pointer' : 'default',
                          background: isActive ? 'rgba(0,128,255,0.08)' : undefined,
                          borderLeft: '1px solid var(--gray-5)',
                          ...(idx === orderCounts.length - 1 ? { borderRight: '1px solid var(--gray-5)' } : {})
                        }}
                        onClick={() => sim && setFilters({ runners: r, orders: o })}
                      >
                        <HoverCard.Root>
                          <HoverCard.Trigger>
                            <Text weight={isActive ? 'bold' : 'regular'}>{label}</Text>
                          </HoverCard.Trigger>
                          <HoverCard.Content size="2" maxWidth="280px">
                            <Text as="div" size="2" style={{ whiteSpace: 'pre-line' }}>{tip}</Text>
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
    </div>
  );
}


