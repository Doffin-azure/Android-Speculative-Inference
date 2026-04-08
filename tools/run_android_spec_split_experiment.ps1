param(
    [string]$DeviceSerial = "",
    [string]$Prompt = "Explain speculative decoding briefly.",
    [string]$BaseUrl = "http://127.0.0.1:8080",
    [string]$DraftModelName = "Llama-3.2-1B-Instruct-Q4_K_M.gguf",
    [string]$TargetModelPath = "",
    [string]$VerifierMode = "llama_cpp_spec_split",
    [int]$Port = 8080
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$logsDir = Join-Path $repoRoot "logs"
$experimentsDir = Join-Path $repoRoot "reference\spec-split-demo-project\experiments"
$dateDir = Join-Path $experimentsDir (Get-Date -Format "yyyy-MM-dd")
$appId = "com.example.myapplication"
$serviceComponent = "$appId/.SpeculativeExperimentService"
$receiverComponent = "$appId/.SpeculativeExperimentReceiver"
$javaHomeDefault = "C:\Program Files\Android\Android Studio\jbr"
$adbPath = Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools\adb.exe"

function New-TimestampTag {
    return (Get-Date -Format "yyyy-MM-ddTHH-mm-sszzz").Replace(":", "-")
}

function New-ShellSingleQuoted {
    param([string]$Value)
    return "'" + $Value.Replace("'", "'\''") + "'"
}

function New-AdbArgs {
    param([string[]]$CommandArgs)
    if ([string]::IsNullOrWhiteSpace($DeviceSerial)) {
        return $CommandArgs
    }
    return @("-s", $DeviceSerial) + $CommandArgs
}

function Invoke-AdbCapture {
    param([string[]]$CommandArgs)
    $args = New-AdbArgs -CommandArgs $CommandArgs
    $stdoutPath = [System.IO.Path]::GetTempFileName()
    $stderrPath = [System.IO.Path]::GetTempFileName()
    try {
        $proc = Start-Process -FilePath $adbPath `
            -ArgumentList $args `
            -NoNewWindow `
            -Wait `
            -PassThru `
            -RedirectStandardOutput $stdoutPath `
            -RedirectStandardError $stderrPath
        $stdout = if (Test-Path $stdoutPath) { Get-Content -Path $stdoutPath -Raw } else { "" }
        $stderr = if (Test-Path $stderrPath) { Get-Content -Path $stderrPath -Raw } else { "" }
        $output = @($stdout, $stderr) | Where-Object { -not [string]::IsNullOrEmpty($_) }
        $exitCode = $proc.ExitCode
    } finally {
        Remove-Item -LiteralPath $stdoutPath -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $stderrPath -ErrorAction SilentlyContinue
    }
    return [pscustomobject]@{
        Output = ($output -join [Environment]::NewLine)
        ExitCode = $exitCode
    }
}

function Invoke-Adb {
    param([string[]]$CommandArgs)
    $result = Invoke-AdbCapture -CommandArgs $CommandArgs
    if ($result.ExitCode -ne 0) {
        throw "adb command failed: $($CommandArgs -join ' ')`n$result"
    }
    return $result.Output
}

function Invoke-RunAsShCapture {
    param([string]$Script)
    $shellCommand = "run-as $appId sh -c " + (New-ShellSingleQuoted $Script)
    return Invoke-AdbCapture -CommandArgs @("shell", $shellCommand)
}

function Invoke-RunAsExecCapture {
    param([string[]]$CommandArgs)
    return Invoke-AdbCapture -CommandArgs (@("exec-out", "run-as", $appId) + $CommandArgs)
}

function Require-Path {
    param([string]$PathValue)
    if (-not (Test-Path $PathValue)) {
        throw "Required path not found: $PathValue"
    }
}

function Start-DesktopService {
    param(
        [string]$ModelPath,
        [string]$RunStamp
    )

    $stdoutPath = Join-Path $logsDir "android_spec_split_service_${RunStamp}.out.log"
    $stderrPath = Join-Path $logsDir "android_spec_split_service_${RunStamp}.err.log"
    $proc = Start-Process -FilePath python `
        -ArgumentList @(
            "tools\desktop_inference_service.py",
            "--host", "127.0.0.1",
            "--port", "$Port",
            "--model-path", $ModelPath,
            "--speculative-verifier-mode", $VerifierMode
        ) `
        -WorkingDirectory $repoRoot `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath `
        -PassThru

    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 1
        try {
            $health = Invoke-RestMethod "http://127.0.0.1:$Port/health"
            return [pscustomobject]@{
                Process = $proc
                Stdout = $stdoutPath
                Stderr = $stderrPath
                Health = $health
            }
        } catch {
        }
    }

    throw "Desktop inference service did not become healthy on port $Port."
}

