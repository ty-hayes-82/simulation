### Blocking holes strategy: UI, simulations, and loading

Goals
- Add top-left animation controls to toggle blocking: none, holes 1–3, holes 10–12, or both.
- For every simulation scenario, generate and publish all four variants by default.
- Preserve total order count: if a sim specifies 30 orders, all 30 must be placed on allowed holes even when some holes are blocked.

UI controls (top-left)
- Use two checkboxes to represent four states cleanly (mutually-composable):
  - Block Front 1–3
  - Block Back 10–12
- Implementation: Radix Themes Checkbox Group with two items; the four states are encoded by the selected values set. Reference: [Radix Themes Checkbox Group](https://www.radix-ui.com/themes/docs/components/checkbox-group).

Example UI snippet (Radix)
```tsx
import { CheckboxGroup, Flex, Text } from '@radix-ui/themes';

function BlockedHolesControls({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  return (
    <Flex direction="column" gap="2">
      <Text size="2" weight="bold">Block Holes</Text>
      <CheckboxGroup.Root value={value} onValueChange={onChange} name="blockedHoles" variant="soft" size="2">
        <Text as="label" size="2">
          <Flex gap="2"><CheckboxGroup.Item value="front_1_3" /> Front 1–3</Flex>
        </Text>
        <Text as="label" size="2">
          <Flex gap="2"><CheckboxGroup.Item value="back_10_12" /> Back 10–12</Flex>
        </Text>
      </CheckboxGroup.Root>
    </Flex>
  );
}
```

Front-end loading strategy
- Extend selection filters to include blocked-holes state:
  - `filters.blockFront123: boolean`
  - `filters.blockBack1012: boolean`
- Extend manifest entries with variant metadata for exact matching:
  - `meta.blockedHoles: number[]` (e.g., `[1,2,3]`, `[10,11,12]`, `[1,2,3,10,11,12]`, or `[]`)
  - Optional `variantKey: 'none' | 'front_1_3' | 'back_10_12' | 'both'` for quick lookup
- Manifest selection logic update:
  - First filter by exact blocked-holes set (by `variantKey` or `meta.blockedHoles` equality)
  - Then apply existing exact-match `runners`, closest-match `orders` tie-breakers
  - Fallback when the requested blocked variant is missing: gracefully fall back to `none` with a small inline notice

Manifest schema additions
```ts
type SimulationMeta = {
  runners?: number;
  bevCarts?: number;
  golfers?: number;
  scenario?: string;
  orders?: number;
  lastModified?: string;
  blockedHoles?: number[]; // new
};

type SimulationEntry = {
  id: string;
  name: string;
  filename: string;
  heatmapFilename?: string;
  metricsFilename?: string;
  holeDeliveryGeojson?: string;
  variantKey?: 'none' | 'front_1_3' | 'back_10_12' | 'both'; // new
  meta?: SimulationMeta;
};
```

Publishing layout (unchanged paths; new variants multiply entries)
```
my-map-animation/public/coordinates/
  manifest.json
  <simId>_<variantKey>.csv
  <simId>_<variantKey>_delivery_heatmap.png        (if exists)
  <simId>_<variantKey>_metrics.json                (if exists)
  hole_delivery_times_<simId>_<variantKey>.geojson (if exists)
```

Simulation generation strategy (4× variants by default)
- For each base scenario (e.g., 1–2 runners × order levels), run four variants:
  - none
  - front_1_3
  - back_10_12
  - both
- Recommended CLI invocations using existing flags:
  - none: no blocking flags
  - front_1_3: `--block-up-to-hole 3` (equivalent to blocking 1–3) or `--block-holes 1 2 3`
  - back_10_12: `--block-holes-10-12` or `--block-holes 10 11 12`
  - both: `--block-holes 1 2 3 10 11 12`

Critical requirement: preserve total order count
- Today, blocking flags are applied after order generation, which reduces counts. Update order generation so total orders remain constant and are reallocated to allowed holes.

Backend changes (proposed)
1) Generation API extension
   - Update `generate_delivery_orders_by_hour_distribution(..., blocked_holes: Optional[set[int]] = None, ensure_total: bool = True)`
   - While sampling each order:
     - Sample an order time in the hour window (existing logic)
     - If inferred hole ∈ blocked_holes, resample time up to K attempts; if still blocked, choose the nearest allowed hole for the same group by adjusting node index to the closest non-blocked hole and recomputing `order_time_s` accordingly
   - Guarantee that exactly `total_orders` orders are returned when `ensure_total=True`

2) Orchestrator wiring
   - When CLI blocking flags are present, construct `blocked_holes` set and pass to the generator (do not filter orders post-hoc)
   - Remove post-generation filtering for blocked holes; keep logging for transparency

3) Metrics consistency
   - Update per-run `simulation_metrics.json` to include `blockedHoles` and `variantKey`
   - Export per-run hole delivery GeoJSON as today; it will naturally reflect the blocked distribution

Batching and automation
- Modify `scripts/optimization/run_staffing_experiments.py` (or add a small wrapper) to expand each base `(runners, orders)` combination into the 4 blocked variants using the CLI flags above.
- Ensure the publisher `my-map-animation/run_map_app.py` emits four manifest entries per base combination and sets the new fields.

Front-end integration plan
- Extend `SimulationContext` filter state with two booleans (`blockFront123`, `blockBack1012`)
- Extend manifest selection to match on `variantKey` first, then `runners` and `orders`
- Add the Radix Checkbox Group to the existing top-left panel in `AnimationView` (next to Speed/Map Style), wiring `onValueChange` to update context filters immediately
- When filters change, rely on existing `selectBestMatch`-style logic with an added `variantKey` check for exact match

URL state and sharing
- Add `bh=` query param encoding: `none`, `front`, `back`, `both`
- Sync param on load and on change to keep deep-links stable

Testing checklist
- With 30-order scenarios, each blocked variant still produces exactly 30 orders
- Orders never appear on blocked holes; distribution shifts to allowed holes consistent with active groups and pacing
- All four variants appear in the manifest and can be selected via the new controls
- Animation and metrics panels update consistently across variants; per-variant heatmaps/GeoJSON load when present

Performance considerations
- Expect ~4× runtime for the full matrix when generating variants. Use `--minimal-outputs` in bulk runs where images are not needed.

References
- Radix Themes Checkbox Group: https://www.radix-ui.com/themes/docs/components/checkbox-group


