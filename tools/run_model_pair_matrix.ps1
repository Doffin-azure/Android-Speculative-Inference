param(
    [string]$PairName,
    [string]$Prompt = "Explain speculative decoding briefly.",
    [string]$DraftModelPath,
    [string]$TargetModelPath,
    [string]$DeviceSerial = "",
    [int]$Threads = 4,
    [int]$DraftMaxTokens = 16,
    [int]$DraftMinTokens = 0,
    [double]$DraftMinProb = 0.75,
    [int]$PollMs = 1
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

function Get-AverageValue {
    param([object[]]$Values)
    if ($null -eq $Values) {
        return $null
    }
    $filtered = @($Values | Where-Object { $null -ne $_ })
    if ($filtered.Count -eq 0) {
        return $null
    }
    return [math]::Round((($filtered | Measure-Object -Average).Average), 3)
}

function Get-LineMetricValue {
    param(
        [Parameter(Mandatory = $true)][string]$Line,
        [Parameter(Mandatory = $true)][string]$Name
    )

    if ($Line -match ("(?:^|\s)" + [regex]::Escape($Name) + "=(?<value>-?[0-9.]+)")) {
        return [double]$matches.value
    }
    return $null
}

function Parse-BaselineLog {
    param([string]$LogPath)
    $draftPerRound = New-Object System.Collections.Generic.List[double]
    $acceptPerRound = New-Object System.Collections.Generic.List[double]
    $draftMs = New-Object System.Collections.Generic.List[double]
    $decodeMs = New-Object System.Collections.Generic.List[double]
    $sampleMs = New-Object System.Collections.Generic.List[double]
    $postMs = New-Object System.Collections.Generic.List[double]
    $totalMs = New-Object System.Collections.Generic.List[double]

    $result = [ordered]@{
        decodedTokens = $null
        decodedSeconds = $null
        decodedTokensPerSecond = $null
        overallTokensPerSecond = $null
        nDrafted = $null
        nAccept = $null
        acceptRatio = $null
        rounds = $null
        rejectRounds = $null
        averageProposedTokensPerRound = $null
        averageAcceptedDraftTokensPerRound = $null
        averageDraftGenerateMs = $null
        averageVerifyDecodeMs = $null
        averageVerifySampleMs = $null
        averagePostMs = $null
        averageRoundTotalMs = $null
    }
    foreach ($line in Get-Content -Path $LogPath) {
        if ($line -match "\[spec-simple\]\[timing\]\s+round=(?<round>\d+)\s+drafted=(?<drafted>\d+)\s+accept=(?<accept>\d+)\s+reject=(?<reject>\d+)\s+draft=(?<draftMs>[0-9.]+)ms\s+decode=(?<decodeMs>[0-9.]+)ms\s+sample=(?<sampleMs>[0-9.]+)ms\s+post=(?<postMs>[0-9.]+)ms\s+total=(?<totalMs>[0-9.]+)ms") {
            $draftPerRound.Add([double]$matches.drafted)
            $acceptPerRound.Add([double]$matches.accept)
            $draftMs.Add([double]$matches.draftMs)
            $decodeMs.Add([double]$matches.decodeMs)
            $sampleMs.Add([double]$matches.sampleMs)
            $postMs.Add([double]$matches.postMs)
            $totalMs.Add([double]$matches.totalMs)
        }
        if ($line -match "decoded\s+(?<tokens>\d+)\s+tokens\s+in\s+(?<seconds>[0-9.]+)\s+seconds,\s+speed:\s+(?<speed>[0-9.]+)\s+t/s") {
            $result.decodedTokens = [int]$matches.tokens
            $result.decodedSeconds = [double]$matches.seconds
            $result.decodedTokensPerSecond = [double]$matches.speed
            $result.overallTokensPerSecond = [double]$matches.speed
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
        if ($line -match "^reject_rounds\s+=\s+(?<value>\d+)") {
            $result.rejectRounds = [int]$matches.value
        }
    }
    if ($draftPerRound.Count -gt 0) {
        $result.averageProposedTokensPerRound = [math]::Round((($draftPerRound | Measure-Object -Average).Average), 3)
        $result.averageAcceptedDraftTokensPerRound = [math]::Round((($acceptPerRound | Measure-Object -Average).Average), 3)
        $result.averageDraftGenerateMs = [math]::Round((($draftMs | Measure-Object -Average).Average), 3)
        $result.averageVerifyDecodeMs = [math]::Round((($decodeMs | Measure-Object -Average).Average), 3)
        $result.averageVerifySampleMs = [math]::Round((($sampleMs | Measure-Object -Average).Average), 3)
        $result.averagePostMs = [math]::Round((($postMs | Measure-Object -Average).Average), 3)
        $result.averageRoundTotalMs = [math]::Round((($totalMs | Measure-Object -Average).Average), 3)
    }
    return $result
}

function Parse-NativeSummary {
    param([string]$SummaryPath)
    $summary = Get-Content -Path $SummaryPath -Raw | ConvertFrom-Json
    $native = $summary.nativeFull
    if ($null -eq $native.wallSeconds) {
        $start = Get-Date $native.start
        $end = Get-Date $native.end
        $native | Add-Member -NotePropertyName wallSeconds -NotePropertyValue ([math]::Round(($end - $start).TotalSeconds, 3))
    }
    if ($null -eq $native.overallTokensPerSecond -and $native.wallSeconds -gt 0) {
        $native | Add-Member -NotePropertyName overallTokensPerSecond -NotePropertyValue ([math]::Round([double]$native.acceptedPos / [double]$native.wallSeconds, 3))
    }
    return [ordered]@{
        nativeFull = $native
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
    $proposedPerRound = New-Object System.Collections.Generic.List[double]
    $draftGenerateMs = New-Object System.Collections.Generic.List[double]
    $draftRollbackMs = New-Object System.Collections.Generic.List[double]
    $verifyDecodeMs = New-Object System.Collections.Generic.List[double]
    $verifyServiceMs = New-Object System.Collections.Generic.List[double]
    $transportMs = New-Object System.Collections.Generic.List[double]
    foreach ($line in Get-Content -Path $appOutputPath) {
        if (-not $line.StartsWith("step=")) {
            continue
        }
        $v = Get-LineMetricValue -Line $line -Name "proposed"
        if ($null -ne $v) { $proposedPerRound.Add($v) }
        $v = Get-LineMetricValue -Line $line -Name "draftGenerateMs"
        if ($null -ne $v) { $draftGenerateMs.Add($v) }
        $v = Get-LineMetricValue -Line $line -Name "draftRollbackMs"
        if ($null -ne $v) { $draftRollbackMs.Add($v) }
        $v = Get-LineMetricValue -Line $line -Name "decodeMs"
        if ($null -ne $v) { $verifyDecodeMs.Add($v) }
        $v = Get-LineMetricValue -Line $line -Name "serviceTotalMs"
        if ($null -ne $v) { $verifyServiceMs.Add($v) }
        $v = Get-LineMetricValue -Line $line -Name "estimatedTransportMs"
        if ($null -ne $v) { $transportMs.Add($v) }
    }
    return [ordered]@{
        summaryPath = $SummaryPath
        outputPath = $appOutputPath
        strategyMode = $metrics.strategyMode
        draftProbabilityThresholdSupported = $metrics.draftProbabilityThresholdSupported
        draftMinTokens = if ($metrics.Contains("draftMinTokens")) { [int]$metrics.draftMinTokens } else { $null }
        draftMinProb = if ($metrics.Contains("draftMinProb")) { [double]$metrics.draftMinProb } else { $null }
        steps = [int]$metrics.steps
        committedTokens = [int]$metrics.committedTokens
        totalProposedTokens = [int]$metrics.totalProposedTokens
        totalMs = [int]$metrics.totalMs
        totalDraftFetchMs = [int]$metrics.totalDraftFetchMs
        totalDraftGenerateMs = [int]$metrics.totalDraftGenerateMs
        totalDraftRollbackMs = [int]$metrics.totalDraftRollbackMs
        totalRemoteProposeMs = [int]$metrics.totalRemoteProposeMs
        overallTokensPerSecond = [double]$metrics.overallTokensPerSecond
        draftTokensPerSecond = [double]$metrics.draftTokensPerSecond
        averageProposedTokensPerRound = Get-AverageValue -Values $proposedPerRound
        averageDraftGenerateMs = Get-AverageValue -Values $draftGenerateMs
        averageDraftRollbackMs = Get-AverageValue -Values $draftRollbackMs
        averageVerifyDecodeMs = Get-AverageValue -Values $verifyDecodeMs
        averageVerifyServiceMs = Get-AverageValue -Values $verifyServiceMs
        averageTransportMs = Get-AverageValue -Values $transportMs
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
python (Join-Path $repoRoot "tools\run_desktop_direct_experiment.py") --prompt $Prompt --model-path $TargetModelPath --threads $Threads
if ($LASTEXITCODE -ne 0) { throw "Desktop direct experiment failed." }
$directSummary = Get-MostRecentFile -DirectoryPath $dateDir -Filter "desktop_direct_summary_*.json" -AfterTime $directStartedAt
$directMetrics = Parse-DesktopDirectSummary -SummaryPath $directSummary.FullName

$nativeStartedAt = Get-Date
& (Join-Path $repoRoot "reference\spec-split-demo-project\run_recorded_native_full_experiment.ps1") `
    -Prompt $Prompt `
    -NMax $DraftMaxTokens `
    -NMin $DraftMinTokens `
    -PMin $DraftMinProb `
    -Threads $Threads `
    -PollMs $PollMs `
    -DraftModel $DraftModelPath `
    -VerifyModel $TargetModelPath
if ($LASTEXITCODE -ne 0) { throw "Native full experiment failed." }
$nativeSummary = Get-MostRecentFile -DirectoryPath $dateDir -Filter "recorded_run_*.json" -AfterTime $nativeStartedAt
$nativeMetrics = Parse-NativeSummary -SummaryPath $nativeSummary.FullName

$baselineStartedAt = Get-Date
& (Join-Path $repoRoot "tools\run_pc_speculative_simple_experiment.ps1") `
    -Prompt $Prompt `
    -Threads $Threads `
    -DraftMinTokens $DraftMinTokens `
    -DraftMinProb $DraftMinProb `
    -DraftModelPath $DraftModelPath `
    -TargetModelPath $TargetModelPath
if ($LASTEXITCODE -ne 0) { throw "PC speculative simple wrapper failed." }
$baselineSummary = Get-MostRecentFile -DirectoryPath $dateDir -Filter "pc_speculative_simple_summary_*.json" -AfterTime $baselineStartedAt
$baselineMetrics = Parse-BaselineSummary -SummaryPath $baselineSummary.FullName

$androidStartedAt = Get-Date
& (Join-Path $repoRoot "tools\run_android_spec_split_experiment.ps1") `
    -DeviceSerial $DeviceSerial `
    -Prompt $Prompt `
    -Threads $Threads `
    -DraftMaxTokens $DraftMaxTokens `
    -InitialDraftTokens $DraftMaxTokens `
    -DraftMinTokens $DraftMinTokens `
    -DraftMinProb $DraftMinProb `
    -AdaptiveDraftingEnabled:$false `
    -AdaptiveDraftMinTokens $DraftMaxTokens `
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
