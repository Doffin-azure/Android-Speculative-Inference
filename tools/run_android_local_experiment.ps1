param(
    [string]$DeviceSerial = "",
    [string]$Prompt = "Explain speculative decoding briefly.",
    [string]$ModelName = "Llama-3.2-1B-Instruct-Q4_K_M.gguf"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$logsDir = Join-Path $repoRoot "logs"
$experimentsDir = Join-Path $repoRoot "reference\spec-split-demo-project\experiments"
$dateDir = Join-Path $experimentsDir (Get-Date -Format "yyyy-MM-dd")
$appId = "com.example.myapplication"
$serviceComponent = "$appId/.AndroidLocalExperimentService"
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

New-Item -ItemType Directory -Force -Path $logsDir | Out-Null
New-Item -ItemType Directory -Force -Path $dateDir | Out-Null

Require-Path $adbPath

$deviceList = Invoke-AdbCapture -CommandArgs @("devices", "-l")
if ($deviceList.ExitCode -ne 0) {
    throw "adb devices failed.`n$($deviceList.Output)"
}
if ($deviceList.Output -notmatch "device product") {
    throw "No online Android device found.`n$($deviceList.Output)"
}

$runStamp = New-TimestampTag
$startedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
$startedAtPath = Join-Path $logsDir "android_local_run_started_at_${runStamp}.txt"
$finishedAtPath = Join-Path $logsDir "android_local_run_finished_at_${runStamp}.txt"
Set-Content -Path $startedAtPath -Value $startedAt

$resultStatus = "unknown"
$failureReason = ""
$appOutputPath = Join-Path $logsDir "android_local_app_output_${runStamp}.txt"
$gradleLogPath = Join-Path $logsDir "android_local_gradle_${runStamp}.log"
$deviceLogcatPath = Join-Path $logsDir "android_local_logcat_${runStamp}.log"
$serviceOutputPath = Join-Path $logsDir "android_local_service_${runStamp}.log"
$modelPushLogPath = Join-Path $logsDir "android_local_model_push_${runStamp}.log"

$caughtError = $null

try {
    $env:JAVA_HOME = $javaHomeDefault
    $env:Path = "$env:JAVA_HOME\bin;$env:Path"

    & "$repoRoot\gradlew.bat" :app:installDebug 2>&1 | Tee-Object -FilePath $gradleLogPath
    if ($LASTEXITCODE -ne 0) {
        $resultStatus = "blocked_install"
        $failureReason = "gradle_install_failed"
        throw "Gradle installDebug failed."
    }

    $modelHostPath = Join-Path $repoRoot "models\$ModelName"
    Require-Path $modelHostPath
    $tmpModelPath = "/data/local/tmp/$ModelName"

    $pushResult = Invoke-AdbCapture -CommandArgs @("push", $modelHostPath, $tmpModelPath)
    Set-Content -Path $modelPushLogPath -Value $pushResult.Output
    if ($pushResult.ExitCode -ne 0) {
        $resultStatus = "blocked_device_state"
        $failureReason = "model_push_failed"
        throw "Failed to push model to device temp path."
    }

    $copyResult = Invoke-RunAsShCapture -Script "mkdir -p files/imported-models files/logs && rm -f files/logs/android-local-experiment-latest.txt && dd if=$tmpModelPath of=files/imported-models/$ModelName bs=4M"
    if ($copyResult.ExitCode -ne 0) {
        $resultStatus = "blocked_device_state"
        $failureReason = "model_copy_failed"
        throw "Failed to copy model into app-private storage.`n$($copyResult.Output)"
    }
    Write-Host "[android-local] model copied to app storage"

    $shellCheck = Invoke-RunAsExecCapture -CommandArgs @("stat", "files/imported-models/$ModelName")
    if ($shellCheck.ExitCode -ne 0 -or $shellCheck.Output -notmatch "Size:\s+807694464") {
        $resultStatus = "blocked_device_state"
        $failureReason = "model_missing_on_device"
        throw "Required model $ModelName is not present in app-private imported-models on device."
    }
    Write-Host "[android-local] model verified on device"

    Invoke-Adb @("logcat", "-c") | Out-Null

    $serviceShellCommand =
        "am start-foreground-service -n $serviceComponent --es prompt " +
        (New-ShellSingleQuoted $Prompt)
    $startResult = Invoke-AdbCapture -CommandArgs @("shell", $serviceShellCommand)
    if ($startResult.ExitCode -ne 0) {
        $resultStatus = "blocked_runtime"
        $failureReason = "service_start_failed"
        throw "Failed to start Android local experiment service.`n$($startResult.Output)"
    }
    Set-Content -Path $serviceOutputPath -Value $startResult.Output
    Write-Host "[android-local] foreground service start completed"

    $latestText = ""
    for ($i = 0; $i -lt 240; $i++) {
        if ($i -gt 0) {
            Start-Sleep -Seconds 2
        }
        $outputResult = Invoke-RunAsShCapture -Script "if [ -f files/logs/android-local-experiment-latest.txt ]; then cat files/logs/android-local-experiment-latest.txt; fi"
        $candidateText = $outputResult.Output.Trim()
        Write-Host "[android-local] output poll $($i + 1) exit=$($outputResult.ExitCode) chars=$($candidateText.Length)"
        if ($outputResult.ExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($candidateText)) {
            if ($candidateText -match "^ANDROID_LOCAL_EXPERIMENT(\r?\n|$)" -or $candidateText -match "^ANDROID_LOCAL_EXPERIMENT_FAILED(\r?\n|$)") {
                $latestText = $candidateText
                Set-Content -Path $appOutputPath -Value $latestText
                break
            }
        }
    }

    if ([string]::IsNullOrWhiteSpace($latestText)) {
        $resultStatus = "blocked_runtime"
        $failureReason = "no_device_output_captured"
        throw "No Android local experiment output was captured from app-private log."
    }
    Write-Host "[android-local] device output captured"

    if ($latestText -match "^ANDROID_LOCAL_EXPERIMENT_FAILED") {
        $resultStatus = "failed_runtime"
        $failureReason = "android_runner_reported_failure"
        throw "Android local experiment runner reported failure."
    }

    $logcatResult = Invoke-AdbCapture -CommandArgs @("logcat", "-d", "-s", "AndroidLocalExpService", "*:S")
    if ($logcatResult.ExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($logcatResult.Output)) {
        Set-Content -Path $deviceLogcatPath -Value $logcatResult.Output
    }

    $resultStatus = "completed"
    Write-Host "[android-local] experiment completed"
} catch {
    $caughtError = $_
    if ([string]::IsNullOrWhiteSpace($failureReason)) {
        $failureReason = "script_exception"
    }
} finally {
    $finishedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
    Set-Content -Path $finishedAtPath -Value $finishedAt

    $archivePaths = [ordered]@{
        startedAt = $startedAtPath
        finishedAt = $finishedAtPath
    }

    foreach ($path in @($gradleLogPath, $serviceOutputPath, $appOutputPath, $deviceLogcatPath, $modelPushLogPath)) {
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
        prompt = $Prompt
        modelName = $ModelName
        archivedFiles = $archivePaths
    }

    $summaryPath = Join-Path $dateDir "android_local_summary_${runStamp}.json"
    $summary | ConvertTo-Json -Depth 6 | Set-Content -Path $summaryPath -Encoding UTF8
    Write-Host "android local summary: $summaryPath"
}

if ($null -ne $caughtError) {
    throw $caughtError
}
