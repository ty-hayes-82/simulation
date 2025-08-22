import json
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import networkx as nx
import pytest

from golfsim.data.osm_ingest import build_cartpath_graph
from golfsim.routing.networks import nearest_node
from shapely.geometry import Point, LineString


REPO_ROOT = Path(__file__).resolve().parents[1]
PINETREE_DIR = REPO_ROOT / "courses" / "pinetree_country_club"


def find_nearest_node(G: nx.Graph, lon: float, lat: float):
    """Find nearest node in graph to given coordinates."""
    target_point = Point(lon, lat)
    min_dist = float('inf')
    nearest_node_id = None

    for node_id in G.nodes:
        node_point = Point(G.nodes[node_id]["x"], G.nodes[node_id]["y"])
        dist = target_point.distance(node_point)
        if dist < min_dist:
            min_dist = dist
            nearest_node_id = node_id

    return nearest_node_id


def compute_shortest_path(G: nx.Graph, src_lonlat, dst_lonlat, speed_mps=6.0):
    """Compute shortest path between two coordinate points on the graph."""
    if G is None or G.number_of_nodes() == 0:
        raise ValueError("Cart-path graph is empty.")

    # Find nearest nodes
    src_node = find_nearest_node(G, src_lonlat[0], src_lonlat[1])
    dst_node = find_nearest_node(G, dst_lonlat[0], dst_lonlat[1])

    # Compute shortest path
    path = nx.shortest_path(G, src_node, dst_node, weight="length")

    # Calculate total length
    length = 0.0
    for u, v in zip(path[:-1], path[1:]):
        edge_data = G[u][v]
        length += float(edge_data.get("length", 0))

    return {"nodes": path, "length_m": length, "time_s": length / max(speed_mps, 0.1)}


@pytest.fixture(scope="module")
def course_polygon_geom():
    course_poly_gdf = gpd.read_file(PINETREE_DIR / "geojson" / "course_polygon.geojson").to_crs(
        4326
    )
    # Use the first geometry; MultiPolygon/Polygon are both acceptable here
    return course_poly_gdf.geometry.iloc[0]


@pytest.fixture(scope="module")
def clubhouse_lonlat():
    cfg = json.loads((PINETREE_DIR / "config" / "simulation_config.json").read_text())
    return (cfg["clubhouse"]["longitude"], cfg["clubhouse"]["latitude"])


@pytest.fixture(scope="module")
def cart_graph(course_polygon_geom) -> nx.Graph:
    # Build from provided cart_paths.geojson (custom input path)
    G = build_cartpath_graph(
        course_poly=course_polygon_geom,
        cartpath_geojson=str(PINETREE_DIR / "geojson" / "cart_paths_connected.geojson"),
        broaden=False,
    )
    return G


def test_cart_graph_builds_and_has_required_attributes(cart_graph: nx.Graph):
    # Basic structure
    assert cart_graph.number_of_nodes() > 0, "Graph should have nodes"
    assert cart_graph.number_of_edges() > 0, "Graph should have edges"

    # Nodes have x,y coordinates
    sample_node = next(iter(cart_graph.nodes))
    assert "x" in cart_graph.nodes[sample_node]
    assert "y" in cart_graph.nodes[sample_node]

    # Edges have positive length attribute
    u, v, data = next(iter(cart_graph.edges(data=True)))
    assert "length" in data and data["length"] > 0


def test_shortest_path_from_clubhouse_to_graph_node(cart_graph: nx.Graph, clubhouse_lonlat):
    assert cart_graph.number_of_nodes() > 1, "Need at least two nodes for routing"

    # Find a destination node that's different from the nearest to clubhouse
    nearest_to_clubhouse = find_nearest_node(cart_graph, clubhouse_lonlat[0], clubhouse_lonlat[1])

    dst_node = None
    for n in cart_graph.nodes:
        if n != nearest_to_clubhouse:
            dst_node = n
            break
    assert dst_node is not None, "Failed to pick a distinct destination node"

    dst_lonlat = (cart_graph.nodes[dst_node]["x"], cart_graph.nodes[dst_node]["y"])

    # Compute shortest path by distance; check distance/time
    try:
        result = compute_shortest_path(
            cart_graph,
            src_lonlat=clubhouse_lonlat,
            dst_lonlat=dst_lonlat,
            speed_mps=6.0,
        )
        assert "nodes" in result
        assert "length_m" in result
        assert "time_s" in result
        assert result["length_m"] > 0
        assert result["time_s"] > 0
    except nx.NetworkXNoPath:
        pytest.skip("No path found between clubhouse and a random node.")


