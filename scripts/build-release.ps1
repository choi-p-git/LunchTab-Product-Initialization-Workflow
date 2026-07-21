param(
    [string]$Version = "",
    [string]$InnoCompiler = ""
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

if (-not $Version) {
    $Pyproject = Get-Content -Raw -LiteralPath (Join-Path $Root "pyproject.toml")
    if ($Pyproject -notmatch '(?m)^version\s*=\s*"([^"]+)"') {
        throw "Could not read project version from pyproject.toml."
    }
    $Version = $Matches[1]
}

if (-not $InnoCompiler) {
    $Candidates = @(
        "C:\Program Files\Inno Setup 7\ISCC.exe",
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    )
    $InnoCompiler = ($Candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1)
}
if (-not $InnoCompiler) {
    throw "Inno Setup compiler was not found. Install Inno Setup or pass -InnoCompiler."
}

$DistDir = Join-Path $Root "dist"
$BuildDir = Join-Path $Root "build"
$ReleaseDir = Join-Path $Root "release"
$VersionReleaseDir = Join-Path $ReleaseDir "v$Version"

foreach ($Path in @($DistDir, $BuildDir, $VersionReleaseDir)) {
    $FullPath = [System.IO.Path]::GetFullPath($Path)
    if (-not $FullPath.StartsWith($Root, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean outside the repository: $Path"
    }
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
}

New-Item -ItemType Directory -Force -Path $VersionReleaseDir | Out-Null

uv run pyinstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onedir `
    --name "Lunchtab Product Initialization" `
    --distpath "$DistDir" `
    --workpath (Join-Path $BuildDir "pyinstaller") `
    --specpath (Join-Path $BuildDir "spec") `
    --collect-submodules openpyxl `
    --collect-data openpyxl `
    --hidden-import pypdf `
    "src\lunchtab_product_init\__main__.py"

$ExePath = Join-Path $DistDir "Lunchtab Product Initialization\Lunchtab Product Initialization.exe"
if (-not (Test-Path -LiteralPath $ExePath)) {
    throw "PyInstaller did not produce the expected executable: $ExePath"
}

& $InnoCompiler "/DMyAppVersion=$Version" "packaging\installer.iss"
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup compiler failed with exit code $LASTEXITCODE."
}

$Installer = Join-Path $VersionReleaseDir "Lunchtab-Product-Initialization-Setup-v$Version.exe"
if (-not (Test-Path -LiteralPath $Installer)) {
    throw "Inno Setup did not produce the expected installer: $Installer"
}

$PortableZip = Join-Path $VersionReleaseDir "Lunchtab-Product-Initialization-Portable-v$Version.zip"
Compress-Archive `
    -LiteralPath (Join-Path $DistDir "Lunchtab Product Initialization") `
    -DestinationPath $PortableZip `
    -CompressionLevel Optimal `
    -Force

$Hashes = foreach ($Artifact in @($Installer, $PortableZip)) {
    $Hash = Get-FileHash -Algorithm SHA256 -LiteralPath $Artifact
    "$($Hash.Hash)  $([System.IO.Path]::GetFileName($Artifact))"
}
$Hashes | Set-Content -Encoding ascii -LiteralPath (Join-Path $VersionReleaseDir "SHA256SUMS.txt")

Write-Host "Built executable: $ExePath"
Write-Host "Built installer: $Installer"
Write-Host "Built portable archive: $PortableZip"
Write-Host "SHA-256:"
$Hashes | ForEach-Object { Write-Host $_ }
