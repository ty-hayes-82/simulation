#!/usr/bin/env python3
"""
Simulation Asset Sync Script

Implements the strategy defined in my-map-animation/docs/simulation_asset_sync_strategy.md
to sync simulation outputs from output/ into my-map-animation/public/coordinates/
"""

from pathlib import Path
import json
import re
import shutil
from typing import Dict, List, Optional, Tuple
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
OUTPUT_DIR = Path('output')
DEST_DIR = Path('my-map-animation/public/coordinates')
ALLOWED_VARIANTS = {'none', 'front', 'back', 'front_mid', 'front_back', 'front_mid_back'}

# Course mapping - can be extended as needed
COURSE_NAMES = {
    'keswick_hall': 'Keswick Hall',
    'pinetree_country_club': 'Pinetree Country Club',
    'gates_four': 'Gates Four',
    'idle_hour': 'Idle Hour',
    'purgatory': 'Purgatory'
}

def latest_timestamp_dir(course_dir: Path) -> Optional[Path]:
    """Find the latest timestamp directory for a course."""
    if not course_dir.exists():
        return None
    
    candidates = [d for d in course_dir.iterdir() if d.is_dir()]
    if not candidates:
        return None
    
    # Sort by name (timestamp format should sort correctly lexicographically)
    return max(candidates, key=lambda x: x.name)

def get_best_run_dir(variant_dir: Path) -> Optional[Path]:
    """
    Select the best run directory from a variant.
    Prefers run_01 for determinism, but could be enhanced to use @aggregate.json
    """
    run_01 = variant_dir / 'run_01'
    if run_01.exists():
        return run_01
    
    # Fallback to any available run
    run_dirs = [d for d in variant_dir.iterdir() if d.is_dir() and d.name.startswith('run_')]
    if run_dirs:
        return sorted(run_dirs)[0]
    
    return None

def get_group_geojson(variant_dir: Path) -> Optional[Path]:
    """Find the aggregated hole_delivery_times.geojson in the group directory."""
    agg_geojson = variant_dir / 'hole_delivery_times.geojson'
    if agg_geojson.exists():
        return agg_geojson
    return None

def aggregate_metrics(metrics_list: List[Dict]) -> Dict:
    """
    Aggregate metrics from multiple runs into a single metrics object.
    Calculates means, standard deviations, and confidence intervals where appropriate.
    """
    if not metrics_list:
        return {}
    
    if len(metrics_list) == 1:
        return metrics_list[0]
    
    # Start with the structure of the first metrics object
    aggregated = json.loads(json.dumps(metrics_list[0]))  # Deep copy
    
    # Helper function to safely get numeric values
    def get_numeric(obj: Dict, key: str, default: float = 0.0) -> float:
        val = obj.get(key, default)
        return float(val) if isinstance(val, (int, float)) and not (isinstance(val, float) and (val != val or val == float('inf') or val == float('-inf'))) else default
    
    # Aggregate delivery metrics
    if 'deliveryMetrics' in aggregated:
        dm_values = []
        for metrics in metrics_list:
            if 'deliveryMetrics' in metrics:
                dm_values.append(metrics['deliveryMetrics'])
        
        if dm_values:
            dm = aggregated['deliveryMetrics']
            
            # Calculate aggregated values
            total_orders = sum(get_numeric(d, 'totalOrders') for d in dm_values)
            successful_deliveries = sum(get_numeric(d, 'successfulDeliveries') for d in dm_values)
            failed_deliveries = sum(get_numeric(d, 'failedDeliveries') for d in dm_values)
            
            # Weighted averages for time-based metrics
            on_time_rates = [get_numeric(d, 'onTimePercentage', get_numeric(d, 'onTimeRate')) for d in dm_values]
            avg_order_times = [get_numeric(d, 'avgOrderTime') for d in dm_values]
            queue_waits = [get_numeric(d, 'queueWaitAvg') for d in dm_values]
            
            # Update aggregated metrics
            dm.update({
                'totalOrders': total_orders,
                'successfulDeliveries': successful_deliveries,
                'failedDeliveries': failed_deliveries,
                'onTimePercentage': sum(on_time_rates) / len(on_time_rates) if on_time_rates else 0,
                'onTimeRate': sum(on_time_rates) / len(on_time_rates) if on_time_rates else 0,
                'avgOrderTime': sum(avg_order_times) / len(avg_order_times) if avg_order_times else 0,
                'queueWaitAvg': sum(queue_waits) / len(queue_waits) if queue_waits else 0,
                'revenue': sum(get_numeric(d, 'revenue') for d in dm_values),
                'runCount': len(metrics_list),
                'onTimeRateStdDev': (sum((x - (sum(on_time_rates) / len(on_time_rates)))**2 for x in on_time_rates) / len(on_time_rates))**0.5 if len(on_time_rates) > 1 else 0,
            })
            
            # Add percentile aggregations if available
            p90_times = [get_numeric(d, 'deliveryCycleTimeP90', get_numeric(d, 'p90_mean')) for d in dm_values if get_numeric(d, 'deliveryCycleTimeP90', get_numeric(d, 'p90_mean')) > 0]
            if p90_times:
                dm['deliveryCycleTimeP90'] = sum(p90_times) / len(p90_times)
            
            # Add efficiency metrics
            orders_per_hour = [get_numeric(d, 'ordersPerRunnerHour') for d in dm_values if get_numeric(d, 'ordersPerRunnerHour') > 0]
            if orders_per_hour:
                dm['ordersPerRunnerHour'] = sum(orders_per_hour) / len(orders_per_hour)
            
            revenue_per_hour = [get_numeric(d, 'revenuePerRunnerHour') for d in dm_values if get_numeric(d, 'revenuePerRunnerHour') > 0]
            if revenue_per_hour:
                dm['revenuePerRunnerHour'] = sum(revenue_per_hour) / len(revenue_per_hour)
    
    # Add aggregation metadata
    aggregated['aggregationInfo'] = {
        'runCount': len(metrics_list),
        'aggregatedAt': json.dumps(datetime.now().isoformat()),
        'sourceRuns': [f"run_{i+1:02d}" for i in range(len(metrics_list))]
    }
    
    return aggregated

