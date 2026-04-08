param(
    [string]$Prompt = "Explain speculative decoding briefly.",
    [int]$NMax = 16,
    [int]$MaxOutputTokens = 65,
    [int]$CtxSize = 512,
    [switch]$RunBaseline
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$referenceRoot = Join-Path $repoRoot "reference\spec-split-demo-project"
$todayDate = Get-Date -Format "yyyy-MM-dd"
$experimentsDir = Join-Path $referenceRoot "experiments\$todayDate"

function Get-LatestFile {
    param(
        [string]$DirectoryPath,
        [string]$Filter
    )

    $file = Get-ChildItem -Path $DirectoryPath -Filter $Filter -File |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($null -eq $file) {
        throw "No file matched '$Filter' in $DirectoryPath"
    }
    return $file
}

function Get-NativeMetrics {
    param([string]$SummaryPath)

    $summary = Get-Content -Path $SummaryPath -Raw | ConvertFrom-Json
    $state = Get-Content -Path $summary.nativeFull.stateFile -Raw | ConvertFrom-Json
    $decision = Get-Content -Path $summary.nativeFull.decisionFile -Raw | ConvertFrom-Json
    return [ordered]@{
        summaryPath = $SummaryPath
        mode = $summary.nativeFull.mode
        start = $summary.nativeFull.start
        end = $summary.nativeFull.end
        prompt = $summary.nativeFull.prompt
        draftModel = $summary.nativeFull.draftModel
        verifyModel = $summary.nativeFull.verifyModel
        nMax = $summary.nativeFull.nMax
        maxOutputTokens = $summary.nativeFull.maxOutputTokens
        ctxSize = $summary.nativeFull.ctxSize
        finalRound = $state.round
        acceptedPos = $state.accepted_pos
        done = $state.done
        finalAcceptedDraft = $decision.accepted_draft
        verifyLog = $summary.nativeFull.verifyLog
        draftLog = $summary.nativeFull.draftLog
        stateFile = $summary.nativeFull.stateFile
        decisionFile = $summary.nativeFull.decisionFile
        baseline = $summary.baseline
    }
}

function Get-AndroidMetrics {
    param([string]$SummaryPath)

    $summary = Get-Content -Path $SummaryPath -Raw | ConvertFrom-Json
    $appOutputPath = $summary.archivedFiles.PSObject.Properties |
        Where-Object { $_.Name -like "android_spec_split_app_output_*" } |
        Select-Object -ExpandProperty Value -First 1
    if ([string]::IsNullOrWhiteSpace($appOutputPath)) {
        throw "Android app output path missing from summary: $SummaryPath"
    }

    $metrics = [ordered]@{}
    foreach ($line in Get-Content -Path $appOutputPath) {
        if ($line -match '^(?<key>[A-Za-z0-9]+)=(?<value>.*)$') {
            $metrics[$matches.key] = $matches.value
        }
    }

    return [ordered]@{
        summaryPath = $SummaryPath
        status = $summary.status
        start = $summary.startedAt
        end = $summary.finishedAt
        prompt = $summary.prompt
        verifierMode = $summary.verifierMode
        draftModel = $summary.draftModelName
        verifyModel = $summary.targetModelPath
        appOutputPath = $appOutputPath
        steps = [int]($metrics.steps)
        committedTokens = [int]($metrics.committedTokens)
        totalAcceptedTokens = [int]($metrics.totalAcceptedTokens)
        totalProposedTokens = [int]($metrics.totalProposedTokens)
        totalMs = [int]($metrics.totalMs)
        totalDraftFetchMs = [int]($metrics.totalDraftFetchMs)
        totalRemoteProposeMs = [int]($metrics.totalRemoteProposeMs)
        overallTokensPerSecond = [double]($metrics.overallTokensPerSecond)
        draftTokensPerSecond = [double]($metrics.draftTokensPerSecond)
        closeStatus = $metrics.closeStatus
        closeReason = $metrics.closeReason
    }
}

New-Item -ItemType Directory -Force -Path $experimentsDir | Out-Null

& (Join-Path $referenceRoot "run_recorded_native_full_experiment.ps1") `
    -Prompt $Prompt `
    -NMax $NMax `
    -MaxOutputTokens $MaxOutputTokens `
    -CtxSize $CtxSize `
    -RunBaseline:$RunBaseline
if ($LASTEXITCODE -ne 0) {
    throw "Reference native full experiment failed."
}

$nativeSummary = Get-LatestFile -DirectoryPath $experimentsDir -Filter "recorded_run_*.json"
$nativeMetrics = Get-NativeMetrics -SummaryPath $nativeSummary.FullName

& (Join-Path $repoRoot "tools\run_android_spec_split_experiment.ps1") -Prompt $Prompt
if ($LASTEXITCODE -ne 0) {
    throw "Android split experiment failed."
}

$androidSummary = Get-LatestFile -DirectoryPath $experimentsDir -Filter "android_spec_split_summary_*.json"
$androidMetrics = Get-AndroidMetrics -SummaryPath $androidSummary.FullName

$comparison = [ordered]@{
    generatedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
    prompt = $Prompt
    referenceNativeFull = $nativeMetrics
    androidSplit = $androidMetrics
    comparison = [ordered]@{
        acceptedPosVsCommittedTokens = $nativeMetrics.acceptedPos - $androidMetrics.committedTokens
        nativeFinalRoundVsAndroidSteps = $nativeMetrics.finalRound - $androidMetrics.steps
        androidOverallTpsDeltaVsNativeAcceptedPosPerSecond = if ($androidMetrics.totalMs -gt 0) {
            $androidMetrics.overallTokensPerSecond - ($nativeMetrics.acceptedPos / (((Get-Date $nativeMetrics.end) - (Get-Date $nativeMetrics.start)).TotalSeconds))
        } else {
            0.0
        }
        androidDraftShare = if ($androidMetrics.totalMs -gt 0) {
            [math]::Round($androidMetrics.totalDraftFetchMs / $androidMetrics.totalMs, 4)
        } else {
            0.0
        }
        androidRemoteShare = if ($androidMetrics.totalMs -gt 0) {
            [math]::Round($androidMetrics.totalRemoteProposeMs / $androidMetrics.totalMs, 4)
        } else {
            0.0
        }
        androidAcceptedPerProposed = if ($androidMetrics.totalProposedTokens -gt 0) {
            [math]::Round($androidMetrics.totalAcceptedTokens / $androidMetrics.totalProposedTokens, 4)
        } else {
            0.0
        }
    }
}

$stamp = (Get-Date -Format "yyyy-MM-ddTHH-mm-sszzz").Replace(":", "-")
$comparisonPath = Join-Path $experimentsDir "split_parity_comparison_${stamp}.json"
$comparison | ConvertTo-Json -Depth 8 | Set-Content -Path $comparisonPath -Encoding UTF8

Write-Host "split parity experiment complete"
Write-Host "reference summary: $($nativeSummary.FullName)"
Write-Host "android summary: $($androidSummary.FullName)"
Write-Host "comparison: $comparisonPath"
