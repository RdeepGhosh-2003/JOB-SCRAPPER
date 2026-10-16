# CareerPulse Resilient Dashboard Launcher
$ErrorActionPreference = "SilentlyContinue"

$port = 8000
$hostAddress = "127.0.0.1"

# Function to test port availability
function Test-PortOpen([string]$ip, [int]$p) {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $iar = $client.BeginConnect($ip, $p, $null, $null)
        $success = $iar.AsyncWaitHandle.WaitOne(400, $false)
        if ($success -and $client.Connected) {
            $client.EndConnect($iar)
            $client.Close()
            return $true
        }
        $client.Close()
        return $false
    } catch {
        return $false
    }
}

# If server is not running, launch it in background
if (-not (Test-PortOpen $hostAddress $port)) {
    $pythonw = "C:\Users\KIIT\AppData\Local\hermes\hermes-agent\venv\Scripts\pythonw.exe"
    $pythonExe = "C:\Users\KIIT\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe"
    $runner = if (Test-Path $pythonw) { $pythonw } else { $pythonExe }
    $workDir = "C:\Users\KIIT\OneDrive\Documents\Automate Jobs\Job Scrapper"

    $cmd = "`"$runner`" -m career_pulse.cli serve --no-reload"
    Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine = $cmd; CurrentDirectory = $workDir} | Out-Null

    # Wait up to 10 seconds for the server to bind and respond
    $maxWait = 20
    $count = 0
    while ($count -lt $maxWait) {
        Start-Sleep -Milliseconds 500
        if (Test-PortOpen $hostAddress $port) {
            break
        }
        $count++
    }
}

# Launch default browser to Dashboard URL
Start-Process "http://127.0.0.1:8000"
