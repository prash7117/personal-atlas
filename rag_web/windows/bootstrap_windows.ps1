# Copyright (c) 2026 Prashanth Shankar Narayan
# SPDX-License-Identifier: Apache-2.0

param(
    [string]$Distro = "",
    [switch]$StartDocker = $true,
    [string]$QdrantContainer = ""
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$setupScript = Join-Path $scriptDir "setup_autostart.ps1"

if (-not (Test-Path $setupScript)) {
    throw "Missing $setupScript"
}

& $setupScript -Distro $Distro -StartDocker:$StartDocker

if ($QdrantContainer) {
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if ($docker) {
        & docker update --restart unless-stopped $QdrantContainer | Out-Null
        Write-Host "Set restart policy for container: $QdrantContainer"
    } else {
        Write-Warning "Docker CLI not found in PATH. Skipping restart policy."
    }
}

Write-Host "Windows bootstrap complete."