function Stop-DesktopService {
    param($ServiceInfo)
    if ($null -ne $ServiceInfo -and $null -ne $ServiceInfo.Process) {
        if (-not $ServiceInfo.Process.HasExited) {
            Stop-Process -Id $ServiceInfo.Process.Id -Force
        }
    }
}

New-Item -ItemType Directory -Force -Path $logsDir | Out-Null
New-Item -ItemType Directory -Force -Path $dateDir | Out-Null

Require-Path $adbPath

if ([string]::IsNullOrWhiteSpace($TargetModelPath)) {
    $TargetModelPath = Join-Path $repoRoot "models\Llama-3.2-3B-Instruct-Q4_K_M.gguf"
}
Require-Path $TargetModelPath

$deviceList = Invoke-AdbCapture -CommandArgs @("devices", "-l")
if ($deviceList.ExitCode -ne 0) {
    throw "adb devices failed.`n$($deviceList.Output)"
}
if ($deviceList.Output -notmatch "device product") {
    throw "No online Android device found.`n$($deviceList.Output)"
}

$runStamp = New-TimestampTag
$startedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
$startedAtPath = Join-Path $logsDir "android_spec_split_run_started_at_${runStamp}.txt"
$finishedAtPath = Join-Path $logsDir "android_spec_split_run_finished_at_${runStamp}.txt"
Set-Content -Path $startedAtPath -Value $startedAt

$serviceInfo = $null
$resultStatus = "unknown"
$failureReason = ""
$appOutputPath = Join-Path $logsDir "android_spec_split_app_output_${runStamp}.txt"
$gradleLogPath = Join-Path $logsDir "android_spec_split_gradle_${runStamp}.log"
$deviceLogcatPath = Join-Path $logsDir "android_spec_split_logcat_${runStamp}.log"
$broadcastOutputPath = Join-Path $logsDir "android_spec_split_broadcast_${runStamp}.log"

$caughtError = $null

