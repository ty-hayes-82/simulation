export type SimulationMeta = {
  runners?: number;
  bevCarts?: number;
  golfers?: number;
  scenario?: string;
  orders?: number;
  lastModified?: string;
};

export type SimulationEntry = {
  id: string;
  name: string;
  filename: string;               // CSV
  heatmapFilename?: string;       // PNG (optional)
  metricsFilename?: string;       // JSON (optional)
  holeDeliveryGeojson?: string;   // GEOJSON (optional)
  description?: string;
  meta?: SimulationMeta;
};

export type SimulationManifest = {
  simulations: SimulationEntry[];
  defaultSimulation?: string;
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
  filters: { runners?: number; orders?: number },
  fallbackId?: string
): SimulationEntry | null {
  const sims = manifest.simulations || [];
  if (sims.length === 0) return null;

  const targetR = typeof filters.runners === 'number' ? filters.runners : undefined;
  const targetO = typeof filters.orders === 'number' ? filters.orders : undefined;

  let candidates = sims;
  
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


