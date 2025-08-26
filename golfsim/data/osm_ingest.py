"""
OSM ingestion utilities:
- Load a course polygon and golf features (holes, tees, greens).
- Build a cart-path graph constrained to the course polygon.
"""

from __future__ import annotations

import warnings
from typing import Dict, List, Optional, Tuple, Callable, Any
import time
import requests

import geopandas as gpd
import networkx as nx
import osmnx as ox
import shapely
from shapely.geometry import Point, Polygon

from golfsim.logging import get_logger

logger = get_logger(__name__)

# Overpass/requests timeouts (seconds)
OVERPASS_TIMEOUT = 180
REQUESTS_TIMEOUT = (15, 90)  # (connect, read)
OVERPASS_ENDPOINTS: List[str] = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
]

def _preflight_reachable_endpoints(candidates: List[str], connect_timeout_sec: float = 3.0) -> List[str]:
    """Probe Overpass endpoints quickly and prioritize those that respond.

    If none respond quickly, return the original list to allow normal retries.
    """
    reachable: List[str] = []
    for ep in candidates:
        try:
            status_url = ep.replace("/interpreter", "/status")
            requests.get(status_url, timeout=(connect_timeout_sec, 5))
            reachable.append(ep)
            continue
        except Exception:
            pass
        try:
            probe = "[out:json];node(1);out;"
            requests.post(ep, data={"data": probe}, timeout=(connect_timeout_sec, 5))
            reachable.append(ep)
        except Exception:
            pass
    return reachable if reachable else candidates

def _with_overpass_retries(operation: Callable[[], Any], desc: str, max_attempts: int = 5, sleep_base_sec: float = 1.5) -> Any:
    last_exc: Optional[BaseException] = None
    endpoints: List[str] = []
    try:
        if isinstance(ox.settings.overpass_endpoint, str) and ox.settings.overpass_endpoint:
            endpoints.append(ox.settings.overpass_endpoint)
    except Exception:
        pass
    for ep in OVERPASS_ENDPOINTS:
        if ep not in endpoints:
            endpoints.append(ep)

    # Prefer endpoints that look reachable right now
    endpoints = _preflight_reachable_endpoints(endpoints)

    for attempt in range(max_attempts):
        endpoint = endpoints[attempt % len(endpoints)]
        try:
            # Configure settings for both OSMnx v1 and v2 APIs
            try:
                ox.settings.requests_timeout = REQUESTS_TIMEOUT  # v2
            except Exception:
                pass
            try:
                ox.settings.timeout = OVERPASS_TIMEOUT  # v1 (deprecated in v2)
            except Exception:
                pass
            try:
                ox.settings.overpass_url = endpoint  # v2
            except Exception:
                pass
            try:
                ox.settings.overpass_endpoint = endpoint  # v1 (deprecated in v2)
            except Exception:
                pass

            # Avoid osmnx internal /status polling which can fail behind firewalls
            ox.settings.overpass_rate_limit = False
            ox.settings.use_cache = True
            ox.settings.log_console = False

            result = operation()
            try:
                import pandas as _pd  # type: ignore
                if isinstance(result, _pd.DataFrame) and getattr(result, "empty", False):
                    raise RuntimeError("Empty Overpass result: " + desc)
            except Exception:
                pass
            return result
        except Exception as e:
            last_exc = e
            wait = min(20.0, sleep_base_sec * (2 ** attempt))
            logger.warning(
                "Overpass op failed (%s) on %s [attempt %d/%d]: %s; retrying in %.1fs",
                desc,
                endpoint,
                attempt + 1,
                max_attempts,
                str(e),
                wait,
            )
            time.sleep(wait)

    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"Overpass operation failed with unknown error: {desc}")

def _features_from_polygon_retry(polygon, tags: Dict[str, str | List[str] | bool]):
    return _with_overpass_retries(lambda: ox.features_from_polygon(polygon, tags=tags), desc=f"features_from_polygon tags={tags}")

def _features_from_place_retry(place: str, tags: Dict[str, str | List[str] | bool]):
    return _with_overpass_retries(lambda: ox.features_from_place(place, tags=tags), desc=f"features_from_place place={place} tags={tags}")

