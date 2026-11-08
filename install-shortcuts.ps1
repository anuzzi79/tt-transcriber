$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonw = (Get-Command pythonw.exe -ErrorAction Stop).Source
$main = Join-Path $projectDir 'main.py'
$shell = New-Object -ComObject WScript.Shell

$desktop = [Environment]::GetFolderPath('Desktop')
$start = Join-Path ([Environment]::GetFolderPath('StartMenu')) 'Programs'

foreach ($folder in @($desktop, $start)) {
    if (-not (Test-Path -LiteralPath $folder)) {
        New-Item -ItemType Directory -Path $folder | Out-Null
    }
    $link = $shell.CreateShortcut((Join-Path $folder 'TT Transcriber.lnk'))
    $link.TargetPath = $pythonw
    $link.Arguments = '"' + $main + '"'
    $link.WorkingDirectory = $projectDir
    $link.Description = 'Live English meeting transcription'
    $link.Save()
}

Write-Host 'Desktop and Start menu shortcuts created.'
