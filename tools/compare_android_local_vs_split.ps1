param(
    [Parameter(Mandatory = $true)]
    [string]$LocalOutputPath,

    [Parameter(Mandatory = $true)]
    [string]$SplitOutputPath
)

$ErrorActionPreference = "Stop"

function Parse-KeyValueText {
    param([string]$Text)
    $result = [ordered]@{}
    $acceptedDraftTokens = 0
    foreach ($line in ($Text -split "`r?`n")) {
        if ($line -match "^[A-Z0-9_]+$") {
            $result["_header"] = $line.Trim()
            continue
        }
        if ($line -match "^step=.*\saccepted=(\d+)") {
            $acceptedDraftTokens += [int]$Matches[1]
        }
        $idx = $line.IndexOf("=")
        if ($idx -lt 1) {
            continue
        }
        $key = $line.Substring(0, $idx).Trim()
        $value = $line.Substring($idx + 1).Trim()
        if (-not $result.Contains($key)) {
            $result[$key] = $value
        }
    }
    $result["_acceptedDraftTokensFromTraces"] = $acceptedDraftTokens
    return $result
}

function To-DoubleOrNull {
    param($Value)
    $parsed = 0.0
    if ([double]::TryParse([string]$Value, [ref]$parsed)) {
        return $parsed
    }
    return $null
}

function To-IntOrNull {
    param($Value)
    $parsed = 0
    if ([int]::TryParse([string]$Value, [ref]$parsed)) {
        return $parsed
    }
    return $null
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$experimentsDir = Join-Path $repoRoot "reference\spec-split-demo-project\experiments"
$dateDir = Join-Path $experimentsDir (Get-Date -Format "yyyy-MM-dd")
New-Item -ItemType Directory -Force -Path $dateDir | Out-Null

$localMetrics = Parse-KeyValueText -Text (Get-Content $LocalOutputPath -Raw)
$splitMetrics = Parse-KeyValueText -Text (Get-Content $SplitOutputPath -Raw)

$comparison = [ordered]@{
    generatedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
    localOutputPath = (Resolve-Path $LocalOutputPath).Path
    splitOutputPath = (Resolve-Path $SplitOutputPath).Path
    promptMatch = ($localMetrics.prompt -eq $splitMetrics.prompt)
    modelAlignment = [ordered]@{
        localModel = $localMetrics.model
        splitDraftModel = $splitMetrics.draftModel
        splitTargetModel = $splitMetrics.targetModel
    }
    local = [ordered]@{
        loadMs = To-IntOrNull $localMetrics.loadMs
        generateMs = To-IntOrNull $localMetrics.generateMs
        totalMs = To-IntOrNull $localMetrics.totalMs
        outputCodePoints = To-IntOrNull $localMetrics.outputCodePoints
        outputWordsApprox = To-IntOrNull $localMetrics.outputWordsApprox
        outputCodePointsPerSecond = To-DoubleOrNull $localMetrics.outputCodePointsPerSecond
        draftLoopProducedTokens = To-IntOrNull $localMetrics.draftLoopProducedTokens
        draftLoopMs = To-IntOrNull $localMetrics.draftLoopMs
        draftLoopTokensPerSecond = To-DoubleOrNull $localMetrics.draftLoopTokensPerSecond
    }
    split = [ordered]@{
        committedTokens = To-IntOrNull $splitMetrics.committedTokens
        totalProposedTokens = To-IntOrNull $splitMetrics.totalProposedTokens
        acceptedDraftTokensFromTraces = To-IntOrNull $splitMetrics._acceptedDraftTokensFromTraces
        totalMs = To-IntOrNull $splitMetrics.totalMs
        totalDraftFetchMs = To-IntOrNull $splitMetrics.totalDraftFetchMs
        totalRemoteProposeMs = To-IntOrNull $splitMetrics.totalRemoteProposeMs
        overallTokensPerSecond = To-DoubleOrNull $splitMetrics.overallTokensPerSecond
        draftTokensPerSecond = To-DoubleOrNull $splitMetrics.draftTokensPerSecond
    }
}

$localDraftLoopMs = $comparison.local.draftLoopMs
$splitTotalMs = $comparison.split.totalMs
$splitCommittedTokens = $comparison.split.committedTokens
$splitDraftFetchMs = $comparison.split.totalDraftFetchMs
$splitRemoteMs = $comparison.split.totalRemoteProposeMs
$localDraftLoopTps = $comparison.local.draftLoopTokensPerSecond
$splitOverallTps = $comparison.split.overallTokensPerSecond
$splitDraftTps = $comparison.split.draftTokensPerSecond
$splitAcceptedDraftTokens = $comparison.split.acceptedDraftTokensFromTraces

$comparison["derived"] = [ordered]@{
    splitAcceptedProposedRatio = if ($comparison.split.totalProposedTokens -and $null -ne $splitAcceptedDraftTokens) {
        [math]::Round($splitAcceptedDraftTokens / $comparison.split.totalProposedTokens, 4)
    } else { $null }
    splitVsLocalDraftLoopMsDelta = if ($null -ne $localDraftLoopMs -and $null -ne $splitTotalMs) {
        $splitTotalMs - $localDraftLoopMs
    } else { $null }
    splitRemoteShare = if ($null -ne $splitRemoteMs -and $null -ne $splitTotalMs -and $splitTotalMs -gt 0) {
        [math]::Round($splitRemoteMs / $splitTotalMs, 4)
    } else { $null }
    splitDraftShare = if ($null -ne $splitDraftFetchMs -and $null -ne $splitTotalMs -and $splitTotalMs -gt 0) {
        [math]::Round($splitDraftFetchMs / $splitTotalMs, 4)
    } else { $null }
    splitOverallTpsVsLocalDraftLoopTpsRatio = if ($null -ne $localDraftLoopTps -and $localDraftLoopTps -gt 0 -and $null -ne $splitOverallTps) {
        [math]::Round($splitOverallTps / $localDraftLoopTps, 4)
    } else { $null }
    splitDraftTpsVsLocalDraftLoopTpsRatio = if ($null -ne $localDraftLoopTps -and $localDraftLoopTps -gt 0 -and $null -ne $splitDraftTps) {
        [math]::Round($splitDraftTps / $localDraftLoopTps, 4)
    } else { $null }
}

$runStamp = (Get-Date -Format "yyyy-MM-ddTHH-mm-sszzz").Replace(":", "-")
$comparisonPath = Join-Path $dateDir "android_local_vs_split_comparison_${runStamp}.json"
$comparison | ConvertTo-Json -Depth 6 | Set-Content -Path $comparisonPath -Encoding UTF8
Write-Host $comparisonPath
