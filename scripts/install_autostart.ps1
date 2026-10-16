$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$batchPath = Join-Path $scriptDir "launch.bat"
if (-not (Test-Path $batchPath)) {
    $batchPath = "c:\Users\KIIT\OneDrive\Documents\Automate Jobs\Job Scrapper\scripts\launch.bat"
}

$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$batchPath`""
$trigger = New-ScheduledTaskTrigger -AtLogon
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Seconds 0)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName "CareerPulse Autostart" -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force

Write-Host "CareerPulse Autostart task installed successfully."
Write-Host "To uninstall, run: .\scripts\uninstall_autostart.ps1"
