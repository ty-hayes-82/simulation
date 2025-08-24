### Blocking holes strategy: UI, simulations, and loading

**Status: Implemented**

Goals
- [DONE] Add top-left animation controls to toggle blocking: none, holes 1–3, holes 10–12, or both.
- [DONE] For every simulation scenario, generate and publish all four variants by default.
- [DONE] Preserve total order count: if a sim specifies 30 orders, all 30 must be placed on allowed holes even when some holes are blocked.

UI controls (top-left)
- [DONE] Use two checkboxes to represent four states cleanly (mutually-composable):
  - Block Front 1–3
  - Block Back 10–12
- [DONE] Implementation: Radix Themes Checkbox Group with two items; the four states are encoded by the selected values set. Reference: [Radix Themes Checkbox Group](https://www.radix-ui.com/themes/docs/components/checkbox-group).

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
- [DONE] Extend selection filters to include blocked-holes state:
  - `filters.blockFront: boolean`
  - `filters.blockBack: boolean`
- [DONE] Extend manifest entries with variant metadata for exact matching:
  - `meta.blockedHoles: number[]` (e.g., `[1,2,3]`, `[10,11,12]`, `[1,2,3,10,11,12]`, or `[]`)
  - `variantKey: 'none' | 'front_1_3' | 'back_1_12' | 'both_1_3_10_12' | 'custom'` for quick lookup
- [DONE] Manifest selection logic update:
  - First filter by exact blocked-holes set (by `variantKey`)
  - Then apply existing exact-match `runners`, closest-match `orders` tie-breakers
  - Fallback when the requested blocked variant is missing: gracefully fall back to `none`.

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
  variantKey?: 'none' | 'front_1_3' | 'back_10_12' | 'both_1_3_10_12' | 'custom'; // new
  meta?: SimulationMeta;
};
```

Publishing layout (unchanged paths; new variants multiply entries)
```
my-map-animation/public/coordinates/
  manifest.json
  <simId>.csv
  <simId>_delivery_heatmap.png        (if exists)
  <simId>_metrics.json                (if exists)
  hole_delivery_times_<simId>.geojson (if exists)
```
_Note: The implementation uses a unique `simId` for each variant, so the `variantKey` is not appended to filenames. The `simId` is derived from the path, which now includes the variant key._

Simulation generation strategy (4× variants by default)
- [DONE] For each base scenario (e.g., 1–2 runners × order levels), run four variants:
  - none
  - front_1_3
  - back_10_12
  - both_1_3_10_12
- [DONE] Recommended CLI invocations using existing flags:
  - none: no blocking flags
  - front_1_3: `--block-up-to-hole 3`
  - back_10_12: `--block-holes-10-12`
  - both_1_3_10_12: `--block-holes 1 2 3 10 11 12`

Critical requirement: preserve total order count
- [DONE] Today, blocking flags are applied after order generation, which reduces counts. Update order generation so total orders remain constant and are reallocated to allowed holes.

Backend changes (proposed)
1) Generation API extension
   - [DONE] Update `generate_delivery_orders_by_hour_distribution(..., blocked_holes: Optional[set[int]] = None)`
   - [DONE] While sampling each order:
     - Sample an order time in the hour window (existing logic)
     - If inferred hole ∈ blocked_holes, resample up to K attempts.
   - [DONE] Guarantee that exactly `total_orders` orders are returned by adding any shortfall at the end.

2) Orchestrator wiring
   - [DONE] When CLI blocking flags are present, construct `blocked_holes` set and pass to the generator (do not filter orders post-hoc)
   - [DONE] Remove post-generation filtering for blocked holes; keep logging for transparency

3) Metrics consistency
   - [DONE] Update per-run `simulation_metrics.json` to include `blockedHoles` and `variantKey`
   - [DONE] Export per-run hole delivery GeoJSON as today; it will naturally reflect the blocked distribution

Batching and automation
- [DONE] Modify `scripts/optimization/run_staffing_experiments.py` to expand each base `(runners, orders)` combination into the 4 blocked variants using a new `--run-blocking-variants` flag.
- [DONE] Ensure the publisher `my-map-animation/run_map_app.py` emits four manifest entries per base combination and sets the new fields.

Front-end integration plan
- [DONE] Extend `SimulationContext` filter state with two booleans (`blockFront`, `blockBack`)
- [DONE] Extend manifest selection to match on `variantKey` first, then `runners` and `orders`
- [DONE] Add the Radix Checkbox Group to the existing top-left panel in `TopBarControls.tsx`, wiring `onValueChange` to update context filters immediately
- [DONE] When filters change, rely on existing `selectBestMatch`-style logic with an added `variantKey` check for exact match

URL state and sharing
- [PENDING] Add `bh=` query param encoding: `none`, `front`, `back`, `both`
- [PENDING] Sync param on load and on change to keep deep-links stable

Testing checklist
- [DONE] With 30-order scenarios, each blocked variant still produces exactly 30 orders
- [DONE] Orders never appear on blocked holes; distribution shifts to allowed holes consistent with active groups and pacing
- [DONE] All four variants appear in the manifest and can be selected via the new controls
- [DONE] Animation and metrics panels update consistently across variants; per-variant heatmaps/GeoJSON load when present

Performance considerations
- [DONE] Expect ~4× runtime for the full matrix when generating variants. Use `--minimal-outputs` in bulk runs where images are not needed.

References
- Radix Themes Checkbox Group: https://www.radix-ui.com/themes/docs/components/checkbox-group


