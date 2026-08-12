# Completes the hosted setup once you are logged into GitHub and have a Neon
# connection string in .env.
#
#   .\finish_setup.ps1                       # private repo named fertilizer-crawler
#   .\finish_setup.ps1 -RepoName my-crawler  # different name
#   .\finish_setup.ps1 -Public               # public repo
#
# Safe to re-run: each step checks whether it is already done.

param(
    [string]$RepoName = "fertilizer-crawler",
    [switch]$Public
)

$ErrorActionPreference = "Stop"
$gh = "C:\Program Files\GitHub CLI\gh.exe"
Set-Location $PSScriptRoot

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "    $msg" -ForegroundColor Green }
function Bad($msg)  { Write-Host "    $msg" -ForegroundColor Red }

# --- preconditions -----------------------------------------------------
Step "Checking GitHub login"
& $gh auth status 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Bad "Not logged in. Run this first, then re-run this script:"
    Bad "  & '$gh' auth login --web"
    exit 1
}
$user = (& $gh api user --jq .login)
Ok "logged in as $user"

Step "Checking Neon connection string"
if (-not (Test-Path ".env")) {
    Bad ".env not found. Create it from the template and paste the Neon string:"
    Bad "  copy .env.example .env"
    exit 1
}
$dsn = (Get-Content .env | Where-Object { $_ -match '^\s*DATABASE_URL\s*=' }) -replace '^\s*DATABASE_URL\s*=\s*', ''
if (-not $dsn -or $dsn -notmatch '^postgres') {
    Bad "DATABASE_URL in .env is empty or not a Postgres string."
    exit 1
}
Ok "found connection to $(($dsn -split '@')[-1] -split '/' | Select-Object -First 1)"

Step "Testing the database connection"
& .\.venv\Scripts\python.exe push_to_postgres.py --check
if ($LASTEXITCODE -ne 0) { Bad "connection failed - fix .env before continuing"; exit 1 }

# --- github repo -------------------------------------------------------
Step "Creating the GitHub repository"
$visibility = if ($Public) { "--public" } else { "--private" }
$existing = & $gh repo view "$user/$RepoName" --json name 2>$null
if ($LASTEXITCODE -eq 0) {
    Ok "$user/$RepoName already exists - reusing it"
    git remote remove origin 2>$null
    git remote add origin "https://github.com/$user/$RepoName.git"
} else {
    & $gh repo create $RepoName $visibility --source=. --remote=origin
    if ($LASTEXITCODE -ne 0) { Bad "could not create the repository"; exit 1 }
    Ok "created $user/$RepoName"
}

Step "Pushing the code"
git branch -M main
git push -u origin main
if ($LASTEXITCODE -ne 0) {
    Bad "push failed. github.com:443 is intermittently blocked on Vietnamese"
    Bad "ISPs - retry, or switch the remote to SSH which stays reachable:"
    Bad "  git remote set-url origin git@github.com:$user/$RepoName.git"
    exit 1
}
Ok "pushed"

# --- secret + data -----------------------------------------------------
Step "Storing DATABASE_URL as a repository secret"
$dsn | & $gh secret set DATABASE_URL --repo "$user/$RepoName"
Ok "secret set"

Step "Copying the local catalogue into Neon"
& .\.venv\Scripts\python.exe push_to_postgres.py

Step "Triggering the workflow now"
& $gh workflow run crawl.yml --repo "$user/$RepoName" -f limit=20
if ($LASTEXITCODE -eq 0) {
    Ok "started - watch it with:"
    Ok "  & '$gh' run watch --repo $user/$RepoName"
} else {
    Bad "could not trigger it; run it by hand from the Actions tab"
}

Write-Host "`nDone. Repository: https://github.com/$user/$RepoName" -ForegroundColor Green
