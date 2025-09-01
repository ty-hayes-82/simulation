import argparse
import json
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


# -----------------------------
# Helpers and data structures
# -----------------------------

@dataclass
class RunPaths:
    run_dir: Path
    report_dir: Path
    results_json: Path
    simulation_metrics_json: Path
    delivery_runner_metrics_json: Optional[Path]
    coordinates_csv: Optional[Path]


def discover_run_paths(run_dir: Path) -> RunPaths:
    results_json = run_dir / "results.json"
    simulation_metrics_json = run_dir / "simulation_metrics.json"
    # delivery_runner_metrics filename may vary by run number
    delivery_runner_metrics_json = None
    for candidate in run_dir.glob("delivery_runner_metrics_*.json"):
        delivery_runner_metrics_json = candidate
        break
    coordinates_csv = run_dir / "coordinates.csv"
    if not coordinates_csv.exists():
        coordinates_csv = None

    report_dir = run_dir / "report"
    return RunPaths(
        run_dir=run_dir,
        report_dir=report_dir,
        results_json=results_json,
        simulation_metrics_json=simulation_metrics_json,
        delivery_runner_metrics_json=delivery_runner_metrics_json,
        coordinates_csv=coordinates_csv,
    )


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def load_json(path: Path) -> Optional[dict]:
    if not path or not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_text(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write(text)


def write_json(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# -----------------------------
# Parsers for standardized logs
# -----------------------------

def export_orders_events(results: dict, out_csv: Path) -> None:
    """
    Convert minimal per-order metrics from results.json to a tidy events CSV.
    If fine-grained events are unavailable, synthesize a minimal lifecycle:
      created -> queued -> assigned -> picked_up -> delivered
    using available timestamps: order_time_s, queue_time_s, drive_time_s.
    """
    orders = results.get("orders", []) if isinstance(results, dict) else []

    header = (
        "ts,order_id,event,queue,runner_id,hole,prep_sla_s,delivered_sla_s\n"
    )
    lines: List[str] = [header]

    for o in orders:
        order_id = str(o.get("order_id", ""))
        placed_hole = o.get("placed_hole")
        delivered_hole = o.get("delivered_hole")
        order_time_s = o.get("order_time_s")
        queue_time_s = o.get("queue_time_s")
        drive_time_s = o.get("drive_time_s")

        # Synthesize timestamps (seconds since day start). We do not have absolute clock; keep seconds.
        if order_time_s is None:
            continue

        created_ts = order_time_s
        queued_ts = created_ts + 1  # minimal separation
        assigned_ts = created_ts + max(1, int(queue_time_s or 0))
        picked_ts = assigned_ts + 1
        delivered_ts = created_ts + max(1, int((queue_time_s or 0) + (drive_time_s or 0)))

        queue_name = infer_queue_from_hole(placed_hole)

        # created
        lines.append(
            f"{created_ts},{order_id},created,{queue_name},,{placed_hole},,,\n"
        )
        # queued
        lines.append(f"{queued_ts},{order_id},queued,{queue_name},,{placed_hole},,,\n")
        # assigned
        lines.append(
            f"{assigned_ts},{order_id},assigned,{queue_name},,{placed_hole},,\n"
        )
        # picked_up
        lines.append(
            f"{picked_ts},{order_id},picked_up,{queue_name},,{placed_hole},,\n"
        )
        # delivered
        lines.append(
            f"{delivered_ts},{order_id},delivered,{queue_name},,{delivered_hole},,,\n"
        )

    write_text(out_csv, "".join(lines))


def infer_queue_from_hole(hole: Optional[int]) -> str:
    if hole is None:
        return "unknown"
    try:
        h = int(hole)
    except Exception:
        return "unknown"
    # Heuristic: 1-9 front_9, 10-18 back_9, else clubhouse/unknown
    if 1 <= h <= 9:
        return "front_9"
    if 10 <= h <= 18:
        return "back_9"
    return "unknown"


def export_runner_states(coordinates_csv: Optional[Path], out_csv: Path) -> None:
    """
    Parse coordinates.csv to extract runner rows and export to standardized runner states CSV.
    Input columns: id, latitude, longitude, timestamp, type, hole, ...
    Output columns: ts, runner_id, state, hole, order_id, lat, lon, speed_mps
    Note: We cannot infer state from this file; default to moving when consecutive, else idle.
    """
    header_out = "ts,runner_id,state,hole,order_id,lat,lon,speed_mps\n"
    if not coordinates_csv or not coordinates_csv.exists():
        write_text(out_csv, header_out)
        return

    lines_out: List[str] = [header_out]

    def parse_line(line: str) -> Optional[Tuple[str, float, float, float, str, str]]:
        parts = line.strip().split(",")
        if len(parts) < 6:
            return None
        _id = parts[0]
        try:
            lat = float(parts[1])
            lon = float(parts[2])
            ts = float(parts[3])
        except Exception:
            return None
        typ = parts[4]
        hole = parts[5]
        return _id, lat, lon, ts, typ, hole

    # Read and filter runner rows
    with coordinates_csv.open("r", encoding="utf-8") as f:
        header_in = f.readline()
        prev_by_runner: Dict[str, Tuple[float, float, float]] = {}
        for raw in f:
            parsed = parse_line(raw)
            if not parsed:
                continue
            _id, lat, lon, ts, typ, hole = parsed
            if typ != "runner":
                continue
            runner_id = _id
            # speed estimate from previous point (m/s) using haversine
            prev = prev_by_runner.get(runner_id)
            speed = ""
            state = "idle"
            if prev:
                prev_lat, prev_lon, prev_ts = prev
                dt = ts - prev_ts
                if dt > 0:
                    dist_m = haversine_meters(prev_lat, prev_lon, lat, lon)
                    spd = dist_m / dt
                    speed = f"{spd:.3f}"
                    state = "moving" if spd > 0.3 else "idle"
            prev_by_runner[runner_id] = (lat, lon, ts)

            lines_out.append(
                f"{ts},{runner_id},{state},{hole},,{lat},{lon},{speed}\n"
            )

    write_text(out_csv, "".join(lines_out))


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def export_queue_levels(orders_events_csv: Path, out_csv: Path) -> None:
    """
    Reconstruct queue time series from orders_events.csv.
    Output columns: ts,queue,length,max_wait_s,arrivals,assignments,abandons
    """
    import csv

    header = "ts,queue,length,max_wait_s,arrivals,assignments,abandons\n"
    if not orders_events_csv.exists():
        write_text(out_csv, header)
        return

    events = []
    with orders_events_csv.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                row['ts'] = int(float(row['ts']))
                events.append(row)
            except (ValueError, TypeError):
                continue
    
    if not events:
        write_text(out_csv, header)
        return

    events.sort(key=lambda x: x['ts'])
    
    all_queues = sorted(list(set(e['queue'] for e in events if e.get('queue'))))
    
    t_start = int(events[0]['ts'] // 60 * 60)
    t_end = int(events[-1]['ts'] // 60 * 60)
    
    lines = [header]
    
    queues_state = {q: {} for q in all_queues}  # {order_id: queued_ts}
    
    event_idx = 0
    
    for t_bucket in range(t_start, t_end + 61, 60):
        # Update state up to t_bucket
        while event_idx < len(events) and events[event_idx]['ts'] < t_bucket:
            event = events[event_idx]
            q_name = event.get('queue')
            oid = event['order_id']
            if q_name in queues_state:
                if event['event'] == 'queued':
                    queues_state[q_name][oid] = event['ts']
                elif event['event'] == 'assigned':
                    if oid in queues_state[q_name]:
                        del queues_state[q_name][oid]
            event_idx += 1
        
        # Record state and bucket events for all queues
        for q_name in all_queues:
            q_content = queues_state.get(q_name, {})
            length = len(q_content)
            max_wait_s = 0
            if length > 0:
                waits = [t_bucket - queued_ts for queued_ts in q_content.values()]
                if waits:
                    max_wait_s = max(waits)
            
            # Count events in bucket [t_bucket, t_bucket + 60)
            arrivals = 0
            assignments = 0
            abandons = 0
            
            temp_idx = event_idx
            while temp_idx < len(events) and events[temp_idx]['ts'] < t_bucket + 60:
                event = events[temp_idx]
                if event.get('queue') == q_name:
                    if event['event'] == 'queued':
                        arrivals += 1
                    elif event['event'] == 'assigned':
                        assignments += 1
                    elif event['event'] == 'abandoned':
                        abandons += 1
                temp_idx += 1
            
            assignments_str = str(assignments) if assignments > 0 else ""
            abandons_str = str(abandons) if abandons > 0 else ""
            
            lines.append(f"{t_bucket},{q_name},{length},{int(max_wait_s)},{arrivals},{assignments_str},{abandons_str}\n")
    
    write_text(out_csv, "".join(lines))


# -----------------------------
# KPIs and report generation
# -----------------------------

def build_kpis(results: Optional[dict], sim_metrics: Optional[dict]) -> dict:
    kpis: Dict[str, Optional[float]] = {}
    if sim_metrics:
        dm = sim_metrics.get("deliveryMetrics") or {}
        kpis.update({
            "totalOrders": dm.get("totalOrders") or sim_metrics.get("total_orders"),
            "successfulDeliveries": dm.get("successfulDeliveries") or sim_metrics.get("successful_orders"),
            "failedDeliveries": dm.get("failedDeliveries") or sim_metrics.get("failed_orders"),
            "avgOrderTimeMin": dm.get("avgOrderTime") or sim_metrics.get("delivery_cycle_time_avg"),
            "onTimePct": dm.get("onTimePercentage") or (sim_metrics.get("on_time_rate") and sim_metrics.get("on_time_rate") * 100),
            "runnerUtilizationPct": dm.get("runnerUtilizationPct") or sim_metrics.get("runner_utilization_driving_pct"),
        })
    # Derive p95 if results have per-order times
    if results and isinstance(results.get("orders"), list):
        durations = []
        for o in results["orders"]:
            val = o.get("total_completion_time_s")
            if isinstance(val, (int, float)):
                durations.append(val / 60.0)
        if durations:
            durations.sort()
            p95 = durations[int(0.95 * (len(durations) - 1))]
            median = durations[len(durations)//2]
            kpis["delivery_minutes_median"] = round(median, 3)
            kpis["delivery_minutes_p95"] = round(p95, 3)
    return kpis


def build_enhanced_html(run_dir: Path, kpis: dict) -> str:
    """
    Build enhanced HTML report with interactive charts using Plotly.
    """
    html = f'''
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8" />
    <title>Golf Delivery Simulation Report</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        body {{ 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif; 
            margin: 0; padding: 0; background: #f8f9fa; 
        }}
        .container {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}
        .header {{ background: white; padding: 24px; border-radius: 8px; margin-bottom: 24px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .header h1 {{ margin: 0 0 8px 0; color: #333; }}
        .header .subtitle {{ color: #666; }}
        .tabs {{ display: flex; background: white; border-radius: 8px 8px 0 0; margin-bottom: 0; }}
        .tab {{ padding: 12px 24px; cursor: pointer; border-bottom: 3px solid transparent; }}
        .tab.active {{ border-bottom-color: #007bff; background: #f8f9fa; }}
        .tab-content {{ background: white; padding: 24px; border-radius: 0 0 8px 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .tab-pane {{ display: none; }}
        .tab-pane.active {{ display: block; }}
        .kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }}
        .kpi-card {{ background: #f8f9fa; padding: 16px; border-radius: 6px; text-align: center; }}
        .kpi-value {{ font-size: 24px; font-weight: bold; color: #333; }}
        .kpi-label {{ font-size: 12px; color: #666; text-transform: uppercase; }}
        .chart-container {{ margin: 16px 0; height: 400px; }}
        .download-links {{ margin-top: 24px; }}
        .download-links a {{ 
            display: inline-block; margin-right: 12px; padding: 8px 16px; 
            background: #007bff; color: white; text-decoration: none; border-radius: 4px; 
        }}
        .download-links a:hover {{ background: #0056b3; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Golf Delivery Simulation Report</h1>
            <div class="subtitle">Run: {run_dir.name} • Generated: {Path(__file__).stat().st_mtime}</div>
        </div>
        
        <div class="tabs">
            <div class="tab active" onclick="showTab('overview')">Overview</div>
            <div class="tab" onclick="showTab('orders')">Orders</div>
            <div class="tab" onclick="showTab('queues')">Queues</div>
            <div class="tab" onclick="showTab('runners')">Runners</div>
            <div class="tab" onclick="showTab('download')">Download</div>
        </div>
        
        <div class="tab-content">
            <div id="overview" class="tab-pane active">
                <div class="kpi-grid">
                    <div class="kpi-card">
                        <div class="kpi-value">{kpis.get('totalOrders', 'N/A')}</div>
                        <div class="kpi-label">Total Orders</div>
                    </div>
                    <div class="kpi-card">
                        <div class="kpi-value">{kpis.get('onTimePct', 'N/A')}{('%' if isinstance(kpis.get('onTimePct'), (int, float)) else '')}</div>
                        <div class="kpi-label">On-Time Rate</div>
                    </div>
                    <div class="kpi-card">
                        <div class="kpi-value">{kpis.get('delivery_minutes_median', 'N/A')}</div>
                        <div class="kpi-label">Median Delivery (min)</div>
                    </div>
                    <div class="kpi-card">
                        <div class="kpi-value">{kpis.get('delivery_minutes_p95', 'N/A')}</div>
                        <div class="kpi-label">P95 Delivery (min)</div>
                    </div>
                    <div class="kpi-card">
                        <div class="kpi-value">{kpis.get('runnerUtilizationPct', 'N/A')}{('%' if isinstance(kpis.get('runnerUtilizationPct'), (int, float)) else '')}</div>
                        <div class="kpi-label">Runner Utilization</div>
                    </div>
                </div>
                <div id="overview-chart" class="chart-container"></div>
            </div>
            
            <div id="orders" class="tab-pane">
                <h3>Order Timeline</h3>
                <div id="orders-chart" class="chart-container"></div>
                <p><em>Chart shows order lifecycle. Future versions will include detailed Gantt charts.</em></p>
            </div>
            
            <div id="queues" class="tab-pane">
                <h3>Queue Levels Over Time</h3>
                <div id="queues-chart" class="chart-container"></div>
            </div>
            
            <div id="runners" class="tab-pane">
                <h3>Runner Activity</h3>
                <div id="runners-chart" class="chart-container"></div>
                <p><em>Shows runner movement and state changes over time.</em></p>
            </div>
            
            <div id="download" class="tab-pane">
                <h3>Download Data</h3>
                <div class="download-links">
                    <a href="orders_events.csv">Orders Events CSV</a>
                    <a href="runner_states.csv">Runner States CSV</a>
                    <a href="queue_levels.csv">Queue Levels CSV</a>
                    <a href="kpis.json">KPIs JSON</a>
                </div>
                <p>Use these standardized files for custom analysis, Excel imports, or BI tools.</p>
            </div>
        </div>
    </div>

    <script>
        function showTab(tabName) {{
            // Hide all tab panes
            document.querySelectorAll('.tab-pane').forEach(pane => pane.classList.remove('active'));
            document.querySelectorAll('.tab').forEach(tab => tab.classList.remove('active'));
            
            // Show selected tab
            document.getElementById(tabName).classList.add('active');
            event.target.classList.add('active');
            
            // Load chart if needed
            if (tabName === 'overview') loadOverviewChart();
            else if (tabName === 'queues') loadQueuesChart();
            else if (tabName === 'orders') loadOrdersChart();
            else if (tabName === 'runners') loadRunnersChart();
        }}
        
        function loadOverviewChart() {{
            const trace = {{
                x: ['Total Orders', 'On-Time %', 'Median Delivery', 'P95 Delivery', 'Utilization %'],
                y: [
                    {kpis.get('totalOrders', 0)},
                    {kpis.get('onTimePct', 0)},
                    {kpis.get('delivery_minutes_median', 0)},
                    {kpis.get('delivery_minutes_p95', 0)},
                    {kpis.get('runnerUtilizationPct', 0)}
                ],
                type: 'bar',
                marker: {{ color: ['#28a745', '#ffc107', '#17a2b8', '#dc3545', '#6f42c1'] }}
            }};
            Plotly.newPlot('overview-chart', [trace], {{
                title: 'Key Performance Indicators',
                xaxis: {{ title: 'Metrics' }},
                yaxis: {{ title: 'Values' }}
            }});
        }}
        
        function loadQueuesChart() {{
            Plotly.newPlot('queues-chart', [{{
                x: [1, 2, 3, 4, 5],
                y: [0, 1, 3, 2, 1],
                type: 'scatter',
                mode: 'lines+markers',
                name: 'Queue Length'
            }}], {{
                title: 'Queue Levels (Placeholder - will load from CSV)',
                xaxis: {{ title: 'Time' }},
                yaxis: {{ title: 'Queue Length' }}
            }});
        }}
        
        function loadOrdersChart() {{
            Plotly.newPlot('orders-chart', [{{
                x: [1, 2, 3, 4, 5],
                y: [10, 15, 13, 17, 12],
                type: 'scatter',
                mode: 'lines+markers',
                name: 'Order Rate'
            }}], {{
                title: 'Order Processing Timeline (Placeholder - will load from CSV)',
                xaxis: {{ title: 'Time' }},
                yaxis: {{ title: 'Orders' }}
            }});
        }}
        
        function loadRunnersChart() {{
            Plotly.newPlot('runners-chart', [{{
                x: ['Runner 1', 'Runner 2'],
                y: [{kpis.get('runnerUtilizationPct', 0)}, {kpis.get('runnerUtilizationPct', 0)}],
                type: 'bar',
                marker: {{ color: '#17a2b8' }}
            }}], {{
                title: 'Runner Utilization',
                xaxis: {{ title: 'Runner' }},
                yaxis: {{ title: 'Utilization %' }}
            }});
        }}
        
        // Load initial chart
        loadOverviewChart();
    </script>
</body>
</html>
'''
    
    return html


# -----------------------------
# CLI
# -----------------------------

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build standardized logs and report for a simulation run")
    parser.add_argument("--run-dir", required=True, help="Path to a specific run directory (contains results.json)")
    parser.add_argument("--emit-csv", action="store_true", help="Emit standardized CSVs")
    parser.add_argument("--html", action="store_true", help="Emit minimal HTML report")
    parser.add_argument("--pdf", action="store_true", help="Emit PDF (future; placeholder)")
    args = parser.parse_args(argv)

    run_dir = Path(args.run_dir).resolve()
    paths = discover_run_paths(run_dir)
    ensure_dir(paths.report_dir)

    results = load_json(paths.results_json)
    sim_metrics = load_json(paths.simulation_metrics_json)

    if args.emit_csv:
        orders_events_csv_path = paths.report_dir / "orders_events.csv"
        export_orders_events(results or {}, orders_events_csv_path)
        export_runner_states(paths.coordinates_csv, paths.report_dir / "runner_states.csv")
        export_queue_levels(orders_events_csv_path, paths.report_dir / "queue_levels.csv")

    kpis = build_kpis(results, sim_metrics)
    write_json(paths.report_dir / "kpis.json", kpis)

    if args.html:
        html = build_enhanced_html(paths.run_dir, kpis)
        write_text(paths.report_dir / "report.html", html)

    # pdf placeholder
    if args.pdf:
        # For now, write a placeholder note; later implement WeasyPrint/Chromium export
        write_text(paths.report_dir / "summary.pdf.txt", "PDF export not yet implemented. Use report.html.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


