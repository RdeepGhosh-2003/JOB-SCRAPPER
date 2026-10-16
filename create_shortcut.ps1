$desktop = [Environment]::GetFolderPath('Desktop')
$wshell = New-Object -ComObject WScript.Shell
$shortcutPath = Join-Path $desktop "CareerPulse Dashboard.lnk"

$shortcut = $wshell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "wscript.exe"
$shortcut.Arguments = '"C:\Users\KIIT\OneDrive\Documents\Automate Jobs\Job Scrapper\launch_dashboard.vbs"'
$shortcut.WorkingDirectory = "C:\Users\KIIT\OneDrive\Documents\Automate Jobs\Job Scrapper"
$shortcut.Description = "CareerPulse Local Career Portal Job Tracker"
$shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,220"
$shortcut.Save()

# Also create a direct .url file for instant browser launch
$urlPath = Join-Path $desktop "CareerPulse Web.url"
@'
[InternetShortcut]
URL=http://127.0.0.1:8000
IconIndex=220
IconFile=C:\Windows\System32\shell32.dll
'@ | Set-Content -Path $urlPath -Encoding UTF8

Write-Output "Created: $shortcutPath"
Write-Output "Created: $urlPath"
