
# ==============================================================================
# Klerno Labs - AI-Powered AML Risk Intelligence Platform
# ==============================================================================

[![License](https://img.shields.io/badge/License-Proprietary-red.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-green.svg)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](Dockerfile)
[![Security](https://img.shields.io/badge/Security-Enhanced-brightgreen.svg)](#security)
[![XRPL](https://img.shields.io/badge/XRPL-Native-orange.svg)](https://xrpl.org)

> **World-class AML risk intelligence for XRPL & beyond**  
> Real-time transaction tagging, risk scoring, alerts, and explainable insights designed for compliance teams that demand speed, clarity, and confidence.

## 🚀 Quick Start

### Prerequisites
- **Python 3.11+** (3.12 recommended)
- **Docker** (optional, for containerized deployment)
- **PostgreSQL** (for production deployments)

### Development Setup

#### Option 1: Automated Setup (Windows)
```powershell
# Clone and run the quick starter
.\start.ps1
```

#### Option 2: Manual Setup (All Platforms)
```bash
# Clone the repository
git clone https://github.com/Klerno-Labs/Klerno-Labs.git
cd Klerno-Labs

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# or
.venv\Scripts\activate     # Windows

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env with your configuration

# Run the application
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

#### Option 3: Docker Deployment
```bash
# Build and run with Docker
docker build -t klerno-labs .
docker run -p 8000:8000 -e APP_ENV=dev klerno-labs

# Or with Docker Compose
docker-compose up -d
```

### First Run Configuration

1. **Navigate to**: `http://localhost:8000`
2. **Set up admin account**: Follow the on-screen setup wizard
3. **Configure API keys**: Go to `/admin` → API Key Management
4. **Test integration**: Use the built-in XRPL sandbox

## 🏗️ Architecture

### Core Components

```
├── app/                    # Core application
│   ├── main.py            # FastAPI application entry point
│   ├── models.py          # Pydantic data models
│   ├── security/          # Authentication & authorization
│   ├── hardening.py       # Security middleware
│   ├── integrations/      # Blockchain integrations
│   └── routes/            # API endpoints
├── automation/            # AI-powered automation
├── data/                  # Data storage & samples
├── docs/                  # Documentation
└── launch/                # Marketing & launch materials
```

### Technology Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| **Backend** | FastAPI + Python 3.11+ | High-performance async API |
| **Database** | PostgreSQL + SQLite | Data persistence & caching |
| **Blockchain** | XRPL-py | Native XRPL integration |
| **AI/ML** | OpenAI GPT-4 | Risk analysis & explanations |
| **Security** | JWT + bcrypt | Authentication & session management |
| **Monitoring** | Built-in metrics | Performance & health tracking |
| **Frontend** | Jinja2 templates | Server-side rendered UI |

## 🔧 Features

### 💰 AML Risk Intelligence
- **Real-time transaction analysis** across XRPL networks
- **Advanced risk scoring** with machine learning models
- **Automated transaction tagging** for compliance categories
- **Explainable AI insights** - understand *why* transactions are flagged

### 🚨 Compliance Automation
- **Instant alerts** with detailed risk explanations
- **Regulatory reporting** with exportable summaries
- **Audit trails** with complete transaction history
- **Custom risk thresholds** per organization

### 📊 Analytics & Reporting
- **Interactive dashboards** with real-time metrics
- **Executive summaries** compress days of activity into actionable insights
- **Trend analysis** to identify emerging risk patterns
- **Export capabilities** for compliance documentation

### 🔐 Enterprise Security
- **Multi-factor authentication** with role-based access control
- **API key rotation** with granular permissions
- **CSRF protection** and comprehensive security headers
- **Audit logging** for all system activities

## 🛠️ Development

### Code Quality Standards
- **Type hints** throughout the codebase
- **Comprehensive testing** with pytest
- **Security scanning** with automated tools
- **Code formatting** with black and isort
- **Documentation** with automated API docs

### Running Tests
```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=html

# Run specific test categories
pytest app/tests/test_security.py -v
pytest app/tests/test_compliance.py -v
```

### API Documentation
- **Interactive docs**: `http://localhost:8000/docs`
- **ReDoc format**: `http://localhost:8000/redoc`
- **OpenAPI spec**: `http://localhost:8000/openapi.json`

## 🔒 Security

### Security Features
- ✅ **HTTPS enforcement** with HSTS headers
- ✅ **Content Security Policy** preventing XSS attacks
- ✅ **CSRF protection** with double-submit cookies
- ✅ **Rate limiting** to prevent abuse
- ✅ **Input validation** and sanitization
- ✅ **Secure session management** with JWT tokens
- ✅ **API key rotation** and secure storage

### Security Reporting
If you discover a security vulnerability, please email: **security@klerno.com**

## 📈 Performance

### Optimization Features
- **Async/await** throughout for high concurrency
- **Connection pooling** for database efficiency
- **Caching strategies** for frequently accessed data
- **Efficient serialization** with orjson
- **Database indexing** for query optimization
- **Horizontal scaling** ready architecture

### Performance Metrics
- **Response times**: < 100ms for most endpoints
- **Throughput**: 1000+ requests/second
- **Memory usage**: < 512MB typical operation
- **Database queries**: Optimized with indexes

## 🌐 Deployment

### Supported Platforms
- **Docker** (recommended)
- **Render.com** (configured)
- **Railway** (configured)
- **AWS/Azure/GCP** (with Docker)
- **Self-hosted** (Linux/Windows/macOS)

### Environment Variables
```bash
# Application Settings
APP_ENV=production
DEMO_MODE=false
SECRET_KEY=your-32-char-secret-key

# Database
DATABASE_URL=postgresql://user:password@host:port/dbname

# XRPL Integration
XRPL_RPC_URL=wss://xrplcluster.com/

# OpenAI (optional)
OPENAI_API_KEY=your-openai-key
OPENAI_MODEL=gpt-4o-mini

# Email Notifications
SENDGRID_API_KEY=your-sendgrid-key
ALERT_EMAIL_FROM=alerts@yourdomain.com

# Stripe (for payments)
STRIPE_SECRET_KEY=your-stripe-key
STRIPE_PRICE_ID=your-price-id
```

## 📚 Documentation

- 📖 **[API Documentation](docs/api.md)** - Complete API reference
- 🏗️ **[Architecture Guide](docs/architecture.md)** - System design and patterns
- 🚀 **[Deployment Guide](docs/deployment.md)** - Production deployment instructions
- 🔐 **[Security Guide](docs/security.md)** - Security best practices
- 🧪 **[Testing Guide](docs/testing.md)** - Testing strategies and guidelines

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details.

### Development Workflow
1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes with tests
4. Run the test suite (`pytest`)
5. Commit your changes (`git commit -m 'Add amazing feature'`)
6. Push to the branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

## 📄 License

This project is proprietary software. All rights reserved by Klerno Labs.  
See [LICENSE](LICENSE) for details.

## 🏢 About Klerno Labs

Klerno Labs is at the forefront of AML risk intelligence, building tools that give compliance teams clarity at the speed of crypto. We believe in transparency, explainability, and precision in financial crime prevention.

**Contact**: [hello@klerno.com](mailto:hello@klerno.com)  
**Website**: [klerno.com](https://klerno.com)  
**LinkedIn**: [Klerno Labs](https://linkedin.com/company/klerno-labs)

---

<div align="center">
  <strong>Clarity at the speed of crypto.</strong><br>
  Built with ❤️ by the Klerno Labs team
</div>
