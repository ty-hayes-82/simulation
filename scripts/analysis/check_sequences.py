from __future__ import annotations

import csv
from pathlib import Path


def latest_dir(glob_pattern: str) -> Path | None:
    roots = sorted([p for p in Path('outputs').glob(glob_pattern) if p.is_dir()])
    return roots[-1] if roots else None


def read_first_n_holes(csv_path: Path, entity_type: str | None = None, entity_id: str | None = None, n: int = 120) -> list[int]:
    holes: list[int] = []
    with csv_path.open('r', encoding='utf-8') as f:
        r = csv.DictReader(f)
        for row in r:
            if entity_type is not None and row.get('type') != entity_type:
                continue
            if entity_id is not None and row.get('id') != entity_id:
                continue
            val = row.get('hole')
            try:
                holes.append(int(val))
            except Exception:
                continue
            if len(holes) >= n:
                break
    return holes


def main() -> None:
    phase2 = latest_dir('*_phase_02')
    phase1 = latest_dir('*_phase_01_with_metrics')

    if not phase2 or not phase1:
        print('Missing outputs to check')
        return

    p2_csv = phase2 / 'sim_01' / 'coordinates.csv'
    p1_csv = phase1 / 'sim_01' / 'coordinates.csv'

    print('P2 CSV:', p2_csv)
    print('P1 CSV:', p1_csv)

    # Phase 2 rows are written with id 'golfer_1' and type 'hole'. Filter by id.
    golfer_seq = read_first_n_holes(p2_csv, entity_id='golfer_1', n=120)
    # Phase 1 bev cart rows have id 'bev_cart_1' and type 'bevcart'. Filter by id for robustness.
    bevcart_seq = read_first_n_holes(p1_csv, entity_id='bev_cart_1', n=120)

    print('golfer first 20 holes:', golfer_seq[:20])
    if golfer_seq:
        print('golfer starts at', golfer_seq[0], 'ends at', golfer_seq[-1])

    print('bevcart first 20 holes:', bevcart_seq[:20])
    if bevcart_seq:
        print('bevcart starts at', bevcart_seq[0], 'ends at', bevcart_seq[-1])


if __name__ == '__main__':
    main()


