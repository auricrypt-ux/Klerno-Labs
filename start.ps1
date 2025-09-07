Param(
    [string]$Port = "8000"
)

Write-Host "Klerno Labs quick starter (Windows)"
Write-Host "----------------------------------"

# 1) Move to script directory (repo root if saved there)
Set-Location -Path (Split-Path -Parent $MyInvocation.MyCommand.Path)

# 2) Verify we're in a repo (has requirements.txt and app/main.py)
if (!(Test-Path ".\requirements.txt") -or !(Test-Path ".\app\main.py")) {
    Write-Error "This script must be placed in your Klerno Labs repo folder (the one with requirements.txt and app\main.py)."
    exit 1
}

# 3) Ensure Python 3.11 is available
$py311 = & py -3.11 -V 2>$null
if (!$py311) {
    Write-Error "Python 3.11 not found. Please install Python 3.11 from python.org and try again."
    exit 1
}

# 4) Create / activate venv .venv311
if (!(Test-Path ".\.venv311")) {
    Write-Host "Creating virtual environment (.venv311) with Python 3.11..."
    & py -3.11 -m venv .venv311
}

Write-Host "Activating virtual environment..."
. .\.venv311\Scripts\Activate.ps1

# 5) Upgrade pip
python -m pip install --upgrade pip

# 6) Install hard prerequisites to avoid NumPy/Pandas build issues
pip install --only-binary=:all: numpy==1.26.4 pandas==2.2.1

# 7) Install project requirements
pip install -r requirements.txt

# 8) Ensure auth deps present (PyJWT, passlib[bcrypt], python-dotenv)
pip install PyJWT==2.8.0 passlib[bcrypt]==1.7.4 python-dotenv==1.0.1

# 9) Create .env if missing
if (!(Test-Path ".\.env")) {
@"
APP_ENV=dev
DEMO_MODE=true
SECRET_KEY=change_me_32+_chars
ACCESS_TOKEN_EXPIRE_MINUTES=60
BOOTSTRAP_ADMIN_EMAIL=klerno@outlook.com
BOOTSTRAP_ADMIN_PASSWORD=Labs2025
STRIPE_PUBLIC_KEY=pk_test_xxx
STRIPE_SECRET_KEY=sk_test_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx
SENDGRID_API_KEY=SG.xxxxx
ALERTS_FROM_EMAIL=alerts@klerno.dev
DATABASE_URL=sqlite:///./klerno.db
"@ | Out-File -FilePath ".\.env" -Encoding utf8
    Write-Host "Created .env"
} else {
    Write-Host ".env already exists (leaving it as-is)."
}

# 10) Launch server
Write-Host "Starting Uvicorn on port $Port ..."
uvicorn app.main:app --reload --port $Port
