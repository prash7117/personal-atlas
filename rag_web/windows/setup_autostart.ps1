# Copyright (c) 2026 Prashanth Shankar Narayan
# SPDX-License-Identifier: Apache-2.0

param(
    [string]$Distro = "",
    [switch]$StartDocker = $true
)

$ErrorActionPreference = "Stop"
$wslExe = "$Env:SystemRoot\System32\wsl.exe"

function Get-DefaultWslDistro {
    $output = & $wslExe -l -v 2>$null
    if ($LASTEXITCODE -eq 0 -and $output) {
        foreach ($line in $output) {
            if ($line -match '^\s*\*\s*(.+?)\s+(Running|Stopped)\s+\d+') {
                return $Matches[1].Trim()
            }
        }
        foreach ($line in $output) {
            if ($line -match '^\s*([^\s].+?)\s+(Running|Stopped)\s+\d+') {
                return $Matches[1].Trim()
            }
        }
    }

    $output = & $wslExe -l -q 2>$null
    if ($LASTEXITCODE -eq 0 -and $output) {
        return ($output | Select-Object -First 1).Trim()
    }
    return $null
}

function Register-RagTask {
    param(
        [string]$TaskName,
        [string]$Command,
        [string]$Arguments,
        [object]$Trigger
    )

    $action = New-ScheduledTaskAction -Execute $Command -Argument $Arguments
    $settings = New-ScheduledTaskSettingsSet -Compatibility Win8 -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest

    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $Trigger -Settings $settings -Principal $principal -Force | Out-Null
}

if (-not $Distro) {
    $Distro = Get-DefaultWslDistro
    if (-not $Distro) {
        throw "Unable to detect WSL distro. Re-run with -Distro <name>."
    }
}

if ($StartDocker) {
    $dockerExe = "$Env:ProgramFiles\Docker\Docker\Docker Desktop.exe"
    if (Test-Path $dockerExe) {
        $logonTrigger = New-ScheduledTaskTrigger -AtLogOn
        Register-RagTask -TaskName "RAG-Start-Docker" -Command $dockerExe -Arguments "" -Trigger $logonTrigger
    } else {
        Write-Warning "Docker Desktop not found at $dockerExe. Skipping Docker task."
    }
}

$logonTrigger = New-ScheduledTaskTrigger -AtLogOn
$wslArgs = "-d $Distro --exec /bin/true"
Register-RagTask -TaskName "RAG-Start-WSL" -Command $wslExe -Arguments $wslArgs -Trigger $logonTrigger

$onDemandTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddYears(10)
$stopArgs = "-u root -d $Distro --exec systemctl stop rag-web"
$restartArgs = "-u root -d $Distro --exec systemctl restart rag-web"
Register-RagTask -TaskName "RAG-Stop-RAG" -Command $wslExe -Arguments $stopArgs -Trigger $onDemandTrigger
Register-RagTask -TaskName "RAG-Restart-RAG" -Command $wslExe -Arguments $restartArgs -Trigger $onDemandTrigger

Write-Host "Scheduled tasks created. Distro: $Distro"
Write-Host "On-demand tasks: RAG-Stop-RAG, RAG-Restart-RAG"
