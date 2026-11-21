<#
.SYNOPSIS
    Packs the MSVC toolchain of an installed Visual Studio into an AutoSDK directory for Wine.

.DESCRIPTION
    Unreal Engine (5.6+) can use a toolchain from an AutoSDK directory instead of an installed
    Visual Studio: set UE_SDKS_ROOT to it. This is how Epic builds the engine under Wine, see
    WineResources/examples/quickstart/autosdk. This script builds the same layout from the
    Visual Studio installed on this PC, x64 parts only:

      AutoSDK/HostWin64/Win64/
        VS2026/<MSVC version>/          VC\Tools\MSVC\<version> (with ATL/MFC)
        Windows Kits/10/                 Windows SDK <version>
        Windows Kits/NETFXSDK/<version>/ .NET Framework SDK (unless -NoNetFx)
        DIA SDK/VS2026/
        LLVM/<version>/                  clang-cl (only with -IncludeLlvm)

    The MSVC and Windows SDK versions are chosen from the engine's Windows_SDK.json:
    a preferred version if installed, otherwise the newest one that is not banned.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File make-autosdk.ps1
    powershell -ExecutionPolicy Bypass -File make-autosdk.ps1 -EngineDir "D:\UE_5.8" -MsvcVersion 14.38.33130
#>
param(
    [string]$EngineDir,           # engine root (with Engine\Config\Windows\Windows_SDK.json); detected if omitted
    [string]$VsPath,              # Visual Studio installation; newest one if omitted
    [string]$MsvcVersion,         # e.g. 14.51.36231; chosen from Windows_SDK.json if omitted
    [string]$WindowsSdkVersion,   # e.g. 10.0.22621.0; chosen from Windows_SDK.json if omitted
    [string]$OutDir = (Join-Path $PSScriptRoot "..\..\AutoSDK-build"),
    [switch]$IncludeLlvm,
    [switch]$NoNetFx,
    [switch]$NoArchive
)

$ErrorActionPreference = "Stop"

function Log($msg) { Write-Host "[make-autosdk] $msg" }
function Fail($msg) { Write-Host "[make-autosdk] error: $msg" -ForegroundColor Red; exit 1 }

# "14.50.35717" -> comparable [version]
function V([string]$s) { [version]($s.Trim()) }
function InRange([string]$ver, [string]$range) {
    $lo, $hi = $range.Split("-")
    (V $ver) -ge (V $lo) -and (V $ver) -le (V $hi)
}