def _features_from_bbox_retry(bbox: Tuple[float, float, float, float], tags: Dict[str, str | List[str] | bool]):
    return _with_overpass_retries(lambda: ox.features_from_bbox(*bbox, tags=tags), desc=f"features_from_bbox bbox={bbox} tags={tags}")

def _graph_from_polygon_retry(polygon, custom_filter: Optional[str] = None, simplify: bool = True, retain_all: bool = True):
    return _with_overpass_retries(
        lambda: ox.graph_from_polygon(polygon, custom_filter=custom_filter, simplify=simplify, retain_all=retain_all),
        desc=f"graph_from_polygon filter={custom_filter}",
    )


def _geoms_from_place_or_bbox(
    tags: Dict[str, str | List[str]],
    within: Optional[str] = None,
    bbox: Optional[Tuple[float, float, float, float]] = None,
    state: Optional[str] = None,
    center_lat: Optional[float] = None,
    center_lon: Optional[float] = None,
    radius_km: float = 10.0,
) -> gpd.GeoDataFrame:
    if (
        within is None
        and bbox is None
        and state is None
        and (center_lat is None or center_lon is None)
    ):
        raise ValueError(
            "Provide either 'within' (place string), 'state' (state name), 'bbox' (west, south, east, north), or coordinates (center_lat, center_lon)."
        )

    # Prefer 'within' when provided to avoid large radius coordinate searches
    if within:
        # Try multiple geographic search areas
        search_areas = [
            within,
            "Kennesaw, Georgia, USA",  # Try more specific
            "Cobb County, Georgia, USA",  # Try county level
            "Georgia, USA",  # Try state level as fallback
        ]

        for area in search_areas:
            try:
                logger.info("Searching in: %s", area)
                result = _features_from_place_retry(area, tags)
                if len(result) > 0:
                    logger.info("Found %d features in %s", len(result), area)
                    return result
                else:
                    logger.warning("No features found in %s", area)
            except Exception as e:
                logger.error("Search failed in %s: %s", area, e)

        # If all searches failed, raise an error
        raise ValueError(f"No features found in any of the search areas: {search_areas}")
    elif center_lat is not None and center_lon is not None:
        # Search around coordinates using a buffer
        logger.info(
            "Searching around coordinates: %s, %s (radius: %.1f km)", center_lat, center_lon, radius_km
        )

        # Create a buffer around the point to search within
        center_point = Point(center_lon, center_lat)  # Point takes (lon, lat)

        # Convert to projected CRS for buffering (meters)
        center_gdf = gpd.GeoDataFrame([1], geometry=[center_point], crs="EPSG:4326")
        center_projected = center_gdf.to_crs("EPSG:3857")  # Web Mercator

        # Create buffer in meters (radius_km * 1000)
        buffer_m = radius_km * 1000
        buffered = center_projected.buffer(buffer_m)

        # Convert back to lat/lon
        buffer_gdf = gpd.GeoDataFrame([1], geometry=buffered, crs="EPSG:3857")
        buffer_latlon = buffer_gdf.to_crs("EPSG:4326")
        search_polygon = buffer_latlon.geometry.iloc[0]

        try:
            result = _features_from_polygon_retry(search_polygon, tags)
            if len(result) > 0:
                logger.info("Found %d features around coordinates", len(result))
                return result
            else:
                logger.warning("No features found around coordinates")
                raise ValueError(
                    f"No features found around coordinates {center_lat}, {center_lon} within {radius_km} km"
                )
        except Exception as e:
            logger.error("Search failed around coordinates: %s", e)
            raise ValueError(f"Search failed around coordinates {center_lat}, {center_lon}: {e}")
    elif state:
        # Search across the entire state for golf courses
        search_areas = [f"{state}, USA", state]

        for area in search_areas:
            try:
                logger.info("Searching across state: %s", area)
                result = _features_from_place_retry(area, tags)
                if len(result) > 0:
                    logger.info("Found %d features in %s", len(result), area)
                    return result
                else:
                    logger.warning("No features found in %s", area)
            except Exception as e:
                logger.error("Search failed in %s: %s", area, e)

        # If state search failed, raise an error
        raise ValueError(f"No features found in any of the state search areas: {search_areas}")
    else:
        return _features_from_bbox_retry(bbox, tags)


