$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$serviceRoot = Join-Path $repoRoot "relationship-desk-mcp"

Set-Location $serviceRoot
$env:RELATIONSHIP_DESK_PORT = "8001"
python main.py
