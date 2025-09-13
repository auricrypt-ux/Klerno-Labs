# ==============================================================================
# Klerno Labs - System Health & Sanity Check
# ==============================================================================
"""
Comprehensive system health validation for Klerno Labs platform.
Validates core functionality, dependencies, and configuration.
"""

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import requests
from pydantic import ValidationError

# Add project root to path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

try:
    from app.models import Transaction, TaggedTransaction, ReportRequest, ReportSummary
    from app.settings import get_settings
    from app.guardian import score_risk
    from app.compliance import tag_category
    from app.security import expected_api_key, generate_api_key
except ImportError as e:
    print(f"❌ Import Error: {e}")
    sys.exit(1)


class HealthChecker:
    """Comprehensive health checking system."""
    
    def __init__(self):
        self.settings = get_settings()
        self.results: List[Dict] = []
    
    def check_component(self, name: str, check_func, *args, **kwargs) -> bool:
        """Execute a health check and record results."""
        try:
            start_time = datetime.now(timezone.utc)
            result = check_func(*args, **kwargs)
            end_time = datetime.now(timezone.utc)
            duration = (end_time - start_time).total_seconds()
            
            success = result is not False
            self.results.append({
                "component": name,
                "status": "✅ PASS" if success else "❌ FAIL",
                "duration_ms": round(duration * 1000, 2),
                "timestamp": start_time.isoformat(),
                "details": str(result) if not success else "OK"
            })
            
            print(f"{'✅' if success else '❌'} {name:<30} ({duration*1000:.1f}ms)")
            return success
            
        except Exception as e:
            self.results.append({
                "component": name,
                "status": "❌ ERROR",
                "duration_ms": 0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "details": str(e)
            })
            print(f"❌ {name:<30} ERROR: {e}")
            return False
    
    def check_basic_imports(self) -> bool:
        """Verify core module imports."""
        required_modules = [
            "fastapi", "uvicorn", "pydantic", "pandas", "numpy",
            "requests", "jinja2", "PyJWT", "passlib", "xrpl"
        ]
        
        for module in required_modules:
            try:
                __import__(module)
            except ImportError:
                return f"Missing module: {module}"
        return True
    
    def check_models(self) -> bool:
        """Validate Pydantic models with sample data."""
        try:
            # Test Transaction model (using correct field names)
            tx_data = {
                "tx_id": "TEST123",
                "timestamp": datetime.now(timezone.utc),
                "chain": "XRP",
                "from_addr": "rFrom123",
                "to_addr": "rTo456",
                "amount": 1000.0,
                "symbol": "XRP",
                "direction": "outgoing",
                "fee": 0.012
            }
            tx = Transaction(**tx_data)
            
            # Test TaggedTransaction model (which accepts from_address/to_address)
            tagged_tx_data = {
                "tx_id": "TEST123",
                "timestamp": datetime.now(timezone.utc),
                "chain": "XRP",
                "from_address": "rFrom123",  # TaggedTransaction accepts this format
                "to_address": "rTo456",
                "amount": 1000.0,
                "currency": "XRP",
                "direction": "outgoing",
                "tx_type": "Payment",
                "fee": 0.012,
                "risk_score": 0.75,
                "risk_flags": ["large_amount"],
                "risk_category": "medium",
                "explanation": "Test explanation"
            }
            tagged_tx = TaggedTransaction(**tagged_tx_data)
            
            # Test ReportRequest model
            report_req = ReportRequest(
                wallet_addresses=["rAlice", "rBob"],
                chain="XRP"
            )
            
            return True
            
        except ValidationError as e:
            return f"Model validation error: {e}"
    
    def check_risk_scoring(self) -> bool:
        """Test risk scoring functionality."""
        try:
            sample_tx = Transaction(
                tx_id="RISK_TEST",
                timestamp=datetime.now(timezone.utc),
                chain="XRP",
                from_addr="rFrom123",
                to_addr="rTo456",
                amount=10000.0,  # Large amount to trigger risk
                symbol="XRP",
                direction="outgoing",
                fee=0.012
            )
            
            risk_data = score_risk(sample_tx)
            if not isinstance(risk_data.get("risk_score"), (int, float)):
                return "Invalid risk score format"
            
            if not 0 <= risk_data["risk_score"] <= 1:
                return "Risk score out of range"
                
            return True
            
        except Exception as e:
            return f"Risk scoring error: {e}"
    
    def check_compliance_tagging(self) -> bool:
        """Test compliance category tagging."""
        try:
            test_cases = [
                ("Large outgoing payment", "Payment", 15000.0),
                ("Fee transaction", "Fee", 0.012),
                ("Exchange deposit", "Payment", 1000.0)
            ]
            
            for description, tx_type, amount in test_cases:
                sample_tx = Transaction(
                    tx_id=f"TAG_TEST_{len(description)}",
                    timestamp=datetime.now(timezone.utc),
                    chain="XRP",
                    from_addr="rFrom123",
                    to_addr="rTo456",
                    amount=amount,
                    symbol="XRP",
                    direction="outgoing",
                    fee=0.012,
                    memo=description
                )
                
                category = tag_category(sample_tx)
                if not isinstance(category, str):
                    return f"Invalid category type for: {description}"
            
            return True
            
        except Exception as e:
            return f"Compliance tagging error: {e}"
    
    def check_settings_configuration(self) -> bool:
        """Validate application settings."""
        try:
            settings = get_settings()
            
            required_settings = [
                "app_env", "jwt_secret", "admin_email",
                "openai_model", "risk_threshold"
            ]
            
            for setting in required_settings:
                if not hasattr(settings, setting):
                    return f"Missing setting: {setting}"
            
            # Validate specific values
            if settings.risk_threshold < 0 or settings.risk_threshold > 1:
                return "Invalid risk threshold range"
            
            if len(settings.jwt_secret) < 16:
                return "JWT secret too short"
                
            return True
            
        except Exception as e:
            return f"Settings error: {e}"
    
    def check_security_components(self) -> bool:
        """Test security functionality."""
        try:
            # Test API key generation
            api_key = generate_api_key()
            if len(api_key) < 32:
                return "Generated API key too short"
            
            # Test API key validation
            expected_key = expected_api_key()
            if expected_key and len(expected_key) < 16:
                return "Expected API key too short"
                
            return True
            
        except Exception as e:
            return f"Security error: {e}"
    
    def check_data_processing(self) -> bool:
        """Test data processing capabilities."""
        try:
            # Test pandas operations
            sample_data = pd.DataFrame({
                "tx_id": ["TX1", "TX2", "TX3"],
                "amount": [100.0, 200.0, 300.0],
                "risk_score": [0.1, 0.5, 0.9]
            })
            
            # Basic operations
            avg_risk = sample_data["risk_score"].mean()
            high_risk_count = (sample_data["risk_score"] > 0.7).sum()
            
            if not isinstance(avg_risk, float):
                return "Invalid average calculation"
            
            if high_risk_count != 1:
                return "Invalid high risk count"
                
            return True
            
        except Exception as e:
            return f"Data processing error: {e}"
    
    def check_network_connectivity(self) -> bool:
        """Test external network connectivity."""
        try:
            # Test basic internet connectivity
            response = requests.get("https://httpbin.org/status/200", timeout=5)
            if response.status_code != 200:
                return f"Network test failed: {response.status_code}"
            
            return True
            
        except requests.exceptions.RequestException as e:
            return f"Network error: {e}"
    
    def generate_report(self) -> Dict:
        """Generate comprehensive health report."""
        total_checks = len(self.results)
        passed_checks = sum(1 for r in self.results if "✅" in r["status"])
        failed_checks = total_checks - passed_checks
        
        total_duration = sum(r["duration_ms"] for r in self.results)
        
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "total_checks": total_checks,
                "passed": passed_checks,
                "failed": failed_checks,
                "success_rate": round(passed_checks / total_checks * 100, 1) if total_checks > 0 else 0,
                "total_duration_ms": round(total_duration, 2)
            },
            "details": self.results,
            "status": "HEALTHY" if failed_checks == 0 else "DEGRADED" if failed_checks < 3 else "UNHEALTHY"
        }