def features_within_radius(
    tags: Dict[str, str | List[str] | bool],
    center_lat: float,
    center_lon: float,
    radius_m: float,
) -> gpd.GeoDataFrame:
    """
    Query OSM features matching 'tags' within a circular buffer of radius_m around
    the provided center point (clubhouse coordinates).

    Args:
        tags: OSM tag dictionary (e.g., {"leisure": "pitch"} or {"natural": "water", "water": True})
        center_lat: Latitude of center point
        center_lon: Longitude of center point
        radius_m: Search radius in meters

    Returns:
        GeoDataFrame of matching features (possibly empty) in EPSG:4326
    """
    try:
        center_point = Point(center_lon, center_lat)
        center_gdf = gpd.GeoDataFrame([1], geometry=[center_point], crs="EPSG:4326")
        center_projected = center_gdf.to_crs("EPSG:3857")
        buffered = center_projected.buffer(radius_m)
        buffer_gdf = gpd.GeoDataFrame([1], geometry=buffered, crs="EPSG:3857")
        buffer_latlon = buffer_gdf.to_crs("EPSG:4326")
        search_polygon = buffer_latlon.geometry.iloc[0]

        result = _features_from_polygon_retry(search_polygon, tags)
        # Normalize CRS
        if not result.empty:
            result = result.to_crs("EPSG:4326")
        logger.info("Found %d features within %.1fm for tags=%s", len(result), radius_m, tags)
        return result
    except Exception as e:
        logger.error("Failed to fetch features within radius: %s", e)
        return gpd.GeoDataFrame()


