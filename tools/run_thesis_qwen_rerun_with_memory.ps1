param(
    [string]$DeviceSerial = "",
    [string]$Prompt = "Write a detailed, continuous technical explanation of speculative decoding for about 1000 tokens. Cover motivation, workflow, acceptance, rejection, system overhead, and deployment tradeoffs. Do not stop early.",
    [string]$DraftModelName = "Qwen2.5-0.5B-Instruct-Q4_K_M.gguf",
    [string]$TargetModelName = "Qwen2.5-7B-Instruct-Q4_K_M.gguf",
    [int]$MaxOutputTokens = 1000,
    [int]$CtxSize = 2048,
    [int]$NMax = 4,
    [int]$NMin = 1,
    [double]$PMin = 0.55,
    [int]$CloudThreads = 8,
    [int]$CrossDeviceVerifyThreads = 10,
    [int]$SampleIntervalSeconds = 2,
    [switch]$SkipAndroidLocal,
    [string]$ExistingAndroidLocalSummary = "",
    [string]$ExistingAndroidLocalMemoryCsv = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$dateDir = Join-Path $repoRoot ("reference\spec-split-demo-project\experiments\" + (Get-Date -Format "yyyy-MM-dd"))
$logsDir = Join-Path $repoRoot "logs"
$appId = "com.example.myapplication"
$adbPath = Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools\adb.exe"
$draftModelPath = Join-Path $repoRoot "models\$DraftModelName"
$targetModelPath = Join-Path $repoRoot "models\$TargetModelName"
$runStamp = (Get-Date -Format "yyyy-MM-ddTHH-mm-sszzz").Replace(":", "-")
$memoryDir = Join-Path $dateDir "memory-$runStamp"

New-Item -ItemType Directory -Force -Path $dateDir | Out-Null
New-Item -ItemType Directory -Force -Path $logsDir | Out-Null
New-Item -ItemType Directory -Force -Path $memoryDir | Out-Null

foreach ($path in @($adbPath, $draftModelPath, $targetModelPath)) {
    if (-not (Test-Path $path)) {
        throw "Required path not found: $path"
    }
}

function Get-MostRecentFile {
    param(
        [Parameter(Mandatory = $true)][string]$DirectoryPath,
        [Parameter(Mandatory = $true)][string]$Filter,
        [Parameter(Mandatory = $true)][datetime]$AfterTime
    )

    $file = Get-ChildItem -Path $DirectoryPath -Filter $Filter -File |
        Where-Object { $_.LastWriteTime -ge $AfterTime } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($null -eq $file) {
        throw "No file matched '$Filter' after $AfterTime in $DirectoryPath"
    }
    return $file
}

function Start-MemoryMonitor {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string]$OutCsv,
        [Parameter(Mandatory = $true)][string]$StopFile,
        [bool]$SampleAndroid,
        [bool]$SampleDesktop
    )

    return Start-Job -ArgumentList $Label, $OutCsv, $StopFile, $SampleAndroid, $SampleDesktop, $adbPath, $DeviceSerial, $appId, $SampleIntervalSeconds -ScriptBlock {
        param($Label, $OutCsv, $StopFile, $SampleAndroid, $SampleDesktop, $AdbPath, $DeviceSerial, $AppId, $SampleIntervalSeconds)

        function New-AdbArgs {
            param([string[]]$CommandArgs)
            if ([string]::IsNullOrWhiteSpace($DeviceSerial)) {
                return $CommandArgs
            }
            return @("-s", $DeviceSerial) + $CommandArgs
        }

        function Get-AndroidPssMb {
            if (-not $SampleAndroid) {
                return $null
            }
            try {
                $args = New-AdbArgs -CommandArgs @("shell", "dumpsys", "meminfo", $AppId)
                $text = & $AdbPath @args 2>$null
                foreach ($line in $text) {
                    if ($line -match "^\s*TOTAL\s+(?<pss>\d+)") {
                        return [math]::Round(([double]$matches.pss / 1024.0), 3)
                    }
                }
            } catch {
            }
            return $null
        }

        function Get-DesktopWorkingSetMb {
            if (-not $SampleDesktop) {
                return $null
            }
            try {
                $interesting = Get-CimInstance Win32_Process |
                    Where-Object {
                        $_.Name -in @("python.exe", "python3.exe", "wsl.exe", "wslservice.exe", "vmmemWSL", "VmmemWSL.exe", "vmmem.exe", "desktop_target_runtime.exe") -and
                        (
                            $_.CommandLine -match "desktop_inference_service|run_recorded_native_full_experiment|desktop_target_runtime|llama|speculative|wsl" -or
                            $_.Name -in @("vmmemWSL", "VmmemWSL.exe", "vmmem.exe", "wslservice.exe", "desktop_target_runtime.exe")
                        )
                    }
                $sum = 0.0
                foreach ($p in $interesting) {
                    if ($null -ne $p.WorkingSetSize) {
                        $sum += [double]$p.WorkingSetSize
                    }
                }
                if ($sum -gt 0) {
                    return [math]::Round($sum / 1MB, 3)
                }
            } catch {
            }
            return $null
        }

        "timestamp,label,androidPssMb,desktopWorkingSetMb" | Set-Content -Path $OutCsv -Encoding UTF8
        while (-not (Test-Path $StopFile)) {
            $android = Get-AndroidPssMb
            $desktop = Get-DesktopWorkingSetMb
            $timestamp = Get-Date -Format "o"
            "$timestamp,$Label,$android,$desktop" | Add-Content -Path $OutCsv -Encoding UTF8
            Start-Sleep -Seconds $SampleIntervalSeconds
        }
    }
}

