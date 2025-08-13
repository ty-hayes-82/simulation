# Lazy imports to avoid geopandas dependency at package level
def _lazy_import():
    """Lazy import function for heavy dependencies"""
    try:
        from .data.osm_ingest import build_cartpath_graph, load_course
        from .preprocess.course_model import build_traditional_route
        from .routing.networks import shortest_path_on_cartpaths
        from .simulation.engine import run_simulation
        return {
            "load_course": load_course,
            "build_cartpath_graph": build_cartpath_graph, 
            "build_traditional_route": build_traditional_route,
            "shortest_path_on_cartpaths": shortest_path_on_cartpaths,
            "run_simulation": run_simulation,
        }
    except ImportError as e:
        raise ImportError(f"Heavy dependencies not available: {e}. Install with 'pip install geopandas'")

# Always available imports (no heavy dependencies)
from .tools import CourseDataGenerator

# Define what's available at package level
__all__ = [
    "load_course",
    "build_cartpath_graph", 
    "build_traditional_route",
    "shortest_path_on_cartpaths",
    "run_simulation",
    "CourseDataGenerator",
]

def __getattr__(name):
    """Dynamic attribute access for lazy imports"""
    if name in ["load_course", "build_cartpath_graph", "build_traditional_route", 
                "shortest_path_on_cartpaths", "run_simulation"]:
        _imports = _lazy_import()
        return _imports[name]
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
