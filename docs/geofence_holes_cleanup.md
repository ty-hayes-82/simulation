## Hole Geofencing Split: Cleanup Strategy

This document outlines a pragmatic, testable plan to clean up `scripts/course_prep/geofence_holes.py` so it reliably partitions an entire golf course polygon into per-hole sections. The plan emphasizes determinism, full coverage, non-overlap, performance, and debuggability.

### Objectives
- **Correctness**: Produce exactly 18 per-hole polygons that are disjoint and whose union equals the course boundary (within a small epsilon).
- **Determinism**: Identical inputs yield identical outputs across runs and platforms.
- **Performance**: Run comfortably with ≤250 seeds per hole on typical courses.
- **Observability**: Provide debug artifacts and clear logs for troubleshooting.
- **Compatibility**: Keep public function signatures stable.

### Scope
- Primary target: `scripts/course_prep/geofence_holes.py`
- Secondary utility: connected path generation (`generate_holes_connected`)
- Does not alter external data formats; leverages existing `holes.geojson` and boundary polygon GeoJSON.

## Current Issues
- **Seed instability**: Duplicate/near-duplicate densified points can cause Voronoi failures or produce unstable cells.
- **Slow nearest mapping**: O(N_cells × N_seeds) nearest seed search during cell assignment.
- **Coverage gaps**: “Leftover area” is conditionally assigned and may leave gaps when large.
- **Overlaps after smoothing**: Smoothing can reintroduce overlaps between adjacent holes.
- **Property assumptions**: `_flatten_holes_path` hard-requires `ref`; real data often uses `hole`, `Hole`, `number`, etc.
- **Light diagnostics**: Limited debug artifacts and invariants checks.

## Invariants to Enforce
- **I1: Exactly 18 features** with `hole` ids, ideally 1..18 (not strictly required but preferred).
- **I2: Full coverage**: Union of all hole polygons equals the course polygon within tolerance.
- **I3: Disjointness**: Pairwise intersections between hole polygons have negligible area (~0 within tolerance).
- **I4: Determinism**: Stable seeding, ordering, and tie-breaking.

## Implementation Plan (edits inside `geofence_holes.py`)

### 1) Input validation and CRS handling
- Normalize hole ids from incoming line features using a candidate list: `("hole", "Hole", "HOLE", "number", "Number", "id", "Id", "ref", "Ref", "REF")`.
- Log chosen projected CRS via `estimate_utm_crs()`; only fall back to `EPSG:3857` if needed.
- Warn if detected unique hole ids ≠ 18; proceed but preserve determinism.

### 2) Seed generation: dedupe and order
- After densification and optional subsampling, **deduplicate seed points** with a small tolerance to avoid Qhull duplicate errors and reduce cost.
- Order seeds deterministically: by `hole_id`, then by along-line position (proxy: index order returned from densification is sufficient and stable).

Pseudo-helper:
```python
def _dedupe_xy(points, tol=1e-6):
    seen = set()
    out = []
    for x, y in points:
        key = (round(x / tol), round(y / tol))
        if key in seen:
            continue
        seen.add(key)
        out.append((x, y))
    return out
```

### 3) Voronoi construction: robust with fallback
- Prefer SciPy Voronoi. Wrap in try/except; on failure (e.g., colinear seeds, duplicates), fall back to `shapely.ops.voronoi_diagram`.
- Use an expanded bbox margin; fix invalid polygons with `buffer(0)`, then clip to course boundary.

### 4) Fast cell-to-hole assignment with spatial index
- Replace O(N×M) nearest-seed lookup with `STRtree` of seed `Point`s.
- Map cell representative point to nearest seed and thus to `hole_id` using an `id()`-keyed dictionary.

Sketch:
```python
from shapely.geometry import Point
from shapely.strtree import STRtree

seed_points = [Point(x, y) for (x, y) in seeds_xy]
point_to_hole = {id(p): hid for p, hid in zip(seed_points, seed_hole_idx)}
tree = STRtree(seed_points)

for cell in vor_polys:
    if cell.is_empty:
        continue
    cpt = cell.representative_point()
    nearest = tree.nearest(cpt)
    hid = point_to_hole[id(nearest)]
    # clip and collect for this hole id
```

### 5) Dissolve per-hole and enforce invariants
1. Dissolve the assigned cells per hole into `hole_polys`.
2. Compute `combined = unary_union(hole_polys.values())`.
3. Fill gaps: `missing = course_geom.difference(combined)`. Always assign all missing area by nearest hole centerline or nearest dissolved hole polygon (via `STRtree`). No 10% cap.
4. Make disjoint deterministically: iterate holes in stable order and do `geom = geom.difference(union_so_far)` as you accumulate a running union. This removes overlaps while preserving total coverage.
5. Optional smoothing: apply small `±smooth_m` and, if used, re-run a quick disjoint pass to neutralize reintroduced overlaps.

### 6) Connected path improvements
- Extend `_flatten_holes_path` to accept multiple property candidates and fall back cleanly to file order if none found.
- Maintain dedup of consecutive coordinates; keep the clubhouse start/end anchoring.

### 7) Debugging and observability
- Add `debug_export_dir: Optional[Path]` (or toggle) to write optional artifacts:
  - `seeds.geojson` with `hole_id`
  - `raw_voronoi_cells.geojson`
  - `cells_assigned.geojson` (pre-dissolve)
  - `holes_dissolved_pre_smooth.geojson`
  - `holes_final.geojson` (post smoothing/disjoint)
- Log summaries:
  - Seeds per hole
  - Number of Voronoi cells
  - Coverage metrics: course area, combined area, missing area, overlap area (pre/post disjoint)
  - Timing for major stages

### 8) Tests (fast unit and integration)
- Exactly 18 features and hole ids present.
- Coverage within epsilon: `area(course) - area(union(holes))` is ~0 (tolerance: ≤0.5%).
- Non-overlap: sum of pairwise intersections ~0.
- Determinism: geometry WKB hashes identical across runs for same inputs.
- Connected path: correct number of minute points equals `golfer_18_holes_minutes`.

## Performance Notes
- Seed dedupe reduces Voronoi complexity and improves robustness.
- `STRtree` changes nearest lookups from O(N×M) to near O(N log M).
- Keep `max_points_per_hole` default at 250; subsample uniformly when exceeded.

## Rollout and Compatibility
- Keep `split_course_into_holes(...)` and `generate_holes_connected(...)` signatures. Consider adding optional `debug_export_dir`.
- No changes to input file formats.
- Produce additional optional debug GeoJSONs when enabled.

## Acceptance Criteria
- Disjoint set of 18 polygons covering the course polygon entirely (within tolerance).
- Stable outputs across platforms and runs for fixed inputs.
- Reasonable runtime with default seed caps.
- Useful debug artifacts and logs for troubleshooting.

## Reference: Debugging Tips
- Validate coordinate formats: clubhouse and hole lines should be `(lon, lat)` tuples; ensure CRS reprojected to 4326 where expected.
- Routing and geometry validity: use `.is_valid` and `buffer(0)` to fix invalid geometries.
- Increase logging to DEBUG for detailed steps and metrics.


