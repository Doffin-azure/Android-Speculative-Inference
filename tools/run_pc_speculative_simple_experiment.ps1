param(
    [string]$Prompt = "Explain speculative decoding briefly.",
    [int]$MaxOutputTokens = 64,
    [int]$CtxSize = 512,
    [string]$DraftModelPath,
    [string]$TargetModelPath,
    [string]$LlamaRoot = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$experimentsRoot = Join-Path $repoRoot "reference\spec-split-demo-project\experiments"
$dateDir = Join-Path $experimentsRoot (Get-Date -Format "yyyy-MM-dd")

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
        if ($line -match "^n_drafted\s+=\s+(?<value>\d+)") { $result.nDrafted = [int]$matches.value }
        if ($line -match "^n_accept\s+=\s+(?<value>\d+)") { $result.nAccept = [int]$matches.value }
        if ($line -match "^accept\s+=\s+(?<value>[0-9.]+)%") { $result.acceptRatio = [double]$matches.value }
        if ($line -match "^rounds\s+=\s+(?<value>\d+)") { $result.rounds = [int]$matches.value }
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
'$binWsl' --model '$targetWsl' --model-draft '$draftWsl' --prompt '$promptEscaped' --ctx-size $CtxSize --ctx-size-draft $CtxSize --predict $MaxOutputTokens --gpu-layers 99 --gpu-layers-draft 99 --batch-size 512 --ubatch-size 512 --temp 0 --top-k 1 --seed 1234 > '$logWsl' 2>&1
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
    $stderr = if (Test-Path $stderrPath) { Get-Content -Path $stderrPath -Raw } else { "" }
} finally {
    Remove-Item -LiteralPath $stdoutPath -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $stderrPath -ErrorAction SilentlyContinue
}
$ended = Get-Date

$status = if ($proc.ExitCode -eq 0) { "completed" } else { "failed" }
$metrics = if (Test-Path $logPath) { Parse-BaselineLog -LogPath $logPath } else { $null }

$summary = [ordered]@{
    generatedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
    script = $MyInvocation.MyCommand.Path
    status = $status
    exitCode = $proc.ExitCode
    start = $started.ToString("yyyy-MM-dd HH:mm:ss zzz")
    end = $ended.ToString("yyyy-MM-dd HH:mm:ss zzz")
    prompt = $Prompt
    maxOutputTokens = $MaxOutputTokens
    ctxSize = $CtxSize
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