def transform_aggregate_json(agg_data: Dict) -> Dict:
    """
    Transforms the structure of an @aggregate.json file to match what the frontend expects.
    - Wraps metrics in a 'deliveryMetrics' object.
    - Converts snake_case keys to camelCase.
    - Calculates derived fields like revenue, late orders, and failed order counts.
    """
    # --- Calculations ---
    runs = agg_data.get('runs', 1)
    if runs == 0: runs = 1 # Avoid division by zero

    total_orders_sum = agg_data.get('total_orders', 0)
    successful_deliveries_sum = agg_data.get('total_successful_orders', 0)
    
    # Calculate averages per run
    avg_orders_per_run = total_orders_sum / runs
    avg_successful_per_run = successful_deliveries_sum / runs
    
    on_time_mean = agg_data.get('on_time_mean', 0) # This is on_time_deliveries / successful_deliveries
    failed_mean = agg_data.get('failed_mean', 0)

    # Correct on-time percentage to be out of total orders, not just successful ones.
    # (on_time / successful) * (successful / total) = on_time / total
    if avg_orders_per_run > 0:
        corrected_on_time_pct = on_time_mean * (avg_successful_per_run / avg_orders_per_run)
    else:
        corrected_on_time_pct = 0
    
    # Calculate derived metrics based on averages
    # Assume $30 per successful order if revenue is not present
    revenue = agg_data.get('revenue', avg_successful_per_run * 30)
    late_orders = round(avg_successful_per_run * (1 - on_time_mean))
    failed_deliveries_count = round(avg_orders_per_run * failed_mean)

    # Calculate drive and shift minutes
    total_drive_time_seconds = sum(agg_data.get('total_drive_time_per_hole', {}).values())
    avg_drive_time_seconds_per_run = (total_drive_time_seconds / runs) if runs > 0 else 0
    avg_drive_minutes_per_run = avg_drive_time_seconds_per_run / 60
    shift_minutes = agg_data.get('totalRunnerShiftMinutes', 420)

    # --- Key Mappings ---
    dm = {
        'totalOrders': round(avg_orders_per_run),
        'successfulDeliveries': round(avg_successful_per_run),
        'onTimePercentage': corrected_on_time_pct * 100,
        'failedDeliveries': failed_deliveries_count,
        'lateOrders': late_orders,
        'deliveryCycleTimeP90': agg_data.get('p90_mean', 0),
        'avgOrderTime': agg_data.get('avg_delivery_time_mean', 0),
        'ordersPerRunnerHour': agg_data.get('oph_mean', 0),
        'queueWaitAvg': agg_data.get('avg_queue_wait_minutes', 0),
        'revenue': revenue,
        'totalRunnerDriveMinutes': avg_drive_minutes_per_run,
        'totalRunnerShiftMinutes': shift_minutes
    }

    # Nested mappings for runner utilization
    if 'runner_utilization_imbalance' in agg_data and 'mean' in agg_data['runner_utilization_imbalance']:
        dm['runnerUtilizationPct'] = agg_data['runner_utilization_imbalance']['mean']

    # Include run count for display
    if 'runs' in agg_data:
        dm['runCount'] = agg_data['runs']

    # --- Final Formatting ---
    # Ensure values that should be integers are rounded
    for key in ['totalOrders', 'successfulDeliveries', 'lateOrders', 'failedDeliveries']:
        if key in dm:
            dm[key] = round(dm[key])
            
    return {
        'deliveryMetrics': dm,
        'hasRunners': True,
        'hasBevCart': False
    }


