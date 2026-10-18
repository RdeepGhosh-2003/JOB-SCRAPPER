$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectDir = Split-Path -Parent $scriptDir
$autostartScript = Join-Path $scriptDir "autostart.pyw"

$pythonw = "C:\Users\KIIT\AppData\Local\Programs\Python\Python313\pythonw.exe"
if (-not (Test-Path $pythonw)) {
    $pythonwCmd = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    if ($pythonwCmd) {
        $pythonw = $pythonwCmd.Source
    }
}

$action = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$autostartScript`"" -WorkingDirectory $projectDir
$trigger = New-ScheduledTaskTrigger -AtLogon
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -Hidden
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName "CareerPulse Autostart" -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force

Write-Host "CareerPulse Silent Autostart task installed successfully (100% windowless)."
Write-Host "To uninstall, run: .\scripts\uninstall_autostart.ps1"
