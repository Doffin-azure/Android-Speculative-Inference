param(
    [string]$Prompt = "Explain speculative decoding briefly.",
    [string]$DeviceSerial = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$modelsDir = Join-Path $repoRoot "models"
$experimentsRoot = Join-Path $repoRoot "reference\spec-split-demo-project\experiments"
$dateDir = Join-Path $experimentsRoot (Get-Date -Format "yyyy-MM-dd")

$pairs = @(
    @{ Name = "qwen25_0.5b_to_3b"; Draft = "Qwen2.5-0.5B-Instruct-Q4_K_M.gguf"; Target = "Qwen2.5-3B-Instruct-Q4_K_M.gguf" },
    @{ Name = "qwen25_1.5b_to_7b"; Draft = "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf"; Target = "Qwen2.5-7B-Instruct-Q4_K_M.gguf" },
    @{ Name = "qwen25_coder_1.5b_to_7b"; Draft = "Qwen2.5-Coder-1.5B-Instruct-Q4_K_M.gguf"; Target = "Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf" },
    @{ Name = "deepseek_r1_distill_qwen_1.5b_to_7b"; Draft = "DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M.gguf"; Target = "DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf" },
    @{ Name = "gemma2_2b_to_9b"; Draft = "gemma-2-2b-it-Q4_K_M.gguf"; Target = "gemma-2-9b-it-Q4_K_M.gguf" }
)

New-Item -ItemType Directory -Force -Path $dateDir | Out-Null
$results = @()

foreach ($pair in $pairs) {
    $draftPath = Join-Path $modelsDir $pair.Draft
    $targetPath = Join-Path $modelsDir $pair.Target
    & (Join-Path $repoRoot "tools\run_model_pair_matrix.ps1") `
        -PairName $pair.Name `
        -Prompt $Prompt `
        -DraftModelPath $draftPath `
        -TargetModelPath $targetPath `
        -DeviceSerial $DeviceSerial
    if ($LASTEXITCODE -ne 0) {
        throw "Model pair matrix failed for $($pair.Name)"
    }

    $latest = Get-ChildItem -Path $dateDir -Filter "model_pair_matrix_$($pair.Name)_*.json" -File |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    $results += Get-Content -Path $latest.FullName -Raw | ConvertFrom-Json
}

$fasterCases = @($results | Where-Object { $_.analysis.androidSplitFasterThanDesktopDirect })
$summary = [ordered]@{
    generatedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
    prompt = $Prompt
    pairCount = $results.Count
    androidSplitFasterThanDesktopDirectCount = $fasterCases.Count
    fasterPairNames = @($fasterCases | ForEach-Object { $_.pairName })
    results = $results
}

$stamp = (Get-Date -Format "yyyy-MM-ddTHH-mm-sszzz").Replace(":", "-")
$summaryPath = Join-Path $dateDir "candidate_model_batch_summary_${stamp}.json"
$summary | ConvertTo-Json -Depth 10 | Set-Content -Path $summaryPath -Encoding UTF8

Write-Host "candidate model batch complete"
Write-Host "summary: $summaryPath"
