param(
    [ValidateSet('Start', 'Status', 'Stop')]
    [string]$Action = 'Start',
    [string]$LaptopIp = '192.168.88.254',
    [string]$PhoneIp = '192.168.88.252',
    [string]$CameraName = 'Lenovo FHD Webcam'
)

$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$dashboard = Join-Path $env:USERPROFILE 'OneDrive\Documents\GitHub\IRC_DASHBOARD'
$runtime = Join-Path $workspace 'work\runtime'
$stateFile = Join-Path $runtime 'irc-rover-processes.json'
$mediaTemplate = Join-Path $PSScriptRoot 'rover-single.yml'
$mediaConfig = Join-Path $runtime 'rover-single-runtime.yml'
$phoneServer = Join-Path $workspace 'work\phone-dashboard.py'
$cameraScript = Join-Path $PSScriptRoot 'test-rovercam.cjs'

function Get-SavedProcesses {
    if (-not (Test-Path -LiteralPath $stateFile)) { return @() }
    return @((Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json).processes)
}

function New-ProcessEntry([string]$Name, $Process) {
    return [pscustomobject]@{
        name = $Name
        pid = $Process.Id
        startTimeUtcTicks = $Process.StartTime.ToUniversalTime().Ticks
    }
}

function Get-MatchingSavedProcess($Entry) {
    if (-not $Entry.startTimeUtcTicks) { return $null }
    $process = Get-Process -Id $Entry.pid -ErrorAction SilentlyContinue
    if (-not $process) { return $null }
    if ($process.StartTime.ToUniversalTime().Ticks -ne [long]$Entry.startTimeUtcTicks) { return $null }
    return $process
}

function Get-PortProcess([int]$Port) {
    $owner = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction Stop |
        Select-Object -First 1 -ExpandProperty OwningProcess
    return Get-Process -Id $owner -ErrorAction Stop
}

function Stop-ProcessTree([int]$ProcessId) {
    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcessId" -ErrorAction SilentlyContinue
    foreach ($child in $children) { Stop-ProcessTree ([int]$child.ProcessId) }
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

function Stop-SavedProcesses($Entries) {
    [array]$reverse = @($Entries)
    [array]::Reverse($reverse)
    foreach ($entry in $reverse) {
        if (Get-MatchingSavedProcess $entry) {
            Stop-ProcessTree ([int]$entry.pid)
        }
    }
}

function Wait-Http([string]$Url, [int]$Seconds = 20) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    do {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -lt 500) { return }
        } catch {}
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)
    throw "Timed out waiting for $Url"
}

function Show-Status {
    $saved = Get-SavedProcesses
    $rows = foreach ($entry in $saved) {
        $process = Get-MatchingSavedProcess $entry
        [pscustomobject]@{
            Component = $entry.name
            State = if ($process) { 'running' } else { 'stopped' }
            PID = $entry.pid
        }
    }
    if ($rows) { $rows | Format-Table -AutoSize } else { Write-Host 'No launcher state is recorded.' }

    foreach ($endpoint in @(
        'http://127.0.0.1:8000/api/radio-link',
        'http://127.0.0.1:5173/',
        "http://${LaptopIp}:5174/",
        'http://127.0.0.1:8889/rovercam/'
    )) {
        try {
            $response = Invoke-WebRequest -Uri $endpoint -UseBasicParsing -TimeoutSec 2
            Write-Host ("UP   {0} ({1})" -f $endpoint, $response.StatusCode)
        } catch {
            Write-Host ("DOWN {0}" -f $endpoint)
        }
    }
}

if ($Action -eq 'Status') { Show-Status; exit 0 }

if ($Action -eq 'Stop') {
    $saved = Get-SavedProcesses
    [array]$reverse = @($saved)
    [array]::Reverse($reverse)
    foreach ($entry in $reverse) {
        if (Get-MatchingSavedProcess $entry) {
            Stop-ProcessTree ([int]$entry.pid)
            Write-Host "Stopped $($entry.name)"
        } else {
            Write-Host "Skipped stale entry for $($entry.name)"
        }
    }
    if (Test-Path -LiteralPath $stateFile) { Remove-Item -LiteralPath $stateFile -Force }
    exit 0
}

if (-not (Test-Path -LiteralPath $dashboard)) { throw "Dashboard repository not found at $dashboard" }
New-Item -ItemType Directory -Path $runtime -Force | Out-Null

$existing = Get-SavedProcesses | Where-Object { Get-MatchingSavedProcess $_ }
if ($existing) {
    throw 'The launcher already has running processes. Run this script with -Action Status or -Action Stop first.'
}

$requiredPorts = 8000, 5173, 5174, 8889, 8189, 9997
$busy = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object LocalPort -in $requiredPorts
if ($busy) {
    $details = ($busy | ForEach-Object { "$($_.LocalAddress):$($_.LocalPort) PID $($_.OwningProcess)" }) -join ', '
    throw "Required ports are already in use. Stop the previous IRC Rover system first. $details"
}

$template = Get-Content -LiteralPath $mediaTemplate -Raw
$template = $template.Replace('192.168.88.254', $LaptopIp).Replace('192.168.88.252', $PhoneIp)
Set-Content -LiteralPath $mediaConfig -Value $template -Encoding UTF8

$mediaExe = Get-Item "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\bluenviron.mediamtx_*\mediamtx.exe" |
    Select-Object -First 1 -ExpandProperty FullName
