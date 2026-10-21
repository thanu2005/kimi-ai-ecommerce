# Start the MCP SSE server.
# Run from anywhere — this script resolves all paths automatically.
#
#   First-time setup:
#       cd mcp_server
#       uv sync
#
#   Usage (from project root or mcp_server/):
#       .\mcp_server\run.ps1
#       .\mcp_server\run.ps1 -Port 8002

param(
    [int]$Port = 8002,
    [string]$BindHost = "0.0.0.0"
)

$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Definition
$Python      = Join-Path $ScriptDir ".venv\Scripts\python.exe"
$StartScript = Join-Path $ScriptDir "start_server.py"

if (-not (Test-Path $Python)) {
    Write-Error "Python not found at $Python`nRun 'uv sync' inside mcp_server/ first."
    exit 1
}

Write-Host "Starting MCP SSE server on port $Port ..." -ForegroundColor Cyan
Write-Host "SSE endpoint : http://localhost:$Port/sse" -ForegroundColor Gray
Write-Host "Press Ctrl+C to stop.`n" -ForegroundColor Gray

& $Python $StartScript --host $BindHost --port $Port
