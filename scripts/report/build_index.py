import argparse
import json
from pathlib import Path
from typing import Dict, List, Optional


def discover_runs(scenario_dir: Path) -> List[Dict[str, str]]:
    """
    Scan scenario directory for run directories and their KPIs.
    Handles both flat and two-pass structures.
    """
    runs = []
    
    # Check for two-pass structure (first_pass/, second_pass/ subdirectories)
    pass_dirs = [d for d in scenario_dir.iterdir() if d.is_dir() and d.name.endswith("_pass")]
    
    search_dirs = pass_dirs if pass_dirs else [scenario_dir]
    
    for search_dir in search_dirs:
        for orders_dir in search_dir.glob("orders_*"):
            orders_level = orders_dir.name.replace("orders_", "")
            
            for runners_dir in orders_dir.glob("runners_*"):
                runner_count = runners_dir.name.replace("runners_", "")
                
                for variant_dir in runners_dir.iterdir():
                    if not variant_dir.is_dir():
                        continue
                    variant = variant_dir.name
                    
                    for run_dir in variant_dir.glob("run_*"):
                        kpis_path = run_dir / "report" / "kpis.json"
                        report_path = run_dir / "report" / "report.html"
                        
                        if kpis_path.exists():
                            try:
                                with kpis_path.open("r") as f:
                                    kpis = json.load(f)
                                
                                # Add pass information for two-pass structure
                                pass_name = search_dir.name if search_dir != scenario_dir else "single_pass"
                                variant_display = f"{variant} ({pass_name})" if pass_dirs else variant
                                
                                runs.append({
                                    "orders_level": orders_level,
                                    "runner_count": runner_count,
                                    "variant": variant_display,
                                    "run_id": run_dir.name,
                                    "kpis": kpis,
                                    "report_url": str(report_path.relative_to(scenario_dir)) if report_path.exists() else "",
                                    "run_path": str(run_dir.relative_to(scenario_dir))
                                })
                            except Exception as e:
                                print(f"Warning: Could not load KPIs from {kpis_path}: {e}")
    
    return runs


def build_index_html(runs: List[Dict], scenario_name: str) -> str:
    """Generate comparison index HTML with run cards in a grid"""
    
    # Group by orders_level and runner_count for matrix layout
    matrix: Dict[str, Dict[str, List[Dict]]] = {}
    for run in runs:
        orders = run["orders_level"]
        runners = run["runner_count"]
        matrix.setdefault(orders, {}).setdefault(runners, []).append(run)
    
    # Build cards HTML
    cards_html = ""
    for orders_level in sorted(matrix.keys()):
        cards_html += f'<h3>Orders Level: {orders_level}</h3>\n<div class="row">\n'
        
        for runner_count in sorted(matrix[orders_level].keys()):
            run_group = matrix[orders_level][runner_count]
            
            # Take first run's KPIs as representative (could aggregate later)
            if run_group:
                kpis = run_group[0]["kpis"]
                report_url = run_group[0]["report_url"]
                
                # Extract key metrics with fallbacks
                total_orders = kpis.get("totalOrders", "N/A")
                on_time_pct = kpis.get("onTimePct", "N/A")
                if isinstance(on_time_pct, (int, float)):
                    on_time_pct = f"{on_time_pct:.1f}%"
                
                delivery_p95 = kpis.get("delivery_minutes_p95", "N/A")
                if isinstance(delivery_p95, (int, float)):
                    delivery_p95 = f"{delivery_p95:.1f} min"
                
                utilization = kpis.get("runnerUtilizationPct", "N/A")
                if isinstance(utilization, (int, float)):
                    utilization = f"{utilization:.1f}%"
                
                # Color coding for on-time percentage
                color_class = "good"
                if isinstance(kpis.get("onTimePct"), (int, float)):
                    if kpis["onTimePct"] < 80:
                        color_class = "poor"
                    elif kpis["onTimePct"] < 90:
                        color_class = "fair"
                
                cards_html += f'''
                <div class="card {color_class}">
                    <h4>{runner_count} Runners</h4>
                    <div class="metrics">
                        <div>Orders: {total_orders}</div>
                        <div>On-time: {on_time_pct}</div>
                        <div>P95 delivery: {delivery_p95}</div>
                        <div>Utilization: {utilization}</div>
                    </div>
                    <div class="variants">
                        {len(run_group)} run(s): {", ".join([r["variant"] for r in run_group])}
                    </div>
                    <div class="actions">
                        {'<a href="' + report_url + '" class="btn">View Report</a>' if report_url else '<span class="btn disabled">No Report</span>'}
                    </div>
                </div>
                '''
        
        cards_html += '</div>\n'
    
    html = f'''
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8" />
    <title>Simulation Scenario Comparison - {scenario_name}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 24px; background: #f8f9fa; }}
        h1 {{ color: #333; margin-bottom: 0.5rem; }}
        h3 {{ color: #555; margin-top: 2rem; margin-bottom: 1rem; }}
        .subtitle {{ color: #666; margin-bottom: 2rem; }}
        .row {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 2rem; }}
        .card {{ 
            background: white; 
            border-radius: 8px; 
            padding: 16px; 
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            min-width: 200px;
            border-left: 4px solid #ddd;
        }}
        .card.good {{ border-left-color: #28a745; }}
        .card.fair {{ border-left-color: #ffc107; }}
        .card.poor {{ border-left-color: #dc3545; }}
        .card h4 {{ margin: 0 0 12px 0; color: #333; }}
        .metrics div {{ margin: 4px 0; font-size: 14px; }}
        .variants {{ margin-top: 12px; font-size: 12px; color: #666; }}
        .actions {{ margin-top: 12px; }}
        .btn {{ 
            display: inline-block; 
            padding: 6px 12px; 
            background: #007bff; 
            color: white; 
            text-decoration: none; 
            border-radius: 4px; 
            font-size: 12px;
        }}
        .btn:hover {{ background: #0056b3; }}
        .btn.disabled {{ background: #6c757d; cursor: not-allowed; }}
    </style>
</head>
<body>
    <h1>Simulation Scenario Comparison</h1>
    <div class="subtitle">{scenario_name}</div>
    
    {cards_html}
    
    <div style="margin-top: 3rem; padding-top: 2rem; border-top: 1px solid #ddd; color: #666; font-size: 12px;">
        Generated by build_index.py • {len(runs)} total runs
    </div>
</body>
</html>
'''
    
    return html


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build scenario comparison index")
    parser.add_argument("--scenario-dir", required=True, help="Path to scenario directory (contains orders_XXX subdirs)")
    parser.add_argument("--html", action="store_true", help="Generate HTML index")
    args = parser.parse_args(argv)
    
    scenario_dir = Path(args.scenario_dir).resolve()
    scenario_name = scenario_dir.name
    
    runs = discover_runs(scenario_dir)
    print(f"Found {len(runs)} runs in {scenario_dir}")
    
    if args.html:
        html = build_index_html(runs, scenario_name)
        index_path = scenario_dir / "index.html"
        with index_path.open("w", encoding="utf-8") as f:
            f.write(html)
        print(f"Generated index at {index_path}")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
