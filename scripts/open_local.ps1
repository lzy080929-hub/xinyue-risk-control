$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
$applicationUrl = 'http://127.0.0.1:5000/?test=1'
$probeUrl = 'http://127.0.0.1:5000/?test=1'

function Test-XinyuePage {
    try {
        $response = Invoke-WebRequest -Uri $probeUrl -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -eq 200 -and $response.Content.Contains('data-ui-version="bank-application-v1"')
    } catch { return $false }
}

if (Test-XinyuePage) {
    Start-Process -FilePath $applicationUrl
    exit 0
}

# This job opens the browser only after this project's application responds.
# The application stays in this window so the user can see errors and stop it.
$openBrowserJob = Start-Job -ArgumentList $probeUrl, $applicationUrl -ScriptBlock {
    param($checkUrl, $openUrl)
    for ($attempt = 0; $attempt -lt 90; $attempt++) {
        try {
            $response = Invoke-WebRequest -Uri $checkUrl -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200 -and $response.Content.Contains('data-ui-version="bank-application-v1"')) {
                Start-Process -FilePath $openUrl
                return
            }
        } catch { }
        Start-Sleep -Milliseconds 500
    }
}

try {
    Write-Host 'Starting Xinyue. Keep this window open while using the local website.'
    & (Join-Path $projectDirectory 'start_local.ps1')
} finally {
    Stop-Job -Job $openBrowserJob -ErrorAction SilentlyContinue
    Remove-Job -Job $openBrowserJob -Force -ErrorAction SilentlyContinue
}
