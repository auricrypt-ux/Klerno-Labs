# ==============================================================================
# Klerno Labs - Cross-Platform Development Launcher
# ==============================================================================
# Enterprise-grade development setup script with comprehensive error handling
# Supports Windows PowerShell, Windows Core, and cross-platform scenarios

Param(
    [string]$Port = "8000",
    [string]$Environment = "development",
    [switch]$SkipVenv,
    [switch]$Force,
    [switch]$Verbose,
    [switch]$Help
)

# ==============================================================================
# Script Configuration
# ==============================================================================
$ErrorActionPreference = "Stop"
$InformationPreference = "Continue"
$WarningPreference = "Continue"

$SCRIPT_VERSION = "2.0.0"
$PYTHON_MIN_VERSION = [Version]"3.11.0"
$REPO_NAME = "Klerno Labs"

# ==============================================================================
# Utility Functions
# ==============================================================================
function Write-Header {
    param([string]$Title, [string]$Subtitle = "")
    
    Write-Host "`n" -NoNewline
    Write-Host "=" * 80 -ForegroundColor Cyan
    Write-Host "  $Title" -ForegroundColor Yellow
    if ($Subtitle) {
        Write-Host "  $Subtitle" -ForegroundColor White
    }
    Write-Host "=" * 80 -ForegroundColor Cyan
    Write-Host ""
}

function Write-Step {
    param([string]$Message, [int]$Step = 0)
    
    if ($Step -gt 0) {
        Write-Host "[$Step] " -NoNewline -ForegroundColor Green
    }
    Write-Host $Message -ForegroundColor White
}

function Write-Success {
    param([string]$Message)
    Write-Host "✅ $Message" -ForegroundColor Green
}

function Write-Warning {
    param([string]$Message)
    Write-Host "⚠️  $Message" -ForegroundColor Yellow
}

function Write-Error {
    param([string]$Message)
    Write-Host "❌ $Message" -ForegroundColor Red
}

function Test-Command {
    param([string]$Command)
    
    try {
        Get-Command $Command -ErrorAction Stop | Out-Null
        return $true
    }
    catch {
        return $false
    }
}

function Get-PythonVersion {
    param([string]$PythonCommand = "python")
    
    try {
        $versionOutput = & $PythonCommand --version 2>&1
        if ($versionOutput -match "Python (\d+\.\d+\.\d+)") {
            return [Version]$Matches[1]
        }
    }
    catch {
        return $null
    }
    return $null
}

function Show-Help {
    @"
Klerno Labs Development Launcher v$SCRIPT_VERSION

USAGE:
    .\start.ps1 [OPTIONS]

OPTIONS:
    -Port <number>          Port to run the server on (default: 8000)
    -Environment <env>      Environment mode (development, production) (default: development)
    -SkipVenv              Skip virtual environment creation/activation
    -Force                 Force reinstall of all dependencies
    -Verbose               Enable verbose output
    -Help                  Show this help message

EXAMPLES:
    .\start.ps1                          # Standard development setup
    .\start.ps1 -Port 8080              # Run on different port
    .\start.ps1 -Force                  # Force clean reinstall
    .\start.ps1 -Environment production  # Production-like setup

REQUIREMENTS:
    - Python 3.11+ (recommended: 3.12)
    - Windows PowerShell 5.1+ or PowerShell Core 7+
    - Internet connection for dependency installation

"@
}

# ==============================================================================
# Main Execution
# ==============================================================================
function Main {
    if ($Help) {
        Show-Help
        exit 0
    }

    Write-Header "$REPO_NAME Development Launcher" "Version $SCRIPT_VERSION"
    
    Write-Information "Environment: $Environment"
    Write-Information "Target Port: $Port"
    Write-Information "PowerShell Version: $($PSVersionTable.PSVersion)"
    Write-Information "Operating System: $($PSVersionTable.OS)"

    try {
        # Step 1: Validate Environment
        Write-Step "Validating development environment..." 1
        Test-Environment

        # Step 2: Locate and Validate Python
        Write-Step "Locating Python installation..." 2
        $pythonCmd = Find-Python

        # Step 3: Setup Virtual Environment
        if (!$SkipVenv) {
            Write-Step "Setting up virtual environment..." 3
            Setup-VirtualEnvironment -PythonCommand $pythonCmd
        }

        # Step 4: Install Dependencies
        Write-Step "Installing dependencies..." 4
        Install-Dependencies -Force:$Force

        # Step 5: Setup Configuration
        Write-Step "Setting up configuration..." 5
        Setup-Configuration

        # Step 6: Run Health Checks
        Write-Step "Running system health checks..." 6
        Run-HealthChecks

        # Step 7: Start Application
        Write-Step "Starting application..." 7
        Start-Application -Port $Port -Environment $Environment

    }
    catch {
        Write-Error "Setup failed: $($_.Exception.Message)"
        Write-Host "`nFor help, run: .\start.ps1 -Help" -ForegroundColor Yellow
        exit 1
    }
}

function Test-Environment {
    # Verify we're in the correct directory
    $requiredFiles = @("requirements.txt", "app\main.py", "README.md")
    
    foreach ($file in $requiredFiles) {
        if (!(Test-Path $file)) {
            throw "Missing required file: $file. Ensure you're in the Klerno Labs repository root."
        }
    }

    # Set working directory to script location
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    if ($scriptDir) {
        Set-Location $scriptDir
    }

    Write-Success "Repository structure validated"
}

