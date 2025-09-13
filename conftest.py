# ==============================================================================
# Klerno Labs - Test Configuration & Global Fixtures
# ==============================================================================
"""
Global pytest configuration and fixtures for the Klerno Labs test suite.
Provides comprehensive test infrastructure for enterprise SaaS testing.
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import AsyncClient

# Add project root to Python path for reliable imports
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Import after path setup
from app.main import app
from app.settings import get_settings


# ==============================================================================
# Session-wide Configuration
# ==============================================================================

@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an instance of the default event loop for the test session."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def test_settings():
    """Override settings for testing environment."""
    # Temporarily override environment for tests
    test_env = {
        "APP_ENV": "test",
        "DEMO_MODE": "true",
        "SECRET_KEY": "test-secret-key-32-characters-long",
        "DATABASE_URL": "sqlite:///test.db",
        "DISABLE_AUTH": "true",
        "OPENAI_API_KEY": "test-key",
        "XRPL_RPC_URL": "wss://s.altnet.rippletest.net:51233",
    }
    
    # Store original values
    original_env = {}
    for key, value in test_env.items():
        original_env[key] = os.environ.get(key)
        os.environ[key] = value
    
    # Clear settings cache to use test values
    get_settings.cache_clear()
    
    yield get_settings()
    
    # Restore original environment
    for key, value in original_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    
    # Clear cache again to restore production settings
    get_settings.cache_clear()


# ==============================================================================
# HTTP Client Fixtures
# ==============================================================================

@pytest.fixture
def client(test_settings) -> TestClient:
    """Synchronous test client for FastAPI application."""
    return TestClient(app)


@pytest.fixture
async def async_client(test_settings) -> AsyncGenerator[AsyncClient, None]:
    """Asynchronous test client for FastAPI application."""
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


# ==============================================================================
# Database & Storage Fixtures
# ==============================================================================

@pytest.fixture
def temp_db():
    """Temporary database for isolated tests."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    
    yield db_path
    
    # Cleanup
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def temp_data_dir():
    """Temporary data directory for file-based tests."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


# ==============================================================================
# Authentication & Security Fixtures
# ==============================================================================

@pytest.fixture
def mock_user():
    """Mock authenticated user for testing."""
    return {
        "id": 1,
        "email": "test@klerno.com",
        "role": "admin",
        "subscription_active": True,
        "created_at": "2025-01-27T00:00:00Z",
    }


@pytest.fixture
def mock_api_key():
    """Mock API key for testing."""
    return "test-api-key-32-characters-long"


@pytest.fixture
def auth_headers(mock_api_key):
    """Authentication headers for API testing."""
    return {"X-API-Key": mock_api_key}


# ==============================================================================
# Mock External Services
# ==============================================================================

@pytest.fixture
def mock_xrpl_client():
    """Mock XRPL client for blockchain integration tests."""
    mock = MagicMock()
    mock.account_tx = AsyncMock(return_value={
        "account": "rTestAccount",
        "transactions": []
    })
    mock.account_info = AsyncMock(return_value={
        "account_data": {
            "Account": "rTestAccount",
            "Balance": "1000000"
        }
    })
    return mock


@pytest.fixture
def mock_openai_client():
    """Mock OpenAI client for AI/ML tests."""
    mock = MagicMock()
    mock.chat.completions.create = AsyncMock(return_value=MagicMock(
        choices=[MagicMock(
            message=MagicMock(content="Mock AI response")
        )]
    ))
    return mock


@pytest.fixture
def mock_sendgrid():
    """Mock SendGrid client for email testing."""
    mock = MagicMock()
    mock.send = MagicMock(return_value=MagicMock(status_code=202))
    return mock


# ==============================================================================
# Test Data Fixtures
# ==============================================================================

@pytest.fixture
def sample_transaction():
    """Sample transaction data for testing."""
    return {
        "tx_id": "TEST123456789",
        "timestamp": "2025-01-27T12:00:00Z",
        "chain": "XRP",
        "from_address": "rFromAddress123",
        "to_address": "rToAddress456",
        "amount": 1000.0,
        "currency": "XRP",
        "direction": "outgoing",
        "tx_type": "Payment",
        "fee": 0.012,
        "memo": "Test transaction",
    }


@pytest.fixture
def sample_risk_data():
    """Sample risk scoring data for testing."""
    return {
        "risk_score": 0.75,
        "risk_flags": ["large_amount", "new_address"],
        "risk_category": "medium",
        "confidence": 0.85,
        "explanation": "Transaction flagged due to large amount and new recipient",
    }


# ==============================================================================
# Performance Testing Fixtures
# ==============================================================================

@pytest.fixture
def performance_timer():
    """Timer utility for performance testing."""
    import time
    
    class Timer:
        def __init__(self):
            self.start_time = None
            self.end_time = None
        
        def start(self):
            self.start_time = time.perf_counter()
        
        def stop(self):
            self.end_time = time.perf_counter()
        
        @property
        def elapsed(self):
            if self.start_time and self.end_time:
                return self.end_time - self.start_time
            return None
    
    return Timer()


# ==============================================================================
# Utility Functions
# ==============================================================================

def pytest_configure(config):
    """Configure pytest with custom settings."""
    # Add custom markers
    config.addinivalue_line("markers", "unit: Unit tests")
    config.addinivalue_line("markers", "integration: Integration tests")
    config.addinivalue_line("markers", "security: Security tests")
    config.addinivalue_line("markers", "performance: Performance tests")
    config.addinivalue_line("markers", "slow: Slow running tests")


def pytest_collection_modifyitems(config, items):
    """Modify test collection to add automatic markers."""
    for item in items:
        # Auto-mark tests based on file paths
        if "test_security" in str(item.fspath):
            item.add_marker(pytest.mark.security)
        elif "test_performance" in str(item.fspath):
            item.add_marker(pytest.mark.performance)
        elif "test_integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
        else:
            item.add_marker(pytest.mark.unit)


# ==============================================================================
# Cleanup & Teardown
# ==============================================================================

@pytest.fixture(autouse=True)
def cleanup_after_test():
    """Automatic cleanup after each test."""
    yield
    # Add any cleanup logic here
    pass
