param(
    [string]$PairName,
    [string]$Prompt = "Explain speculative decoding briefly.",
    [string]$DraftModelPath,
    [string]$TargetModelPath,
    [string]$DeviceSerial = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$experimentsRoot = Join-Path $repoRoot "reference\spec-split-demo-project\experiments"
$dateDir = Join-Path $experimentsRoot (Get-Date -Format "yyyy-MM-dd")

function Get-MostRecentFile {
    param(
        [string]$DirectoryPath,
        [string]$Filter,
        [datetime]$AfterTime
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

function Parse-BaselineLog {
    param([string]$LogPath)
    $result = [ordered]@{
        decodedTokens = $null
        decodedSeconds = $null
        decodedTokensPerSecond = $null
        nDrafted = $null
        nAccept = $null
        acceptRatio = $null
        rounds = $null
    }
    foreach ($line in Get-Content -Path $LogPath) {
        if ($line -match "decoded\s+(?<tokens>\d+)\s+tokens\s+in\s+(?<seconds>[0-9.]+)\s+seconds,\s+speed:\s+(?<speed>[0-9.]+)\s+t/s") {
            $result.decodedTokens = [int]$matches.tokens
            $result.decodedSeconds = [double]$matches.seconds
            $result.decodedTokensPerSecond = [double]$matches.speed
        }
        if ($line -match "^n_drafted\s+=\s+(?<value>\d+)") {
            $result.nDrafted = [int]$matches.value
        }
        if ($line -match "^n_accept\s+=\s+(?<value>\d+)") {
            $result.nAccept = [int]$matches.value
        }
        if ($line -match "^accept\s+=\s+(?<value>[0-9.]+)%") {
            $result.acceptRatio = [double]$matches.value
        }
        if ($line -match "^rounds\s+=\s+(?<value>\d+)") {
            $result.rounds = [int]$matches.value
        }
    }
    return $result
}

function Parse-NativeSummary {
    param([string]$SummaryPath)
    $summary = Get-Content -Path $SummaryPath -Raw | ConvertFrom-Json
    $start = Get-Date $summary.nativeFull.start
    $end = Get-Date $summary.nativeFull.end
    $elapsed = ($end - $start).TotalSeconds
    return [ordered]@{
        nativeFull = [ordered]@{
            start = $summary.nativeFull.start
            end = $summary.nativeFull.end
            wallSeconds = [math]::Round($elapsed, 3)
            acceptedPos = [int]$summary.nativeFull.acceptedPos
            acceptedTokensPerSecond = if ($elapsed -gt 0) { [math]::Round([int]$summary.nativeFull.acceptedPos / $elapsed, 3) } else { $null }
            finalRound = [int]$summary.nativeFull.finalRound
            nMax = [int]$summary.nativeFull.nMax
            verifyLog = $summary.nativeFull.verifyLog
            draftLog = $summary.nativeFull.draftLog
        }
    }
}

function Parse-AndroidSplitSummary {
    param([string]$SummaryPath)
    $summary = Get-Content -Path $SummaryPath -Raw | ConvertFrom-Json
    $appOutputPath = $summary.archivedFiles.PSObject.Properties |
        Where-Object { $_.Name -like "android_spec_split_app_output_*" } |
        Select-Object -ExpandProperty Value -First 1
    $metrics = [ordered]@{}
    foreach ($line in Get-Content -Path $appOutputPath) {
        if ($line -match '^(?<key>[A-Za-z0-9]+)=(?<value>.*)$') {
            $metrics[$matches.key] = $matches.value
        }
    }
    return [ordered]@{
        summaryPath = $SummaryPath
        outputPath = $appOutputPath
        committedTokens = [int]$metrics.committedTokens
        totalProposedTokens = [int]$metrics.totalProposedTokens
        totalMs = [int]$metrics.totalMs
        totalDraftFetchMs = [int]$metrics.totalDraftFetchMs
        totalRemoteProposeMs = [int]$metrics.totalRemoteProposeMs
        overallTokensPerSecond = [double]$metrics.overallTokensPerSecond
        draftTokensPerSecond = [double]$metrics.draftTokensPerSecond
    }
}

function Parse-DesktopDirectSummary {
    param([string]$SummaryPath)
    $summary = Get-Content -Path $SummaryPath -Raw | ConvertFrom-Json
    return $summary
}

function Parse-BaselineSummary {
    param([string]$SummaryPath)
    return Get-Content -Path $SummaryPath -Raw | ConvertFrom-Json
}

if ([string]::IsNullOrWhiteSpace($PairName)) {
    $PairName = [System.IO.Path]::GetFileNameWithoutExtension($DraftModelPath) + "__" + [System.IO.Path]::GetFileNameWithoutExtension($TargetModelPath)
}
if (-not (Test-Path $DraftModelPath)) { throw "Draft model not found: $DraftModelPath" }
if (-not (Test-Path $TargetModelPath)) { throw "Target model not found: $TargetModelPath" }

New-Item -ItemType Directory -Force -Path $dateDir | Out-Null

$startedAt = Get-Date

$directStartedAt = Get-Date
python (Join-Path $repoRoot "tools\run_desktop_direct_experiment.py") --prompt $Prompt --model-path $TargetModelPath
if ($LASTEXITCODE -ne 0) { throw "Desktop direct experiment failed." }
$directSummary = Get-MostRecentFile -DirectoryPath $dateDir -Filter "desktop_direct_summary_*.json" -AfterTime $directStartedAt
$directMetrics = Parse-DesktopDirectSummary -SummaryPath $directSummary.FullName

$nativeStartedAt = Get-Date
& (Join-Path $repoRoot "reference\spec-split-demo-project\run_recorded_native_full_experiment.ps1") `
    -Prompt $Prompt `
    -DraftModel $DraftModelPath `
    -VerifyModel $TargetModelPath
if ($LASTEXITCODE -ne 0) { throw "Native full experiment failed." }
$nativeSummary = Get-MostRecentFile -DirectoryPath $dateDir -Filter "recorded_run_*.json" -AfterTime $nativeStartedAt
$nativeMetrics = Parse-NativeSummary -SummaryPath $nativeSummary.FullName

$baselineStartedAt = Get-Date
& (Join-Path $repoRoot "tools\run_pc_speculative_simple_experiment.ps1") `
    -Prompt $Prompt `
    -DraftModelPath $DraftModelPath `
    -TargetModelPath $TargetModelPath
if ($LASTEXITCODE -ne 0) { throw "PC speculative simple wrapper failed." }
$baselineSummary = Get-MostRecentFile -DirectoryPath $dateDir -Filter "pc_speculative_simple_summary_*.json" -AfterTime $baselineStartedAt
$baselineMetrics = Parse-BaselineSummary -SummaryPath $baselineSummary.FullName

$androidStartedAt = Get-Date
& (Join-Path $repoRoot "tools\run_android_spec_split_experiment.ps1") `
    -DeviceSerial $DeviceSerial `
    -Prompt $Prompt `
    -DraftModelName ([System.IO.Path]::GetFileName($DraftModelPath)) `
    -TargetModelPath $TargetModelPath
if ($LASTEXITCODE -ne 0) { throw "Android split experiment failed." }
$androidSummary = Get-MostRecentFile -DirectoryPath $dateDir -Filter "android_spec_split_summary_*.json" -AfterTime $androidStartedAt
$androidMetrics = Parse-AndroidSplitSummary -SummaryPath $androidSummary.FullName

$desktopDirectTps = $directMetrics.metrics.generationTokensPerSecond
if ($null -eq $desktopDirectTps) {
    $desktopDirectTps = $directMetrics.metrics.wallTokensPerSecond
}

$matrix = [ordered]@{
    generatedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
    pairName = $PairName
    prompt = $Prompt
    draftModelPath = $DraftModelPath
    targetModelPath = $TargetModelPath
    experiments = [ordered]@{
        desktopDirect = $directMetrics
        pcSpeculativeSimple = $baselineMetrics
        pcDualProcessSplit = $nativeMetrics.nativeFull
        androidPcSplit = $androidMetrics
    }
    analysis = [ordered]@{
        androidSplitFasterThanDesktopDirect = (
            $null -ne $desktopDirectTps -and
            $androidMetrics.overallTokensPerSecond -gt [double]$desktopDirectTps
        )
        androidSplitMinusDesktopDirectTps = if ($null -ne $desktopDirectTps) {
            [math]::Round($androidMetrics.overallTokensPerSecond - [double]$desktopDirectTps, 3)
        } else {
            $null
        }
        androidSplitVsDesktopDirectRatio = if ($null -ne $desktopDirectTps -and [double]$desktopDirectTps -gt 0) {
            [math]::Round($androidMetrics.overallTokensPerSecond / [double]$desktopDirectTps, 4)
        } else {
            $null
        }
        androidSplitVsBaselineSpecRatio = if ($baselineMetrics.status -eq "completed" -and $null -ne $baselineMetrics.metrics.decodedTokensPerSecond -and [double]$baselineMetrics.metrics.decodedTokensPerSecond -gt 0) {
            [math]::Round($androidMetrics.overallTokensPerSecond / [double]$baselineMetrics.metrics.decodedTokensPerSecond, 4)
        } else {
            $null
        }
    }
}

$stamp = (Get-Date -Format "yyyy-MM-ddTHH-mm-sszzz").Replace(":", "-")
$safePairName = $PairName -replace '[^A-Za-z0-9._-]', '_'
$matrixPath = Join-Path $dateDir "model_pair_matrix_${safePairName}_${stamp}.json"
$matrix | ConvertTo-Json -Depth 8 | Set-Content -Path $matrixPath -Encoding UTF8

Write-Host "model pair matrix complete"
Write-Host "pair: $PairName"
Write-Host "summary: $matrixPath"