function Invoke-WithMemoryMonitor {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][scriptblock]$Action,
        [bool]$SampleAndroid,
        [bool]$SampleDesktop
    )

    $csv = Join-Path $memoryDir "$Label-memory.csv"
    $stop = Join-Path $memoryDir "$Label.stop"
    Remove-Item -LiteralPath $stop -Force -ErrorAction SilentlyContinue
    $job = Start-MemoryMonitor -Label $Label -OutCsv $csv -StopFile $stop -SampleAndroid $SampleAndroid -SampleDesktop $SampleDesktop
    try {
        & $Action | Out-Host
    } finally {
        Set-Content -Path $stop -Value "stop"
        Wait-Job $job -Timeout 10 | Out-Null
        Receive-Job $job | Out-Null
        Remove-Job $job -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $stop -Force -ErrorAction SilentlyContinue
    }
    Write-Output $csv
}

function Get-MemoryStats {
    param([Parameter(Mandatory = $true)][string]$CsvPath)
    $rows = Import-Csv $CsvPath
    $android = @($rows | ForEach-Object { if ($_.androidPssMb -ne "") { [double]$_.androidPssMb } })
    $desktop = @($rows | ForEach-Object { if ($_.desktopWorkingSetMb -ne "") { [double]$_.desktopWorkingSetMb } })
    return [ordered]@{
        csv = $CsvPath
        samples = $rows.Count
        androidPeakPssMb = if ($android.Count -gt 0) { [math]::Round((($android | Measure-Object -Maximum).Maximum), 3) } else { $null }
        androidAveragePssMb = if ($android.Count -gt 0) { [math]::Round((($android | Measure-Object -Average).Average), 3) } else { $null }
        desktopPeakWorkingSetMb = if ($desktop.Count -gt 0) { [math]::Round((($desktop | Measure-Object -Maximum).Maximum), 3) } else { $null }
        desktopAverageWorkingSetMb = if ($desktop.Count -gt 0) { [math]::Round((($desktop | Measure-Object -Average).Average), 3) } else { $null }
    }
}

$result = [ordered]@{
    generatedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
    runStamp = $runStamp
    prompt = $Prompt
    config = [ordered]@{
        draftModelName = $DraftModelName
        targetModelName = $TargetModelName
        maxOutputTokens = $MaxOutputTokens
        ctxSize = $CtxSize
        nMax = $NMax
        nMin = $NMin
        pMin = $PMin
        cloudThreads = $CloudThreads
        crossDeviceVerifyThreads = $CrossDeviceVerifyThreads
    }
    outputs = [ordered]@{}
    memory = [ordered]@{}
}

