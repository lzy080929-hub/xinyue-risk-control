$ErrorActionPreference = 'Stop'
$projectDirectory = $PSScriptRoot
Set-Location -LiteralPath $projectDirectory
$projectPython = Join-Path $projectDirectory '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) {
    throw 'Please create .venv and install requirements-dev.txt first. See README.md.'
}
& $projectPython -X utf8 (Join-Path $projectDirectory 'scripts/backup_local.py')
if ($LASTEXITCODE -ne 0) { throw 'Backup failed. Database migration was not started.' }
& $projectPython -m flask --app app db upgrade
if ($LASTEXITCODE -ne 0) { throw 'Database migration failed. Existing data was not reset.' }
Write-Host 'Open http://127.0.0.1:5000/?test=1 to test the application.'
Write-Host 'Open http://127.0.0.1:5000/admin/login to set up or log in to the local admin.'
& $projectPython -X utf8 (Join-Path $projectDirectory 'app.py')