def _ensure_polygon(gdf: gpd.GeoDataFrame) -> gpd.GeoSeries:
    polys = gdf[gdf.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    if len(polys) == 0:
        raise ValueError("No polygon geometries found for course.")
    return polys.geometry.unary_union


def _course_polygon_by_name(
    course_name: str,
    within: str | None = None,
    bbox=None,
    state: str | None = None,
    center_lat: float | None = None,
    center_lon: float | None = None,
    radius_km: float = 10.0,
) -> Polygon:
    """
    Try to fetch the golf course polygon by name (exact or fuzzy) and leisure=golf_course tag.
    """
    tags = {"leisure": "golf_course"}
    gdf = _geoms_from_place_or_bbox(
        tags,
        within=within,
        bbox=bbox,
        state=state,
        center_lat=center_lat,
        center_lon=center_lon,
        radius_km=radius_km,
    )

    logger.info("Found %d golf courses in area", len(gdf))
    if "name" in gdf.columns:
        # Debug: show all available course names
        available_names = gdf["name"].dropna().tolist()
        logger.info("Available course names: %s", available_names)

        # Try multiple search strategies for the specific course name
        search_strategies = []
        if "pinetree" in course_name.lower():
            search_strategies = [
                course_name,  # Exact search: "Pinetree Country Club"
                "Pinetree Country Club",  # Explicit
                "Pinetree",  # Just the first part
                "Pine Tree",  # With space
                "pinetree",  # Lowercase
            ]
        else:
            search_strategies = [course_name]  # For other courses, just try the exact name

        sub = gdf.iloc[0:0]  # Empty dataframe
        for search_term in search_strategies:
            logger.info("Trying search term: '%s'", search_term)
            temp_sub = gdf[gdf["name"].astype(str).str.contains(search_term, case=False, na=False)]
            if len(temp_sub) > 0:
                logger.info("Found match with '%s': %s", search_term, temp_sub['name'].iloc[0])
                sub = temp_sub
                break
    else:
        sub = gdf.iloc[0:0]
        logger.warning("No 'name' column found in golf course data")

    if len(sub) == 0:
        # Debug: show details about what we're falling back to
        candidates = gdf[gdf.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
        if len(candidates) == 0:
            raise ValueError("Could not find leisure=golf_course polygons in the given area.")
        # If coordinates are provided, choose the nearest polygon to the clubhouse
        chosen = None
        if center_lat is not None and center_lon is not None:
            logger.warning("No name matches found. Choosing nearest golf_course polygon to given coordinates.")

            # Compute haversine distance to centroid for each candidate
            def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
                import math
                phi1 = math.radians(lat1)
                phi2 = math.radians(lat2)
                dphi = math.radians(lat2 - lat1)
                dlambda = math.radians(lon2 - lon1)
                a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
                c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
                return 6371000.0 * c

            distances: List[Tuple[float, int]] = []
            for idx, row in candidates.iterrows():
                try:
                    centroid = row.geometry.centroid
                    d = _haversine_m(center_lon, center_lat, float(centroid.x), float(centroid.y))
                    distances.append((d, idx))
                except Exception:
                    continue
            if distances:
                distances.sort(key=lambda t: t[0])
                nearest_idx = distances[0][1]
                chosen = candidates.loc[[nearest_idx]]
                logger.info(
                    "Nearest candidate: %s (%.1fm)",
                    chosen.iloc[0].get("name", "Unnamed"),
                    distances[0][0],
                )

        if chosen is None:
            # Fallback to largest area when coordinates are not provided or distances unavailable
            candidates["area"] = candidates.geometry.area
            candidates = candidates.sort_values("area", ascending=False)
            logger.warning("No name matches found. Available courses by size:")
            for idx, row in candidates.head(3).iterrows():
                course_name_fallback = row.get("name", "Unnamed")
                area = row["area"]
                logger.info("  - %s (area: %.6f)", course_name_fallback, area)
            chosen = candidates.head(1)
            warnings.warn(
                f"Course by name not found. Using largest golf_course polygon: {chosen['name'].iloc[0] if 'name' in chosen.columns else 'Unnamed'}"
            )
        return _ensure_polygon(chosen)
    return _ensure_polygon(sub)


def load_course(
    course_name: str,
    within: Optional[str] = None,
    bbox: Optional[Tuple[float, float, float, float]] = None,
    state: Optional[str] = None,
    center_lat: Optional[float] = None,
    center_lon: Optional[float] = None,
    radius_km: float = 10.0,
    include_cart_paths: bool = False,
    cartpath_geojson: Optional[str] = None,
    broaden: bool = False,
    include_streets: bool = False,
) -> Dict[str, gpd.GeoDataFrame | shapely.geometry.base.BaseGeometry | nx.Graph]:
    """
    Returns a dict with:
    - 'course_poly': course polygon
    - 'holes': holes (golf=hole), may include 'ref' for hole number
    - 'tees': points (golf=tee)
    - 'greens': polygons/points (golf=green)
    - 'cart_graph': NetworkX graph of cart paths (if include_cart_paths=True)
    - 'streets': GeoDataFrame of nearby streets (if include_streets=True)
    """
    course_poly = _course_polygon_by_name(
        course_name,
        within=within,
        bbox=bbox,
        state=state,
        center_lat=center_lat,
        center_lon=center_lon,
        radius_km=radius_km,
    )

    # Holes, tees, greens inside polygon
    tags = {"golf": ["hole", "tee", "green"]}
    gdf = _features_from_polygon_retry(course_poly, tags)

    holes = gdf[gdf["golf"] == "hole"].copy()
    tees = gdf[gdf["golf"] == "tee"].copy()
    greens = gdf[gdf["golf"] == "green"].copy()

    # Normalize geometry types for tees/greens
    tees = tees.to_crs(3857)
    greens = greens.to_crs(3857)
    holes = holes.to_crs(3857)
    course_poly_3857 = gpd.GeoSeries([course_poly], crs=4326).to_crs(3857).iloc[0]
    # Add small buffer (100m) to capture holes near the boundary
    buffered_course_poly = course_poly_3857.buffer(100)

    # Keep only within buffered polygon - use intersects for more permissive filtering
    # This helps capture holes that might extend slightly beyond the course boundary
    tees = tees[tees.geometry.intersects(buffered_course_poly)]
    greens = greens[greens.geometry.intersects(buffered_course_poly)]
    holes = holes[holes.geometry.intersects(buffered_course_poly)]

    # Back to lat/lon
    tees = tees.to_crs(4326)
    greens = greens.to_crs(4326)
    holes = holes.to_crs(4326)

    # Build the result dictionary
    result = {
        "course_poly": course_poly,
        "holes": holes.reset_index(drop=True),
        "tees": tees.reset_index(drop=True),
        "greens": greens.reset_index(drop=True),
    }

    # Optionally include cart paths
    if include_cart_paths:
        cart_graph = build_cartpath_graph(
            course_poly, cartpath_geojson=cartpath_geojson, broaden=broaden
        )
        result["cart_graph"] = cart_graph

    if include_streets:
        logger.info("Fetching nearby streets...")
        streets_gdf = _get_streets_near_course(course_poly, buffer_dist_m=500)
        result["streets"] = streets_gdf
        logger.info("Found %d street segments", len(streets_gdf))

    return result


def _get_streets_near_course(
    course_poly, buffer_dist_m: float = 500, course_buffer_m: float = 100
) -> gpd.GeoDataFrame:
    """
    Get streets within a certain buffer of the course polygon, filtered to only include
    streets that are within course_buffer_m of the actual course boundary.

    Args:
        course_poly: Course polygon (Polygon or MultiPolygon)
        buffer_dist_m: Search buffer for finding streets (default 500m)
        course_buffer_m: Filter buffer - only keep streets within this distance of course (default 100m)
    """
    # Buffer the course polygon for search
    course_gdf = gpd.GeoDataFrame([1], geometry=[course_poly], crs="EPSG:4326")
    course_proj = course_gdf.to_crs("EPSG:3857")
    search_buffered_proj = course_proj.buffer(buffer_dist_m)
    search_buffered_gdf = gpd.GeoDataFrame([1], geometry=search_buffered_proj, crs="EPSG:3857")
    search_buffered_poly = search_buffered_gdf.to_crs("EPSG:4326").iloc[0].geometry

    # Define street types to query
    street_tags = {
        "highway": ["residential", "primary", "secondary", "tertiary", "unclassified", "service"]
    }

    # Query OSM for streets within the search buffer
    try:
        streets_gdf = _features_from_polygon_retry(search_buffered_poly, street_tags)
        # Filter to LineString geometries
        streets_gdf = streets_gdf[streets_gdf.geometry.type == 'LineString']

        if len(streets_gdf) == 0:
            logger.warning("No streets found in search area")
            return gpd.GeoDataFrame()

        logger.info(
            "Found %d streets in search area, filtering to course boundary...",
            len(streets_gdf),
        )

        # Create a smaller buffer around the course for filtering streets
        filter_buffered_proj = course_proj.buffer(course_buffer_m)
        filter_buffered_gdf = gpd.GeoDataFrame([1], geometry=filter_buffered_proj, crs="EPSG:3857")
        filter_buffered_poly = filter_buffered_gdf.to_crs("EPSG:4326").iloc[0].geometry

        # Filter streets to only those that intersect with the course boundary buffer
        streets_gdf = streets_gdf.to_crs("EPSG:4326")

        # Check which streets intersect with the course boundary buffer
        intersects_course = streets_gdf.geometry.intersects(filter_buffered_poly)
        filtered_streets = streets_gdf[intersects_course].copy()

        logger.info(
            "Filtered to %d streets within %dm of course boundary",
            len(filtered_streets),
            course_buffer_m,
        )

        return filtered_streets.reset_index(drop=True)

    except Exception as e:
        logger.error("Could not fetch streets: %s", e)
        return gpd.GeoDataFrame()


def build_cartpath_graph(
    course_poly: Polygon, cartpath_geojson: Optional[str] = None, broaden: bool = False
) -> nx.Graph:
    """
    Build a graph representing cart paths within the course polygon.

    Strategy:
    1) If a custom GeoJSON is provided, build graph from its LineString/MultiLineString.
    2) Else, query OSM for path/track/service/footway within course polygon and build a graph.
       If 'broaden=True', include residential/tertiary service ways as fallback.

    Returns an undirected NetworkX graph with 'length' on edges and 'x','y' on nodes.
    """
    if cartpath_geojson:
        gdf = gpd.read_file(cartpath_geojson)
        lines = gdf[gdf.geom_type.isin(["LineString", "MultiLineString"])].to_crs(4326)
        G = nx.Graph()
        # Ensure CRS is set for downstream osmnx helpers (e.g., nearest_nodes)
        G.graph["crs"] = "EPSG:4326"
        for geom in lines.geometry:
            if geom.geom_type == "LineString":
                coords = list(geom.coords)
                _add_linestring_to_graph(G, coords)
            elif geom.geom_type == "MultiLineString":
                for part in geom.geoms:
                    coords = list(part.coords)
                    _add_linestring_to_graph(G, coords)
        return G

    # OSM approach - prioritize golf-specific cart path tags
    logger.info("Trying golf-specific cart path filters...")

    # Strategy 1: Golf cart paths (highest priority)
    logger.info("Searching for golf=cartpath features...")
    try:
        golf_paths = _features_from_polygon_retry(course_poly, tags={"golf": "cartpath"})
        if len(golf_paths) > 0:
            logger.info("Found %d golf cart path features", len(golf_paths))
            G = _build_graph_from_features(golf_paths)
        else:
            logger.warning("No golf=cartpath features found")
            G = nx.Graph()
    except Exception as e:
        logger.error("Error searching for golf=cartpath: %s", e)
        G = nx.Graph()

    # Strategy 2: Golf cart access ways
    if G.number_of_edges() == 0:
        logger.info("Searching for golf_cart=yes features...")
        try:
            golf_cart_ways = _features_from_polygon_retry(course_poly, tags={"golf_cart": "yes"})
            if len(golf_cart_ways) > 0:
                logger.info("Found %d golf_cart=yes features", len(golf_cart_ways))
                G = _build_graph_from_features(golf_cart_ways)
            else:
                logger.warning("No golf_cart=yes features found")
        except Exception as e:
            logger.error("Error searching for golf_cart=yes: %s", e)

    # Strategy 3: Combined golf cart path query
    if G.number_of_edges() == 0:
        logger.info("Trying combined golf cart path query...")
        try:
            # Try to get paths with golf cart characteristics within the polygon
            combined_tags = {"highway": "path", "golf_cart": True}
            combined_paths = _features_from_polygon_retry(course_poly, tags=combined_tags)
            if len(combined_paths) > 0:
                logger.info("Found %d highway=path with golf_cart features", len(combined_paths))
                G = _build_graph_from_features(combined_paths)
        except Exception as e:
            logger.error("Error with combined query: %s", e)

    # Strategy 4: Standard cart paths (fallback)
    if G.number_of_edges() == 0:
        logger.info("No golf-specific paths found, trying standard path filters...")
        base_filter = '["highway"~"path|track|service|footway"]'
        G = _try_build_graph_with_filter(course_poly, base_filter)

    if G.number_of_edges() == 0 and broaden:
        logger.info("No paths found with standard filter, trying broader search...")
        # Strategy 5: Include more road types
        broad_filter = '["highway"~"path|track|service|footway|residential|tertiary|unclassified|living_street"]'
        G = _try_build_graph_with_filter(course_poly, broad_filter)

    if G.number_of_edges() == 0:
        logger.info("Trying to find ANY ways within the course polygon...")
        # Strategy 6: Get all ways and filter manually
        try:
            # Get all features within the polygon
            all_ways = _features_from_polygon_retry(course_poly, tags={"highway": True})
            if len(all_ways) > 0:
                logger.info("Found %d total highway features", len(all_ways))
                # Build graph from LineString geometries
                G = _build_graph_from_features(all_ways)
            else:
                logger.warning("No highway features found in course polygon")
        except Exception as e:
            logger.error("Error getting all ways: %s", e)

    # Strategy 7: If still no edges, try to get individual path features
    if G.number_of_edges() == 0:
        logger.info("Searching for individual path features...")
        try:
            # Try to get path features individually
            path_tags = {
                "highway": ["path", "track", "footway", "cycleway"],
                "golf": ["cartpath"],
                "access": ["private", "permissive"],
            }
            for tag_key, tag_values in path_tags.items():
                features = _features_from_polygon_retry(course_poly, tags={tag_key: tag_values})
                if len(features) > 0:
                    logger.info("Found %d features with %s tags", len(features), tag_key)
                    temp_graph = _build_graph_from_features(features)
                    if temp_graph.number_of_edges() > 0:
                        # Merge with existing graph
                        G = nx.compose(G, temp_graph)
        except Exception as e:
            logger.error("Error searching for individual paths: %s", e)

    # Strategy 8: Create a basic connectivity network if we still have very few edges or many components
    components = list(nx.connected_components(G))
    # Only enhance if we have very few edges AND many small components (indicating truly sparse data)
    # Don't enhance if we found good golf-specific cart paths
    has_golf_paths = any(data.get('golf') == 'cartpath' for u, v, data in G.edges(data=True))

    if G.number_of_edges() < 10 and len(components) > 5 and not has_golf_paths:
        logger.info(
            "Sparse/fragmented cart path network (%d components), creating basic connectivity...",
            len(components),
        )
        G = _enhance_sparse_network(G, course_poly)
    elif len(components) > 3:
        logger.info(
            "Cart path network has %d disconnected components, but good edge density (%d edges)",
            len(components),
            G.number_of_edges(),
        )
        logger.info(
            "Skipping grid enhancement since we have %s cart path data",
            'golf-specific' if has_golf_paths else 'sufficient',
        )

    # Try to connect nearby components if graph is fragmented
    if G.number_of_nodes() > 0:
        G = _connect_nearby_components(
            G, max_distance_m=100
        )  # Increased distance for better connectivity

    return G


def _try_build_graph_with_filter(course_poly: Polygon, custom_filter: str) -> nx.Graph:
    """Try to build a graph with a specific OSM filter"""
    try:
        G_multi = _graph_from_polygon_retry(
            course_poly,
            custom_filter=custom_filter,
            simplify=True,
            retain_all=True,  # Keep all components
        )

        # Convert to undirected simple graph with length
        G = ox.convert.to_undirected(G_multi)

        # Ensure all edges have length
        for u, v, data in G.edges(data=True):
            if "length" not in data:
                pu = Point((G.nodes[u]["x"], G.nodes[u]["y"]))
                pv = Point((G.nodes[v]["x"], G.nodes[v]["y"]))
                data["length"] = pu.distance(pv) * 111_139

        logger.info("Built graph with %d nodes, %d edges", G.number_of_nodes(), G.number_of_edges())
        return G

    except Exception as e:
        logger.error("Failed to build graph with filter %s: %s", custom_filter, e)
        return nx.Graph()


def _build_graph_from_features(features_gdf: gpd.GeoDataFrame) -> nx.Graph:
    """Build a graph from GeoDataFrame features with LineString geometries"""
    G = nx.Graph()
    # Ensure CRS is set for downstream osmnx helpers
    G.graph["crs"] = "EPSG:4326"

    # Filter to LineString geometries
    lines = features_gdf[features_gdf.geom_type == "LineString"].copy()

    for idx, row in lines.iterrows():
        geom = row.geometry
        if geom and hasattr(geom, 'coords'):
            coords = list(geom.coords)
            # Extract relevant tags for edge metadata
            edge_data = {}
            if 'highway' in row:
                edge_data['highway'] = row['highway']
            if 'golf' in row:
                edge_data['golf'] = row['golf']
            if 'golf_cart' in row:
                edge_data['golf_cart'] = row['golf_cart']
            _add_linestring_to_graph_with_data(G, coords, edge_data)

    logger.info("Built graph from features: %d nodes, %d edges", G.number_of_nodes(), G.number_of_edges())
    return G


def _enhance_sparse_network(G: nx.Graph, course_poly: Polygon) -> nx.Graph:
    """Create a basic cart path network when OSM data is too sparse"""

    # Get bounding box of course
    minx, miny, maxx, maxy = course_poly.bounds

    # Create a simple grid network within the course polygon
    logger.info(
        "Creating basic grid network for course bounds: %.4f, %.4f, %.4f, %.4f",
        minx,
        miny,
        maxx,
        maxy,
    )

    # Create grid points
    n_points = 8  # 8x8 grid
    x_step = (maxx - minx) / (n_points - 1)
    y_step = (maxy - miny) / (n_points - 1)

    # Add existing nodes to the enhanced graph
    enhanced_G = G.copy()

    grid_nodes = []
    for i in range(n_points):
        for j in range(n_points):
            x = minx + i * x_step
            y = miny + j * y_step
            point = Point(x, y)

            # Only add points that are within the course polygon
            if course_poly.contains(point) or course_poly.boundary.distance(point) < 0.001:
                node_id = (round(x, 6), round(y, 6))
                enhanced_G.add_node(node_id, x=x, y=y)
                grid_nodes.append(node_id)

    # Connect adjacent grid nodes
    for i, node1 in enumerate(grid_nodes):
        for j, node2 in enumerate(grid_nodes[i + 1 :], i + 1):
            p1 = Point(enhanced_G.nodes[node1]['x'], enhanced_G.nodes[node1]['y'])
            p2 = Point(enhanced_G.nodes[node2]['x'], enhanced_G.nodes[node2]['y'])
            dist_m = p1.distance(p2) * 111_139

            # Connect nodes that are close enough (adjacent in grid)
            if dist_m < max(x_step, y_step) * 111_139 * 1.5:  # Allow diagonal connections
                enhanced_G.add_edge(node1, node2, length=dist_m)

    logger.info(
        "Enhanced network: %d nodes, %d edges",
        enhanced_G.number_of_nodes(),
        enhanced_G.number_of_edges(),
    )
    return enhanced_G


def _connect_nearby_components(G: nx.Graph, max_distance_m: float = 50) -> nx.Graph:
    """Connect nearby disconnected components of the graph"""
    if G.number_of_nodes() == 0:
        return G

    # Find connected components
    components = list(nx.connected_components(G))
    if len(components) <= 1:
        return G  # Already connected

    logger.info("Graph has %d disconnected components, attempting to connect...", len(components))

    # For each pair of components, find closest nodes and connect if close enough
    for i in range(len(components)):
        for j in range(i + 1, len(components)):
            comp1_nodes = list(components[i])
            comp2_nodes = list(components[j])

            min_dist = float('inf')
            closest_pair = None

            # Find closest nodes between components
            for n1 in comp1_nodes[:10]:  # Limit to avoid O(n²) explosion
                for n2 in comp2_nodes[:10]:
                    p1 = Point(G.nodes[n1]['x'], G.nodes[n1]['y'])
                    p2 = Point(G.nodes[n2]['x'], G.nodes[n2]['y'])
                    dist_m = p1.distance(p2) * 111_139

                    if dist_m < min_dist:
                        min_dist = dist_m
                        closest_pair = (n1, n2)

            # Connect if close enough
            if closest_pair and min_dist <= max_distance_m:
                n1, n2 = closest_pair
                G.add_edge(n1, n2, length=min_dist)
                logger.info("Connected components with %.1fm bridge", min_dist)

    final_components = list(nx.connected_components(G))
    logger.info("Final graph: %d components", len(final_components))
    return G


def _add_linestring_to_graph(G: nx.Graph, coords: List[Tuple[float, float]]):
    # coords: [(lon, lat), ...]
    _add_linestring_to_graph_with_data(G, coords, {})


def _add_linestring_to_graph_with_data(
    G: nx.Graph, coords: List[Tuple[float, float]], edge_data: dict
):
    # coords: [(lon, lat), ...]
    last = None
    for lon, lat in coords:
        node = (round(lon, 7), round(lat, 7))
        if node not in G:
            G.add_node(node, x=lon, y=lat)
        if last is not None:
            pu = Point((G.nodes[last]["x"], G.nodes[last]["y"]))
            pv = Point((G.nodes[node]["x"], G.nodes[node]["y"]))
            length = pu.distance(pv) * 111_139
            # Combine default length with any additional edge data
            edge_attrs = {"length": length}
            edge_attrs.update(edge_data)
            G.add_edge(last, node, **edge_attrs)
        last = node