def scan_course(course_id: str, course_name: str) -> List[Dict]:
    """Scan a course directory and return simulation entries."""
    # Clear previous assets for this course
    logger.info(f"Clearing previous assets for course: {course_id}")
    deleted_count = 0
    for old_file in DEST_DIR.glob(f"{course_id}__*"):
        try:
            old_file.unlink()
            deleted_count += 1
        except OSError as e:
            logger.error(f"Error deleting file {old_file}: {e}")
    if deleted_count > 0:
        logger.info(f"Cleared {deleted_count} old asset files for {course_id}.")

    course_dir = OUTPUT_DIR / course_id
    if not course_dir.exists():
        logger.warning(f"Course directory not found: {course_dir}")
        return []
    
    # Find latest timestamp
    ts_dir = latest_timestamp_dir(course_dir)
    if not ts_dir:
        logger.warning(f"No timestamp directories found for course: {course_id}")
        return []
    
    logger.info(f"Using timestamp directory: {ts_dir}")
    
    # Process both first_pass and second_pass directories
    pass_dirs = []
    for pass_name in ['first_pass', 'second_pass']:
        pass_dir = ts_dir / pass_name
        if pass_dir.exists():
            pass_dirs.append((pass_name, pass_dir))
    
    if not pass_dirs:
        logger.warning(f"No pass directories found in: {ts_dir}")
        return []
    
    logger.info(f"Processing pass directories: {[p[0] for p in pass_dirs]}")
    
    simulations = []
    
    # Process each pass directory
    for pass_name, pass_dir in pass_dirs:
        logger.info(f"Processing {pass_name} directory: {pass_dir}")
        
        # Scan orders directories
        for orders_dir in sorted(pass_dir.glob('orders_*')):
            orders_match = re.search(r'orders_(\d+)', orders_dir.name)
            if not orders_match:
                continue
            orders = int(orders_match.group(1))
            
            # Scan runners directories
            for runners_dir in sorted(orders_dir.glob('runners_*')):
                runners_match = re.search(r'runners_(\d+)', runners_dir.name)
                if not runners_match:
                    continue
                runners = int(runners_match.group(1))
                
                # Scan variant directories
                for variant_dir in sorted(runners_dir.iterdir()):
                    if not variant_dir.is_dir():
                        continue
                    
                    variant = variant_dir.name
                    if variant not in ALLOWED_VARIANTS:
                        continue
                    
                    # --- MODIFICATION START ---
                    # Prioritize loading from @aggregate.json if it exists
                    agg_metrics_src = variant_dir / '@aggregate.json'
                    aggregated_metrics = None
                    run_count = 0
                    representative_run = None

                    if agg_metrics_src.exists():
                        logger.info(f"Found @aggregate.json, using it as the source of truth for: {variant_dir}")
                        try:
                            with open(agg_metrics_src, 'r') as f:
                                raw_agg_metrics = json.load(f)
                            
                            # Transform the metrics to the frontend-compatible structure
                            aggregated_metrics = transform_aggregate_json(raw_agg_metrics)

                            # Determine run count from the file or by counting folders
                            run_dirs = [d for d in variant_dir.iterdir() if d.is_dir() and d.name.startswith('run_')]
                            run_count = raw_agg_metrics.get('runs', len(run_dirs))

                            # Still need a representative run for coordinates
                            run_01_dir = variant_dir / 'run_01'
                            if run_01_dir.exists() and (run_01_dir / 'coordinates.csv').exists():
                                representative_run = run_01_dir
                            elif run_dirs:
                                representative_run = sorted(run_dirs)[0]

                        except Exception as e:
                            logger.warning(f"Could not process {agg_metrics_src}: {e}. Falling back to run-by-run aggregation.")
                            aggregated_metrics = None # Reset to trigger fallback

                    if aggregated_metrics is None:
                        # Fallback to original method: aggregate from individual runs
                        logger.info(f"Aggregating metrics run-by-run for: {variant_dir}")
                        run_dirs = [d for d in variant_dir.iterdir() if d.is_dir() and d.name.startswith('run_')]
                        if not run_dirs:
                            logger.warning(f"No run directories found in: {variant_dir}")
                            continue
                        
                        all_metrics = []
                        for run_dir in sorted(run_dirs):
                            metrics_src = run_dir / 'simulation_metrics.json'
                            if not metrics_src.exists():
                                logger.warning(f"Missing simulation_metrics.json in: {run_dir}")
                                continue
                            try:
                                with open(metrics_src, 'r') as f:
                                    all_metrics.append(json.load(f))
                                if representative_run is None: # Set representative run from first valid run dir
                                    # Prefer run_01 for deterministic animation coordinates
                                    run_01_dir = variant_dir / 'run_01'
                                    if run_01_dir.exists() and (run_01_dir / 'coordinates.csv').exists():
                                        representative_run = run_01_dir
                                    else:
                                        representative_run = run_dir
                            except Exception as e:
                                logger.warning(f"Error loading metrics from {metrics_src}: {e}")

                        if not all_metrics:
                            logger.warning(f"No valid metrics files found for: {variant_dir}")
                            continue

                        aggregated_metrics = aggregate_metrics(all_metrics)
                        run_count = len(all_metrics)

                    if not aggregated_metrics or not representative_run:
                        logger.warning(f"Could not produce aggregated metrics for: {variant_dir}")
                        continue
                    
                    # Build base filename
                    base = f"{course_id}__{pass_name}__orders_{orders:03d}__runners_{runners}__{variant}"
                    
                    # Define destination files
                    csv_dst = DEST_DIR / f"{base}__run_01.csv"
                    metrics_dst = DEST_DIR / f"{base}.metrics.json"
                    geojson_dst = DEST_DIR / f"{base}.hole_delivery.geojson"
                    
                    # Copy files from representative run
                    logger.info(f"Processing {run_count} runs for: {base}")
                    try:
                        # Copy coordinate file from representative run
                        shutil.copy2(representative_run / 'coordinates.csv', csv_dst)
                        
                        # Write the aggregated metrics (either from @aggregate.json or calculated)
                        with open(metrics_dst, 'w') as f:
                            json.dump(aggregated_metrics, f, indent=2)
                        
                        # Check for aggregated geojson at the group level
                        has_geojson = False
                        agg_geojson_src = get_group_geojson(variant_dir)
                        if agg_geojson_src:
                            shutil.copy2(agg_geojson_src, geojson_dst)
                            has_geojson = True
                        
                        # Create simulation entry
                        sim_entry = {
                            'id': base,
                            'name': f"{course_name} — {pass_name} — {orders} orders — {runners} runners — {variant} (avg of {run_count} runs)",
                            'filename': csv_dst.name,
                            'metricsFilename': metrics_dst.name,
                            'variantKey': variant,
                            'meta': {
                                'runners': runners, 
                                'orders': orders,
                                'pass': pass_name,
                                'runCount': run_count
                            },
                            'courseId': course_id,
                            'courseName': course_name,
                        }
                        
                        if has_geojson:
                            sim_entry['holeDeliveryGeojson'] = geojson_dst.name
                        
                        simulations.append(sim_entry)
                        logger.info(f"Successfully processed: {base} (aggregated {run_count} runs)")
                        
                    except Exception as e:
                        logger.error(f"Error processing {base}: {e}")
                        continue
    
    return simulations

