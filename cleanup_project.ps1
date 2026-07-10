# cleanup_project.ps1

Write-Host "Nettoyage Restor-PC RescueGrid..." -ForegroundColor Cyan

$archive = "docs\archive_old_readmes"
New-Item -ItemType Directory -Force -Path $archive | Out-Null

$patterns = @(
    "README_V*.md",
    "RELEASE_NOTES_*.md"
)

foreach ($pattern in $patterns) {
    Get-ChildItem -Path . -Filter $pattern -File | ForEach-Object {
        Write-Host "Archive: $($_.Name)"
        Move-Item $_.FullName -Destination $archive -Force
    }
}

$keep = @(
    "README.md",
    "CHANGELOG.md",
    "README_DEPLOIEMENT.md",
    "README_LANCEMENT.md"
)

Write-Host "Fichiers principaux conservés :" -ForegroundColor Green
$keep | ForEach-Object { Write-Host " - $_" }

Write-Host "Nettoyage terminé." -ForegroundColor Green