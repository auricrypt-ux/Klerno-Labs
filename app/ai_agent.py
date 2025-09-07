"""
Safe Auto-Improver (proposal-only).
"""
from __future__ import annotations

import difflib
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime, timezone

import yaml

ROOT = Path(__file__).resolve().parents[1]

@dataclass
class Suggestion:
    file: str         # repo-relative, POSIX
    before: str
    after: str
    rationale: str

def load_policy() -> Dict[str, Any]:
    p = ROOT / "automation" / "policy.yaml"
    if not p.exists():
        # No policy? Act as "deny all" to be safe.
        return {"allowed_paths": []}
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {"allowed_paths": []}
    except Exception as e:
        # Malformed policy -> deny all
        print(f"[policy] Failed to load policy.yaml: {e}")
        return {"allowed_paths": []}

def _insert_future_annotations(content: str) -> str:
    """
    Insert 'from __future__ import annotations' at a safe position:
    - after shebang/encoding lines
    - after a leading module docstring (if present)
    """
    lines = content.splitlines()
    i = 0

    # Skip shebang and encoding cookies
    if i < len(lines) and lines[i].startswith("#!"):
        i += 1
    if i < len(lines) and "coding" in lines[i] and "utf-8" in lines[i].lower():
        i += 1

    # Detect leading module docstring (simple heuristic for triple quotes)
    if i < len(lines) and lines[i].lstrip().startswith(("'''", '"""')):
        quote = lines[i].lstrip()[:3]
        i += 1
        # advance until closing triple quote
        while i < len(lines):
            if lines[i].rstrip().endswith(quote):
                i += 1
                break

    # If already present anywhere, return original
    if "from __future__ import annotations" in content:
        return content

    insert_line = "from __future__ import annotations"
    # Insert with a trailing newline, and add a blank line after for readability
    new_lines = lines[:i] + [insert_line, ""] + lines[i:]
    return "\n".join(new_lines) + ("\n" if content.endswith("\n") else "")

def llm_suggest(file_path: Path, content: str) -> List[Suggestion]:
    suggestions: List[Suggestion] = []

    # Only suggest future import on Python < 3.11
    if sys.version_info < (3, 11) and file_path.suffix == ".py":
        after = _insert_future_annotations(content)
        if after != content:
            suggestions.append(
                Suggestion(
                    file=str(file_path.relative_to(ROOT).as_posix()),
                    before=content,
                    after=after,
                    rationale=(
                        "Enable postponed evaluation of annotations for forward references "
                        "on Python < 3.11."
                    ),
                )
            )

    return suggestions

def bounded_change_allowed(policy: Dict[str, Any], abs_path: Path) -> bool:
    allowed = policy.get("allowed_paths", []) or []
    # Convert allowed entries to absolute paths under the repo root
    allowed_dirs = [(ROOT / a).resolve() for a in allowed]
    abs_path = abs_path.resolve()
    for base in allowed_dirs:
        try:
            if abs_path.is_relative_to(base):
                return True
        except AttributeError:
            # Python < 3.9 fallback
            from os.path import commonpath
            if commonpath([str(abs_path), str(base)]) == str(base):
                return True
    return False

def make_patch(before: str, after: str, file_label: str) -> str:
    before_lines = before.splitlines(keepends=True)
    after_lines = after.splitlines(keepends=True)
    diff = difflib.unified_diff(
        before_lines,
        after_lines,
        fromfile=file_label,
        tofile=file_label,
        n=3,
    )
    return "".join(diff)

def propose_changes() -> None:
    policy = load_policy()
    proposals_dir = ROOT / "automation" / "proposals"
    patches_dir = ROOT / "automation" / "patches"
    proposals_dir.mkdir(parents=True, exist_ok=True)
    patches_dir.mkdir(parents=True, exist_ok=True)

    for p in (ROOT / "app").rglob("*.py"):
        if not bounded_change_allowed(policy, p):
            continue

        content = p.read_text(encoding="utf-8")
        for sug in llm_suggest(p, content):
            patch = make_patch(sug.before, sug.after, sug.file)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            uid = uuid.uuid4().hex[:8]
            proposals_path = proposals_dir / f"proposal_{stamp}_{uid}_{p.stem}.md"
            patches_path = patches_dir / f"patch_{stamp}_{uid}_{p.stem}.patch"

            proposals_path.write_text(
                f"# Improvement Proposal\n\n"
                f"**File:** `{sug.file}`\n\n"
                f"**Rationale:** {sug.rationale}\n\n"
                f"**How to apply:**\n"
                f"```bash\ngit apply automation/patches/{patches_path.name}\n```\n",
                encoding="utf-8",
            )
            patches_path.write_text(patch, encoding="utf-8")

if __name__ == "__main__":
    propose_changes()
