
"""
Safe Auto-Improver (proposal-only).
"""
import difflib, glob, time
from dataclasses import dataclass
from typing import List, Dict
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]

@dataclass
class Suggestion:
    file: str
    before: str
    after: str
    rationale: str

def load_policy() -> Dict:
    p = ROOT / "automation" / "policy.yaml"
    return yaml.safe_load(p.read_text())

def llm_suggest(file_path: Path, content: str) -> List[Suggestion]:
    suggestions: List[Suggestion] = []
    if file_path.suffix == ".py" and "from __future__ import annotations" not in content:
        after = "from __future__ import annotations\n" + content
        suggestions.append(Suggestion(
            file=str(file_path.relative_to(ROOT)),
            before=content, after=after,
            rationale="Enable postponed evaluation of annotations for forward references."
        ))
    return suggestions

def bounded_change_allowed(policy: Dict, rel_path: str) -> bool:
    allowed = policy.get("allowed_paths", [])
    return any(rel_path.startswith(a) for a in allowed)

def make_patch(before: str, after: str, file: str) -> str:
    before_lines = before.splitlines(keepends=True)
    after_lines = after.splitlines(keepends=True)
    diff = difflib.unified_diff(before_lines, after_lines, fromfile=file, tofile=file)
    return "".join(diff)

def propose_changes():
    policy = load_policy()
    proposals_dir = ROOT / "automation" / "proposals"
    patches_dir = ROOT / "automation" / "patches"
    proposals_dir.mkdir(parents=True, exist_ok=True)
    patches_dir.mkdir(parents=True, exist_ok=True)

    for path in glob.glob(str(ROOT / "app" / "**" / "*.py"), recursive=True):
        p = Path(path)
        rel = str(p.relative_to(ROOT))
        if not bounded_change_allowed(policy, rel):
            continue
        content = p.read_text()
        for sug in llm_suggest(p, content):
            patch = make_patch(sug.before, sug.after, sug.file)
            ts = int(time.time())
            (proposals_dir / f"proposal_{ts}_{p.stem}.md").write_text(
                f"# Improvement Proposal\n\nFile: {sug.file}\n\nRationale:\n{sug.rationale}\n"
            )
            (patches_dir / f"patch_{ts}_{p.stem}.patch").write_text(patch)

if __name__ == "__main__":
    propose_changes()
