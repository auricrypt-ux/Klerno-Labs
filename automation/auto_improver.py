
import subprocess, sys, time
from pathlib import Path
from app.ai_agent import propose_changes, load_policy

ROOT = Path(__file__).resolve().parents[1]

def run_tests() -> bool:
    try:
        subprocess.check_call([sys.executable, "-m", "pytest", "-q"], cwd=ROOT)
        return True
    except subprocess.CalledProcessError:
        return False

def main():
    policy = load_policy()
    stamp = ROOT / "automation" / ".last_run"
    if stamp.exists():
        elapsed = time.time() - stamp.stat().st_mtime
        if elapsed < policy.get("rate_limit_minutes",60)*60:
            print("Rate limited. Try later.")
            return
    ok = run_tests()
    if not ok and policy.get("require_tests", True):
        print("Tests failing; aborting proposal.")
        return
    propose_changes()
    stamp.write_text(str(time.time()))
    print("Proposals generated. Review automation/proposals and automation/patches.")

if __name__ == "__main__":
    main()
