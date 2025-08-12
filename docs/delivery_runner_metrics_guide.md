# Delivery Runner Metrics Guide

This guide explains the comprehensive metrics system for delivery runner only simulations with Clubhouse delivery (1-2 runners) context.

## Overview

The delivery runner metrics system provides detailed analysis of delivery operations, including business performance, service quality, operational efficiency, and financial analysis. These metrics are designed to help optimize delivery runner operations and make data-driven decisions about staffing and service levels.

## Core Business Metrics

### 1. Revenue per Round (RPR)
- **Formula**: F&B revenue ÷ rounds in service window
- **Purpose**: Measures revenue generation per golf round
- **Target**: Higher values indicate better revenue performance
- **Unit**: Dollars per round

### 2. Order Penetration Rate
- **Formula**: Unique orders ÷ rounds (or groups)
- **Purpose**: Measures how many rounds place orders
- **Target**: Higher values indicate better customer engagement
- **Unit**: Orders per round (percentage)

### 3. Average Order Value (AOV)
- **Formula**: Revenue ÷ orders
- **Purpose**: Measures the average revenue per order
- **Target**: Higher values indicate better order value
- **Unit**: Dollars per order

### 4. Orders per Runner-Hour
- **Formula**: Orders ÷ active runner hours
- **Purpose**: Measures runner productivity
- **Target**: Higher values indicate better efficiency
- **Unit**: Orders per hour

## Service Quality Metrics

### 5. On-Time Rate vs Promised ETA
- **Formula**: % delivered ≤ quoted time
- **Purpose**: Measures service reliability
- **Target**: Higher values indicate better service quality
- **Unit**: Percentage

### 6. Delivery Cycle Time (P50/P90)
- **Formula**: Delivered_at − Order_placed_at
- **Purpose**: Measures total delivery time from order to delivery
- **Target**: Lower values indicate faster service
- **Unit**: Minutes (50th and 90th percentiles)

### 7. Dispatch Delay
- **Formula**: Runner_assigned_at − Ready_at
- **Purpose**: Measures time between order ready and runner dispatch
- **Target**: Lower values indicate better operational efficiency
- **Unit**: Minutes

### 8. Travel Time
- **Formula**: Delivered_at − Depart_at
- **Purpose**: Measures actual travel time to delivery location
- **Target**: Lower values indicate better routing efficiency
- **Unit**: Minutes

### 9. Failed Rate
- **Formula**: Failed orders ÷ Total orders
- **Purpose**: Measures order failure rate
- **Target**: Lower values indicate better reliability
- **Unit**: Percentage

## Operational Metrics

### 10. Runner Utilization Mix
- **Formula**: % driving / waiting at kitchen / handoff / deadhead
- **Purpose**: Measures how runners spend their time
- **Target**: Optimize mix for efficiency
- **Unit**: Percentage breakdown

### 11. Distance per Delivery
- **Formula**: Total distance ÷ number of deliveries
- **Purpose**: Measures average delivery distance
- **Target**: Lower values indicate better routing
- **Unit**: Meters or minutes

### 12. Queue Depth & Wait at Kitchen
- **Formula**: Orders waiting; avg wait time
- **Purpose**: Measures kitchen congestion
- **Target**: Lower values indicate better capacity management
- **Unit**: Number of orders, minutes

### 13. Capacity per 15-min Window
- **Formula**: Maximum orders in any 15-minute window before SLA breach
- **Purpose**: Measures peak capacity requirements
- **Target**: Higher values indicate better capacity planning
- **Unit**: Orders per 15-minute window

## Financial Analysis

### 14. Second-Runner Break-Even
- **Formula**: Marginal contribution ≥ marginal labor
- **Purpose**: Determines when adding a second runner is profitable
- **Target**: Lower values indicate easier break-even
- **Unit**: Orders needed for break-even

## Zone Analysis

### 15. Zone Heatmap from Clubhouse
- **Formula**: Service time by hole/cluster
- **Purpose**: Identifies service time patterns by location
- **Target**: Identify optimization opportunities
- **Unit**: Average service time per hole/zone

## Usage Instructions

### Running Simulations with Metrics

1. **Basic Simulation with Metrics**:
   ```bash
   python scripts/sim/phase_06_runner_plus_one_group/run_runner_phase6_with_metrics.py \
     --course-dir courses/pinetree_country_club \
     --num-runs 10 \
     --revenue-per-order 25.0 \
     --sla-minutes 30
   ```

2. **Custom Parameters**:
   ```bash
   python scripts/sim/phase_06_runner_plus_one_group/run_runner_phase6_with_metrics.py \
     --course-dir courses/pinetree_country_club \
     --num-runs 20 \
     --order-hole 8 \
     --prep-time 8 \
     --runner-speed 7.0 \
     --revenue-per-order 30.0 \
     --sla-minutes 25 \
     --service-hours 12.0
   ```

### Analyzing Existing Results

1. **Analyze Simulation Output**:
   ```bash
   python scripts/analysis/analyze_delivery_runner_metrics.py \
     outputs/delivery_runner_phase6_with_metrics \
     --output-dir outputs/delivery_runner_analysis \
     --revenue-per-order 25.0 \
     --sla-minutes 30
   ```

2. **Custom Analysis Parameters**:
   ```bash
   python scripts/analysis/analyze_delivery_runner_metrics.py \
     outputs/delivery_runner_phase6_with_metrics \
     --output-dir outputs/custom_analysis \
     --revenue-per-order 30.0 \
     --sla-minutes 25 \
     --service-hours 12.0
   ```