def generate_manifest(all_simulations: List[Dict]) -> Dict:
    """Generate the manifest.json structure."""
    # Build courses list from discovered course IDs
    course_ids = set(sim['courseId'] for sim in all_simulations)
    courses = []
    for course_id in sorted(course_ids):
        course_name = COURSE_NAMES.get(course_id, course_id.replace('_', ' ').title())
        courses.append({'id': course_id, 'name': course_name})
    
    manifest = {
        'courses': courses,
        'simulations': all_simulations
    }
    
    return manifest

def main():
    """Main sync function."""
    logger.info("Starting simulation asset sync...")
    
    # Ensure destination directory exists
    DEST_DIR.mkdir(parents=True, exist_ok=True)
    
    # Discover courses from output directory
    if not OUTPUT_DIR.exists():
        logger.error(f"Output directory not found: {OUTPUT_DIR}")
        return
    
    course_dirs = [d for d in OUTPUT_DIR.iterdir() if d.is_dir()]
    if not course_dirs:
        logger.error("No course directories found in output/")
        return
    
    all_simulations = []
    
    # Process each course
    for course_dir in course_dirs:
        course_id = course_dir.name
        course_name = COURSE_NAMES.get(course_id, course_id.replace('_', ' ').title())
        
        logger.info(f"Processing course: {course_id} ({course_name})")
        simulations = scan_course(course_id, course_name)
        all_simulations.extend(simulations)
    
    if not all_simulations:
        logger.warning("No simulations found to sync")
        return
    
    # Generate and write manifest
    manifest = generate_manifest(all_simulations)
    manifest_path = DEST_DIR / 'manifest.json'
    
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    
    logger.info(f"Generated manifest with {len(all_simulations)} simulations")
    logger.info(f"Manifest written to: {manifest_path}")
    
    # Summary
    course_count = len(manifest['courses'])
    logger.info(f"Sync complete: {course_count} courses, {len(all_simulations)} simulations")

if __name__ == '__main__':
    main()
