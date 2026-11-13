param()

$ErrorActionPreference = 'Stop'
$version = '8.6.0'
$archiveName = "naps2-$version-win-x64.zip"
$archiveHash = '5337339764A948722A7B1D3286116AD486A633C13EC006C81EEE3A99B9AF12E2'
$sourceName = "naps2-v$version-source.zip"
$sourceHash = '1207D36A021115632FE2AEB53AA9E4ACD843F390C324C3E5B7F3F2DB481DB50E'
$root = $PSScriptRoot
$archive = Join-Path $root $archiveName
$source = Join-Path $root $sourceName
$payload = Join-Path $root 'payload'
$runtime = Join-Path $payload 'naps2'
$licenses = Join-Path $payload 'licenses'

if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) {
    Invoke-WebRequest -Uri "https://github.com/cyanfish/naps2/releases/download/v$version/$archiveName" -OutFile $archive
}
if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $archiveHash) {
    throw "NAPS2 portable archive checksum mismatch: $archive"
}
if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
    Invoke-WebRequest -Uri "https://github.com/cyanfish/naps2/archive/refs/tags/v$version.zip" -OutFile $source
}
if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
    throw "Matching NAPS2 source archive is required: $source"
}
if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne $sourceHash) {
    throw "NAPS2 source archive checksum mismatch: $source"
}

New-Item -ItemType Directory -Path $runtime, $licenses -Force | Out-Null
Expand-Archive -LiteralPath $archive -DestinationPath $runtime -Force
$console = Join-Path $runtime 'App\NAPS2.Console.exe'
$license = Join-Path $runtime 'App\license.txt'
if (-not (Test-Path -LiteralPath $console -PathType Leaf) -or
    -not (Test-Path -LiteralPath $license -PathType Leaf)) {
    throw 'The portable archive is missing NAPS2.Console.exe or its license.'
}
Copy-Item -LiteralPath $source -Destination (Join-Path $licenses $sourceName) -Force
Copy-Item -LiteralPath $license -Destination (Join-Path $licenses 'NAPS2-LICENSE.txt') -Force
Copy-Item -LiteralPath (Join-Path $root 'NAPS2-NOTICE.txt') -Destination $licenses -Force
Write-Host "Prepared NAPS2 $version runtime and source for the offline installer."
