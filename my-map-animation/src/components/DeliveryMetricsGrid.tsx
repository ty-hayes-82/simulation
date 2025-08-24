import React from 'react';

interface DeliveryMetrics {
  orderCount: number;
  revenue: number;
  avgOrderTime: number;
  onTimeRate: number;
  failedOrderCount: number;
  queueWaitAvg: number;
  deliveryCycleTimeP90: number;
  ordersPerRunnerHour: number;
  revenuePerRunnerHour: number;
  runnerUtilizationPct?: number;
  lateOrders?: number;
  totalRunnerDriveMinutes?: number;
  totalRunnerShiftMinutes?: number;
  // Allow other properties from the simulation
  [key: string]: any;
}

interface DeliveryMetricsGridProps {
  deliveryMetrics: DeliveryMetrics | null;
}

export default function DeliveryMetricsGrid({ deliveryMetrics }: DeliveryMetricsGridProps) {
  if (!deliveryMetrics) {
    return null;
  }

  const dm: any = deliveryMetrics || {};
  const totalOrders = Number(dm.totalOrders ?? dm.orderCount ?? 0);
  const failed = Number(dm.failedDeliveries ?? dm.failedOrderCount ?? 0);
  const successful = Number.isFinite(dm.successfulDeliveries)
    ? Number(dm.successfulDeliveries)
    : Math.max(0, totalOrders - (Number.isFinite(failed) ? failed : 0));
  const onTimePct = Number(dm.onTimePercentage ?? dm.onTimeRate ?? 0);
  const onTimeCount = (onTimePct / 100) * successful;

  // Use late orders from the data if available, otherwise calculate
  const late = Number.isFinite(dm.lateOrders) 
    ? Number(dm.lateOrders)
    : Math.max(0, Math.round(successful - onTimeCount));
  
  const avgOrderTimeMin = Number(dm.avgOrderTime ?? 0);
  const queueWaitMin = Number(dm.queueWaitAvg ?? 0);
  const runnerUtilPct = dm.runnerUtilizationPct;
  const revenue = Number(dm.revenue ?? 0);
  const totalRunnerDriveMin = Number(dm.totalRunnerDriveMinutes ?? 0);
  const totalRunnerShiftMin = Number(dm.totalRunnerShiftMinutes ?? 0);

  return (
    <div style={{ marginBottom: 16 }}>
      <h4 style={{ margin: '0 0 8px 0', color: '#333', fontSize: 14, fontWeight: 600, textTransform: 'uppercase', borderBottom: '1px solid #e9ecef', paddingBottom: 4 }}>
        Delivery Metrics
      </h4>
      <div style={{ display: 'grid', gridTemplateColumns: 'auto auto', gap: '6px 12px', fontSize: 13, alignItems: 'center' }}>
        <span style={{ justifySelf: 'start' }}>Order Count:</span><strong style={{ justifySelf: 'end' }}>{totalOrders}</strong>
        <span style={{ justifySelf: 'start' }}>Avg Order Time:</span><strong style={{ justifySelf: 'end' }}>{Math.round(avgOrderTimeMin)}m</strong>
        <span style={{ justifySelf: 'start' }}>Avg Queue Wait:</span><strong style={{ justifySelf: 'end' }}>{Math.round(queueWaitMin)}m</strong>
        <span style={{ justifySelf: 'start' }}>Late Orders:</span><strong style={{ justifySelf: 'end' }}>{late}</strong>
        <span style={{ justifySelf: 'start' }}>Failed Orders:</span><strong style={{ justifySelf: 'end' }}>{Number.isFinite(failed) ? failed : 0}</strong>
        <span style={{ justifySelf: 'start' }}>Runner Utilization %:</span><strong style={{ justifySelf: 'end' }}>{Number.isFinite(runnerUtilPct) ? `${Number(runnerUtilPct).toFixed(0)}%` : '—'}</strong>
        <span style={{ justifySelf: 'start' }}>On-Time %:</span><strong style={{ justifySelf: 'end' }}>{Number.isFinite(onTimePct) ? `${onTimePct.toFixed(0)}%` : '—'}</strong>
        <span style={{ justifySelf: 'start' }}>Total Revenue:</span><strong style={{ justifySelf: 'end' }}>${revenue.toFixed(0)}</strong>
        <span style={{ justifySelf: 'start' }}>Runner Drive Minutes:</span><strong style={{ justifySelf: 'end' }}>{Math.round(totalRunnerDriveMin)}m</strong>
        <span style={{ justifySelf: 'start' }}>Runner Shift Minutes:</span><strong style={{ justifySelf: 'end' }}>{Math.round(totalRunnerShiftMin)}m</strong>
      </div>
    </div>
  );
}