# copy a directory tree with robocopy, excluding directory names
function Copy-Tree([string]$src, [string]$dst, [string[]]$excludeDirs = @()) {
    if (-not (Test-Path $src)) { return }
    $rcArgs = @($src, $dst, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/NP", "/R:1", "/W:1", "/MT:16")
    if ($excludeDirs.Count) { $rcArgs += "/XD"; $rcArgs += $excludeDirs }
    & robocopy @rcArgs | Out-Null
    if ($LASTEXITCODE -ge 8) { Fail "copying $src failed (robocopy $LASTEXITCODE)" }
}

# ------------------------------------------------------------------ inputs

if (-not $VsPath) {
    $vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    if (-not (Test-Path $vswhere)) { Fail "vswhere.exe not found, pass -VsPath" }
    $VsPath = & $vswhere -latest -prerelease -products * -property installationPath
    if (-not $VsPath) { Fail "no Visual Studio installation found" }
}
$vsMajor = [int](Get-Content (Join-Path $VsPath "Common7\IDE\devenv.isolation.ini") -ErrorAction SilentlyContinue |
    Select-String "^InstallationVersion=(\d+)" | ForEach-Object { $_.Matches[0].Groups[1].Value } | Select-Object -First 1)
if (-not $vsMajor) { $vsMajor = if ($VsPath -match "\\18\\") { 18 } else { 17 } }
$vsId = @{ 16 = "VS2019"; 17 = "VS2022"; 18 = "VS2026" }[$vsMajor]
Log "Visual Studio: $VsPath ($vsId)"

if (-not $EngineDir) {
    $EngineDir = Get-ChildItem "C:\Program Files\Epic Games" -Directory -ErrorAction SilentlyContinue |
        Where-Object { Test-Path (Join-Path $_.FullName "Engine\Config\Windows\Windows_SDK.json") } |
        Sort-Object Name -Descending | Select-Object -First 1 -ExpandProperty FullName
}
$sdkJson = $null
if ($EngineDir) {
    $jsonPath = Join-Path $EngineDir "Engine\Config\Windows\Windows_SDK.json"
    if (Test-Path $jsonPath) {
        # the file has // keys but is otherwise plain JSON
        $sdkJson = Get-Content $jsonPath -Raw | ConvertFrom-Json
        Log "engine requirements: $jsonPath"
    }
}

# ------------------------------------------------------------------ choose versions

$msvcRoot = Join-Path $VsPath "VC\Tools\MSVC"
$installedMsvc = Get-ChildItem $msvcRoot -Directory | Where-Object { Test-Path (Join-Path $_.FullName "bin\Hostx64\x64\cl.exe") } |
    Select-Object -ExpandProperty Name
if (-not $installedMsvc) { Fail "no x64 MSVC toolset in $msvcRoot" }

# Like UBT: the folder name is the toolset family (preferred ranges are matched against it),
# cl.exe has the actual version (minimum and banned ranges are matched against that).
# cl.exe 19.50.35739 -> 14.50.35739
function Get-ToolVersion([string]$family) {
    $fv = (Get-Item (Join-Path $msvcRoot "$family\bin\Hostx64\x64\cl.exe")).VersionInfo
    "14.$($fv.FileMinorPart).$($fv.FileBuildPart)"
}

if (-not $MsvcVersion) {
    $candidates = $installedMsvc
    if ($sdkJson) {
        $candidates = $candidates | Where-Object {
            $v = Get-ToolVersion $_
            ((V $v) -ge (V $sdkJson.MinimumVisualCppVersion)) -and
            -not ($sdkJson.BannedVisualCppVersions | Where-Object { InRange $v $_ })
        }
        $preferred = $candidates | Where-Object { $v = $_; $sdkJson.PreferredVisualCppVersions | Where-Object { InRange $v $_ } }
        if ($preferred) { $candidates = $preferred }
    }
    $MsvcVersion = $candidates | Sort-Object { V $_ } -Descending | Select-Object -First 1
    if (-not $MsvcVersion) { Fail "none of the installed MSVC versions ($($installedMsvc -join ', ')) is allowed by the engine" }
}
if ($installedMsvc -notcontains $MsvcVersion) { Fail "MSVC $MsvcVersion is not installed (have: $($installedMsvc -join ', '))" }

$kitsRoot = "${env:ProgramFiles(x86)}\Windows Kits\10"
$installedSdk = Get-ChildItem (Join-Path $kitsRoot "Include") -Directory | Where-Object { Test-Path (Join-Path $_.FullName "um\windows.h") } |
    Select-Object -ExpandProperty Name
if (-not $WindowsSdkVersion) {
    if ($sdkJson -and $installedSdk -contains $sdkJson.MainVersion) { $WindowsSdkVersion = $sdkJson.MainVersion }
    else { $WindowsSdkVersion = $installedSdk | Sort-Object { V $_ } -Descending | Select-Object -First 1 }
}
if ($installedSdk -notcontains $WindowsSdkVersion) { Fail "Windows SDK $WindowsSdkVersion is not installed (have: $($installedSdk -join ', '))" }

Log "MSVC $MsvcVersion, Windows SDK $WindowsSdkVersion"

# ------------------------------------------------------------------ assemble

$OutDir = [IO.Path]::GetFullPath($OutDir)
$root = Join-Path $OutDir "AutoSDK"
$win64 = Join-Path $root "HostWin64\Win64"
if (Test-Path $root) { Log "removing previous $root"; Remove-Item $root -Recurse -Force }
New-Item -ItemType Directory -Force $win64 | Out-Null
$noArm = @("arm", "arm64", "arm64ec", "ARM", "ARM64")

Log "copying MSVC $MsvcVersion"
$msvcSrc = Join-Path $msvcRoot $MsvcVersion
$msvcDst = Join-Path $win64 "$vsId\$MsvcVersion"
foreach ($sub in @("include", "lib\x64", "bin\Hostx64\x64", "atlmfc\include", "atlmfc\lib\x64", "modules", "Auxiliary\VS")) {
    Copy-Tree (Join-Path $msvcSrc $sub) (Join-Path $msvcDst $sub)
}

Log "copying Windows SDK $WindowsSdkVersion"
$kitsDst = Join-Path $win64 "Windows Kits\10"
foreach ($sub in @("Include", "Lib", "bin", "UnionMetadata", "References", "Redist", "Platforms\UAP")) {
    Copy-Tree (Join-Path $kitsRoot "$sub\$WindowsSdkVersion") (Join-Path $kitsDst "$sub\$WindowsSdkVersion") $noArm
}
Copy-Tree (Join-Path $kitsRoot "Redist\ucrt") (Join-Path $kitsDst "Redist\ucrt") $noArm
Copy-Tree (Join-Path $kitsRoot "Debuggers\x64") (Join-Path $kitsDst "Debuggers\x64")
Get-ChildItem $kitsRoot -File | Copy-Item -Destination $kitsDst

if (-not $NoNetFx) {
    $netfx = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\NETFXSDK" -Directory -ErrorAction SilentlyContinue |
        Sort-Object { V $_.Name } -Descending | Select-Object -First 1
    if ($netfx) {
        Log "copying .NET Framework SDK $($netfx.Name)"
        Copy-Tree $netfx.FullName (Join-Path $win64 "Windows Kits\NETFXSDK\$($netfx.Name)") $noArm
    }
}

Log "copying DIA SDK"
Copy-Tree (Join-Path $VsPath "DIA SDK") (Join-Path $win64 "DIA SDK\$vsId") $noArm

$llvmVersion = ""
if ($IncludeLlvm) {
    $clang = Join-Path $VsPath "VC\Tools\Llvm\x64\bin\clang-cl.exe"
    if (Test-Path $clang) {
        $llvmVersion = ((& $clang --version) | Select-String "clang version ([\d.]+)").Matches[0].Groups[1].Value
        Log "copying LLVM $llvmVersion"
        Copy-Tree (Join-Path $VsPath "VC\Tools\Llvm\x64") (Join-Path $win64 "LLVM\$llvmVersion")
    }
}

# what is inside
@"
vs=$vsId
vs_path=$VsPath
msvc=$MsvcVersion
windows_sdk=$WindowsSdkVersion
llvm=$llvmVersion
engine=$EngineDir
created=$(Get-Date -Format s)
"@ | Set-Content -Encoding ascii (Join-Path $root "autosdk-info.txt")

$size = (Get-ChildItem $root -Recurse -File | Measure-Object Length -Sum).Sum
Log ("AutoSDK assembled: {0} ({1:N1} GB)" -f $root, ($size / 1GB))

# ------------------------------------------------------------------ archive

if (-not $NoArchive) {
    $archive = Join-Path $OutDir "AutoSDK-$vsId-$MsvcVersion-$WindowsSdkVersion.tar.gz"
    Log "packing $archive (this takes a few minutes)"
    if (Test-Path $archive) { Remove-Item $archive -Force }
    & "$env:SystemRoot\System32\tar.exe" -czf $archive -C $OutDir AutoSDK
    if ($LASTEXITCODE -ne 0) { Fail "tar failed with $LASTEXITCODE" }
    Log ("archive: {0} ({1:N1} GB)" -f $archive, ((Get-Item $archive).Length / 1GB))
}
