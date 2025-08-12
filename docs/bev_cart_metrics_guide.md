# Beverage Cart Metrics Guide

This guide explains the comprehensive metrics system for beverage cart simulations, including all the metrics requested and how to use them.

## Overview

The beverage cart metrics system provides detailed analysis of cart performance, revenue, customer behavior, and operational efficiency. These metrics are calculated for every simulation and summarized across multiple runs.

## Core Metrics

### 1. Revenue per Round (RPR)
**Formula**: F&B revenue ÷ rounds in service window
- **Purpose**: Measures revenue generation efficiency per golf round
- **Target**: Higher values indicate better revenue performance
- **Example**: $24.47 per round means the cart generates $24.47 in revenue for each round of golf

### 2. Order Penetration Rate
**Formula**: Unique orders ÷ rounds (or groups)
- **Purpose**: Measures how many customers place orders relative to available opportunities
- **Target**: Values > 100% indicate multiple orders per round
- **Example**: 140% means 1.4 orders per round on average

### 3. Average Order Value (AOV)
**Formula**: Revenue ÷ orders
- **Purpose**: Measures the typical transaction size
- **Target**: Higher values indicate better revenue per transaction
- **Example**: $15.71 average order value

### 4. Orders per Cart Hour
**Formula**: Orders ÷ active cart hours
- **Purpose**: Measures operational efficiency and throughput
- **Target**: Higher values indicate better utilization
- **Example**: 0.38 orders per hour means the cart processes 0.38 orders per hour of operation

### 5. Tip Rate / Tips per Order
**Formulas**: 
- Tip Rate: Tips ÷ revenue
- Tips per Order: Tips ÷ orders
- **Purpose**: Measures gratuity performance
- **Target**: Industry standard is typically 15-20%
- **Example**: 15% tip rate with $2.36 tips per order

### 6. Holes Covered per Hour / Minutes per Hole per Cart
**Formulas**:
- Holes Covered per Hour: Total holes covered ÷ service hours
- Minutes per Hole per Cart: (Service hours × 60) ÷ total holes covered
- **Purpose**: Measures course coverage efficiency
- **Target**: Higher coverage indicates better course presence
- **Example**: 2.25 holes per hour, 26.7 minutes per hole

### 7. Golfer Repeat Rate & Frequency
**Formulas**:
- Golfer Repeat Rate: Buyers with ≥2 orders ÷ total buyers
- Average Orders per Customer: Total orders ÷ unique customers
- **Purpose**: Measures customer loyalty and repeat business
- **Target**: Higher values indicate better customer retention
- **Example**: 10% repeat rate, 1.10 orders per customer

### 8. Golfer Visibility Interval
**Formula**: Average time between cart sightings (GPS proximity 60–80m for ≥30s)
- **Purpose**: Measures how often golfers see the cart
- **Target**: Lower intervals indicate better visibility
- **Example**: 0.0 minutes (no visibility events in bev-cart only simulation)

## Usage

### Running Simulations with Metrics

1. **Enhanced Phase 1 Simulation**:
   ```bash
   python scripts/sim/phase_01_beverage_cart_only/run_bev_cart_phase1_with_metrics.py
   ```

2. **Analyzing Existing Results**:
   ```bash
   python scripts/analysis/analyze_bev_cart_metrics.py outputs/your_simulation_directory
   ```

### Output Files

Each simulation generates:
- `metrics_report.md`: Individual simulation metrics
- `bev_cart_metrics.json`: Machine-readable metrics data
- `comprehensive_metrics_summary.md`: Summary across all simulations

### Configuration Options

The metrics system supports several configuration parameters:

```python
metrics = calculate_bev_cart_metrics(
    sales_data=sales_data,
    coordinates=coordinates,
    golfer_data=golfer_data,  # Optional for visibility metrics
    service_start_s=7200,     # 9 AM
    service_end_s=36000,      # 5 PM
    simulation_id="unique_id",
    cart_id="bev_cart_1",
    tip_rate_percentage=15.0,  # Default tip rate
    proximity_threshold_m=70.0,  # Visibility distance
    proximity_duration_s=30     # Minimum visibility duration
)
```

## Interpreting Results

### Revenue Performance
- **High RPR**: Cart is generating good revenue per round
- **High AOV**: Customers are spending well per transaction
- **High Orders/Hour**: Cart is efficiently processing orders

### Operational Efficiency
- **High Holes/Hour**: Cart covers more of the course
- **Low Minutes/Hole**: Cart spends appropriate time at each location
- **Good Visibility**: Cart is seen frequently by golfers

### Customer Behavior
- **High Repeat Rate**: Customers return for multiple purchases
- **High Penetration**: Most customers place orders
- **Good Tips**: Customers are satisfied with service

## Integration with Other Phases

The metrics system can be integrated with other simulation phases:

### Phase 3+ (Beverage Cart + Golfers)
- Real sales data from golfer interactions
- Actual visibility events from GPS proximity
- Customer behavior based on real encounters

### Phase 5+ (Multiple Groups)
- More complex customer patterns
- Higher order volumes
- Better statistical significance

### Phase 11+ (Multiple Carts)
- Per-cart metrics comparison
- System-wide efficiency analysis
- Resource allocation optimization

## Advanced Analysis

### Statistical Summaries
The system provides statistical summaries across multiple simulations:
- Mean, min, max values for each metric
- Confidence intervals for key performance indicators
- Trend analysis across different scenarios

### Custom Metrics
You can extend the system with custom metrics by:
1. Adding new fields to the `BevCartMetrics` dataclass
2. Implementing calculation logic in `calculate_bev_cart_metrics()`
3. Updating the reporting functions

### Data Export
Metrics can be exported in multiple formats:
- JSON for programmatic analysis
- Markdown for human-readable reports
- CSV for spreadsheet analysis

## Best Practices

1. **Run Multiple Simulations**: Use at least 5-10 runs for statistical significance
2. **Compare Scenarios**: Test different configurations to find optimal settings
3. **Monitor Trends**: Track metrics over time to identify improvements
4. **Set Targets**: Establish performance targets for each metric
5. **Validate Results**: Cross-check metrics with business logic

## Troubleshooting

### Common Issues
- **Zero Visibility Events**: Normal for bev-cart only simulations
- **Low Revenue**: Check sales data generation and probabilities
- **High Penetration Rates**: May indicate unrealistic order frequencies

### Debugging
- Enable verbose logging with `--verbose` flag
- Check individual simulation reports for details
- Validate input data formats and completeness

## Future Enhancements

Potential improvements to the metrics system:
- Real-time metrics calculation during simulation
- Integration with course-specific benchmarks
- Weather and seasonal adjustment factors
- Customer satisfaction scoring
- Predictive analytics for demand forecasting