## Output Files

### Individual Run Files
- `delivery_metrics_run_XX.json` - Raw metrics data
- `delivery_metrics_run_XX.md` - Human-readable metrics report
- `stats_run_XX.md` - Enhanced simulation statistics
- `results.json` - Complete simulation results

### Summary Files
- `comprehensive_delivery_metrics_summary.md` - Complete summary report
- `delivery_runner_metrics_summary.md` - Metrics-focused summary
- `summary.md` - Traditional simulation summary

## Configuration Parameters

### Revenue and Financial
- `revenue_per_order`: Revenue per successful order (default: $25.0)
- `sla_minutes`: Service level agreement time (default: 30 minutes)

### Operational
- `service_hours`: Active service hours for runner (default: 10.0 hours)
- `prep_time_min`: Food preparation time (default: 10 minutes)
- `runner_speed_mps`: Runner speed in meters/second (default: 6.0)

### Simulation
- `num_runs`: Number of simulation runs (default: 10)
- `order_hole`: Specific hole for orders (default: random)
- `course_dir`: Course directory path

## Interpreting Results

### Key Performance Indicators

1. **High RPR + High Order Penetration**: Excellent revenue performance
2. **Low On-Time Rate**: Service quality issues, need capacity improvement
3. **High Failed Rate**: Operational problems, need process improvement
4. **Low Runner Utilization**: Inefficient operations, need optimization
5. **High Queue Depth**: Capacity constraints, need additional staffing

### Optimization Opportunities

1. **Route Optimization**: Look for high travel times or distances
2. **Capacity Planning**: Analyze 15-minute window capacity
3. **Staffing Decisions**: Use second-runner break-even analysis
4. **Service Quality**: Focus on on-time rate and cycle time improvements

## Integration with Other Phases

### Phase 2: Single Runner + One Group
- Use for baseline single-runner performance
- Compare with multi-runner scenarios

### Phase 3: Single Runner + Multiple Groups
- Analyze capacity under increased demand
- Identify bottlenecks and optimization opportunities

### Phase 4: Multiple Runners
- Compare single vs. multi-runner performance
- Validate second-runner break-even calculations

## Advanced Analysis

### Custom Metrics
You can extend the metrics system by adding custom calculations:

```python
from golfsim.analysis.delivery_runner_metrics import calculate_delivery_runner_metrics

# Calculate base metrics
metrics = calculate_delivery_runner_metrics(
    delivery_stats=delivery_stats,
    activity_log=activity_log,
    orders=orders,
    failed_orders=failed_orders,
    revenue_per_order=25.0,
    sla_minutes=30,
)

# Add custom calculations
custom_metric = metrics.total_revenue / metrics.active_runner_hours
print(f"Revenue per hour: ${custom_metric:.2f}")
```

### Batch Analysis
For large-scale analysis, you can process multiple simulation directories:

```python
from golfsim.analysis.delivery_runner_metrics import analyze_multiple_simulations

# Analyze multiple simulation directories
metrics_list = analyze_multiple_simulations(
    root_dir=Path("outputs/multiple_simulations"),
    output_dir=Path("outputs/analysis"),
    revenue_per_order=25.0,
    sla_minutes=30,
)

# Process results
for metrics in metrics_list:
    print(f"{metrics.simulation_id}: RPR=${metrics.revenue_per_round:.2f}")
```

## Best Practices

### 1. Consistent Parameters
- Use the same revenue and SLA parameters across comparisons
- Document parameter choices for reproducibility

### 2. Sample Size
- Run at least 10 simulations for reliable statistics
- Use 20+ runs for detailed analysis

### 3. Parameter Sensitivity
- Test different SLA times to understand trade-offs
- Vary runner speed to find optimal settings

### 4. Comparative Analysis
- Compare different scenarios (single vs. multi-runner)
- Analyze before/after optimization changes

## Troubleshooting

### Common Issues

1. **No Metrics Generated**:
   - Check that simulation completed successfully
   - Verify delivery_stats or orders data exists
   - Ensure proper file paths and permissions

2. **Incorrect Calculations**:
   - Verify input data format and types
   - Check parameter values (revenue, SLA, etc.)
   - Review activity log for proper activity types

3. **Missing Data**:
   - Ensure simulation tracks coordinates and activity logs
   - Check that orders and delivery_stats are generated
   - Verify file naming conventions

### Debug Mode
Enable debug logging for detailed analysis:

```bash
python scripts/sim/phase_06_runner_plus_one_group/run_runner_phase6_with_metrics.py \
  --log-level DEBUG \
  --course-dir courses/pinetree_country_club \
  --num-runs 1
```

## Performance Considerations

### Large Simulations
- For 100+ runs, consider batch processing
- Use JSON output for programmatic analysis
- Monitor memory usage with large datasets

### Data Storage
- Metrics files are typically small (< 1MB each)
- Consider archiving old simulation results
- Use compression for long-term storage

## Future Enhancements

### Planned Features
1. **Real-time Metrics**: Live dashboard for ongoing simulations
2. **Predictive Analytics**: Forecast capacity needs
3. **Cost Analysis**: Detailed cost breakdown per delivery
4. **Customer Satisfaction**: Simulated customer feedback metrics

### Extensibility
The metrics system is designed to be easily extended with new calculations and analysis methods. See the source code for examples of how to add custom metrics.
