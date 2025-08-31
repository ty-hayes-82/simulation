import React from 'react';
import DeliveryMetricsDisplay from './DeliveryMetricsDisplay';

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

interface DeliveryMetricsGridProps {
  deliveryMetrics: DeliveryMetrics | null;
}

export default function DeliveryMetricsGrid({ deliveryMetrics }: DeliveryMetricsGridProps) {
  return (
    <DeliveryMetricsDisplay 
      deliveryMetrics={deliveryMetrics} 
      variant="panel" 
      showTitle={true} 
    />
  );
}
