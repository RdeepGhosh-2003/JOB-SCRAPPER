# CareerPulse Launcher Script
$ErrorActionPreference = "SilentlyContinue"

# Check if port 8000 is active
$portOpen = $false
try {
    $tcp = New-Object System.Net.Sockets.TcpClient
    $tcp.Connect("127.0.0.1", 8000)
    $portOpen = $true
    $tcp.Close()
} catch {
    $portOpen = $false
}

if (-not $portOpen) {
    $pythonExe = "C:\Users\KIIT\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe"
    $workDir = "C:\Users\KIIT\OneDrive\Documents\Automate Jobs\Job Scrapper"
    Start-Process $pythonExe -ArgumentList "-m career_pulse.cli serve" -WorkingDirectory $workDir -WindowStyle Hidden
    Start-Sleep -Seconds 2
}

Start-Process "http://127.0.0.1:8000"
