param(
    [string]$Prompt = "Explain speculative decoding briefly.",
    [int]$MaxOutputTokens = 64,
    [int]$DraftMaxTokens = 4,
    [int]$CtxSize = 512,
    [int]$Threads = 4,
    [int]$DraftMinTokens = 0,
    [double]$DraftMinProb = 0.75,
    [string]$DraftModelPath,
    [string]$TargetModelPath,
    [string]$LlamaRoot = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$experimentsRoot = Join-Path $repoRoot "reference\spec-split-demo-project\experiments"
$dateDir = Join-Path $experimentsRoot (Get-Date -Format "yyyy-MM-dd")
$experimentLockDir = Join-Path $repoRoot ".experiment-lock"
$experimentLockInfoPath = Join-Path $experimentLockDir "owner.json"

function Acquire-ExperimentLock {
    param(
        [Parameter(Mandatory = $true)][string]$LockDir,
        [Parameter(Mandatory = $true)][string]$OwnerInfoPath
    )

    try {
        New-Item -ItemType Directory -Path $LockDir -ErrorAction Stop | Out-Null
    } catch {
        $ownerInfo = ""
        if (Test-Path $OwnerInfoPath) {
            $ownerInfo = Get-Content -Path $OwnerInfoPath -Raw
        }
        throw "Another experiment is already running. lockDir=$LockDir owner=$ownerInfo"
    }

    $owner = [ordered]@{
        pid = $PID
        script = $MyInvocation.MyCommand.Path
        startedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
        host = $env:COMPUTERNAME
    }
    $owner | ConvertTo-Json -Depth 4 | Set-Content -Path $OwnerInfoPath -Encoding UTF8
}

function Release-ExperimentLock {
    param([Parameter(Mandatory = $true)][string]$LockDir)
    if (Test-Path $LockDir) {
        Remove-Item -LiteralPath $LockDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Acquire-ExperimentLock -LockDir $experimentLockDir -OwnerInfoPath $experimentLockInfoPath

try {
    function Convert-ToWslPath {
        param([Parameter(Mandatory = $true)][string]$WindowsPath)
        $fullPath = [System.IO.Path]::GetFullPath($WindowsPath)
        $drive = $fullPath.Substring(0, 1).ToLowerInvariant()
        $tail = $fullPath.Substring(2).Replace("\", "/")
        return "/mnt/$drive$tail"
    }

    function Read-GradleLocalProperties {
        $path = Join-Path $repoRoot "gradle-local.properties"
        $result = @{}
        if (-not (Test-Path $path)) {
            return $result
        }
        Get-Content $path | ForEach-Object {
            if ($_ -match "^\s*#" -or $_ -notmatch "=") {
                return
            }
            $parts = $_ -split "=", 2
            $result[$parts[0].Trim()] = $parts[1].Trim()
        }
        return $result
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
            steadyStateWallSeconds = $null
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
            if ($line -match "^n_drafted\s+=\s+(?<value>\d+)") { $result.nDrafted = [int]$matches.value }
            if ($line -match "^n_accept\s+=\s+(?<value>\d+)") { $result.nAccept = [int]$matches.value }
            if ($line -match "^accept\s+=\s+(?<value>[0-9.]+)%") { $result.acceptRatio = [double]$matches.value }
            if ($line -match "^rounds\s+=\s+(?<value>\d+)") { $result.rounds = [int]$matches.value }
            if ($line -match "^reject_rounds\s+=\s+(?<value>\d+)") { $result.rejectRounds = [int]$matches.value }
        }
        if ($draftPerRound.Count -gt 0) {
            $result.averageProposedTokensPerRound = [math]::Round((($draftPerRound | Measure-Object -Average).Average), 3)
            $result.averageAcceptedDraftTokensPerRound = [math]::Round((($acceptPerRound | Measure-Object -Average).Average), 3)
            $result.averageDraftGenerateMs = [math]::Round((($draftMs | Measure-Object -Average).Average), 3)
            $result.averageVerifyDecodeMs = [math]::Round((($decodeMs | Measure-Object -Average).Average), 3)
            $result.averageVerifySampleMs = [math]::Round((($sampleMs | Measure-Object -Average).Average), 3)
            $result.averagePostMs = [math]::Round((($postMs | Measure-Object -Average).Average), 3)
            $result.averageRoundTotalMs = [math]::Round((($totalMs | Measure-Object -Average).Average), 3)
            $steadyStateWallSeconds = (($totalMs | Measure-Object -Sum).Sum) / 1000.0
            $result.steadyStateWallSeconds = [math]::Round($steadyStateWallSeconds, 3)
            if ($result.decodedTokens -and $steadyStateWallSeconds -gt 0) {
                $result.overallTokensPerSecond = [math]::Round($result.decodedTokens / $steadyStateWallSeconds, 3)
            }
        }
        return $result
    }

    $gradleLocal = Read-GradleLocalProperties
    if ([string]::IsNullOrWhiteSpace($LlamaRoot)) {
        $LlamaRoot = $gradleLocal["llamaCppSourceDir"]
    }
    if ([string]::IsNullOrWhiteSpace($LlamaRoot)) {
        $LlamaRoot = Join-Path (Split-Path -Parent $repoRoot) "llama.cpp"
    }

    $baselineBin = Join-Path $LlamaRoot "build-wsl-server\bin\llama-speculative-simple"
    foreach ($path in @($DraftModelPath, $TargetModelPath, $baselineBin)) {
        if (-not (Test-Path $path)) {
            throw "Required path not found: $path"
        }
    }

    New-Item -ItemType Directory -Force -Path $dateDir | Out-Null

    $draftWsl = Convert-ToWslPath $DraftModelPath
    $targetWsl = Convert-ToWslPath $TargetModelPath
    $binWsl = Convert-ToWslPath $baselineBin
    $started = Get-Date
    $stamp = ($started.ToString("yyyy-MM-ddTHH-mm-sszzz")).Replace(":", "-")
    $logPath = Join-Path $dateDir "pc_speculative_simple_${stamp}.log"
    $logWsl = Convert-ToWslPath $logPath
    $promptEscaped = $Prompt.Replace("'", "'\''")
    $bashCommand = @"
set -e
START_TS="`$(date "+%Y-%m-%d %H:%M:%S %z")"
echo "__EXPERIMENT_START__=`$START_TS"
'$binWsl' --model '$targetWsl' --model-draft '$draftWsl' --prompt '$promptEscaped' --ctx-size $CtxSize --ctx-size-draft $CtxSize --predict $MaxOutputTokens --gpu-layers 99 --gpu-layers-draft 99 --batch-size 512 --ubatch-size 512 -t $Threads --temp 0 --top-k 1 --seed 1234 --draft $DraftMaxTokens --draft-min $DraftMinTokens --draft-p-min $DraftMinProb > '$logWsl' 2>&1
END_TS="`$(date "+%Y-%m-%d %H:%M:%S %z")"
echo "__EXPERIMENT_END__=`$END_TS"
"@

    $stdoutPath = [System.IO.Path]::GetTempFileName()
    $stderrPath = [System.IO.Path]::GetTempFileName()
    try {
        $proc = Start-Process -FilePath wsl.exe `
            -ArgumentList @("bash", "-lc", $bashCommand) `
            -NoNewWindow `
            -Wait `
            -PassThru `
            -RedirectStandardOutput $stdoutPath `
            -RedirectStandardError $stderrPath
        $stdout = if (Test-Path $stdoutPath) { Get-Content -Path $stdoutPath -Raw } else { "" }
        $stderr = if (Test-Path $stderrPath) { Get-Content -Path $stderrPath -Raw } else { "" }
    } finally {
        Remove-Item -LiteralPath $stdoutPath -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $stderrPath -ErrorAction SilentlyContinue
    }
    $ended = Get-Date

    $markerStart = $null
    $markerEnd = $null
    if ($stdout -match "__EXPERIMENT_START__=(?<value>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} [+-]\d{4})") {
        $markerStart = $matches.value
    }
    if ($stdout -match "__EXPERIMENT_END__=(?<value>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} [+-]\d{4})") {
        $markerEnd = $matches.value
    }

    $status = if ($proc.ExitCode -eq 0) { "completed" } else { "failed" }
    $metrics = if (Test-Path $logPath) { Parse-BaselineLog -LogPath $logPath } else { $null }

    $summary = [ordered]@{
        generatedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
        script = $MyInvocation.MyCommand.Path
        status = $status
        exitCode = $proc.ExitCode
        start = if ($markerStart) { $markerStart } else { $started.ToString("yyyy-MM-dd HH:mm:ss zzz") }
        end = if ($markerEnd) { $markerEnd } else { $ended.ToString("yyyy-MM-dd HH:mm:ss zzz") }
        prompt = $Prompt
        timingBasis = "steady_state_wall_time_from_sum_of_speculative_round_totals"
        maxOutputTokens = $MaxOutputTokens
        draftMaxTokens = $DraftMaxTokens
        ctxSize = $CtxSize
        threads = $Threads
        draftMinTokens = $DraftMinTokens
        draftMinProb = $DraftMinProb
        draftModelPath = $DraftModelPath
        targetModelPath = $TargetModelPath
        logPath = $logPath
        stderr = $stderr
        metrics = $metrics
    }

    $summaryPath = Join-Path $dateDir "pc_speculative_simple_summary_${stamp}.json"
    $summary | ConvertTo-Json -Depth 6 | Set-Content -Path $summaryPath -Encoding UTF8

    Write-Host "pc speculative simple experiment $status"
    Write-Host "summary: $summaryPath"
    Write-Host "log: $logPath"
} finally {
    Release-ExperimentLock -LockDir $experimentLockDir
}
