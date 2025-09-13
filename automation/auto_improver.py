
# ==============================================================================
# Klerno Labs - Automated Improvement System
# ==============================================================================
"""
Enterprise-grade automated code improvement and CI/CD system.
Safely analyzes code, suggests improvements, and maintains quality standards.
"""

import asyncio
import logging
import subprocess
import sys
import time
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('automation/logs/auto_improver.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Project configuration
ROOT = Path(__file__).resolve().parents[1]
AUTOMATION_DIR = ROOT / "automation"
REPORTS_DIR = AUTOMATION_DIR / "reports"
PROPOSALS_DIR = AUTOMATION_DIR / "proposals"
PATCHES_DIR = AUTOMATION_DIR / "patches"

# Ensure directories exist
for directory in [REPORTS_DIR, PROPOSALS_DIR, PATCHES_DIR]:
    directory.mkdir(parents=True, exist_ok=True)


@dataclass
class ImprovementPolicy:
    """Configuration for automated improvement system."""
    rate_limit_minutes: int = 60
    require_tests: bool = True
    max_suggestions: int = 10
    auto_apply_safe: bool = False
    safety_threshold: float = 0.8
    excluded_paths: List[str] = None
    required_approvals: int = 1
    
    def __post_init__(self):
        if self.excluded_paths is None:
            self.excluded_paths = [
                ".git/", "__pycache__/", ".venv/", "node_modules/",
                "*.pyc", "*.log", ".env*"
            ]


@dataclass
class QualityMetrics:
    """System quality and health metrics."""
    test_pass_rate: float
    code_coverage: float
    security_score: float
    performance_score: float
    maintainability_score: float
    timestamp: datetime
    
    @classmethod
    def measure_current(cls) -> 'QualityMetrics':
        """Measure current system quality metrics."""
        return cls(
            test_pass_rate=measure_test_pass_rate(),
            code_coverage=measure_code_coverage(),
            security_score=measure_security_score(),
            performance_score=measure_performance_score(),
            maintainability_score=measure_maintainability_score(),
            timestamp=datetime.now(timezone.utc)
        )


@dataclass
class ImprovementSuggestion:
    """A specific improvement suggestion."""
    id: str
    category: str
    description: str
    file_path: str
    line_number: Optional[int]
    confidence: float
    impact: str  # low, medium, high
    effort: str  # low, medium, high
    safety_rating: float
    automated_fix: Optional[str]
    reasoning: str


class AutomatedImprover:
    """Main automated improvement system."""
    
    def __init__(self, policy: Optional[ImprovementPolicy] = None):
        self.policy = policy or self.load_policy()
        self.last_run_file = AUTOMATION_DIR / ".last_run"
        self.metrics_file = AUTOMATION_DIR / "metrics.json"
        
    def load_policy(self) -> ImprovementPolicy:
        """Load improvement policy from configuration."""
        policy_file = AUTOMATION_DIR / "policy.yaml"
        if policy_file.exists():
            try:
                import yaml
                with open(policy_file) as f:
                    config = yaml.safe_load(f)
                return ImprovementPolicy(**config)
            except Exception as e:
                logger.warning(f"Failed to load policy file: {e}")
        
        return ImprovementPolicy()
    
    def should_run(self) -> Tuple[bool, str]:
        """Check if the improver should run based on rate limiting."""
        if not self.last_run_file.exists():
            return True, "First run"
        
        last_run = self.last_run_file.stat().st_mtime
        elapsed_minutes = (time.time() - last_run) / 60
        
        if elapsed_minutes < self.policy.rate_limit_minutes:
            remaining = self.policy.rate_limit_minutes - elapsed_minutes
            return False, f"Rate limited. {remaining:.1f} minutes remaining."
        
        return True, "Rate limit expired"
    
    async def run_comprehensive_analysis(self) -> Dict:
        """Run comprehensive code analysis and improvement suggestions."""
        logger.info("🔍 Starting comprehensive code analysis...")
        
        results = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metrics": {},
            "suggestions": [],
            "safety_report": {},
            "summary": {}
        }
        
        # Measure current quality metrics
        logger.info("📊 Measuring quality metrics...")
        metrics = QualityMetrics.measure_current()
        results["metrics"] = asdict(metrics)
        
        # Run different types of analysis
        analyses = [
            ("Security Analysis", self.analyze_security),
            ("Performance Analysis", self.analyze_performance),
            ("Code Quality Analysis", self.analyze_code_quality),
            ("Test Coverage Analysis", self.analyze_test_coverage),
            ("Documentation Analysis", self.analyze_documentation),
        ]
        
        all_suggestions = []
        for analysis_name, analysis_func in analyses:
            logger.info(f"🔍 Running {analysis_name}...")
            try:
                suggestions = await analysis_func()
                all_suggestions.extend(suggestions)
                logger.info(f"✅ {analysis_name} completed: {len(suggestions)} suggestions")
            except Exception as e:
                logger.error(f"❌ {analysis_name} failed: {e}")
        
        # Filter and prioritize suggestions
        filtered_suggestions = self.filter_suggestions(all_suggestions)
        results["suggestions"] = [asdict(s) for s in filtered_suggestions]
        
        # Generate safety report
        results["safety_report"] = self.generate_safety_report(filtered_suggestions)
        
        # Create summary
        results["summary"] = self.create_summary(metrics, filtered_suggestions)
        
        return results
    
    async def analyze_security(self) -> List[ImprovementSuggestion]:
        """Analyze code for security vulnerabilities."""
        suggestions = []
        
        # Run bandit security analysis
        try:
            result = subprocess.run([
                sys.executable, "-m", "bandit", "-r", "app/", "-f", "json"
            ], capture_output=True, text=True, cwd=ROOT)
            
            if result.returncode == 0:
                bandit_data = json.loads(result.stdout)
                for issue in bandit_data.get("results", []):
                    suggestions.append(ImprovementSuggestion(
                        id=f"security_{issue['test_id']}_{hash(issue['filename'])}",
                        category="security",
                        description=issue["issue_text"],
                        file_path=issue["filename"],
                        line_number=issue["line_number"],
                        confidence=issue["confidence"] / 100.0,
                        impact="high" if issue["severity"] == "HIGH" else "medium",
                        effort="low",
                        safety_rating=0.9,
                        automated_fix=None,
                        reasoning=f"Security scanner detected: {issue['test_name']}"
                    ))
        except Exception as e:
            logger.warning(f"Security analysis failed: {e}")
        
        return suggestions
    
    async def analyze_performance(self) -> List[ImprovementSuggestion]:
        """Analyze code for performance improvements."""
        suggestions = []
        
        # Check for common performance anti-patterns
        performance_patterns = [
            {
                "pattern": r"for .+ in .+:\s*.*\.append\(",
                "suggestion": "Consider using list comprehension for better performance",
                "category": "performance",
                "impact": "medium"
            },
            {
                "pattern": r"\.format\(",
                "suggestion": "Consider using f-strings for better performance",
                "category": "performance", 
                "impact": "low"
            }
        ]
        
        import re
        for py_file in ROOT.rglob("*.py"):
            if any(excluded in str(py_file) for excluded in self.policy.excluded_paths):
                continue
                
            try:
                content = py_file.read_text()
                lines = content.split('\n')
                
                for i, line in enumerate(lines, 1):
                    for pattern_info in performance_patterns:
                        if re.search(pattern_info["pattern"], line):
                            suggestions.append(ImprovementSuggestion(
                                id=f"perf_{hash(str(py_file))}_{i}",
                                category="performance",
                                description=pattern_info["suggestion"],
                                file_path=str(py_file.relative_to(ROOT)),
                                line_number=i,
                                confidence=0.7,
                                impact=pattern_info["impact"],
                                effort="low",
                                safety_rating=0.9,
                                automated_fix=None,
                                reasoning="Performance pattern analysis"
                            ))
            except Exception as e:
                logger.warning(f"Failed to analyze {py_file}: {e}")
        
        return suggestions
    
    async def analyze_code_quality(self) -> List[ImprovementSuggestion]:
        """Analyze code quality and style issues."""
        suggestions = []
        
        # Run flake8 for style issues
        try:
            result = subprocess.run([
                sys.executable, "-m", "flake8", "app/", "--format=json"
            ], capture_output=True, text=True, cwd=ROOT)
            
            # Note: flake8 doesn't output JSON by default, so we'll parse the standard format
            if result.stdout:
                for line in result.stdout.strip().split('\n'):
                    if ':' in line:
                        parts = line.split(':')
                        if len(parts) >= 4:
                            suggestions.append(ImprovementSuggestion(
                                id=f"style_{hash(line)}",
                                category="code_quality",
                                description=':'.join(parts[3:]).strip(),
                                file_path=parts[0],
                                line_number=int(parts[1]) if parts[1].isdigit() else None,
                                confidence=0.8,
                                impact="low",
                                effort="low",
                                safety_rating=0.95,
                                automated_fix=None,
                                reasoning="Code style analysis"
                            ))
        except Exception as e:
            logger.warning(f"Code quality analysis failed: {e}")
        
        return suggestions
    
    async def analyze_test_coverage(self) -> List[ImprovementSuggestion]:
        """Analyze test coverage and suggest improvements."""
        suggestions = []
        
        try:
            # Run coverage analysis
            result = subprocess.run([
                sys.executable, "-m", "pytest", "--cov=app", "--cov-report=json", "--cov-report=term-missing"
            ], capture_output=True, text=True, cwd=ROOT)
            
            coverage_file = ROOT / "coverage.json"
            if coverage_file.exists():
                with open(coverage_file) as f:
                    coverage_data = json.load(f)
                
                for file_path, file_data in coverage_data.get("files", {}).items():
                    coverage_percent = file_data.get("summary", {}).get("percent_covered", 100)
                    
                    if coverage_percent < 80:
                        suggestions.append(ImprovementSuggestion(
                            id=f"coverage_{hash(file_path)}",
                            category="testing",
                            description=f"Test coverage is {coverage_percent:.1f}%, should be >80%",
                            file_path=file_path,
                            line_number=None,
                            confidence=0.9,
                            impact="medium",
                            effort="medium",
                            safety_rating=0.95,
                            automated_fix=None,
                            reasoning="Test coverage analysis"
                        ))
        except Exception as e:
            logger.warning(f"Test coverage analysis failed: {e}")
        
        return suggestions
    
    async def analyze_documentation(self) -> List[ImprovementSuggestion]:
        """Analyze documentation completeness."""
        suggestions = []
        
        # Check for missing docstrings
        import ast
        
        for py_file in ROOT.rglob("*.py"):
            if any(excluded in str(py_file) for excluded in self.policy.excluded_paths):
                continue
            
            try:
                with open(py_file) as f:
                    tree = ast.parse(f.read())
                
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
                        if not ast.get_docstring(node):
                            suggestions.append(ImprovementSuggestion(
                                id=f"doc_{hash(str(py_file))}_{node.lineno}",
                                category="documentation",
                                description=f"Missing docstring for {node.name}",
                                file_path=str(py_file.relative_to(ROOT)),
                                line_number=node.lineno,
                                confidence=0.9,
                                impact="low",
                                effort="low",
                                safety_rating=1.0,
                                automated_fix=None,
                                reasoning="Documentation completeness check"
                            ))
            except Exception as e:
                logger.warning(f"Failed to analyze documentation in {py_file}: {e}")
        
        return suggestions
    
    def filter_suggestions(self, suggestions: List[ImprovementSuggestion]) -> List[ImprovementSuggestion]:
        """Filter and prioritize suggestions based on policy."""
        # Remove duplicates
        unique_suggestions = {}
        for suggestion in suggestions:
            key = (suggestion.file_path, suggestion.line_number, suggestion.description)
            if key not in unique_suggestions:
                unique_suggestions[key] = suggestion
        
        filtered = list(unique_suggestions.values())
        
        # Sort by priority (confidence * impact * safety)
        impact_weights = {"low": 1, "medium": 2, "high": 3}
        
        def priority_score(s: ImprovementSuggestion) -> float:
            impact_score = impact_weights.get(s.impact, 1)
            return s.confidence * impact_score * s.safety_rating
        
        filtered.sort(key=priority_score, reverse=True)
        
        # Limit to max suggestions
        return filtered[:self.policy.max_suggestions]
    
    def generate_safety_report(self, suggestions: List[ImprovementSuggestion]) -> Dict:
        """Generate safety assessment report."""
        total_suggestions = len(suggestions)
        safe_suggestions = [s for s in suggestions if s.safety_rating >= self.policy.safety_threshold]
        
        return {
            "total_suggestions": total_suggestions,
            "safe_suggestions": len(safe_suggestions),
            "safety_ratio": len(safe_suggestions) / total_suggestions if total_suggestions > 0 else 1.0,
            "high_impact_suggestions": len([s for s in suggestions if s.impact == "high"]),
            "auto_applicable": len([s for s in suggestions if s.automated_fix and s.safety_rating >= 0.9])
        }
    
    def create_summary(self, metrics: QualityMetrics, suggestions: List[ImprovementSuggestion]) -> Dict:
        """Create executive summary of analysis."""
        categories = {}
        for suggestion in suggestions:
            categories[suggestion.category] = categories.get(suggestion.category, 0) + 1
        
        return {
            "overall_health_score": (
                metrics.test_pass_rate + 
                metrics.code_coverage + 
                metrics.security_score + 
                metrics.performance_score + 
                metrics.maintainability_score
            ) / 5,
            "total_suggestions": len(suggestions),
            "categories": categories,
            "priority_suggestions": len([s for s in suggestions if s.impact == "high"]),
            "quick_wins": len([s for s in suggestions if s.effort == "low" and s.impact in ["medium", "high"]])
        }
    
    def save_results(self, results: Dict) -> None:
        """Save analysis results to files."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Save full results
        results_file = REPORTS_DIR / f"analysis_{timestamp}.json"
        with open(results_file, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        
        # Save metrics history
        metrics_history = []
        if self.metrics_file.exists():
            with open(self.metrics_file) as f:
                metrics_history = json.load(f)
        
        metrics_history.append(results["metrics"])
        with open(self.metrics_file, 'w') as f:
            json.dump(metrics_history[-100:], f, indent=2, default=str)  # Keep last 100 entries
        
        logger.info(f"📄 Results saved to {results_file}")
    
    async def run(self) -> bool:
        """Main execution method."""
        logger.info("🚀 Klerno Labs Automated Improvement System Starting...")
        
        # Check if we should run
        should_run, reason = self.should_run()
        if not should_run:
            logger.info(f"⏸️  Skipping run: {reason}")
            return False
        
        # Check tests if required
        if self.policy.require_tests:
            logger.info("🧪 Running test suite...")
            if not run_tests():
                logger.error("❌ Tests failing; aborting analysis")
                return False
            logger.info("✅ All tests passing")
        
        try:
            # Run comprehensive analysis
            results = await self.run_comprehensive_analysis()
            
            # Save results
            self.save_results(results)
            
            # Update last run timestamp
            self.last_run_file.write_text(str(time.time()))
            
            # Log summary
            summary = results["summary"]
            logger.info("🎯 Analysis Summary:")
            logger.info(f"   Overall Health Score: {summary['overall_health_score']:.2f}")
            logger.info(f"   Total Suggestions: {summary['total_suggestions']}")
            logger.info(f"   Priority Items: {summary['priority_suggestions']}")
            logger.info(f"   Quick Wins: {summary['quick_wins']}")
            
            logger.info("✅ Automated improvement analysis completed successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Analysis failed: {e}")
            return False


# Utility functions
def run_tests() -> bool:
    """Run the test suite and return success status."""
    try:
        result = subprocess.run([
            sys.executable, "-m", "pytest", "-x", "--tb=short"
        ], cwd=ROOT, capture_output=True, text=True)
        return result.returncode == 0
    except Exception:
        return False


def measure_test_pass_rate() -> float:
    """Measure current test pass rate."""
    try:
        result = subprocess.run([
            sys.executable, "-m", "pytest", "--tb=no", "-q"
        ], cwd=ROOT, capture_output=True, text=True)
        
        if "failed" in result.stdout or result.returncode != 0:
            return 0.8  # Assume some failures
        return 1.0
    except Exception:
        return 0.0


def measure_code_coverage() -> float:
    """Measure current code coverage."""
    try:
        result = subprocess.run([
            sys.executable, "-m", "pytest", "--cov=app", "--cov-report=term-missing"
        ], cwd=ROOT, capture_output=True, text=True)
        
        # Parse coverage from output
        for line in result.stdout.split('\n'):
            if "TOTAL" in line and "%" in line:
                parts = line.split()
                for part in parts:
                    if "%" in part:
                        return float(part.replace("%", "")) / 100.0
        return 0.8  # Default estimate
    except Exception:
        return 0.0


def measure_security_score() -> float:
    """Measure security score based on known issues."""
    # This would integrate with security scanning tools
    return 0.9  # Placeholder


def measure_performance_score() -> float:
    """Measure performance score."""
    # This would integrate with performance monitoring
    return 0.85  # Placeholder


def measure_maintainability_score() -> float:
    """Measure code maintainability score."""
    # This would integrate with static analysis tools
    return 0.88  # Placeholder


async def main():
    """Main entry point for automated improvement system."""
    improver = AutomatedImprover()
    success = await improver.run()
    
    if success:
        print("✅ Automated improvement analysis completed successfully!")
        print(f"📄 Check {REPORTS_DIR} for detailed results")
        print(f"💡 Review suggestions in the latest analysis report")
    else:
        print("❌ Automated improvement analysis failed")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
