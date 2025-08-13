# Course Preparation Scripts Migration

## Archived Files (Post-Refactoring)

The following files have been archived after the Phase 1 refactoring that introduced the `golfsim.tools` package:

### `generate_lcm_course_nodes_legacy.py` (formerly `scripts/course_prep/generate_lcm_course_nodes.py`)
- **Status**: ✅ **ARCHIVED** - Superseded by unified tools
- **Replaced by**: 
  - Core logic: `golfsim.tools.node_generator.generate_lcm_course_nodes()`
  - CLI wrapper: `scripts/prep/generate_lcm_nodes.py`
- **Migration**: Functionality moved to the unified tools package with better error handling and integration

### `geofence_holes_legacy.py` (formerly `scripts/course_prep/geofence_holes.py`)
- **Status**: ✅ **ARCHIVED** - Superseded by unified tools
- **Replaced by**: 
  - Core logic: `golfsim.tools.course_data_generator.CourseDataGenerator` (with fallback implementation)
  - Integration: Auto-generated via `CourseDataGenerator.ensure_all_required_files()`
- **Migration**: `scripts/routing/extract_course_data.py` updated to use unified tools with graceful fallback

### `course_prep_init_legacy.py` (formerly `scripts/course_prep/__init__.py`)
- **Status**: ✅ **ARCHIVED** - Package disbanded
- **Migration**: Entire `scripts/course_prep/` package removed, functionality moved to `golfsim.tools`

## Migration Benefits

1. **Unified API**: All course data generation now available via `golfsim.tools.CourseDataGenerator`
2. **Better Error Handling**: Graceful fallbacks for missing dependencies
3. **Self-healing**: Auto-generation of missing files
4. **Simplified Workflow**: Single command vs multiple manual steps

## New Workflow

```bash
# Old (multiple steps):
python scripts/course_prep/generate_lcm_course_nodes.py
python scripts/course_prep/geofence_holes.py --boundary ... --holes ...

# New (single step):
python scripts/prep/generate_course_data.py --course-dir courses/pinetree_country_club
```
