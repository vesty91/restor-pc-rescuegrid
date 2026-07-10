param(
    [Parameter(Mandatory=$true)]
    [string]$GitHubUrl,

    [string]$CommitMessage = "Initial release Restor-PC RescueGrid v9.2"
)

Write-Host "=== Restor-PC RescueGrid -> GitHub ===" -ForegroundColor Cyan

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "ERREUR: Git n'est pas installé." -ForegroundColor Red
    exit 1
}

$gitignore = @"
.venv/
__pycache__/
*.pyc
.env
*.db
*.sqlite
storage/
backend/storage/
Intervention_*/
*.zip
*.7z
tools/*.exe
tools/*.msi
tools/*.iso
*.log
"@

Set-Content -Path ".gitignore" -Value $gitignore -Encoding UTF8
Write-Host ".gitignore créé." -ForegroundColor Green

if (-not (Test-Path ".git")) {
    git init
}

git add .
git commit -m "$CommitMessage"

git branch -M main

$remoteExists = git remote | Select-String "origin"
if ($remoteExists) {
    git remote set-url origin $GitHubUrl
} else {
    git remote add origin $GitHubUrl
}

git push -u origin main

Write-Host "Projet envoyé sur GitHub avec succès." -ForegroundColor Green