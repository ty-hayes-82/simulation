export type SimulationMeta = {
  runners?: number;
  bevCarts?: number;
  golfers?: number;
  scenario?: string;
  orders?: number;
  lastModified?: string;
  blockedHoles?: number[]; // new
};

export type SimulationEntry = {
  id: string;
  name: string;
  filename: string;               // CSV
  heatmapFilename?: string;       // PNG (optional)
  metricsFilename?: string;       // JSON (optional)
  holeDeliveryGeojson?: string;   // GEOJSON (optional)
  description?: string;
  variantKey?: 'none' | 'front' | 'mid' | 'back' | 'front_mid' | 'front_back' | 'mid_back' | 'front_mid_back' | 'custom'; // new
  meta?: SimulationMeta;
  // Added for course selection
  courseId?: string;
  courseName?: string;
};

export type SimulationManifest = {
  simulations: SimulationEntry[];
  defaultSimulation?: string;
  // Optional list of distinct courses present in the manifest
  courses?: { id: string; name: string }[];
};

let manifestCache: SimulationManifest | null = null;

export async function loadManifest(): Promise<SimulationManifest> {
  if (manifestCache) return manifestCache;
  const res = await fetch(`/coordinates/manifest.json?t=${Date.now()}`);
  if (!res.ok) return { simulations: [] };
  const data = await res.json();
  manifestCache = data as SimulationManifest;
  return manifestCache;
}

export function distinctRunnerCounts(manifest: SimulationManifest): number[] {
  const counts = new Set<number>();
  for (const sim of manifest.simulations || []) {
    const n = sim.meta?.runners;
    if (typeof n === 'number' && Number.isFinite(n)) counts.add(n);
  }
  return Array.from(counts).sort((a, b) => a - b);
}

export function selectBestMatch(
  manifest: SimulationManifest,
  filters: { runners?: number; orders?: number; variantKey?: string },
  fallbackId?: string
): SimulationEntry | null {
  const sims = manifest.simulations || [];
  if (sims.length === 0) return null;

  const targetR = typeof filters.runners === 'number' ? filters.runners : undefined;
  const targetO = typeof filters.orders === 'number' ? filters.orders : undefined;
  const targetV = filters.variantKey;

  let candidates = sims;
  
  // --- Start of new filtering logic ---
  // 1. Exact match for variantKey
  if (targetV) {
    const exactVariant = candidates.filter(s => s.variantKey === targetV);
    if (exactVariant.length > 0) {
      candidates = exactVariant;
    } else {
      // Fallback: if requested variant is missing, try to find a 'none' for the same combo
      const noneVariant = candidates.filter(s => s.variantKey === 'none');
      if (noneVariant.length > 0) candidates = noneVariant;
    }
  }
  // --- End of new filtering logic ---
  
  // Filter by runners
  if (typeof targetR === 'number') {
    const exact = candidates.filter(s => (s.meta?.runners ?? NaN) === targetR);
    candidates = exact.length > 0 ? exact : candidates;
  }
  
  // Sort by orders proximity
  if (typeof targetO === 'number') {
    candidates = [...candidates].sort((a, b) => {
      const ao = a.meta?.orders ?? Number.POSITIVE_INFINITY;
      const bo = b.meta?.orders ?? Number.POSITIVE_INFINITY;
      return Math.abs((ao as number) - targetO) - Math.abs((bo as number) - targetO);
    });
  }

  const pick = candidates[0] || sims[0];
  return pick || (fallbackId ? sims.find(s => s.id === fallbackId) || null : null);
}


export function distinctOrderCounts(manifest: SimulationManifest): number[] {
  const counts = new Set<number>();
  for (const sim of manifest.simulations || []) {
    const n = sim.meta?.orders;
    if (typeof n === 'number' && Number.isFinite(n)) counts.add(n);
  }
  return Array.from(counts).sort((a, b) => a - b);
}