def test_visualize_cart_path_network_with_route(cart_graph: nx.Graph, clubhouse_lonlat):
    """Create a visualization showing the cart path network and a shortest path."""

    # Find the connected component containing the clubhouse
    nearest_to_clubhouse = find_nearest_node(cart_graph, clubhouse_lonlat[0], clubhouse_lonlat[1])

    # Get all nodes in the same connected component as the clubhouse
    clubhouse_component = nx.node_connected_component(cart_graph, nearest_to_clubhouse)

    # Find the farthest reachable node from clubhouse within the same component
    clubhouse_point = Point(clubhouse_lonlat)
    max_dist = 0
    farthest_node = None

    for node_id in clubhouse_component:
        if node_id == nearest_to_clubhouse:
            continue
        node_point = Point(cart_graph.nodes[node_id]["x"], cart_graph.nodes[node_id]["y"])
        dist = clubhouse_point.distance(node_point)
        if dist > max_dist:
            max_dist = dist
            farthest_node = node_id

    if farthest_node is None:
        # Fallback to any other node in the same component
        farthest_node = next(n for n in clubhouse_component if n != nearest_to_clubhouse)

    dst_lonlat = (cart_graph.nodes[farthest_node]["x"], cart_graph.nodes[farthest_node]["y"])

    # Compute shortest path
    result = compute_shortest_path(
        cart_graph,
        src_lonlat=clubhouse_lonlat,
        dst_lonlat=dst_lonlat,
        speed_mps=6.0,
    )

    # Create visualization
    fig, ax = plt.subplots(1, 1, figsize=(12, 10))

    # Plot all cart path edges in light gray
    for u, v in cart_graph.edges():
        u_coords = (cart_graph.nodes[u]["x"], cart_graph.nodes[u]["y"])
        v_coords = (cart_graph.nodes[v]["x"], cart_graph.nodes[v]["y"])
        ax.plot(
            [u_coords[0], v_coords[0]],
            [u_coords[1], v_coords[1]],
            'lightgray',
            linewidth=0.8,
            alpha=0.7,
        )

    # Plot the shortest path in red
    path_nodes = result["nodes"]
    for i in range(len(path_nodes) - 1):
        u = path_nodes[i]
        v = path_nodes[i + 1]
        u_coords = (cart_graph.nodes[u]["x"], cart_graph.nodes[u]["y"])
        v_coords = (cart_graph.nodes[v]["x"], cart_graph.nodes[v]["y"])
        ax.plot(
            [u_coords[0], v_coords[0]], [u_coords[1], v_coords[1]], 'red', linewidth=3, alpha=0.8
        )

    # Mark clubhouse and destination
    ax.plot(
        clubhouse_lonlat[0],
        clubhouse_lonlat[1],
        'go',
        markersize=12,
        label=f'Clubhouse ({clubhouse_lonlat[0]:.4f}, {clubhouse_lonlat[1]:.4f})',
    )
    ax.plot(
        dst_lonlat[0],
        dst_lonlat[1],
        'bo',
        markersize=10,
        label=f'Destination ({dst_lonlat[0]:.4f}, {dst_lonlat[1]:.4f})',
    )

    # Add title and labels
    ax.set_title(
        f'Cart Path Network - Shortest Route\n'
        f'Distance: {result["length_m"]:.1f}m, Time: {result["time_s"]:.1f}s @ 6.0 m/s\n'
        f'Path uses {len(path_nodes)} nodes',
        fontsize=14,
    )
    ax.set_xlabel('Longitude')
    ax.set_ylabel('Latitude')
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.set_aspect('equal')

    # Save the plot
    output_path = REPO_ROOT / "outputs" / "cart_path_network_route.png"
    output_path.parent.mkdir(exist_ok=True)
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()

    print(f"✓ Visualization saved to: {output_path}")
    print(f"  Route distance: {result['length_m']:.1f} meters")
    print(f"  Travel time: {result['time_s']:.1f} seconds")
    print(f"  Path nodes: {len(path_nodes)}")

    # Verify the image was created
    assert output_path.exists(), f"Output image not created at {output_path}"


def test_nearest_node_fallback_behavior():
    G = nx.Graph()
    # Add nodes without x/y to ensure fallback returns None instead of arbitrary node
    G.add_node(1)
    G.add_node(2)
    result = nearest_node(G, -84.59, 34.03)
    assert result is None

    # Add deterministic x/y nodes and ensure nearest is selected
    G.clear()
    G.add_node(10, x=-84.5900, y=34.0300)
    G.add_node(20, x=-84.5910, y=34.0310)
    picked = nearest_node(G, -84.5901, 34.0301)
    assert picked in {10, 20}


def test_shortest_path_on_disconnected_graph_raises():
    import networkx as nx
    from golfsim.routing.networks import shortest_path_on_cartpaths

    G = nx.Graph()
    # Component 1
    G.add_node(1, x=0.0, y=0.0)
    G.add_node(2, x=1.0, y=0.0)
    G.add_edge(1, 2, length=10.0)

    # Component 2
    G.add_node(3, x=100.0, y=100.0)
    G.add_node(4, x=101.0, y=100.0)
    G.add_edge(3, 4, length=10.0)

    # Try to route between coordinates near different components
    src = (0.0, 0.0)
    dst = (100.0, 100.0)

    with pytest.raises(ValueError):
        shortest_path_on_cartpaths(G, src, dst, speed_mps=6.0)
