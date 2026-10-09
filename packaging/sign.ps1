param(
    [Parameter(Mandatory = $true)]
    [string]$CertificatePath,
    [string]$CertificatePassword,
    [string]$TimestampUrl = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot ".."))
$CertificatePath = (Resolve-Path $CertificatePath).Path
$SignToolCommand = Get-Command signtool.exe -ErrorAction SilentlyContinue

if (-not $SignToolCommand) {
    throw "signtool.exe not found. Install the Windows SDK or Visual Studio signing tools."
}
if (-not (Test-Path $CertificatePath)) {
    throw "Certificate file not found: $CertificatePath"
}

if (-not $CertificatePassword) {
    $secure = Read-Host "Certificate password" -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $CertificatePassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    }
}

$targets = @()
$targets += Get-ChildItem (Join-Path $Root "dist\Yinlingban") -Recurse -File `
    -Include *.exe,*.dll,*.pyd -ErrorAction SilentlyContinue
$targets += Get-ChildItem (Join-Path $Root "release") -File `
    -Filter *.exe -ErrorAction SilentlyContinue

if (-not $targets) {
    throw "No build artifacts found. Run packaging\build.ps1 -Installer first."
}

foreach ($target in $targets) {
    Write-Host "Signing $($target.FullName)"
    & $SignToolCommand.Source sign /fd SHA256 /f $CertificatePath /p $CertificatePassword `
        /tr $TimestampUrl /td SHA256 $target.FullName
    if ($LASTEXITCODE -ne 0) {
        throw "Signing failed for $($target.FullName)"
    }
}

foreach ($target in $targets) {
    & $SignToolCommand.Source verify /pa /all $target.FullName | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Signature verification failed for $($target.FullName)"
    }
}

Write-Host "Authenticode signing and verification completed."
