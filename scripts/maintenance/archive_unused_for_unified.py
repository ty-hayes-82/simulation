from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path


def extract_backticked_tokens(readme_text: str) -> set[str]:

	return set(re.findall(r"`([^`]+)`", readme_text))


def tokens_to_keeper_paths(tokens: set[str], repo_root: Path) -> set[Path]:

	keepers: set[Path] = set()
	for token in tokens:
		if "/" in token and token.endswith(".py"):
			candidate = (repo_root / token).resolve()
			keepers.add(candidate)
			continue

		# Map dotted module names to file paths when they live in our codebase
		if token.startswith("golfsim.") or token.startswith("utils."):
			module_path = token.replace(".", "/") + ".py"
			candidate = (repo_root / module_path).resolve()
			keepers.add(candidate)

	return keepers


def find_all_python_files(repo_root: Path) -> list[Path]:

	search_roots = [
		repo_root / "golfsim",
		repo_root / "scripts",
		repo_root / "utils",
	]
	all_files: list[Path] = []
	for root in search_roots:
		if not root.exists():
			continue
		all_files.extend(p for p in root.rglob("*.py"))

	# Top-level Python files in repo root
	all_files.extend(p for p in repo_root.glob("*.py"))
	return all_files


def should_skip(path: Path, maint_script_path: Path) -> bool:

	# Never move package markers
	if path.name == "__init__.py":
		return True

	# Skip tests and archived content
	parts = {part.lower() for part in path.parts}
	if "tests" in parts or "test" in parts and "scripts" in parts:
		return True
	if "_archive" in parts or "archive" in parts:
		return True

	# Skip the maintenance tool itself
	try:
		if path.resolve() == maint_script_path.resolve():
			return True
	except FileNotFoundError:
		# If the path was moved or not resolvable, ignore
		pass

	return False


def main() -> None:

	maint_script_path = Path(__file__).resolve()
	repo_root = maint_script_path.parents[2]
	readme_path = repo_root / "scripts" / "sim" / "README_run_unified_simulation_dependencies.md"

	if not readme_path.exists():
		raise SystemExit(f"Dependency README not found: {readme_path}")

	readme_text = readme_path.read_text(encoding="utf-8")
	tokens = extract_backticked_tokens(readme_text)
	keepers = tokens_to_keeper_paths(tokens, repo_root)

	all_py_files = find_all_python_files(repo_root)

	# Build archive destination folder
	stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
	archive_root = repo_root / "archive" / f"unified_unused_{stamp}"
	archive_root.mkdir(parents=True, exist_ok=True)

	moved: list[Path] = []
	kept: list[Path] = []

	for py_path in all_py_files:
		if should_skip(py_path, maint_script_path):
			kept.append(py_path)
			continue

		# Keep explicitly referenced files
		try:
			resolved = py_path.resolve()
		except FileNotFoundError:
			# The file may have been moved already in this run
			continue

		if resolved in keepers:
			kept.append(py_path)
			continue

		# Otherwise move to archive, preserving relative structure from repo root
		rel = resolved.relative_to(repo_root)
		target = archive_root / rel
		target.parent.mkdir(parents=True, exist_ok=True)
		shutil.move(str(resolved), str(target))
		moved.append(resolved)

	# Write report
	print("Archive destination:", archive_root)
	print(f"Kept files: {len(kept)}")
	print(f"Moved files: {len(moved)}")
	for p in sorted(moved):
		print("MOVED:", p.relative_to(repo_root))


if __name__ == "__main__":
	main()


