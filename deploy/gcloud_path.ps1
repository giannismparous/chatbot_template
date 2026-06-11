# Add Google Cloud SDK to PATH for the current PowerShell session.
# Install (if missing): winget install Google.CloudSDK
# After first install, restart Cursor or run: . .\deploy\gcloud_path.ps1

$gcloudBin = Join-Path $env:LOCALAPPDATA "Google\Cloud SDK\google-cloud-sdk\bin"
if (-not (Test-Path (Join-Path $gcloudBin "gcloud.cmd"))) {
    $gcloudBin = "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin"
}
if (-not (Test-Path (Join-Path $gcloudBin "gcloud.cmd"))) {
    Write-Error "gcloud not found. Install with: winget install Google.CloudSDK"
    exit 1
}
$env:Path = "$gcloudBin;$env:Path"
Write-Host "gcloud on PATH: $gcloudBin"
gcloud --version
