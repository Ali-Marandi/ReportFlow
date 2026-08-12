[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ExecutablePath,
    [Parameter(Mandatory = $true)][ValidateSet("certificate-store", "pfx")][string]$SigningMode,
    [Parameter(Mandatory = $true)][string]$TimestampUrl,
    [string]$CertificateThumbprint,
    [string]$Description = "ReportFlow Desktop",
    [string]$DescriptionUrl = "https://github.com/Ali-Marandi/ReportFlow"
)

$ErrorActionPreference = "Stop"

function Get-SignTool {
    $candidates = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Filter signtool.exe -Recurse -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending
    if (-not $candidates) { throw "SignTool.exe was not found. Install the Windows SDK on the isolated signing runner." }
    return $candidates[0].FullName
}

if (-not (Test-Path -LiteralPath $ExecutablePath -PathType Leaf)) { throw "The executable to sign does not exist." }
if ($TimestampUrl -notmatch '^https://') { throw "The RFC 3161 timestamp URL must use HTTPS." }

$signTool = Get-SignTool
$temporaryPfx = $null
$importedThumbprint = $null
try {
    if ($SigningMode -eq "certificate-store") {
        if (-not $CertificateThumbprint -or $CertificateThumbprint -notmatch '^[A-Fa-f0-9]{40}$') {
            throw "certificate-store signing requires a 40-character SHA-1 certificate thumbprint."
        }
        # Production mode: use a non-exportable key in a CSP/KSP backed by an HSM.
        # The key ACL must grant access only to the hardened signing-runner identity.
        & $signTool sign /sha1 $CertificateThumbprint /fd SHA256 /tr $TimestampUrl /td SHA256 /d $Description /du $DescriptionUrl $ExecutablePath
    }
    else {
        $PfxBase64 = $env:REPORTFLOW_PFX_BASE64
        $PfxPassword = $env:REPORTFLOW_PFX_PASSWORD
        if (-not $PfxBase64 -or -not $PfxPassword) { throw "pfx signing requires a short-lived PFX payload and password." }
        # This fallback is for private CI test environments only. Production should use certificate-store/HSM mode.
        $temporaryPfx = Join-Path $env:RUNNER_TEMP "reportflow-signing-$([guid]::NewGuid().ToString()).pfx"
        [IO.File]::WriteAllBytes($temporaryPfx, [Convert]::FromBase64String($PfxBase64))
        $securePassword = ConvertTo-SecureString $PfxPassword -AsPlainText -Force
        $certificate = Import-PfxCertificate -FilePath $temporaryPfx -CertStoreLocation Cert:\CurrentUser\My -Password $securePassword -Exportable:$false
        $importedThumbprint = $certificate.Thumbprint
        & $signTool sign /sha1 $importedThumbprint /fd SHA256 /tr $TimestampUrl /td SHA256 /d $Description /du $DescriptionUrl $ExecutablePath
    }
    if ($LASTEXITCODE -ne 0) { throw "SignTool signing failed with exit code $LASTEXITCODE." }
    & $signTool verify /pa /all /tw /v $ExecutablePath
    if ($LASTEXITCODE -ne 0) { throw "Authenticode verification failed with exit code $LASTEXITCODE." }
}
finally {
    if ($importedThumbprint) { Remove-Item -Path "Cert:\CurrentUser\My\$importedThumbprint" -Force -ErrorAction SilentlyContinue }
    if ($temporaryPfx) { Remove-Item -LiteralPath $temporaryPfx -Force -ErrorAction SilentlyContinue }
}