function Find-Python {
    $pythonCandidates = @(
        "py -3.12", "py -3.11", "python3.12", "python3.11", "python3", "python"
    )

    foreach ($candidate in $pythonCandidates) {
        try {
            $version = Get-PythonVersion -PythonCommand $candidate
            if ($version -and $version -ge $PYTHON_MIN_VERSION) {
                Write-Success "Found Python $version using command: $candidate"
                return $candidate
            }
        }
        catch {
            continue
        }
    }

    throw "Python $PYTHON_MIN_VERSION or higher not found. Please install from https://python.org"
}

function Setup-VirtualEnvironment {
    param([string]$PythonCommand)

    $venvPath = ".\.venv"
    
    if (!(Test-Path $venvPath) -or $Force) {
        if ($Force -and (Test-Path $venvPath)) {
            Write-Warning "Removing existing virtual environment..."
            Remove-Item $venvPath -Recurse -Force
        }

        Write-Information "Creating virtual environment..."
        & $PythonCommand -m venv $venvPath
        
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to create virtual environment"
        }
    }

    # Activate virtual environment
    $activateScript = "$venvPath\Scripts\Activate.ps1"
    if (Test-Path $activateScript) {
        Write-Information "Activating virtual environment..."
        & $activateScript
    }
    else {
        throw "Virtual environment activation script not found"
    }

    Write-Success "Virtual environment ready"
}

function Install-Dependencies {
    param([switch]$Force)

    # Upgrade pip first
    Write-Information "Upgrading pip..."
    python -m pip install --upgrade pip setuptools wheel

    if ($Force) {
        Write-Information "Force reinstalling all dependencies..."
        python -m pip install --force-reinstall -r requirements.txt
    }
    else {
        Write-Information "Installing/updating dependencies..."
        python -m pip install -r requirements.txt
    }

    # Install development dependencies
    Write-Information "Installing development dependencies..."
    python -m pip install pytest pytest-asyncio pytest-cov black isort flake8 mypy

    Write-Success "Dependencies installed successfully"
}

function Setup-Configuration {
    $envFile = ".\.env"
    
    if (!(Test-Path $envFile) -or $Force) {
        Write-Information "Creating environment configuration..."
        
        $envContent = @"
# ==============================================================================
# Klerno Labs - Development Environment Configuration
# ==============================================================================
# Generated by start.ps1 on $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")

# Application Settings
APP_ENV=$Environment
DEMO_MODE=true
DEBUG=true

# Security (CHANGE IN PRODUCTION!)
SECRET_KEY=dev-secret-key-change-in-production-32-chars
JWT_SECRET=dev-jwt-secret-change-in-production
ACCESS_TOKEN_EXPIRE_MINUTES=60

# Admin Bootstrap
BOOTSTRAP_ADMIN_EMAIL=admin@klerno.dev
BOOTSTRAP_ADMIN_PASSWORD=KlernoLabs2025!

# Database
DATABASE_URL=sqlite:///./data/klerno.db

# XRPL Configuration
XRPL_RPC_URL=wss://s.altnet.rippletest.net:51233

# External Services (Optional - Add your keys)
OPENAI_API_KEY=your-openai-key-here
SENDGRID_API_KEY=your-sendgrid-key-here
STRIPE_SECRET_KEY=your-stripe-secret-key-here
STRIPE_PRICE_ID=your-stripe-price-id-here
STRIPE_WEBHOOK_SECRET=your-stripe-webhook-secret-here

# Email Configuration
ALERT_EMAIL_FROM=alerts@klerno.dev
ALERT_EMAIL_TO=you@example.com

# Performance & Monitoring
ENABLE_METRICS=true
LOG_LEVEL=INFO
"@

        $envContent | Out-File -FilePath $envFile -Encoding UTF8
        Write-Success "Environment configuration created: $envFile"
    }
    else {
        Write-Success "Environment configuration already exists"
    }

    # Ensure data directory exists
    if (!(Test-Path ".\data")) {
        New-Item -ItemType Directory -Name "data" -Force | Out-Null
        Write-Success "Created data directory"
    }
}

function Run-HealthChecks {
    Write-Information "Running comprehensive health checks..."
    
    try {
        python sanity_check.py
        Write-Success "All health checks passed"
    }
    catch {
        Write-Warning "Some health checks failed, but continuing startup..."
        Write-Information "Run 'python sanity_check.py' manually for detailed diagnostics"
    }
}

function Start-Application {
    param([string]$Port, [string]$Environment)

    Write-Header "Starting Klerno Labs Application" "Environment: $Environment | Port: $Port"
    
    $uvicornArgs = @(
        "app.main:app"
        "--host", "0.0.0.0"
        "--port", $Port
    )

    if ($Environment -eq "development") {
        $uvicornArgs += "--reload"
        $uvicornArgs += "--log-level", "debug"
    }
    else {
        $uvicornArgs += "--log-level", "info"
    }

    Write-Information "Application will be available at:"
    Write-Host "  🌐 Local:   http://localhost:$Port" -ForegroundColor Green
    Write-Host "  🌐 Network: http://0.0.0.0:$Port" -ForegroundColor Green
    Write-Host "  📚 API Docs: http://localhost:$Port/docs" -ForegroundColor Green
    Write-Host ""
    Write-Information "Press Ctrl+C to stop the server"
    Write-Host ""

    try {
        uvicorn @uvicornArgs
    }
    catch {
        Write-Error "Failed to start application: $($_.Exception.Message)"
        Write-Information "Check that port $Port is available and try again"
        exit 1
    }
}

# ==============================================================================
# Script Entry Point
# ==============================================================================
if ($MyInvocation.InvocationName -ne '.') {
    Main
}
