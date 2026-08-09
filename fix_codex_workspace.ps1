$workspaceId = "798f52198b2eec213f39d0338bb6708d"
$targetPath = Join-Path $env:APPDATA "Code\User\workspaceStorage\$workspaceId"
$backupPath = Join-Path $env:APPDATA "Code\User\workspaceStorage\$workspaceId.bak-codex-debug"

if (Test-Path $targetPath) {
    if (Test-Path $backupPath) {
        Remove-Item $backupPath -Recurse -Force
    }
    Rename-Item -Path $targetPath -NewName "$workspaceId.bak-codex-debug" -Force
    Write-Host "Renamed workspace storage to backup successfully."
} else {
    Write-Host "Workspace storage already missing or renamed."
}