def main():
    """Execute comprehensive health checks."""
    print("🔍 Klerno Labs - System Health Check")
    print("=" * 50)
    
    checker = HealthChecker()
    
    # Execute all health checks
    checks = [
        ("Core Imports", checker.check_basic_imports),
        ("Pydantic Models", checker.check_models),
        ("Risk Scoring Engine", checker.check_risk_scoring),
        ("Compliance Tagging", checker.check_compliance_tagging),
        ("Settings Configuration", checker.check_settings_configuration),
        ("Security Components", checker.check_security_components),
        ("Data Processing", checker.check_data_processing),
        ("Network Connectivity", checker.check_network_connectivity),
    ]
    
    for name, check_func in checks:
        checker.check_component(name, check_func)
    
    # Generate and display report
    print("\n" + "=" * 50)
    report = checker.generate_report()
    
    print(f"📊 Health Check Summary:")
    print(f"   Status: {report['status']}")
    print(f"   Checks: {report['summary']['passed']}/{report['summary']['total_checks']} passed")
    print(f"   Success Rate: {report['summary']['success_rate']}%")
    print(f"   Total Duration: {report['summary']['total_duration_ms']}ms")
    
    # Exit with appropriate code
    if report["status"] == "HEALTHY":
        print("\n✅ All systems operational!")
        sys.exit(0)
    elif report["status"] == "DEGRADED":
        print("\n⚠️  Some issues detected, but system functional")
        sys.exit(1)
    else:
        print("\n❌ Critical issues detected!")
        sys.exit(2)


if __name__ == "__main__":
    main()
