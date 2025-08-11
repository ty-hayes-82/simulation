# Scripts Archive

This directory contains archived/deprecated scripts that are no longer actively maintained but are kept for historical reference.

## Archive Policy

Files in this directory:
- Are **read-only** and should not be modified
- Are **excluded from CI/test runs** 
- May contain outdated code patterns or dependencies
- Are retained for historical reference only

## Usage

**DO NOT** use scripts from this archive directory. Instead, use the current active scripts organized in the main scripts/ subdirectories:

- `scripts/sim/` - Simulation entrypoints
- `scripts/routing/` - Routing and network utilities
- `scripts/viz/` - Visualization tools
- `scripts/analysis/` - Analysis and reporting

## Migration History

Scripts are moved to this archive when they are:
- Superseded by newer, better implementations
- Duplicates of functionality available elsewhere
- No longer compatible with current system architecture
- Replaced by library functions in the `golfsim/` package

## If You Need Archived Functionality

If you need functionality from an archived script:

1. **First check** if equivalent functionality exists in the current active scripts
2. **Check the `golfsim/` library modules** for the functionality you need
3. **If neither exists**, consider whether the archived script should be restored and updated rather than used as-is

## Current Archive Status

*This archive is currently empty. Scripts will be moved here as part of the ongoing refactoring process when duplicates or obsolete functionality is identified.*

---

*Last updated: 2024*
