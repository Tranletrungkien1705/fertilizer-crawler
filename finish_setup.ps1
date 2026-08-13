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

# Windows PowerShell turns a native program's stderr into real errors, so any
# gh command that chats on stderr - including successful ones, and the "not
# found" probe below - would abort the script under ErrorActionPreference Stop.
function Try-Gh {
    param([Parameter(ValueFromRemainingArguments)] [string[]]$GhArgs)
    $old = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & $script:gh @GhArgs 2>&1 | Out-String
        return [pscustomobject]@{ Ok = ($LASTEXITCODE -eq 0); Output = $output }
    } finally {
        $ErrorActionPreference = $old
    }
}

# --- preconditions -----------------------------------------------------
Step "Checking GitHub login"
if (-not (Try-Gh auth status).Ok) {
    Bad "Not logged in. Run this first, then re-run this script:"
    Bad "  & '$gh' auth login --web"
    exit 1
}
$whoami = Try-Gh api user --jq .login
$user = $whoami.Output.Trim()
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
if ((Try-Gh repo view "$user/$RepoName" --json name).Ok) {
    Ok "$user/$RepoName already exists - reusing it"
    Try-Gh repo set-default "$user/$RepoName" | Out-Null
    git remote remove origin 2>&1 | Out-Null
    git remote add origin "https://github.com/$user/$RepoName.git"
} else {
    $created = Try-Gh repo create $RepoName $visibility --source=. --remote=origin
    if (-not $created.Ok) {
        Bad "could not create the repository:"
        Bad $created.Output.Trim()
        exit 1
    }
    Ok "created $user/$RepoName"
}

Step "Pushing the code"
git branch -M main
$ErrorActionPreference = "Continue"
git push -u origin main 2>&1 | Write-Host
$pushed = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = "Stop"
if (-not $pushed) {
    Bad "push failed. github.com:443 is intermittently blocked on Vietnamese"
    Bad "ISPs - retry, or switch the remote to SSH which stays reachable:"
    Bad "  git remote set-url origin git@github.com:$user/$RepoName.git"
    exit 1
}
Ok "pushed"

# --- secret + data -----------------------------------------------------
Step "Storing DATABASE_URL as a repository secret"
$ErrorActionPreference = "Continue"
$dsn | & $gh secret set DATABASE_URL --repo "$user/$RepoName" 2>&1 | Out-Null
$secretOk = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = "Stop"
if ($secretOk) { Ok "secret set" } else { Bad "could not set the secret - add it by hand in Settings > Secrets" }

Step "Copying the local catalogue into Neon"
& .\.venv\Scripts\python.exe push_to_postgres.py

Step "Triggering the workflow now"
$run = Try-Gh workflow run crawl.yml --repo "$user/$RepoName" -f limit=20
if ($run.Ok) {
    Ok "started - watch it with:"
    Ok "  & '$gh' run watch --repo $user/$RepoName"
} else {
    Bad "could not trigger it yet (GitHub needs a moment to register a new"
    Bad "workflow file); run it from the Actions tab, or retry this script."
}

Write-Host "`nDone. Repository: https://github.com/$user/$RepoName" -ForegroundColor Green