if ($SkipAndroidLocal) {
    if ([string]::IsNullOrWhiteSpace($ExistingAndroidLocalSummary) -or -not (Test-Path $ExistingAndroidLocalSummary)) {
        throw "-SkipAndroidLocal requires -ExistingAndroidLocalSummary."
    }
    if ([string]::IsNullOrWhiteSpace($ExistingAndroidLocalMemoryCsv) -or -not (Test-Path $ExistingAndroidLocalMemoryCsv)) {
        throw "-SkipAndroidLocal requires -ExistingAndroidLocalMemoryCsv."
    }
    $result.outputs.androidLocalSummary = (Resolve-Path $ExistingAndroidLocalSummary).Path
    $result.memory.androidLocal = Get-MemoryStats -CsvPath (Resolve-Path $ExistingAndroidLocalMemoryCsv).Path
} else {
    $androidLocalStartedAt = Get-Date
    $result.memory.androidLocal = Get-MemoryStats -CsvPath (Invoke-WithMemoryMonitor -Label "android-local-7b" -SampleAndroid $true -SampleDesktop $false -Action {
        & (Join-Path $repoRoot "tools\run_android_local_experiment.ps1") `
            -DeviceSerial $DeviceSerial `
            -Prompt $Prompt `
            -ModelName $TargetModelName `
            -MaxGenerateTokens $MaxOutputTokens
        if ($LASTEXITCODE -ne 0) {
            throw "Android local experiment failed."
        }
    })
    $result.outputs.androidLocalSummary = (Get-MostRecentFile -DirectoryPath $dateDir -Filter "android_local_summary_*.json" -AfterTime $androidLocalStartedAt).FullName
}

$cloudStartedAt = Get-Date
$result.memory.cloudLocal = Get-MemoryStats -CsvPath (Invoke-WithMemoryMonitor -Label "cloud-local-spec" -SampleAndroid $false -SampleDesktop $true -Action {
    & (Join-Path $repoRoot "reference\spec-split-demo-project\run_recorded_native_full_experiment.ps1") `
        -Prompt $Prompt `
        -NMax $NMax `
        -NMin $NMin `
        -PMin $PMin `
        -MaxOutputTokens $MaxOutputTokens `
        -CtxSize $CtxSize `
        -Threads $CloudThreads `
        -DraftModel $draftModelPath `
        -VerifyModel $targetModelPath `
        -RunBaseline
    if ($LASTEXITCODE -ne 0) {
        throw "Cloud local native experiment failed."
    }
})
$result.outputs.cloudLocalSummary = (Get-MostRecentFile -DirectoryPath $dateDir -Filter "recorded_run_*.json" -AfterTime $cloudStartedAt).FullName

$crossStartedAt = Get-Date
$result.memory.crossDevice = Get-MemoryStats -CsvPath (Invoke-WithMemoryMonitor -Label "android-cloud-split" -SampleAndroid $true -SampleDesktop $true -Action {
    & (Join-Path $repoRoot "tools\run_android_spec_split_experiment.ps1") `
        -DeviceSerial $DeviceSerial `
        -Prompt $Prompt `
        -DraftModelName $DraftModelName `
        -TargetModelPath $targetModelPath `
        -MaxAcceptedTokens $MaxOutputTokens `
        -Threads $CrossDeviceVerifyThreads `
        -DraftMaxTokens $NMax `
        -InitialDraftTokens $NMax `
        -DraftMinTokens $NMin `
        -DraftMinProb $PMin `
        -AdaptiveDraftingEnabled:$false `
        -AdaptiveDraftMinTokens $NMax
    if ($LASTEXITCODE -ne 0) {
        throw "Android split experiment failed."
    }
})
$result.outputs.crossDeviceSummary = (Get-MostRecentFile -DirectoryPath $dateDir -Filter "android_spec_split_summary_*.json" -AfterTime $crossStartedAt).FullName

$summaryPath = Join-Path $dateDir "thesis_qwen_rerun_with_memory_${runStamp}.json"
$result | ConvertTo-Json -Depth 8 | Set-Content -Path $summaryPath -Encoding UTF8

Write-Host "thesis qwen rerun complete"
Write-Host "summary: $summaryPath"
