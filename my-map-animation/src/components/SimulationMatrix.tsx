import React, { useEffect, useMemo, useState } from 'react';
import { Card, Flex, Table, Text, HoverCard } from '@radix-ui/themes';
import { useSimulation } from '../context/SimulationContext';
import DeliveryMetricsDisplay from './DeliveryMetricsDisplay';

type LoadedMetrics = {
  hasRunners?: boolean;
  hasBevCart?: boolean;
  deliveryMetrics?: any;
  bevCartMetrics?: any;
};

const HEADER_MAP: Record<string, string> = {
  'none': 'None',
  'front': '1-3',
  'back': '10-12',
  'front_mid': '1-6',
  'front_back': '1-3 & 10-12',
  'front_mid_back': '1-6 & 10-12',
};

export default function SimulationMatrix() {
  const { manifest, filters, setFilters, selectedCourseId } = useSimulation();
  const [metricsById, setMetricsById] = useState<Record<string, LoadedMetrics>>({});

  // Filter simulations by selected course
  const sims = useMemo(() => {
    if (!manifest?.simulations) return [];
    return selectedCourseId
      ? manifest.simulations.filter(s => (s.courseId || '') === selectedCourseId)
      : manifest.simulations;
  }, [manifest?.simulations, selectedCourseId]);

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

  const { blockFront, blockMid, blockBack } = filters;
  const currentVariantKey = useMemo(() => {
    const parts = [];
    if (blockFront) parts.push('front');
    if (blockMid) parts.push('mid');
    if (blockBack) parts.push('back');
    return parts.length > 0 ? parts.join('_') : 'none';
  }, [blockFront, blockMid, blockBack]);

  const getSimFor = (runners: number, orders: number) =>
    sims.find(s => (s.meta?.runners ?? NaN) === runners && (s.meta?.orders ?? NaN) === orders && s.variantKey === currentVariantKey);

  const formatOnTime = (metrics?: LoadedMetrics): string => {
    if (!metrics || !metrics.deliveryMetrics) return '—';
    const dm: any = metrics.deliveryMetrics || {};
    const pct = Number((dm.onTimePercentage ?? dm.onTimeRate ?? 0));
    if (!Number.isFinite(pct)) return '—';
    return `${pct.toFixed(0)}%`;
  };



  const title = useMemo(() => {
    const header = HEADER_MAP[currentVariantKey] || 'Custom';
    if (header === 'None') {
      return 'On-Time % (Baseline)';
    }
    return `On-Time % (Blocked: ${header})`;
  }, [currentVariantKey]);

  if (runnerCounts.length === 0 || orderCounts.length === 0) return null;

  return (
    <div style={{ position: 'absolute', bottom: 20, right: 20, zIndex: 25 }}>
      <Card style={{ background: 'rgba(255,255,255,0.95)' }}>
        <Flex direction="column" gap="2" p="3">
          <Text size="2" weight="bold" style={{ alignSelf: 'center' }}>{title}</Text>
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
                          <HoverCard.Content size="2" maxWidth="340px">
                            <DeliveryMetricsDisplay 
                              deliveryMetrics={m?.deliveryMetrics} 
                              variant="tooltip" 
                              showTitle={true} 
                            />
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


