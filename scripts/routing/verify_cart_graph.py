#!/usr/bin/env python3
from __future__ import annotations

import pickle
from pathlib import Path
import sys
import json

import networkx as nx


def main(course_dir: str = "courses/pinetree_country_club") -> int:
    pkl_path = Path(course_dir) / "pkl" / "cart_graph.pkl"
    if not pkl_path.exists():
        print(f"ERROR: Missing graph: {pkl_path}")
        return 1

    with pkl_path.open("rb") as f:
        G = pickle.load(f)

    clubhouse = None
    for n, d in G.nodes(data=True):
        if d.get("kind") == "clubhouse":
            clubhouse = n
            break

    print(json.dumps({
        "clubhouse_node": clubhouse,
        "has_edge_clubhouse_120": (clubhouse is not None and G.has_edge(clubhouse, 120)),
        "has_edge_120_121": G.has_edge(120, 121),
        "path_len_clubhouse_to_121": (len(nx.shortest_path(G, clubhouse, 121, weight="length")) if clubhouse is not None else None),
    }, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]) if len(sys.argv) > 1 else main())