try {
    $serviceInfo = Start-DesktopService -ModelPath $TargetModelPath -RunStamp $runStamp
    Write-Host "[android-spec] desktop service ready"
    $probe = Invoke-RestMethod "http://127.0.0.1:$Port/probe"
    if ($probe.speculativeVerifierMode -ne $VerifierMode) {
        throw "Expected verifier mode $VerifierMode, got $($probe.speculativeVerifierMode)"
    }

    Invoke-Adb @("reverse", "tcp:$Port", "tcp:$Port") | Out-Null

    $env:JAVA_HOME = $javaHomeDefault
    $env:Path = "$env:JAVA_HOME\bin;$env:Path"

    & "$repoRoot\gradlew.bat" :app:installDebug 2>&1 | Tee-Object -FilePath $gradleLogPath
    if ($LASTEXITCODE -ne 0) {
        $resultStatus = "blocked_install"
        $failureReason = "gradle_install_failed"
        throw "Gradle installDebug failed."
    }

    $draftModelHostPath = Join-Path $repoRoot "models\$DraftModelName"
    Require-Path $draftModelHostPath

    $tmpModelPath = "/data/local/tmp/$DraftModelName"
    $modelPushLogPath = Join-Path $logsDir "android_spec_split_model_push_${runStamp}.log"
    $pushResult = Invoke-AdbCapture -CommandArgs @("push", $draftModelHostPath, $tmpModelPath)
    Set-Content -Path $modelPushLogPath -Value $pushResult.Output
    if ($pushResult.ExitCode -ne 0) {
        $resultStatus = "blocked_device_state"
        $failureReason = "draft_model_push_failed"
        throw "Failed to push draft model to device temp path."
    }

    $copyResult = Invoke-RunAsShCapture -Script "mkdir -p files/imported-models files/logs && rm -f files/logs/speculative-experiment-latest.txt && dd if=$tmpModelPath of=files/imported-models/$DraftModelName bs=4M"
    if ($copyResult.ExitCode -ne 0) {
        $resultStatus = "blocked_device_state"
        $failureReason = "draft_model_copy_failed"
        throw "Failed to copy draft model into app-private storage.`n$($copyResult.Output)"
    }
    Write-Host "[android-spec] draft model copied to app storage"

    $shellCheck = Invoke-RunAsExecCapture -CommandArgs @("stat", "files/imported-models/$DraftModelName")
    if ($shellCheck.ExitCode -ne 0 -or $shellCheck.Output -notmatch "Size:\s+807694464") {
        $resultStatus = "blocked_device_state"
        $failureReason = "draft_model_missing_on_device"
        throw "Required draft model $DraftModelName is not present in app-private imported-models on device."
    }
    Write-Host "[android-spec] draft model verified on device"

    Invoke-Adb @("logcat", "-c") | Out-Null

    $receiverArgs = @("shell", "am", "broadcast", "-n", $receiverComponent, "--es", "baseUrl", $BaseUrl)
    $startResult = Invoke-AdbCapture -CommandArgs $receiverArgs
    if ($startResult.ExitCode -ne 0) {
        $resultStatus = "blocked_runtime"
        $failureReason = "receiver_start_failed"
        throw "Failed to trigger Android speculative experiment receiver.`n$($startResult.Output)"
    }
    Set-Content -Path $broadcastOutputPath -Value $startResult.Output
    Write-Host "[android-spec] receiver broadcast completed"

    $latestText = ""
    for ($i = 0; $i -lt 90; $i++) {
        if ($i -gt 0) {
            Start-Sleep -Seconds 2
        }
        $outputResult = Invoke-RunAsShCapture -Script "if [ -f files/logs/speculative-experiment-latest.txt ]; then cat files/logs/speculative-experiment-latest.txt; fi"
        $candidateText = $outputResult.Output.Trim()
        Write-Host "[android-spec] output poll $($i + 1) exit=$($outputResult.ExitCode) chars=$($candidateText.Length)"
        if ($outputResult.ExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($candidateText)) {
            if ($candidateText -match "^ANDROID_SPEC_EXPERIMENT(\r?\n|$)" -or $candidateText -match "^ANDROID_SPEC_EXPERIMENT_FAILED(\r?\n|$)") {
                $latestText = $candidateText
                Set-Content -Path $appOutputPath -Value $latestText
                break
            }
        }
    }

    if ([string]::IsNullOrWhiteSpace($latestText)) {
        $resultStatus = "blocked_runtime"
        $failureReason = "no_device_output_captured"
        throw "No Android experiment output was captured from app-private log."
    }
    Write-Host "[android-spec] device output captured"

    if ($latestText -match "^ANDROID_SPEC_EXPERIMENT_FAILED") {
        $resultStatus = "failed_runtime"
        $failureReason = "android_runner_reported_failure"
        throw "Android experiment runner reported failure."
    }

    $logcatResult = Invoke-AdbCapture -CommandArgs @("logcat", "-d", "-s", "SpecExpReceiver", "SpecExpService", "*:S")
    if ($logcatResult.ExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($logcatResult.Output)) {
        Set-Content -Path $deviceLogcatPath -Value $logcatResult.Output
    }

    $resultStatus = "completed"
    Write-Host "[android-spec] experiment completed"
} catch {
    $caughtError = $_
    if ([string]::IsNullOrWhiteSpace($failureReason)) {
        $failureReason = "script_exception"
    }
} finally {
    $finishedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
    Set-Content -Path $finishedAtPath -Value $finishedAt
    Stop-DesktopService -ServiceInfo $serviceInfo

    $archivePaths = [ordered]@{
        startedAt = $startedAtPath
        finishedAt = $finishedAtPath
    }

    foreach ($path in @($gradleLogPath, $broadcastOutputPath, $appOutputPath, $deviceLogcatPath, $modelPushLogPath, $serviceInfo.Stdout, $serviceInfo.Stderr)) {
        if ($path -and (Test-Path $path)) {
            $dest = Join-Path $dateDir ([System.IO.Path]::GetFileName($path))
            Copy-Item $path $dest -Force
            $archivePaths[[System.IO.Path]::GetFileNameWithoutExtension($path)] = $dest
        }
    }

    $summary = [ordered]@{
        generatedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
        startedAt = $startedAt
        finishedAt = $finishedAt
        status = $resultStatus
        failureReason = $failureReason
        exception = if ($null -ne $caughtError) { $caughtError.ToString() } else { "" }
        deviceSerial = if ([string]::IsNullOrWhiteSpace($DeviceSerial)) { "" } else { $DeviceSerial }
        packageName = $appId
        serviceComponent = $serviceComponent
        receiverComponent = $receiverComponent
        baseUrl = $BaseUrl
        verifierMode = $VerifierMode
        prompt = $Prompt
        draftModelName = $DraftModelName
        targetModelPath = $TargetModelPath
        archivedFiles = $archivePaths
    }

    $summaryPath = Join-Path $dateDir "android_spec_split_summary_${runStamp}.json"
    $summary | ConvertTo-Json -Depth 6 | Set-Content -Path $summaryPath -Encoding UTF8

    Write-Host "android spec split summary: $summaryPath"
    if ($resultStatus -ne "completed") {
        if ($null -ne $caughtError) {
            throw $caughtError
        }
        throw "Android spec split experiment did not complete. status=$resultStatus reason=$failureReason"
    }
}
