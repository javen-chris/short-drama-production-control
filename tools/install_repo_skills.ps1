param(
    [string]$Destination = (Join-Path $env:USERPROFILE '.codex\skills'),
    [switch]$Replace
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$sourceRoot = Join-Path $repoRoot 'skills'
$manifest = Get-Content -LiteralPath (Join-Path $sourceRoot 'skill-chain.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$names = $manifest.steps.skill | Sort-Object -Unique
New-Item -ItemType Directory -Path $Destination -Force | Out-Null

foreach ($name in $names) {
    $source = Join-Path $sourceRoot $name
    $target = Join-Path $Destination $name
    if (-not (Test-Path -LiteralPath (Join-Path $source 'SKILL.md'))) {
        throw "Missing source Skill: $name"
    }
    if (Test-Path -LiteralPath $target) {
        if (-not $Replace) {
            Write-Output "SKIP $name (already installed)"
            continue
        }
        Remove-Item -LiteralPath $target -Recurse -Force
    }
    Copy-Item -LiteralPath $source -Destination $target -Recurse
    $hash = (Get-FileHash -LiteralPath (Join-Path $target 'SKILL.md') -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Output "INSTALLED $name $hash"
}
