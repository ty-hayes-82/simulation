import React from 'react';
import { Text, Flex } from '@radix-ui/themes';

interface DeliveryMetrics {
  orderCount?: number;
  totalOrders?: number;
  revenue?: number;
  avgOrderTime?: number;
  onTimeRate?: number;
  onTimePercentage?: number;
  failedOrderCount?: number;
  failedDeliveries?: number;
  queueWaitAvg?: number;
  deliveryCycleTimeP90?: number;
  ordersPerRunnerHour?: number;
  revenuePerRunnerHour?: number;
  runnerUtilizationPct?: number;
  lateOrders?: number;
  totalRunnerDriveMinutes?: number;
  totalRunnerShiftMinutes?: number;
  successfulDeliveries?: number;
  // Allow other properties from the simulation
  [key: string]: any;
}

interface DeliveryMetricsDisplayProps {
  deliveryMetrics: DeliveryMetrics | null;
  variant?: 'panel' | 'tooltip';
  showTitle?: boolean;
}

// Unified metrics calculation logic
export const calculateMetrics = (dm: any) => {
  const totalOrders = Number(dm?.totalOrders ?? dm?.orderCount ?? 0);
  const failed = Number(dm?.failedDeliveries ?? dm?.failedOrderCount ?? 0);
  const successful = Number.isFinite(dm?.successfulDeliveries)
    ? Number(dm?.successfulDeliveries)
    : Math.max(0, totalOrders - (Number.isFinite(failed) ? failed : 0));
  const onTimePct = Number(dm?.onTimePercentage ?? dm?.onTimeRate ?? 0);
  const onTimeCount = (onTimePct / 100) * successful;

  // Use late orders from the data if available, otherwise calculate
  const late = Number.isFinite(dm?.lateOrders) 
    ? Number(dm?.lateOrders)
    : Math.max(0, Math.round(successful - onTimeCount));
  
  const avgOrderTimeMin = Number(dm?.avgOrderTime ?? 0);
  const p90OrderTimeMin = Number(dm?.deliveryCycleTimeP90 ?? 0);
  const queueWaitMin = Number(dm?.queueWaitAvg ?? 0);
  const runnerUtilPct = dm?.runnerUtilizationPct;
  const revenue = Number(dm?.revenue ?? 0);
  const totalRunnerDriveMin = Number(dm?.totalRunnerDriveMinutes ?? 0);
  const totalRunnerShiftMin = Number(dm?.totalRunnerShiftMinutes ?? 0);

  return {
    totalOrders,
    failed,
    successful,
    onTimePct,
    late,
    avgOrderTimeMin,
    p90OrderTimeMin,
    queueWaitMin,
    runnerUtilPct,
    revenue,
    totalRunnerDriveMin,
    totalRunnerShiftMin,
  };
};

// Unified metrics data structure
export const getMetricsData = (deliveryMetrics: DeliveryMetrics | null) => {
  if (!deliveryMetrics) return [];

  const metrics = calculateMetrics(deliveryMetrics);

  return [
    { label: 'Order Count', value: metrics.totalOrders.toString() },
    { label: 'Avg Order Time', value: `${Math.round(metrics.avgOrderTimeMin)}m` },
    { label: 'P90 Order Time', value: `${Math.round(metrics.p90OrderTimeMin)}m` },
    { label: 'Avg Queue Wait', value: `${Math.round(metrics.queueWaitMin)}m` },
    { label: 'Late Orders', value: metrics.late.toString() },
    { label: 'Failed Orders', value: (Number.isFinite(metrics.failed) ? metrics.failed : 0).toString() },
    { label: 'Runner Utilization %', value: Number.isFinite(metrics.runnerUtilPct) ? `${Number(metrics.runnerUtilPct).toFixed(0)}%` : '—' },
    { label: 'On-Time %', value: Number.isFinite(metrics.onTimePct) ? `${metrics.onTimePct.toFixed(0)}%` : '—' },
    { label: 'Total Revenue', value: `$${metrics.revenue.toFixed(0)}` },
    { label: 'Runner Drive Minutes', value: `${Math.round(metrics.totalRunnerDriveMin)}m` },
    { label: 'Runner Shift Minutes', value: `${Math.round(metrics.totalRunnerShiftMin)}m` },
  ];
};

export default function DeliveryMetricsDisplay({ 
  deliveryMetrics, 
  variant = 'panel', 
  showTitle = true 
}: DeliveryMetricsDisplayProps) {
  const metricsData = getMetricsData(deliveryMetrics);
  
  if (metricsData.length === 0) {
    if (variant === 'tooltip') {
      return <Text as="div" size="2">No metrics available</Text>;
    }
    return null;
  }

  const gridStyle = variant === 'tooltip' 
    ? { display: 'grid', gridTemplateColumns: 'auto auto', gap: '4px 12px', alignItems: 'center' }
    : { display: 'grid', gridTemplateColumns: 'auto auto', gap: '6px 12px', fontSize: 13, alignItems: 'center' };

  const titleStyle = variant === 'tooltip'
    ? { margin: '0 0 8px 0', fontSize: 12, fontWeight: 600 }
    : { margin: '0 0 8px 0', color: '#333', fontSize: 14, fontWeight: 600, textTransform: 'uppercase' as const, borderBottom: '1px solid #e9ecef', paddingBottom: 4 };

  const content = (
    <>
      {showTitle && (
        <h4 style={titleStyle}>
          Delivery Metrics
        </h4>
      )}
      <div style={gridStyle}>
        {metricsData.map(({ label, value }) => (
          <React.Fragment key={label}>
            <Text 
              size={variant === 'tooltip' ? '2' : undefined} 
              style={{ justifySelf: 'start' }}
            >
              {label}:
            </Text>
            <Text 
              size={variant === 'tooltip' ? '2' : undefined} 
              weight="bold" 
              style={{ justifySelf: 'end' }}
            >
              {value}
            </Text>
          </React.Fragment>
        ))}
      </div>
    </>
  );

  if (variant === 'tooltip') {
    return <div>{content}</div>;
  }

  return (
    <div style={{ marginBottom: 16 }}>
      {content}
    </div>
  );
}