$backendPython = Join-Path $dashboard '.venv\Scripts\python.exe'
$nodeExe = (Get-Command node.exe).Source
$pythonExe = (Get-Command python.exe).Source
$viteEntry = Join-Path $dashboard 'node_modules\vite\bin\vite.js'
$codex = Get-AppxPackage OpenAI.Codex | Select-Object -First 1
if (-not $codex) { throw 'The camera automation runtime was not found. Keep Codex installed or use the manual publisher page.' }
$playwright = Join-Path $codex.InstallLocation 'app\resources\cua_node\bin\node_modules\playwright-core'

$started = [System.Collections.Generic.List[object]]::new()
try {
    $media = Start-Process -FilePath $mediaExe -ArgumentList @($mediaConfig) -WorkingDirectory $workspace `
        -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtime 'mediamtx.log') `
        -RedirectStandardError (Join-Path $runtime 'mediamtx-error.log')
    $started.Add((New-ProcessEntry 'MediaMTX' $media))
    Wait-Http 'http://127.0.0.1:8889/rovercam/publish'
    $started[$started.Count - 1] = New-ProcessEntry 'MediaMTX' (Get-PortProcess 8889)

    $oldNoise = $env:MIKROTIK_ALLOW_DISRUPTIVE_NOISE_SCAN
    $env:MIKROTIK_ALLOW_DISRUPTIVE_NOISE_SCAN = 'false'
    $backend = Start-Process -FilePath $backendPython -ArgumentList @('-m','uvicorn','main:app','--host','127.0.0.1','--port','8000','--env-file','.env') `
        -WorkingDirectory (Join-Path $dashboard 'backend') -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $runtime 'backend.log') -RedirectStandardError (Join-Path $runtime 'backend-error.log')
    $env:MIKROTIK_ALLOW_DISRUPTIVE_NOISE_SCAN = $oldNoise
    $started.Add((New-ProcessEntry 'Dashboard backend' $backend))
    Wait-Http 'http://127.0.0.1:8000/api/radio-link' 30
    $started[$started.Count - 1] = New-ProcessEntry 'Dashboard backend' (Get-PortProcess 8000)

    $frontend = Start-Process -FilePath $nodeExe -ArgumentList @($viteEntry,'--host','127.0.0.1','--port','5173','--strictPort') `
        -WorkingDirectory $dashboard -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $runtime 'frontend.log') -RedirectStandardError (Join-Path $runtime 'frontend-error.log')
    $started.Add((New-ProcessEntry 'Laptop dashboard' $frontend))
    Wait-Http 'http://127.0.0.1:5173/'
    $started[$started.Count - 1] = New-ProcessEntry 'Laptop dashboard' (Get-PortProcess 5173)

    $phone = Start-Process -FilePath $pythonExe -ArgumentList @($phoneServer,$LaptopIp,$PhoneIp) `
        -WorkingDirectory $workspace -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $runtime 'phone-dashboard.log') -RedirectStandardError (Join-Path $runtime 'phone-dashboard-error.log')
    $started.Add((New-ProcessEntry 'Phone dashboard' $phone))
    Wait-Http "http://${LaptopIp}:5174/"
    $started[$started.Count - 1] = New-ProcessEntry 'Phone dashboard' (Get-PortProcess 5174)

    $oldPlaywright = $env:PLAYWRIGHT_CORE_PATH
    $oldCameraName = $env:ROVER_CAMERA_NAME
    $env:PLAYWRIGHT_CORE_PATH = $playwright
    $env:ROVER_CAMERA_NAME = $CameraName
    $camera = Start-Process -FilePath $nodeExe -ArgumentList @($cameraScript,'--live','--low-rate','--skip-layout') `
        -WorkingDirectory $workspace -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $runtime 'camera.log') -RedirectStandardError (Join-Path $runtime 'camera-error.log')
    $env:PLAYWRIGHT_CORE_PATH = $oldPlaywright
    $env:ROVER_CAMERA_NAME = $oldCameraName
    $started.Add((New-ProcessEntry 'USB camera publisher' $camera))

    $cameraDeadline = (Get-Date).AddSeconds(40)
    do {
        try {
            $sessions = Invoke-RestMethod 'http://127.0.0.1:9997/v3/webrtc/sessions/list' -TimeoutSec 2
            $publisher = $sessions.items | Where-Object {
                $_.path -eq 'rovercam' -and $_.state -eq 'publish' -and $_.peerConnectionEstablished
            }
        } catch {
            $publisher = $null
        }
        if (-not $publisher) { Start-Sleep -Milliseconds 500 }
    } while (-not $publisher -and (Get-Date) -lt $cameraDeadline)
    if (-not $publisher) { throw 'The USB camera publisher did not connect within 40 seconds.' }

    [pscustomobject]@{ started = (Get-Date).ToString('o'); laptopIp = $LaptopIp; phoneIp = $PhoneIp; cameraName = $CameraName; processes = $started } |
        ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $stateFile -Encoding UTF8
    Write-Host 'IRC Rover system started.'
    Write-Host 'Laptop dashboard  http://127.0.0.1:5173/'
    Write-Host "Phone dashboard   http://${LaptopIp}:5174/"
    Write-Host 'The visible Chrome window owns the webcam. Keep it open.'
    Write-Host "Camera             $CameraName"
} catch {
    Stop-SavedProcesses $started
    throw
}
