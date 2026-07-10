param(
    [Parameter(Mandatory = $true)]
    [string]$ClientName,

    [Parameter(Mandatory = $true)]
    [string]$BackupRoot,

    [string]$UserProfilePath,

    [string]$OfflineWindowsPath,

    [switch]$BackupEssentialFoldersOnly,

    [switch]$CreateZip,

    [string]$DashboardUploadUrl,

    [string]$UploadApiKey,

    [switch]$SkipConsent,

    [string]$PhotoBefore,

    [string]$PhotoAfter,

    [string]$SignatureFile,

    [switch]$GeneratePDF,
    [switch]$NoPDF,

    [switch]$ExportCSV,
    [switch]$ExportJSON,
    [switch]$SilentMode
)

$ErrorActionPreference = "Continue"
$startedAt = Get-Date
$safeClientName = ($ClientName -replace '[^a-zA-Z0-9_-]', '_')
$interventionName = "Intervention_{0}_{1}" -f (Get-Date -Format "yyyy-MM-dd_HHmmss"), $safeClientName
$interventionPath = Join-Path $BackupRoot $interventionName
$eventLogPath = Join-Path $interventionPath "eventlogs"
$proofPath = Join-Path $interventionPath "preuves"
$registryHivePath = Join-Path $interventionPath "registry_hives"
$bsodDumpPath = Join-Path $interventionPath "bsod_dumps"
$actionLogPath = Join-Path $interventionPath "actions_log.txt"

function Write-ActionLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$timestamp | $Message" | Out-File -FilePath $actionLogPath -Encoding utf8 -Append
}

New-Item -ItemType Directory -Path $interventionPath -Force | Out-Null
New-Item -ItemType Directory -Path $eventLogPath -Force | Out-Null
New-Item -ItemType Directory -Path $proofPath -Force | Out-Null
New-Item -ItemType Directory -Path $registryHivePath -Force | Out-Null
New-Item -ItemType Directory -Path $bsodDumpPath -Force | Out-Null
Write-ActionLog "Intervention demarree: $interventionName"
Write-ActionLog "Client: $ClientName"
Write-ActionLog "Operateur: $env:USERNAME sur $env:COMPUTERNAME"

# Consentement client
if (-not $SkipConsent) {
    Write-Host ""
    Write-Host "=============================================" -ForegroundColor Cyan
    Write-Host "   CONSENTEMENT CLIENT OBLIGATOIRE" -ForegroundColor Yellow
    Write-Host "=============================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Avant de proceder, le client doit reconnaitre :" -ForegroundColor White
    Write-Host "  1. Aucune action destructive ne sera lancee automatiquement." -ForegroundColor Gray
    Write-Host "  2. Aucune suppression de fichier source." -ForegroundColor Gray
    Write-Host "  3. CHKDSK /F ne sera pas execute sans votre accord." -ForegroundColor Gray
    Write-Host "  4. Les donnees sont collectees en lecture seule." -ForegroundColor Gray
    Write-Host ""
    $response = Read-Host "Le client consent-il ? (O/N)"
    if ($response -ne "O" -and $response -ne "o") {
        Write-Host "Consentement refuse. Intervention annulee." -ForegroundColor Red
        Write-ActionLog "Consentement refuse par le client. Intervention annulee."
        exit 1
    }
    Write-ActionLog "Consentement client obtenu."
    Write-Host "Consentement enregistre." -ForegroundColor Green
}

function Invoke-SafeCommand {
    param(
        [Parameter(Mandatory = $true)] [scriptblock]$Script,
        [AllowNull()] [object]$Fallback = $null
    )

    try {
        & $Script
    }
    catch {
        Write-ActionLog "SafeCommand echec: $($_.Exception.Message)"
        $Fallback
    }
}

function ConvertTo-Status {
    param([string]$Level)

    switch ($Level) {
        "OK" { @{ label = "OK"; css = "ok" } }
        "WARN" { @{ label = "Attention"; css = "warn" } }
        "BAD" { @{ label = "Intervention recommandee"; css = "bad" } }
        "CRITICAL" { @{ label = "Risque critique donnees"; css = "critical" } }
        default { @{ label = "Inconnu"; css = "warn" } }
    }
}


function Get-RgFirstValue {
    param($Value, $Default = "")
    if ($null -eq $Value) { return $Default }
    if ($Value -is [array]) {
        if ($Value.Count -eq 0) { return $Default }
        return $Value[0]
    }
    return $Value
}

function Get-RgNumber {
    param($Value, [double]$Default = 0)
    try {
        $v = Get-RgFirstValue $Value $Default
        if ($null -eq $v -or "$v" -eq "") { return $Default }
        return [double]$v
    }
    catch {
        return $Default
    }
}

function Get-RgTemperatureNumber {
    param($Value, [Nullable[double]]$Default = $null)
    try {
        $v = Get-RgFirstValue $Value $Default
        if ($null -eq $v) { return $Default }
        $s = [string]$v
        if ([string]::IsNullOrWhiteSpace($s)) { return $Default }

        # Accepte: 33, 33C, 33°C, 33 Celsius, 33Â°C
        $m = [regex]::Match($s, '(-?\d+(?:[\.,]\d+)?)')
        if (-not $m.Success) { return $Default }

        return [double]($m.Groups[1].Value -replace ',', '.')
    }
    catch {
        return $Default
    }
}

function Test-RgDiskEvent {
    param($Event)

    $source = [string](Get-RgFirstValue $Event.ProviderName (Get-RgFirstValue $Event.Source ""))
    $id = [int](Get-RgNumber (Get-RgFirstValue $Event.Id 0) 0)
    $message = [string](Get-RgFirstValue $Event.Message "")

    if ($source -match '(?i)\b(Ntfs|Disk|volmgr|storahci|iaStor|stornvme|partmgr)\b') { return $true }
    if ($id -in @(7, 11, 15, 51, 52, 55, 57, 129, 153, 157, 158, 161)) { return $true }
    if ($message -match '(?i)MFT|syst[eè]me de fichiers|file system|bad block|secteur|I/O|E/S|disk|disque|volume') { return $true }

    return $false
}

function Get-RgDiskEvents {
    param($Inventory)
    $events = @()
    $events += @($Inventory.system_errors)
    $events += @($Inventory.classic_event_log)
    return @($events | Where-Object { Test-RgDiskEvent $_ })
}

function Get-RgArray {
    param($Value)
    if ($null -eq $Value) { return @() }
    return @($Value)
}

function ConvertTo-RgHtml {
    param($Value)
    if ($null -eq $Value) { return "" }
    return [System.Net.WebUtility]::HtmlEncode([string]$Value)
}

function Format-RgDateFr {
    param($Value)
    try {
        if ($Value -is [datetime]) { return $Value.ToString("dd/MM/yyyy HH:mm:ss") }
        if ($null -eq $Value -or [string]::IsNullOrWhiteSpace([string]$Value)) { return "" }
        return ([datetime]::Parse([string]$Value)).ToString("dd/MM/yyyy HH:mm:ss")
    }
    catch {
        return [string]$Value
    }
}

function Get-RgCleanBiosSerial {
    param($Value)
    $s = [string](Get-RgFirstValue $Value "")
    $invalid = @("", "Default string", "To be filled by O.E.M.", "To Be Filled By O.E.M.", "System Serial Number", "None", "Unknown", "Not Specified", "Not Applicable", "0", "00000000")
    if ($invalid -contains $s.Trim()) { return "Non renseigne par le constructeur" }
    return $s
}

function Get-RgSmartCtlCommand {
    $candidates = @(
        (Get-Command smartctl -ErrorAction SilentlyContinue).Source,
        (Join-Path $PSScriptRoot "smartctl.exe"),
        (Join-Path $PSScriptRoot "tools\smartctl.exe"),
        (Join-Path $PSScriptRoot "tools\smartmontools\bin\smartctl.exe"),
        (Join-Path $PSScriptRoot "..\tools\smartmontools\bin\smartctl.exe"),
        (Join-Path $PSScriptRoot "..\..\tools\smartmontools\bin\smartctl.exe"),
        "$env:ProgramFiles\smartmontools\bin\smartctl.exe",
        "${env:ProgramFiles(x86)}\smartmontools\bin\smartctl.exe"
    )
    foreach ($candidate in $candidates) {
        if (-not [string]::IsNullOrWhiteSpace([string]$candidate) -and (Test-Path $candidate)) {
            return (Resolve-Path $candidate).Path
        }
    }
    return $null
}

function Get-RgCrystalDiskInfoCommand {
    $names = @("DiskInfo64.exe", "DiskInfo32.exe", "DiskInfo.exe")
    foreach ($name in $names) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    $roots = @(
        $PSScriptRoot,
        (Join-Path $PSScriptRoot "tools"),
        (Join-Path $PSScriptRoot "..\tools"),
        (Join-Path $PSScriptRoot "..\..\tools"),
        "$env:ProgramFiles\CrystalDiskInfo",
        "${env:ProgramFiles(x86)}\CrystalDiskInfo"
    )
    foreach ($root in $roots) {
        if ([string]::IsNullOrWhiteSpace([string]$root) -or -not (Test-Path $root)) { continue }
        foreach ($name in $names) {
            $found = Get-ChildItem -Path $root -Filter $name -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($found) { return $found.FullName }
        }
    }
    return $null
}

function Get-RgTemperatureFromCrystalText {
    param([string[]]$Lines)
    foreach ($line in @($Lines)) {
        if ($line -match '(?i)(Temperature|Temp|Temperature actuelle|Current Temperature).*?(\d{1,3})\s*(?:C|°C|Celsius)') {
            return [int]$Matches[2]
        }
    }
    return $null
}

function Format-RgGB {
    param($Bytes)
    $n = Get-RgNumber $Bytes 0
    if ($n -le 0) { return "0 GB" }
    return ("{0} GB" -f ([math]::Round($n / 1GB, 2)))
}

function Get-RgBestString {
    param(
        [object[]]$Values,
        [string]$Default = ""
    )
    foreach ($v in $Values) {
        if ($null -ne $v -and -not [string]::IsNullOrWhiteSpace([string]$v)) {
            return [string]$v
        }
    }
    return $Default
}

function Get-RgBestInt64 {
    param(
        [object[]]$Values,
        [Int64]$Default = 0
    )
    foreach ($v in $Values) {
        try {
            if ($null -ne $v -and "$v" -ne "") {
                $n = [Int64]$v
                if ($n -gt 0) { return $n }
            }
        } catch {}
    }
    return $Default
}


function Get-RgNormalizeSmartText {
    param($Value)
    if ($null -eq $Value) { return "" }
    return ([string]$Value).ToUpperInvariant() -replace '[^A-Z0-9]', ''
}

function Get-RgSmartCtlDevices {
    $cmd = Get-RgSmartCtlCommand
    if (-not $cmd) { return @() }

    $devices = @()
    try {
        $scan = & $cmd --scan 2>$null
        foreach ($line in @($scan)) {
            $l = [string]$line
            if ($l -match '^(\/dev\/\S+)(?:\s+-d\s+([^\s#]+))?') {
                $device = $Matches[1]
                $type = ""
                if ($Matches.Count -gt 2) { $type = $Matches[2] }
                $devices += [pscustomobject]@{
                    Device = $device
                    Type = $type
                    RawLine = $l
                }
            }
        }
    } catch {}

    if ($devices.Count -gt 0) { return $devices }

    # Fallback conservateur si smartctl --scan ne retourne rien.
    return @(
        [pscustomobject]@{ Device='/dev/sda'; Type=''; RawLine='/dev/sda' },
        [pscustomobject]@{ Device='/dev/sdb'; Type=''; RawLine='/dev/sdb' },
        [pscustomobject]@{ Device='/dev/sdc'; Type=''; RawLine='/dev/sdc' },
        [pscustomobject]@{ Device='/dev/sdd'; Type=''; RawLine='/dev/sdd' },
        [pscustomobject]@{ Device='/dev/nvme0'; Type='nvme'; RawLine='/dev/nvme0 -d nvme' },
        [pscustomobject]@{ Device='/dev/nvme1'; Type='nvme'; RawLine='/dev/nvme1 -d nvme' }
    )
}


function Convert-RgSmartNumber {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { return "" }

    # v8.5: smartctl sous Windows peut insérer des séparateurs de milliers
    # Unicode/CP1252 (espace insécable, narrow no-break space, caractère de remplacement).
    # On garde uniquement les chiffres pour éviter 33 082 -> 33.
    $clean = ([string]$Value) -replace '[^0-9]', ''
    if ([string]::IsNullOrWhiteSpace($clean)) { return "" }
    return $clean
}

function Normalize-RgSmartText {
    param([string]$Value)
    if ($null -eq $Value) { return "" }
    $text = [string]$Value
    $text = $text -replace [string][char]0xFFFD, ' '
    $text = $text -replace [string][char]0x00A0, ' '
    $text = $text -replace [string][char]0x202F, ' '
    $text = $text -replace '\s+', ' '
    return $text.Trim()
}

function Get-RgSmartFieldFromText {
    param(
        [string[]]$Lines,
        [string[]]$Patterns
    )
    foreach ($line in @($Lines)) {
        $l = [string]$line
        foreach ($pattern in $Patterns) {
            if ($l -match $pattern) { return ($Matches[1]).Trim() }
        }
    }
    return ""
}


function Get-RgSmartAttention {
    param($Smart)

    $available = ($Smart.smart_available -eq $true -or -not [string]::IsNullOrWhiteSpace([string]$Smart.smart_model))
    if (-not $available) {
        return [ordered]@{
            level = "unavailable"
            label = "SMART non disponible"
            css = "warning-badge"
            severity = 0
            reasons = @("SMART inaccessible ou non expose par le controleur.")
        }
    }

    $reasons = @()
    $severity = 0

    $criticalWarning = [string]$Smart.smart_critical_warning
    $mediaErrors = [int](Get-RgNumber $Smart.smart_media_errors 0)
    $temp = Get-RgTemperatureNumber $Smart.temperature_celsius $null

    # v8.7 : les compteurs NVMe "Error Information Log Entries" sont souvent historiques
    # et ne doivent pas transformer un SMART PASSED en SMART Attention.
    # Seuls Critical Warning, erreurs media/integrite, ou temperature critique changent l'etat SMART.
    if ($criticalWarning -and $criticalWarning -notin @("0", "0x00", "00")) {
        $severity = [math]::Max($severity, 3)
        $reasons += "Critical Warning SMART=$criticalWarning"
    }
    if ($mediaErrors -gt 0) {
        $severity = [math]::Max($severity, 3)
        $reasons += "Erreurs media SMART=$mediaErrors"
    }
    if ($null -ne $temp -and $temp -ge 60) {
        $severity = [math]::Max($severity, 3)
        $reasons += "Temperature critique $temp C"
    }
    elseif ($null -ne $temp -and $temp -ge 55) {
        $severity = [math]::Max($severity, 1)
        $reasons += "Temperature elevee $temp C"
    }

    if ($severity -ge 3) {
        return [ordered]@{ level = "critical"; label = "SMART critique"; css = "critical-badge"; severity = $severity; reasons = $reasons }
    }
    elseif ($severity -ge 1) {
        return [ordered]@{ level = "attention"; label = "SMART Attention"; css = "warning-badge"; severity = $severity; reasons = $reasons }
    }

    return [ordered]@{ level = "ok"; label = "SMART OK"; css = "good-badge"; severity = 0; reasons = @() }
}


function Get-RgSmartInfoFromText {
    param(
        [string[]]$Lines,
        [string]$Device = "",
        [string]$Type = "",
        [bool]$IsUsable = $true,
        [string]$SmartError = ""
    )

    $model = Get-RgSmartFieldFromText -Lines $Lines -Patterns @(
        '^\s*Model Number:\s*(.+)$',
        '^\s*Device Model:\s*(.+)$',
        '^\s*Product:\s*(.+)$',
        '^\s*Model Family:\s*(.+)$'
    )
    $serial = Get-RgSmartFieldFromText -Lines $Lines -Patterns @(
        '^\s*Serial Number:\s*(.+)$',
        '^\s*Serial number:\s*(.+)$'
    )
    $temperature = if ($IsUsable) { Get-RgTemperatureFromText $Lines } else { $null }
    $percentageUsedRaw = Get-RgSmartFieldFromText -Lines $Lines -Patterns @('^\s*Percentage Used:\s*(\d+)\s*%')
    $powerOnHoursRaw = Get-RgSmartFieldFromText -Lines $Lines -Patterns @('^\s*Power On Hours:\s*(.+)$')
    $criticalWarning = Get-RgSmartFieldFromText -Lines $Lines -Patterns @('^\s*Critical Warning:\s*(.+)$')
    $mediaErrorsRaw = Get-RgSmartFieldFromText -Lines $Lines -Patterns @('^\s*Media and Data Integrity Errors:\s*(.+)$')
    $errorLogEntriesRaw = Get-RgSmartFieldFromText -Lines $Lines -Patterns @('^\s*Error Information Log Entries:\s*(.+)$')
    $dataWritten = Normalize-RgSmartText (Get-RgSmartFieldFromText -Lines $Lines -Patterns @('^\s*Data Units Written:\s*(.+)$'))

    $attrs = @()
    if ($IsUsable) {
        foreach ($line in @($Lines)) {
            $l = Normalize-RgSmartText ([string]$line)
            if ($l -match '^\s*\d+\s+[A-Za-z_].*') { $attrs += $l.Trim() }
            elseif ($l -match '^\s*(Critical Warning|Available Spare|Percentage Used|Data Units Written|Power On Hours|Unsafe Shutdowns|Media and Data Integrity Errors|Error Information Log Entries):') { $attrs += $l.Trim() }
        }
    }

    return [pscustomobject]@{
        Device = $Device
        Type = $Type
        Model = $model
        Serial = $serial
        ModelKey = Get-RgNormalizeSmartText $model
        SerialKey = Get-RgNormalizeSmartText $serial
        Temperature = $temperature
        PercentageUsed = Convert-RgSmartNumber $percentageUsedRaw
        PowerOnHours = Convert-RgSmartNumber $powerOnHoursRaw
        CriticalWarning = $criticalWarning
        MediaErrors = Convert-RgSmartNumber $mediaErrorsRaw
        ErrorLogEntries = Convert-RgSmartNumber $errorLogEntriesRaw
        DataWritten = $dataWritten
        Attributes = $attrs
        Lines = @($Lines)
        Assigned = $false
        SmartAvailable = [bool]$IsUsable
        SmartError = $SmartError
    }
}


function Invoke-RgSmartCtlDevice {
    param(
        [string]$SmartCtl,
        $DeviceInfo
    )

    $args = @("-a", [string]$DeviceInfo.Device)
    if (-not [string]::IsNullOrWhiteSpace([string]$DeviceInfo.Type)) {
        $args += @("-d", [string]$DeviceInfo.Type)
    }

    try {
        $output = & $SmartCtl @args 2>&1
        $text = ($output -join "`n")

        # v8.4: ne jamais considérer une sortie smartctl "Open failed" comme un disque exploitable.
        # Sinon le mapping peut attribuer les données SMART d'un autre disque à un boîtier USB.
        if ($text -match '(?i)Open failed|Permission denied|Access is denied|Error=5|Read Device Identity failed|Unable to detect device type') {
            return [pscustomobject]@{
                Lines = @($output)
                Success = $false
                Error = ($text -split "`n" | Select-Object -Last 1)
            }
        }

        if ($text -match '(?i)START OF INFORMATION SECTION|SMART/Health Information|SMART overall-health|Model Number|Device Model|Temperature') {
            return [pscustomobject]@{
                Lines = @($output)
                Success = $true
                Error = ""
            }
        }

        if (-not [string]::IsNullOrWhiteSpace($text)) {
            return [pscustomobject]@{
                Lines = @($output)
                Success = $false
                Error = "Sortie smartctl non exploitable"
            }
        }
    } catch {
        return [pscustomobject]@{
            Lines = @()
            Success = $false
            Error = $_.Exception.Message
        }
    }
    return $null
}


function Select-RgSmartRecordForDisk {
    param(
        $Disk,
        [object[]]$Records,
        [int]$Index
    )

    $diskNameKey = Get-RgNormalizeSmartText $Disk.FriendlyName
    $diskSerialKey = Get-RgNormalizeSmartText $Disk.SerialNumber
    $usable = @($Records | Where-Object { -not $_.Assigned -and $_.SmartAvailable })

    # 1) Correspondance modèle/friendly name stricte ou contenue.
    foreach ($record in $usable) {
        if (-not [string]::IsNullOrWhiteSpace($diskNameKey) -and -not [string]::IsNullOrWhiteSpace($record.ModelKey)) {
            if ($record.ModelKey.Contains($diskNameKey) -or $diskNameKey.Contains($record.ModelKey)) {
                $record.Assigned = $true
                return $record
            }
        }
    }

    # 2) Correspondance par numéro de série nettoyé.
    foreach ($record in $usable) {
        if (-not [string]::IsNullOrWhiteSpace($diskSerialKey) -and -not [string]::IsNullOrWhiteSpace($record.SerialKey)) {
            if ($diskSerialKey.Contains($record.SerialKey) -or $record.SerialKey.Contains($diskSerialKey)) {
                $record.Assigned = $true
                return $record
            }
        }
    }

    # v8.4 : pas de fallback aveugle par index.
    # Un boîtier USB/SAT qui retourne "Open failed" ne doit jamais récupérer le SMART d'un autre disque.
    return $null
}

function Get-RgTemperatureFromText {
    param([string[]]$Lines)

    foreach ($line in @($Lines)) {
        $l = [string]$line

        # ATA SMART attribute 194 Temperature_Celsius. The raw value is often the last integer.
        if ($l -match '^\s*194\s+Temperature_Celsius\b') {
            $nums = [regex]::Matches($l, '\b\d{1,3}\b') | ForEach-Object { [int]$_.Value }
            if ($nums.Count -gt 0) { return $nums[-1] }
        }

        # NVMe / smartctl common formats
        if ($l -match '(?i)Composite\s+Temperature\s*:\s*(\d{1,3})\s*(?:Celsius|C|°C)') { return [int]$Matches[1] }
        if ($l -match '(?i)Temperature\s+Sensor\s+\d+\s*:\s*(\d{1,3})\s*(?:Celsius|C|°C)') { return [int]$Matches[1] }
        if ($l -match '(?i)Current\s+Drive\s+Temperature\s*:\s*(\d{1,3})\s*(?:Celsius|C|°C)') { return [int]$Matches[1] }
        if ($l -match '(?i)Drive\s+Temperature\s*:\s*(\d{1,3})\s*(?:Celsius|C|°C)') { return [int]$Matches[1] }
        if ($l -match '(?i)Temperature_Celsius.*?(\d{1,3})(?:\s*\(|\s*$)') { return [int]$Matches[1] }
        if ($l -match '(?i)\bTemperature\b\s*:\s*(\d{1,3})\s*(?:Celsius|C|°C)') { return [int]$Matches[1] }
        if ($l -match '(?i)Temperature:\s*(\d{1,3})\s*Celsius') { return [int]$Matches[1] }
        if ($l -match '(?i)Airflow_Temperature_Cel.*?(\d{1,3})(?:\s|$)') { return [int]$Matches[1] }
        if ($l -match '(?i)Temperature_Internal.*?(\d{1,3})(?:\s|$)') { return [int]$Matches[1] }
        if ($l -match '(?i)Temperature.*?Current\s+(\d{1,3})') { return [int]$Matches[1] }
    }

    return $null
}


function Get-RgTemperatureByFriendlyName {
    param([string]$FriendlyName)
    try {
        $name = [regex]::Escape($FriendlyName)
        $diskTemps = Get-CimInstance -Namespace root\wmi -ClassName MSStorageDriver_FailurePredictData -ErrorAction SilentlyContinue
        # Beaucoup de contrôleurs NVMe ne relient pas proprement l'InstanceName au FriendlyName.
        # On retourne la première température plausible détectée uniquement si une seule valeur fiable existe.
        $temps = @()
        foreach ($item in @($diskTemps)) {
            $bytes = @($item.VendorSpecific)
            for ($i = 0; $i -lt ($bytes.Count - 12); $i += 12) {
                $attrId = [int]$bytes[$i]
                if ($attrId -in 190, 194) {
                    $candidate = [int]$bytes[$i + 5]
                    if ($candidate -gt 0 -and $candidate -lt 100) { $temps += $candidate }
                }
            }
        }
        $temps = @($temps | Select-Object -Unique)
        if ($temps.Count -eq 1) { return [int]$temps[0] }
    } catch {}
    return $null
}

function Get-RgMachineInfo {
    $cs = Invoke-SafeCommand -Script { Get-CimInstance Win32_ComputerSystem } -Fallback $null
    $os = Invoke-SafeCommand -Script { Get-CimInstance Win32_OperatingSystem } -Fallback $null
    $baseboard = Invoke-SafeCommand -Script { Get-CimInstance Win32_BaseBoard } -Fallback $null
    $computerInfo = Invoke-SafeCommand -Script { Get-ComputerInfo } -Fallback $null

    $name = Get-RgBestString @($cs.Name, $computerInfo.CsName, $env:COMPUTERNAME) $env:COMPUTERNAME
    $manufacturer = Get-RgBestString @($cs.Manufacturer, $computerInfo.CsManufacturer, $baseboard.Manufacturer) ""
    $model = Get-RgBestString @($cs.Model, $computerInfo.CsModel, $baseboard.Product) ""
    $windowsName = Get-RgBestString @($os.Caption, $computerInfo.WindowsProductName) ""
    $windowsVersion = Get-RgBestString @($os.Version, $computerInfo.WindowsVersion, $computerInfo.OsVersion) ""
    $ramBytes = Get-RgBestInt64 @($cs.TotalPhysicalMemory, $computerInfo.CsTotalPhysicalMemory, $os.TotalVisibleMemorySize * 1KB) 0

    return [ordered]@{
        CsName = $name
        CsManufacturer = $manufacturer
        CsModel = $model
        WindowsProductName = $windowsName
        WindowsVersion = $windowsVersion
        CsTotalPhysicalMemory = $ramBytes
        TotalPhysicalMemory = $ramBytes
    }
}

function Get-RgHealthDetails {
    param($Health)
    if ($null -eq $Health -or $null -eq $Health.details) { return @() }

    $details = $Health.details
    if ($details -is [System.Collections.IDictionary]) {
        return @($details.GetEnumerator() | ForEach-Object { $_.Value })
    }

    return @($details.PSObject.Properties | Where-Object { $_.MemberType -eq "NoteProperty" } | ForEach-Object { $_.Value })
}

function Test-RescueGridReportData {
    param($Inventory, $BlackBox)

    $issues = @()

    if ($null -eq $Inventory) { $issues += "Inventory absent." }
    if ($null -eq $BlackBox) { $issues += "BlackBox absent." }

    if ($Inventory) {
        if ($null -eq $Inventory.machine) { $issues += "Informations machine absentes." }
        if ($null -eq $Inventory.health) { $issues += "Score sante absent." }
        if ($null -eq $Inventory.health.details) { $issues += "Sous-scores absents." }
        if ($null -eq $Inventory.disks -or @(Get-RgArray $Inventory.disks).Count -eq 0) { $issues += "Aucun disque detecte." }

        foreach ($d in (Get-RgHealthDetails $Inventory.health)) {
            $score = Get-RgNumber $d.score 0
            $max = Get-RgNumber $d.max 0
            if ($max -le 0) { $issues += "Sous-score invalide: max=0 pour '$($d.label)'." }
            if ($score -lt 0) { $issues += "Sous-score invalide: score negatif pour '$($d.label)'." }
        }
    }

    if ($BlackBox) {
        if ([string]::IsNullOrWhiteSpace([string]$BlackBox.intervention_id)) { $issues += "BlackBox: intervention_id vide." }
        if ([string]::IsNullOrWhiteSpace([string]$BlackBox.client_name)) { $issues += "BlackBox: client_name vide." }
    }

    return $issues
}


function Get-SmartSnapshot {
    $smart = @()
    $smartctlStatus = Get-RgSmartCtlCommand
    $crystalStatus = Get-RgCrystalDiskInfoCommand
    if ($smartctlStatus) { Write-ActionLog "smartctl detecte: $smartctlStatus" } else { Write-ActionLog "smartctl absent - temperatures SMART avancees limitees" }
    if ($crystalStatus) { Write-ActionLog "CrystalDiskInfo detecte: $crystalStatus" } else { Write-ActionLog "CrystalDiskInfo absent - fallback Windows uniquement" }

    $physicalDisks = Invoke-SafeCommand -Script { Get-PhysicalDisk } -Fallback @()

    # Lecture smartctl une seule fois par périphérique détecté.
    # v8.3 : respecte le mapping /dev/sdX + -d nvme/sat retourné par smartctl --scan.
    $smartRecords = @()
    if ($smartctlStatus) {
        $devices = @(Get-RgSmartCtlDevices)
        Write-ActionLog "smartctl devices detectes: $($devices.Count)"
        foreach ($dev in $devices) {
            $result = Invoke-RgSmartCtlDevice -SmartCtl $smartctlStatus -DeviceInfo $dev
            if ($result -and $result.Success) {
                $info = Get-RgSmartInfoFromText -Lines $result.Lines -Device $dev.Device -Type $dev.Type -IsUsable $true
                $smartRecords += $info
                Write-ActionLog "smartctl OK: $($dev.Device) $($dev.Type) model=$($info.Model) temp=$($info.Temperature)"
            }
            elseif ($result) {
                $info = Get-RgSmartInfoFromText -Lines $result.Lines -Device $dev.Device -Type $dev.Type -IsUsable $false -SmartError $result.Error
                $smartRecords += $info
                Write-ActionLog "smartctl non exploitable: $($dev.Device) $($dev.Type) - $($result.Error)"
            }
            else {
                Write-ActionLog "smartctl aucune donnee exploitable: $($dev.RawLine)"
            }
        }
    }

    # Export CrystalDiskInfo global si disponible. Les versions GUI ne supportent pas toutes /OutputFile.
    $crystalGlobalFile = $null
    if ($crystalStatus) {
        try {
            $crystalGlobalFile = Join-Path $interventionPath "crystal_diskinfo.txt"
            $crystalOutput = & $crystalStatus /CopyExit 2>&1
            if ($crystalOutput) {
                $crystalOutput | Out-File -FilePath $crystalGlobalFile -Encoding utf8
                Write-ActionLog "CrystalDiskInfo sortie capturee"
            }
            elseif (Test-Path $crystalGlobalFile) {
                Write-ActionLog "CrystalDiskInfo fichier exporte"
            }
            else {
                Write-ActionLog "CrystalDiskInfo detecte mais aucune sortie CLI exploitable"
                $crystalGlobalFile = $null
            }
        }
        catch {
            Write-ActionLog "CrystalDiskInfo detecte mais execution CLI non exploitable"
            $crystalGlobalFile = $null
        }
    }

    $diskIndex = 0
    foreach ($disk in @($physicalDisks)) {
        $entry = [ordered]@{
            friendly_name = $disk.FriendlyName
            media_type = $disk.MediaType
            health_status = [string]$disk.HealthStatus
            operational_status = [string]($disk.OperationalStatus -join ", ")
            size_bytes = $disk.Size
            temperature_celsius = if ($disk.Temperature) { [int]$disk.Temperature } else { $null }
            smart_attributes = @()
            smart_device = $null
            smart_model = $null
            smart_serial = $null
            smart_percentage_used = $null
            smart_power_on_hours = $null
            smart_data_units_written = $null
            smart_critical_warning = $null
            smart_media_errors = $null
            smart_error_log_entries = $null
            smart_available = $false
            smart_error = $null
            crystal_diskinfo = $crystalGlobalFile
        }

        if (-not $entry.temperature_celsius) {
            try {
                $reliability = $disk | Get-StorageReliabilityCounter -ErrorAction Stop
                if ($reliability -and $reliability.Temperature) {
                    $entry.temperature_celsius = [int]$reliability.Temperature
                }
            }
            catch {
                Write-ActionLog "Temperature Windows indisponible pour $($entry.friendly_name)"
            }
        }

        if (-not $entry.temperature_celsius) {
            $wmiTemp = Get-RgTemperatureByFriendlyName -FriendlyName $entry.friendly_name
            if ($wmiTemp) { $entry.temperature_celsius = [int]$wmiTemp }
        }

        $record = Select-RgSmartRecordForDisk -Disk $disk -Records $smartRecords -Index $diskIndex
        if ($record) {
            if ($null -ne $record.Temperature) { $entry.temperature_celsius = [int]$record.Temperature }
            $entry.smart_attributes = @($record.Attributes)
            $entry.smart_device = $record.Device
            $entry.smart_model = $record.Model
            $entry.smart_serial = $record.Serial
            $entry.smart_percentage_used = $record.PercentageUsed
            $entry.smart_power_on_hours = $record.PowerOnHours
            $entry.smart_data_units_written = $record.DataWritten
            $entry.smart_critical_warning = $record.CriticalWarning
            $entry.smart_media_errors = $record.MediaErrors
            $entry.smart_error_log_entries = $record.ErrorLogEntries
            $entry.smart_available = [bool]$record.SmartAvailable
            $entry.smart_error = $record.SmartError

            $outFile = Join-Path $interventionPath ("smart_disk{0}.txt" -f $diskIndex)
            @($record.Lines) | Out-File -FilePath $outFile -Encoding utf8
            Write-ActionLog "SMART mappe: $($entry.friendly_name) -> $($record.Device) $($record.Type) ($($record.Model))"
        }
        else {
            Write-ActionLog "Aucun mapping smartctl pour $($entry.friendly_name)"
        }

        $smart += $entry
        $diskIndex++
    }

    # Export smart.txt
    $smartTextPath = Join-Path $interventionPath "smart.txt"
    $smart | ForEach-Object {
        "Disque: $($_.friendly_name)"
        "  Type: $($_.media_type)"
        "  Sante: $($_.health_status)"
        "  Statut: $($_.operational_status)"
        "  Taille: $($_.size_bytes) octets"
        if ($_.smart_device) { "  smartctl device: $($_.smart_device)" }
        if ($_.smart_model) { "  Modele SMART: $($_.smart_model)" }
        if ($_.smart_serial) { "  Serie SMART: $($_.smart_serial)" }
        if ($_.temperature_celsius) { "  Temperature: $($_.temperature_celsius) C" } else { "  Temperature: Non disponible (installer smartmontools/CrystalDiskInfo)" }
        if ($_.smart_percentage_used) { "  Usure NVMe: $($_.smart_percentage_used)%" }
        if ($_.smart_power_on_hours) { "  Heures fonctionnement: $($_.smart_power_on_hours)" }
        if ($_.smart_data_units_written) { "  Donnees ecrites: $($_.smart_data_units_written)" }
        if ($_.smart_media_errors) { "  Erreurs media: $($_.smart_media_errors)" }
        if ($_.smart_error_log_entries) { "  Entrees journal erreurs: $($_.smart_error_log_entries)" }
        if ($_.smart_attributes.Count -gt 0) { "  Attributs SMART: $($_.smart_attributes.Count)" } else { "  Attributs SMART: Non disponibles" }
        ""
    } | Out-File -FilePath $smartTextPath -Encoding utf8

    Add-Content -Path $smartTextPath -Encoding utf8 -Value "Outils detectes:"
    Add-Content -Path $smartTextPath -Encoding utf8 -Value ("  smartctl: " + $(if ($smartctlStatus) { $smartctlStatus } else { "absent" }))
    Add-Content -Path $smartTextPath -Encoding utf8 -Value ("  CrystalDiskInfo: " + $(if ($crystalStatus) { $crystalStatus } else { "absent" }))
    Add-Content -Path $smartTextPath -Encoding utf8 -Value ""
    if (-not $smartctlStatus -and -not $crystalStatus) {
        Add-Content -Path $smartTextPath -Encoding utf8 -Value "Conseil: lancer .\start_tools_install.bat pour installer les outils SMART."
    }

    Write-ActionLog "Smart avance realise: $(@($smart).Count) disques"
    return $smart
}

function Get-BiosInfo {
    return Invoke-SafeCommand -Script {
        Get-CimInstance Win32_BIOS | Select-Object Manufacturer, Name, Version, SerialNumber, SMBIOSBIOSVersion, ReleaseDate
    } -Fallback @()
}

function Get-ProcessorInfo {
    return Invoke-SafeCommand -Script {
        Get-CimInstance Win32_Processor | Select-Object Name, Manufacturer, MaxClockSpeed, NumberOfCores, NumberOfLogicalProcessors, SocketDesignation
    } -Fallback @()
}

function Get-VideoControllerInfo {
    return Invoke-SafeCommand -Script {
        Get-CimInstance Win32_VideoController | Select-Object Name, AdapterRAM, DriverVersion, VideoModeDescription, VideoProcessor
    } -Fallback @()
}

function Get-AdvancedHardwareInfo {
    # Détection matérielle avancée (v5.0)
    $hw = [ordered]@{}
    
    # Batterie
    $hw.battery = Invoke-SafeCommand -Script {
        Get-CimInstance Win32_Battery | Select-Object EstimatedChargeRemaining, BatteryStatus, BatteryVoltage
    } -Fallback @()
    
    # Carte mère
    $hw.motherboard = Invoke-SafeCommand -Script {
        Get-CimInstance Win32_BaseBoard | Select-Object Manufacturer, Product, Version, SerialNumber
    } -Fallback @()
    
    # Slots RAM
    $hw.memory_slots = Invoke-SafeCommand -Script {
        Get-CimInstance Win32_PhysicalMemory | Select-Object Manufacturer, Capacity, Speed, PartNumber, DeviceLocator
    } -Fallback @()
    
    # Réseau
    $hw.network = Invoke-SafeCommand -Script {
        Get-CimInstance Win32_NetworkAdapter | Where-Object { $_.PhysicalAdapter } | Select-Object Name, MACAddress, Speed, AdapterType
    } -Fallback @()
    
    return $hw
}

function Get-ClassicEventLog {
    return Invoke-SafeCommand -Script {
        Get-EventLog -LogName System -EntryType Error, Warning -Newest 50 | Select-Object TimeGenerated, Source, EntryType, Message
    } -Fallback @()
}

function Get-HealthScore {
    param($Inventory)

    $systemErrors = @($Inventory.system_errors)
    $classicErrors = @($Inventory.classic_event_log)
    $allErrors = @($systemErrors + $classicErrors)
    $diskEvents = @(Get-RgDiskEvents -Inventory $Inventory)

    # --- Sous-score Disque (sur 25) ---
    $diskScore = 25
    $smartIssues = 0

    $smartContextPenalty = 0
    foreach ($disk in @($Inventory.smart)) {
        if ($disk.health_status -and "$($disk.health_status)" -notin @("Healthy", "OK", "")) { $smartIssues++ }

        $temp = Get-RgTemperatureNumber $disk.temperature_celsius $null
        if ($null -ne $temp -and $temp -gt 55) { $diskScore -= 5 }
        elseif ($null -ne $temp -and $temp -gt 50) { $diskScore -= 2 }

        # v8.7 : les historiques NVMe (Error Log Entries, heures, usure raisonnable)
        # sont informatifs. Seul SMART critique/temperature elevee penalise le score.
        $smartStatus = Get-RgSmartAttention $disk
        if ($smartStatus.level -eq "attention") {
            $smartContextPenalty += [math]::Min(2, [int]$smartStatus.severity)
        }
        elseif ($smartStatus.level -eq "critical") {
            $smartContextPenalty += 10
        }
    }

    if ($smartIssues -gt 0) { $diskScore -= $smartIssues * 8 }
    if ($smartContextPenalty -gt 0) { $diskScore -= [math]::Min(10, $smartContextPenalty) }

    # v8.8 : séparation stricte SMART matériel / NTFS filesystem.
    # Un NTFS ID55 est une anomalie de système de fichiers, pas une panne SMART.
    # Il ne dégrade plus le score disque matériel si SMART est sain.
    $filesystemEvents = @($diskEvents | Where-Object {
        $src = [string](Get-RgFirstValue $_.ProviderName (Get-RgFirstValue $_.Source ""))
        $id = [int](Get-RgNumber (Get-RgFirstValue $_.Id 0) 0)
        $src -match '(?i)^Ntfs$' -or $id -eq 55
    })
    $severeDiskEvents = @($diskEvents | Where-Object {
        $src = [string](Get-RgFirstValue $_.ProviderName (Get-RgFirstValue $_.Source ""))
        $id = [int](Get-RgNumber (Get-RgFirstValue $_.Id 0) 0)
        $src -match '(?i)Disk|storahci|stornvme|iaStor|WHEA' -or $id -in @(7, 11, 51, 129, 153, 157, 161)
    })

    if ($severeDiskEvents.Count -gt 0) {
        $diskScore -= [math]::Min(8, 4 + ($severeDiskEvents.Count * 2))
    }

    if ($diskScore -lt 0) { $diskScore = 0 }

    # Niveau disque = état matériel SMART/contrôleur uniquement.
    # Le NTFS est exposé séparément dans filesystem_status et dans la recommandation.
    $diskLevel = if ($diskScore -ge 20) { "OK" } elseif ($diskScore -ge 10) { "WARN" } else { "BAD" }
    $filesystemLevel = if ($filesystemEvents.Count -gt 0) { "WARN" } else { "OK" }

    # --- Sous-score RAM (sur 10) ---
    $ramScore = 10
    $totalRAM = Get-RgNumber (Get-RgFirstValue $Inventory.machine.CsTotalPhysicalMemory $Inventory.machine.TotalPhysicalMemory) 0
    if ($totalRAM -and $totalRAM -lt 4GB) { $ramScore -= 5 }
    elseif ($totalRAM -and $totalRAM -lt 8GB) { $ramScore -= 2 }
    $ramLevel = if ($ramScore -ge 8) { "OK" } elseif ($ramScore -ge 5) { "WARN" } else { "BAD" }

    # --- Sous-score Windows / systeme de fichiers (sur 30) ---
    # v8.9 : NTFS ID55 est un probleme logique de systeme de fichiers.
    # Il ne doit pas degrader le score disque SMART/materiel.
    $windowsScore = 30
    $errorCount = $allErrors.Count

    $ntfsEventsForWindows = @($allErrors | Where-Object {
        $source = [string](Get-RgFirstValue $_.ProviderName (Get-RgFirstValue $_.Source ""))
        $id = [int](Get-RgNumber (Get-RgFirstValue $_.Id 0) 0)
        $source -match '(?i)^Ntfs$' -or $id -eq 55
    })

    # Bruit Windows courant : DCOM, Store, GamingServices, WindowsUpdate.
    # On limite volontairement l'impact pour garder un score coherent avec un PC fonctionnel.
    $minorPenalty = 0
    if ($errorCount -gt 50) { $minorPenalty = 2 }
    elseif ($errorCount -gt 20) { $minorPenalty = 1 }

    $criticalWindowsEvents = @($allErrors | Where-Object {
        $source = [string](Get-RgFirstValue $_.ProviderName (Get-RgFirstValue $_.Source ""))
        $id = [int](Get-RgNumber (Get-RgFirstValue $_.Id 0) 0)
        $msg = [string](Get-RgFirstValue $_.Message "")

        # Exclusions: NTFS ID55 traite separement, erreurs applicatives courantes non critiques.
        if ($source -match '(?i)^Ntfs$' -and $id -eq 55) { return $false }
        if ($source -match '(?i)DistributedCOM|DeviceAssociationService|WindowsUpdateClient|GamingServices') { return $false }

        $source -match '(?i)WHEA|Kernel-Power|BugCheck|BitLocker|Boot' -or
        $id -in @(41, 1001, 1008, 6008) -or
        $msg -match '(?i)BSOD|bugcheck|boot failure|echec demarrage|échec démarrage'
    })

    # NTFS ID55 = -1 a -2 max selon occurrences, pas une panne materielle.
    $filesystemPenalty = 0
    if ($ntfsEventsForWindows.Count -gt 0) { $filesystemPenalty = [math]::Min(2, $ntfsEventsForWindows.Count) }

    $criticalPenalty = [math]::Min(3, @($criticalWindowsEvents).Count)
    $windowsScore = 30 - $minorPenalty - $filesystemPenalty - $criticalPenalty

    if (($Inventory.bitlocker_text -join "`n") -match "(?i)Locked|Verrouillé") { $windowsScore -= 3 }
    if ($windowsScore -lt 0) { $windowsScore = 0 }
    if ($windowsScore -gt 30) { $windowsScore = 30 }

    $windowsLevel = if ($windowsScore -ge 29 -and $errorCount -le 10) { "OK" } elseif ($windowsScore -ge 20) { "WARN" } else { "BAD" }

    # --- Sous-score Drivers (sur 20) ---
    $driverScore = 20
    $videoControllers = @($Inventory.video_controllers)
    foreach ($video in $videoControllers) {
        if (-not $video.DriverVersion) { $driverScore -= 5 }
    }

    $driverErrors = $systemErrors | Where-Object { $_.ProviderName -match "Driver|Display|NVIDIA|AMD|Intel" -or $_.Id -in @(4101, 4103, 219) }
    $driverErrorsCount = @($driverErrors).Count
    $driverScore -= [math]::Min(15, $driverErrorsCount * 3)
    if ($driverScore -lt 0) { $driverScore = 0 }
    $driverLevel = if ($driverScore -ge 16) { "OK" } elseif ($driverScore -ge 10) { "WARN" } else { "BAD" }

    # --- Sous-score Températures (sur 15) ---
    $tempScore = 15
    $maxTemp = 0
    foreach ($disk in @($Inventory.smart)) {
        $temp = Get-RgTemperatureNumber $disk.temperature_celsius $null
        if ($null -ne $temp -and $temp -gt $maxTemp) { $maxTemp = $temp }
    }

    if ($maxTemp -gt 60) { $tempScore -= 10 }
    elseif ($maxTemp -gt 50) { $tempScore -= 5 }
    elseif ($maxTemp -gt 45) { $tempScore -= 2 }

    if ($tempScore -lt 0) { $tempScore = 0 }
    $tempLevel = if ($tempScore -ge 12) { "OK" } elseif ($tempScore -ge 7) { "WARN" } else { "BAD" }

    # --- Score global ---
    $globalScore = $diskScore + $ramScore + $windowsScore + $driverScore + $tempScore
    if ($globalScore -gt 100) { $globalScore = 100 }

    $risk = "Faible"
    # v8.9 : le risque perte de donnees est pilote par SMART/erreurs media/score global.
    # Un NTFS ID55 isole reste une verification filesystem, pas une alerte materielle.
    if ($globalScore -lt 80) { $risk = "Moyen" }
    if ($globalScore -lt 55) { $risk = "Eleve" }
    if ($globalScore -lt 35) { $risk = "Critique" }

    return [ordered]@{
        global_score = [int]$globalScore
        details = [ordered]@{
            disk = [ordered]@{ score = [int]$diskScore; max = 25; label = "Disque"; level = (ConvertTo-Status $diskLevel) }
            ram = [ordered]@{ score = [int]$ramScore; max = 10; label = "RAM/Memoire"; level = (ConvertTo-Status $ramLevel) }
            windows = [ordered]@{ score = [int]$windowsScore; max = 30; label = "Windows/Systeme"; level = (ConvertTo-Status $windowsLevel) }
            drivers = [ordered]@{ score = [int]$driverScore; max = 20; label = "Pilotes/Drivers"; level = (ConvertTo-Status $driverLevel) }
            temperatures = [ordered]@{ score = [int]$tempScore; max = 15; label = "Temperatures"; level = (ConvertTo-Status $tempLevel) }
        }
        data_loss_risk = $risk
        scoring_notes = [ordered]@{
            total_events = $errorCount
            critical_windows_events = @($criticalWindowsEvents).Count
            disk_events = $diskEvents.Count
            filesystem_events = @($filesystemEvents).Count
            severe_disk_events = @($severeDiskEvents).Count
            filesystem_status = (ConvertTo-Status $filesystemLevel)
            max_temperature_celsius = $maxTemp
        }
        disk = ConvertTo-Status $diskLevel
        ram = ConvertTo-Status $ramLevel
        windows = ConvertTo-Status $windowsLevel
        drivers = ConvertTo-Status $driverLevel
        temperatures = ConvertTo-Status $tempLevel
        boot = ConvertTo-Status "OK"
        bitlocker = if (($Inventory.bitlocker_text -join "`n") -match "(?i)Locked|Verrouillé") { ConvertTo-Status "WARN" } else { ConvertTo-Status "OK" }
    }
}

function Get-DiskRiskAssessment {
    param($Inventory)

    $riskLevel = "healthy"
    $recommendation = "Copie fichiers standard autorisee."
    $reasons = @()
    $recommendedModes = @("Sauvegarde", "Rapport")

    foreach ($disk in @($Inventory.disks)) {
        $healthStatus = [string]$disk.HealthStatus
        $operationalStatus = [string]($disk.OperationalStatus -join ", ")

        if ($healthStatus -and "$healthStatus" -notin @("Healthy", "", "0")) {
            $riskLevel = "suspect"
            $reasons += "Disque $($disk.Number): HealthStatus=$healthStatus"
        }

        if ($operationalStatus -match "Lost Communication|No Media|Pred Fail|Unhealthy|Unknown") {
            $riskLevel = "critical"
            $reasons += "Disque $($disk.Number): OperationalStatus=$operationalStatus"
        }
    }

    # Analyse SMART avancee avec seuils
    foreach ($smart in @($Inventory.smart)) {
        if ($smart.health_status -and "$($smart.health_status)" -notin @("Healthy", "OK", "")) {
            if ($riskLevel -ne "critical") { $riskLevel = "suspect" }
            $reasons += "SMART $($smart.friendly_name): $($smart.health_status)"
        }

        # Seuil temperature
        if ($smart.temperature_celsius -and $smart.temperature_celsius -gt 60) {
            $riskLevel = "critical"
            $reasons += "Temperature $($smart.temperature_celsius)°C sur $($smart.friendly_name) > 60°C (critique)"
        }
        elseif ($smart.temperature_celsius -and $smart.temperature_celsius -gt 50) {
            if ($riskLevel -ne "critical") { $riskLevel = "suspect" }
            $reasons += "Temperature $($smart.temperature_celsius)°C sur $($smart.friendly_name) > 50°C (surveillance)"
        }

        # Analyse attributs SMART pour reallocated sectors
        foreach ($attr in $smart.smart_attributes) {
            if ($attr -match "^\d+\s+Reallocated_Sector") {
                $parts = $attr -split '\s+'
                if ($parts.Count -ge 10 -and [int]$parts[9] -gt 10) {
                    $riskLevel = "critical"
                    $reasons += "Reallocated sectors > 10 ($($parts[9])) sur $($smart.friendly_name)"
                }
                elseif ($parts.Count -ge 10 -and [int]$parts[9] -gt 0) {
                    if ($riskLevel -ne "critical") { $riskLevel = "suspect" }
                    $reasons += "Reallocated sectors > 0 ($($parts[9])) sur $($smart.friendly_name)"
                }
            }
            if ($attr -match "^\d+\s+Current_Pending_Sector") {
                $parts = $attr -split '\s+'
                if ($parts.Count -ge 10 -and [int]$parts[9] -gt 0) {
                    $riskLevel = "critical"
                    $reasons += "Current pending sectors > 0 ($($parts[9])) sur $($smart.friendly_name)"
                }
            }
            if ($attr -match "^\d+\s+Uncorrectable_Sector") {
                $parts = $attr -split '\s+'
                if ($parts.Count -ge 10 -and [int]$parts[9] -gt 0) {
                    $riskLevel = "critical"
                    $reasons += "Uncorrectable sectors > 0 ($($parts[9])) sur $($smart.friendly_name)"
                }
            }
        }
    }

    # v8.8 : séparation SMART matériel / NTFS filesystem.
    # NTFS ID55 = anomalie logique filesystem ; le niveau disque matériel reste OK si SMART est sain.
    $diskEvents = @(Get-RgDiskEvents -Inventory $Inventory)
    $filesystemEvents = @($diskEvents | Where-Object {
        $src = [string](Get-RgFirstValue $_.ProviderName (Get-RgFirstValue $_.Source ""))
        $id = [int](Get-RgNumber (Get-RgFirstValue $_.Id 0) 0)
        $src -match '(?i)^Ntfs$' -or $id -eq 55
    })
    $severeDiskEvents = @($diskEvents | Where-Object {
        $src = [string](Get-RgFirstValue $_.ProviderName (Get-RgFirstValue $_.Source ""))
        $id = [int](Get-RgNumber (Get-RgFirstValue $_.Id 0) 0)
        $src -match '(?i)Disk|storahci|stornvme|iaStor|WHEA' -or $id -in @(7, 11, 51, 129, 153, 157, 161)
    })

    if ($severeDiskEvents.Count -gt 0 -and $riskLevel -eq "healthy") {
        $riskLevel = "suspect"
    }
    elseif ($riskLevel -eq "attention" -and $severeDiskEvents.Count -gt 0) {
        $riskLevel = "suspect"
    }

    if ($diskEvents.Count -gt 0) {
        $sample = $diskEvents | Select-Object -First 3 | ForEach-Object {
            $src = Get-RgFirstValue $_.ProviderName (Get-RgFirstValue $_.Source "")
            $id = Get-RgFirstValue $_.Id ""
            "$src ID $id"
        }
        if ($filesystemEvents.Count -gt 0) {
            $reasons += "Anomalie filesystem detectee: $($sample -join ', ')"
        }
        elseif ($severeDiskEvents.Count -gt 0) {
            $reasons += "Evenements disque materiel detectes: $($sample -join ', ')"
        }
    }

    # Decisions par niveau de risque
    if ($riskLevel -eq "healthy") {
        if ($filesystemEvents.Count -gt 0) {
            $recommendation = "SMART materiel OK. Volume NTFS ayant signale une anomalie ID55. Sauvegarde recommandee avant CHKDSK /F ou toute reparation filesystem."
            $recommendedModes = @("Sauvegarde", "Controle filesystem", "Rapport")
        }
        else {
            $recommendation = "Copie fichiers standard autorisee. Aucune action urgente requise."
            $recommendedModes = @("Sauvegarde", "Rapport", "Diagnostic")
        }
    }
    elseif ($riskLevel -eq "attention") {
        $recommendation = "Sauvegarde conseillee. Verifier le systeme de fichiers avant toute reparation destructive. CHKDSK /F seulement apres sauvegarde ou image."
        $recommendedModes = @("Sauvegarde", "Controle filesystem", "Rapport")
    }
    elseif ($riskLevel -eq "suspect") {
        $recommendation = "Image disque recommandee avant reparation. Ne pas lancer CHKDSK /F. Prioriser sauvegarde des donnees."
        $recommendedModes = @("Sauvegarde prioritaire", "Image disque", "Rapport")
    }
    elseif ($riskLevel -eq "critical") {
        $recommendation = "ARRETER les reparations. Priorite ddrescue/image disque avant toute extraction. Risque de perte imminente."
        $recommendedModes = @("ddrescue", "Image disque", "Rapport seulement")
    }

    if (-not $reasons.Count) { $reasons = @("Aucun indicateur critique remonte par Windows.") }

    Write-ActionLog "Risque disque evalue: $riskLevel ($($reasons.Count) raison(s)) - Modes recommandes: $($recommendedModes -join ', ')"

    return [ordered]@{
        level = $riskLevel
        recommendation = $recommendation
        reasons = $reasons
        recommended_modes = $recommendedModes
        thresholds_used = @(
            "Temperature > 60°C = critique, > 50°C = suspect",
            "Reallocated sectors > 10 = critique, > 0 = suspect",
            "Current pending sectors > 0 = critique",
            "Uncorrectable sectors > 0 = critique",
            "NTFS ID55 isole = alerte filesystem separee, pas panne disque materiel"
        )
    }
}

function Get-BackupSources {
    param([string]$ProfilePath, [switch]$EssentialOnly)

    if (-not $EssentialOnly) {
        return @([ordered]@{ name = "profile"; path = $ProfilePath })
    }

    $folderNames = @("Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music", "Favorites")
    $sources = @()
    foreach ($folderName in $folderNames) {
        $path = Join-Path $ProfilePath $folderName
        if (Test-Path -LiteralPath $path) {
            $folderItem = Get-Item -LiteralPath $path -ErrorAction SilentlyContinue
            if (-not $folderItem.PSIsContainer -or ($folderItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
                continue  # Skip symlinks/reparse points
            }
            $sources += [ordered]@{ name = $folderName; path = $path }
        }
    }

    return $sources
}

function Get-FolderStats {
    param([string]$Path)

    try {
        $files = @(Get-ChildItem -LiteralPath $Path -File -Recurse -Force -ErrorAction SilentlyContinue)
        $totalBytes = ($files | Measure-Object -Property Length -Sum).Sum
        if ($null -eq $totalBytes) { $totalBytes = 0 }
    }
    catch {
        $files = @()
        $totalBytes = 0
    }

    return [ordered]@{
        file_count = $files.Count
        total_bytes = [int64]$totalBytes
    }
}

function Copy-IfExists {
    param(
        [Parameter(Mandatory = $true)] [string]$Source,
        [Parameter(Mandatory = $true)] [string]$Destination
    )

    if (Test-Path -LiteralPath $Source) {
        try {
            Copy-Item -LiteralPath $Source -Destination $Destination -Force -ErrorAction SilentlyContinue
            return $true
        }
        catch {
            return $false
        }
    }

    return $false
}

function Get-OfflineWindowsAnalysis {
    param([string]$WindowsPath)

    $analysis = [ordered]@{
        enabled = $false
        windows_path = $WindowsPath
        valid_windows_directory = $false
        registry_hives = @()
        event_logs = @()
        bsod_dumps = @()
        user_profiles = @()
        efi_partitions = @()
        bitlocker = @()
        findings = @()
    }

    if (-not $WindowsPath) {
        $analysis.findings += "Aucun chemin Windows hors ligne fourni."
        return $analysis
    }

    $analysis.enabled = $true
    $system32 = Join-Path $WindowsPath "System32"
    $configPath = Join-Path $system32 "Config"
    $logsPath = Join-Path $system32 "winevt\Logs"

    if (-not (Test-Path -LiteralPath $system32)) {
        $analysis.findings += "Chemin invalide: dossier System32 introuvable."
        Write-ActionLog "Offline: System32 introuvable dans $WindowsPath"
        return $analysis
    }

    $analysis.valid_windows_directory = $true
    Write-ActionLog "Analyse Windows offline: $WindowsPath"

    foreach ($hive in @("SYSTEM", "SOFTWARE", "SAM", "SECURITY", "DEFAULT")) {
        $source = Join-Path $configPath $hive
        $destination = Join-Path $registryHivePath $hive
        if (Copy-IfExists -Source $source -Destination $destination) {
            $analysis.registry_hives += [ordered]@{ name = $hive; copied_to = $destination }
            Write-ActionLog "Offline: ruche $hive copiee"
        }
    }

    if (Test-Path -LiteralPath $logsPath) {
        Get-ChildItem -LiteralPath $logsPath -Filter "*.evtx" -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -in @("System.evtx", "Application.evtx", "Setup.evtx", "Microsoft-Windows-WindowsUpdateClient%4Operational.evtx") } |
            ForEach-Object {
                $destination = Join-Path $eventLogPath $_.Name
                Copy-Item -LiteralPath $_.FullName -Destination $destination -Force -ErrorAction SilentlyContinue
                $analysis.event_logs += [ordered]@{ name = $_.Name; copied_to = $destination; size_bytes = $_.Length }
                Write-ActionLog "Offline: journal $($_.Name) copie"
            }
    }

    $dumpSources = @(
        (Join-Path $WindowsPath "MEMORY.DMP"),
        (Join-Path $WindowsPath "Minidump")
    )
    foreach ($dumpSource in $dumpSources) {
        if (Test-Path -LiteralPath $dumpSource) {
            $item = Get-Item -LiteralPath $dumpSource -ErrorAction SilentlyContinue
            if ($item.PSIsContainer) {
                Get-ChildItem -LiteralPath $dumpSource -Filter "*.dmp" -File -ErrorAction SilentlyContinue | ForEach-Object {
                    $destination = Join-Path $bsodDumpPath $_.Name
                    Copy-Item -LiteralPath $_.FullName -Destination $destination -Force -ErrorAction SilentlyContinue
                    $analysis.bsod_dumps += [ordered]@{ name = $_.Name; copied_to = $destination; size_bytes = $_.Length }
                }
            }
            else {
                $destination = Join-Path $bsodDumpPath $item.Name
                Copy-Item -LiteralPath $item.FullName -Destination $destination -Force -ErrorAction SilentlyContinue
                $analysis.bsod_dumps += [ordered]@{ name = $item.Name; copied_to = $destination; size_bytes = $item.Length }
            }
            Write-ActionLog "Offline: dumps BSOD copies depuis $dumpSource"
        }
    }

    $driveRoot = Split-Path $WindowsPath -Parent
    $usersPath = Join-Path $driveRoot "Users"
    if (Test-Path -LiteralPath $usersPath) {
        Get-ChildItem -LiteralPath $usersPath -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -notin @("All Users", "Default", "Default User", "Public") } |
            ForEach-Object {
                $analysis.user_profiles += [ordered]@{ name = $_.Name; path = $_.FullName; last_write_time = $_.LastWriteTime.ToString("o") }
            }
        Write-ActionLog "Offline: $(@($analysis.user_profiles).Count) profils utilisateurs detectes"
    }

    $analysis.efi_partitions = @(Invoke-SafeCommand -Script { Get-Partition | Where-Object { $_.GptType -eq "{c12a7328-f81f-11d2-ba4b-00a0c93ec93b}" -or $_.Type -eq "System" } | Select-Object DiskNumber, PartitionNumber, DriveLetter, Type, GptType, Size } -Fallback @())
    $analysis.bitlocker = @(Invoke-SafeCommand -Script { manage-bde -status 2>&1 } -Fallback "manage-bde indisponible")

    if (@($analysis.registry_hives).Count -gt 0) { $analysis.findings += "Ruches registre offline copiees." }
    if (@($analysis.event_logs).Count -gt 0) { $analysis.findings += "Journaux Windows offline copies." }
    if (@($analysis.bsod_dumps).Count -gt 0) { $analysis.findings += "Dumps BSOD detectes." }
    if (@($analysis.user_profiles).Count -gt 0) { $analysis.findings += "Profils utilisateurs offline detectes." }

    return $analysis
}

# ===== B1 : ddrescue / TestDisk / PhotoRec Integration =====
function Invoke-Ddrescue {
    param(
        [string]$SourceDisk,
        [string]$ImagePath,
        [string]$LogPath
    )
    # Chercher ddrescue (WSL ou natif)
    $ddrescue = Get-Command ddrescue -ErrorAction SilentlyContinue
    if (-not $ddrescue) {
        $wslDdrescue = Get-Command wsl -ErrorAction SilentlyContinue
        if ($wslDdrescue) {
            Write-Host "[ddrescue] Utilisation via WSL..." -ForegroundColor Yellow
            $ddrescueCmd = "wsl ddrescue -d -f -r3 $SourceDisk $ImagePath $LogPath"
            Invoke-Expression $ddrescueCmd
            return $LASTEXITCODE
        }
        Write-Host "[ddrescue] NON DISPONIBLE - Installer ddrescue ou WSL" -ForegroundColor Red
        return $null
    }
    Write-Host "[ddrescue] Demarrage de l'image disque..." -ForegroundColor Cyan
    & ddrescue -d -f -r3 $SourceDisk $ImagePath $LogPath 2>&1
    $exitCode = $LASTEXITCODE
    Write-Host "[ddrescue] Termine (code: $exitCode)" -ForegroundColor Green
    return $exitCode
}

function Invoke-TestDisk {
    param([string]$TargetDisk)
    $testdisk = Get-Command testdisk -ErrorAction SilentlyContinue
    if (-not $testdisk) {
        $wslTestdisk = Get-Command wsl -ErrorAction SilentlyContinue
        if ($wslTestdisk) {
            Write-Host "[TestDisk] Utilisation via WSL..." -ForegroundColor Yellow
            wsl testdisk /log $TargetDisk 2>&1
            return $LASTEXITCODE
        }
        Write-Host "[TestDisk] NON DISPONIBLE" -ForegroundColor Red
        return $null
    }
    Write-Host "[TestDisk] Lancement de l'analyse des partitions..." -ForegroundColor Cyan
    & testdisk /log $TargetDisk 2>&1
    return $LASTEXITCODE
}

function Invoke-PhotoRec {
    param(
        [string]$TargetDisk,
        [string]$OutputDir
    )
    $photorec = Get-Command photorec -ErrorAction SilentlyContinue
    if (-not $photorec) {
        $wslPhotoRec = Get-Command wsl -ErrorAction SilentlyContinue
        if ($wslPhotoRec) {
            Write-Host "[PhotoRec] Utilisation via WSL..." -ForegroundColor Yellow
            wsl photorec /d $OutputDir /log $TargetDisk 2>&1
            return $LASTEXITCODE
        }
        Write-Host "[PhotoRec] NON DISPONIBLE" -ForegroundColor Red
        return $null
    }
    Write-Host "[PhotoRec] Demarrage de la recuperation de fichiers..." -ForegroundColor Cyan
    & photorec /d $OutputDir /log $TargetDisk 2>&1
    return $LASTEXITCODE
}

function Get-RecoveryWorkflow {
    param($Inventory)
    $riskLevel = $Inventory.disk_risk.level
    $workflow = [ordered]@{
        risk_level = $riskLevel
        recommended_actions = @()
        available_tools = @()
    }
    # Detecter outils disponibles
    if (Get-Command ddrescue -ErrorAction SilentlyContinue) { $workflow.available_tools += "ddrescue" }
    if (Get-Command testdisk -ErrorAction SilentlyContinue) { $workflow.available_tools += "testdisk" }
    if (Get-Command photorec -ErrorAction SilentlyContinue) { $workflow.available_tools += "photorec" }
    # Actions recommandees par niveau
    switch ($riskLevel) {
        "healthy" {
            $workflow.recommended_actions = @(
                @{ action = "copie_fichiers"; tool = "robocopy"; description = "Copie standard des fichiers utilisateur" }
            )
        }
        "suspect" {
            $workflow.recommended_actions = @(
                @{ action = "image_disque"; tool = "ddrescue"; description = "Creer une image disque avant reparation" }
                @{ action = "analyse_image"; tool = "testdisk"; description = "Analyser les partitions sur l'image" }
            )
        }
        "critical" {
            $workflow.recommended_actions = @(
                @{ action = "ddrescue_prioritaire"; tool = "ddrescue"; description = "ddrescue -d -f -r3 pour sauver les secteurs lisibles" }
                @{ action = "recuperation_fichiers"; tool = "photorec"; description = "PhotoRec sur l'image pour extraire fichiers par signature" }
                @{ action = "analyse_partitions"; tool = "testdisk"; description = "TestDisk pour restaurer la table de partitions" }
            )
        }
    }
    return $workflow
}

function Write-HtmlReport {
    param($Inventory, $BlackBox, [string]$Path)

    $machine = $Inventory.machine
    $health = $Inventory.health
    $diskRisk = $Inventory.disk_risk
    $backupSummary = $BlackBox.backup
    $offline = $Inventory.offline_windows
    $bios = $Inventory.bios
    $processors = $Inventory.processors
    $video = $Inventory.video_controllers
    $classicLogs = $Inventory.classic_event_log
    $details = $health.details
    $smartData = $Inventory.smart

    $disksRows = ($Inventory.disks | ForEach-Object { "<tr><td>$($_.Number)</td><td>$($_.FriendlyName)</td><td>$($_.BusType)</td><td>$($_.HealthStatus)</td><td>$($_.PartitionStyle)</td><td>$([math]::Round($_.Size / 1GB, 2)) GB</td></tr>" }) -join "`n"
    $volumeRows = ($Inventory.volumes | ForEach-Object { "<tr><td>$($_.DriveLetter)</td><td>$($_.FileSystemLabel)</td><td>$($_.FileSystem)</td><td>$([math]::Round($_.SizeRemaining / 1GB, 2)) / $([math]::Round($_.Size / 1GB, 2)) GB</td></tr>" }) -join "`n"
    
    $importantProviders = 'Disk|Ntfs|volmgr|storahci|iaStor|Kernel-Power|WHEA|BitLocker|VSS|Boot|WindowsUpdateClient|Service Control Manager'
    $filteredErrors = @($Inventory.system_errors | Where-Object { 
        ($_.ProviderName -match $importantProviders) -or ($_.Id -in 7, 51, 55, 129, 153, 1001, 6008, 7000, 7001, 7009, 7023, 7034)
    })
    if ($filteredErrors.Count -eq 0) { $filteredErrors = @($Inventory.system_errors | Select-Object -First 5) }
    $errorRows = ($filteredErrors | Select-Object -First 10 | ForEach-Object { 
        "<tr><td>$($_.TimeCreated)</td><td>$($_.ProviderName)</td><td>$($_.Id)</td><td>$($_.LevelDisplayName)</td><td>$([System.Net.WebUtility]::HtmlEncode($_.Message))</td></tr>" 
    }) -join "`n"
    if (-not $errorRows) { $errorRows = '<tr><td colspan="5"><span class="muted">Aucune erreur importante detectee.</span></td></tr>' }

    $filteredClassic = @($classicLogs | Where-Object { 
        ($_.Source -match $importantProviders) -or ($_.EventID -in 7, 51, 55, 129, 153, 1001, 6008, 7000, 7001, 7009, 7023, 7034)
    })
    if ($filteredClassic.Count -eq 0) { $filteredClassic = @($classicLogs | Select-Object -First 5) }
    $classicRows = ($filteredClassic | Select-Object -First 10 | ForEach-Object { 
        "<tr><td>$($_.TimeGenerated)</td><td>$($_.Source)</td><td>$($_.EntryType)</td><td>$([System.Net.WebUtility]::HtmlEncode($_.Message))</td></tr>" 
    }) -join "`n"
    if (-not $classicRows) { $classicRows = '<tr><td colspan="4"><span class="muted">Aucune erreur classique importante detectee.</span></td></tr>' }
    
    $backupItems = @(Get-RgArray $backupSummary.items)
    if ($backupItems.Count -gt 0) {
        $backupRows = ($backupItems | ForEach-Object { "<tr><td>$($_.name)</td><td>$($_.source)</td><td>$($_.destination)</td><td>$($_.exit_code)</td><td>$($_.file_count)</td><td>$([math]::Round((Get-RgNumber $_.total_bytes 0) / 1GB, 2)) GB</td></tr>" }) -join "`n"
    }
    else {
        $backupRows = '<tr><td colspan="6"><span class="muted">Aucune sauvegarde effectuee pour cette intervention.</span></td></tr>'
    }
    $offlineFindings = [System.Net.WebUtility]::HtmlEncode(($offline.findings -join " | "))
    $offlineProfileRows = ($offline.user_profiles | ForEach-Object { "<tr><td>$($_.name)</td><td>$($_.path)</td><td>$($_.last_write_time)</td></tr>" }) -join "`n"

    $biosInfo = ""
    if ($bios) {
        $biosInfo = "<tr><th>BIOS</th><td>$($bios.Manufacturer) $($bios.Version) (SN: $(Get-RgCleanBiosSerial $bios.SerialNumber))</td></tr>"
    }

    $cpuInfo = ""
    if ($processors) {
        $cpuList = ($processors | ForEach-Object { "$($_.Name) @ $($_.MaxClockSpeed) MHz ($($_.NumberOfCores) coeurs / $($_.NumberOfLogicalProcessors) logiques)" }) -join ", "
        $cpuInfo = "<tr><th>Processeur(s)</th><td>$cpuList</td></tr>"
    }

    $gpuInfo = ""
    if ($video) {
        $gpuList = ($video | ForEach-Object { "$($_.Name) (RAM: $([math]::Round($_.AdapterRAM / 1GB, 2)) GB / Driver: $($_.DriverVersion))" }) -join ", "
        $gpuInfo = "<tr><th>Carte graphique</th><td>$gpuList</td></tr>"
    }

    # --- Sous-scores avec jauges ---
    $jaugeRows = ""
    $detailItems = Get-RgHealthDetails $health
    if ($detailItems.Count -gt 0) {
        $jaugeRows = ($detailItems | ForEach-Object {
            $d = $_
            $score = Get-RgNumber $d.score 0
            $max = Get-RgNumber $d.max 0
            if ($max -le 0) { $pct = 0 } else { $pct = [math]::Round(($score / $max) * 100) }
            if ($pct -lt 0) { $pct = 0 }
            if ($pct -gt 100) { $pct = 100 }
            $levelNameForColor = [string]$d.level.label
            $color = if ($levelNameForColor -eq "OK") { "#15803d" } elseif ($levelNameForColor -eq "Attention") { "#d97706" } else { "#dc2626" }
            $label = ConvertTo-RgHtml $d.label
            $levelCss = ConvertTo-RgHtml $d.level.css
            $levelLabel = ConvertTo-RgHtml $d.level.label
            @"
<div style="margin-bottom: 14px;">
  <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
    <strong>$label</strong>
    <span>$score/$max <span class="$levelCss">$levelLabel</span></span>
  </div>
  <div style="background: #e5e7eb; border-radius: 8px; height: 18px; overflow: hidden;">
    <div style="width: $pct%; background: $color; height: 100%; border-radius: 8px; transition: width .5s;"></div>
  </div>
</div>
"@
        }) -join "`n"
    }
    else {
        $jaugeRows = '<p class="muted">Sous-scores indisponibles.</p>'
    }

    # --- Photos avant/après ---
    $photosHtml = ""
    if ($BlackBox.photo_before -or $BlackBox.photo_after) {
        $photosHtml = '<h2>Photos intervention</h2><div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px;">'
        if ($BlackBox.photo_before) { $photosHtml += "<div><strong>Avant</strong><br><img src=`"$($BlackBox.photo_before)`" style=`"max-width:100%; border-radius:12px;`"></div>" }
        if ($BlackBox.photo_after) { $photosHtml += "<div><strong>Apres</strong><br><img src=`"$($BlackBox.photo_after)`" style=`"max-width:100%; border-radius:12px;`"></div>" }
        $photosHtml += "</div>"
    }

    # --- SMART températures ---
    $tempRows = ""
    if ($smartData) {
        $tempRows = ($smartData | ForEach-Object {
            $tempNumber = Get-RgTemperatureNumber $_.temperature_celsius $null
            if ($null -ne $tempNumber) {
                $tempDisplay = [math]::Round($tempNumber, 0)
                $badge = if ($tempNumber -gt 55) { "class=`"critical`"" } elseif ($tempNumber -gt 45) { "class=`"warn`"" } else { "class=`"ok`"" }
                "<tr><td>$(ConvertTo-RgHtml $_.friendly_name)</td><td><strong $badge>$($tempDisplay)&#176;C</strong></td></tr>"
            }
            else {
                "<tr><td>$(ConvertTo-RgHtml $_.friendly_name)</td><td><span class=`"muted`">Non disponible</span></td></tr>"
            }
        }) -join "`n"
    }

    # --- SMART detaille ---
    $smartDetailRows = ""
    if ($smartData) {
        $smartDetailRows = ($smartData | ForEach-Object {
            $tempNumber = Get-RgTemperatureNumber $_.temperature_celsius $null
            $tempHtml = if ($null -ne $tempNumber) { "$([math]::Round($tempNumber,0))&#176;C" } else { "<span class=`"muted`">Non disponible</span>" }
            $modelHtml = if ($_.smart_model) { ConvertTo-RgHtml $_.smart_model } else { "<span class=`"muted`">Non disponible</span>" }
            $serialHtml = if ($_.smart_serial) { ConvertTo-RgHtml $_.smart_serial } else { "<span class=`"muted`">Non disponible</span>" }
            $wearHtml = if ($_.smart_percentage_used) { "$(ConvertTo-RgHtml $_.smart_percentage_used)%" } else { "<span class=`"muted`">Non disponible</span>" }
            $hoursHtml = if ($_.smart_power_on_hours) { ConvertTo-RgHtml $_.smart_power_on_hours } else { "<span class=`"muted`">Non disponible</span>" }
            $writtenHtml = if ($_.smart_data_units_written) { ConvertTo-RgHtml $_.smart_data_units_written } else { "<span class=`"muted`">Non disponible</span>" }
            $mediaHtml = if ($_.smart_media_errors -ne $null -and "$($_.smart_media_errors)" -ne "") { ConvertTo-RgHtml $_.smart_media_errors } else { "<span class=`"muted`">Non disponible</span>" }
            $deviceHtml = if ($_.smart_device) { ConvertTo-RgHtml $_.smart_device } else { "<span class=`"muted`">Non mappe</span>" }
            $smartStatus = Get-RgSmartAttention $_
            $statusHtml = "<span class=`"$($smartStatus.css)`">$(ConvertTo-RgHtml $smartStatus.label)</span>"
            "<tr><td>$(ConvertTo-RgHtml $_.friendly_name)</td><td>$deviceHtml</td><td>$modelHtml</td><td>$tempHtml</td><td>$wearHtml</td><td>$hoursHtml</td><td>$writtenHtml</td><td>$mediaHtml</td><td>$statusHtml</td></tr>"
        }) -join "`n"
    }
    if ([string]::IsNullOrWhiteSpace($smartDetailRows)) {
        $smartDetailRows = "<tr><td colspan=`"9`"><span class=`"muted`">Aucune donnee SMART detaillee disponible.</span></td></tr>"
    }

    $clientNameHtml = ConvertTo-RgHtml (Get-RgFirstValue $Inventory.client_name $BlackBox.client_name)
    $operatorHtml = ConvertTo-RgHtml (Get-RgFirstValue $BlackBox.operator $env:USERNAME)
    $sourceMachineHtml = ConvertTo-RgHtml (Get-RgFirstValue $BlackBox.source_machine $env:COMPUTERNAME)
    $machineNameHtml = ConvertTo-RgHtml (Get-RgFirstValue $machine.CsName $env:COMPUTERNAME)
    $manufacturerHtml = ConvertTo-RgHtml (Get-RgFirstValue $machine.CsManufacturer "")
    $modelHtml = ConvertTo-RgHtml (Get-RgFirstValue $machine.CsModel "")
    $windowsNameHtml = ConvertTo-RgHtml (Get-RgFirstValue $machine.WindowsProductName "")
    $windowsVersionHtml = ConvertTo-RgHtml (Get-RgFirstValue $machine.WindowsVersion "")
    $ramBytes = Get-RgBestInt64 @($machine.CsTotalPhysicalMemory, $machine.TotalPhysicalMemory) 0
    $ramGb = [math]::Round($ramBytes / 1GB, 2)
    $biosSerialHtml = ConvertTo-RgHtml (Get-RgCleanBiosSerial $bios.SerialNumber)
    $finishedAtDisplay = ConvertTo-RgHtml (Format-RgDateFr $BlackBox.finished_at)
    $startedAtDisplay = ConvertTo-RgHtml (Format-RgDateFr $BlackBox.started_at)
    $generatedAtDisplay = ConvertTo-RgHtml (Get-Date -Format "dd/MM/yyyy HH:mm:ss")
    $globalScore = [int](Get-RgNumber $health.global_score 0)
    $diskCss = ConvertTo-RgHtml $health.disk.css
    $diskLabel = ConvertTo-RgHtml $health.disk.label
    $windowsCss = ConvertTo-RgHtml $health.windows.css
    $windowsLabel = ConvertTo-RgHtml $health.windows.label
    $dataLossRisk = ConvertTo-RgHtml $health.data_loss_risk
    $diskRiskDisplay = if ($diskRisk.level -eq "healthy") { "OK" } else { $diskRisk.level }
    $filesystemStatus = Get-RgFirstValue $health.scoring_notes.filesystem_status $null

    $executiveSummary = @()
    $diskEventsForSummary = @(Get-RgDiskEvents -Inventory $Inventory)

    # v8.9 : resume executif simplifie et coherent avec la separation SMART / NTFS.
    if ($globalScore -ge 90) { $executiveSummary += "Machine fonctionnelle." }
    elseif ($globalScore -ge 80) { $executiveSummary += "Machine fonctionnelle avec points a surveiller." }
    elseif ($globalScore -ge 60) { $executiveSummary += "Maintenance conseillee." }
    else { $executiveSummary += "Intervention recommandee." }

    $smartAvailable = @($smartData | Where-Object { $_.smart_available -eq $true -or $_.smart_model })
    $smartMediaErrorCount = @($smartAvailable | Where-Object { [int](Get-RgNumber $_.smart_media_errors 0) -gt 0 }).Count
    $smartCritical = @($smartAvailable | Where-Object { (Get-RgSmartAttention $_).level -eq "critical" })

    if ($smartAvailable.Count -gt 0) {
        if ($smartCritical.Count -eq 0 -and $smartMediaErrorCount -eq 0) {
            $executiveSummary += "Tous les SSD analyses presentent un etat SMART satisfaisant."
            $executiveSummary += "Aucun indicateur de panne materielle disque n'a ete releve."
        }
        elseif ($smartCritical.Count -gt 0) {
            $names = ($smartCritical | Select-Object -First 3 | ForEach-Object { $_.friendly_name }) -join ", "
            $executiveSummary += "Alerte SMART critique pour : $names."
        }
        elseif ($smartMediaErrorCount -gt 0) {
            $executiveSummary += "Des erreurs media SMART ont ete detectees sur au moins un disque."
        }
    }

    $ntfsEventsForSummary = @($diskEventsForSummary | Where-Object {
        $src = [string](Get-RgFirstValue $_.ProviderName (Get-RgFirstValue $_.Source ""))
        $id = [int](Get-RgNumber (Get-RgFirstValue $_.Id 0) 0)
        $src -match '(?i)^Ntfs$' -or $id -eq 55
    })
    if ($ntfsEventsForSummary.Count -gt 0) {
        $executiveSummary += "Une incoherence NTFS a ete detectee et necessite une verification du systeme de fichiers apres sauvegarde."
    }

    if ($windowsLabel -ne "OK") {
        $executiveSummary += "Quelques evenements Windows non critiques sont presents dans les journaux."
    }

    $executiveSummaryHtml = ($executiveSummary | ForEach-Object { "<li>$(ConvertTo-RgHtml $_)</li>" }) -join "`n"

    $offlineHtml = ""
    if ($offline -and $offline.enabled) {
        $offlineHtml = @"
  $offlineHtml
"@
    }

    $html = @"
<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <title>Rapport Restor-PC RescueGrid</title>
  <style>
    body { font-family: Segoe UI, Arial, sans-serif; margin: 32px; color: #172033; background: #f5f7fb; }
    .page { max-width: 1120px; margin: auto; background: white; padding: 32px; border-radius: 18px; box-shadow: 0 16px 40px rgba(23,32,51,.10); }
    h1 { margin: 0 0 6px; color: #0f766e; font-size: 28px; }
    .subtitle { color: #667085; margin-bottom: 20px; }
    h2 { margin-top: 28px; border-bottom: 2px solid #e5e7eb; padding-bottom: 8px; color: #134e4a; }
    .grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
    .card { border: 1px solid #e5e7eb; border-radius: 14px; padding: 16px; background: #fbfdff; }
    .card .label { font-size: 12px; text-transform: uppercase; letter-spacing: .5px; color: #667085; }
    .score { font-size: 42px; font-weight: 800; line-height: 1.1; }
    .ok { color: #15803d; } .warn { color: #d97706; } .bad { color: #dc2626; } .critical { color: #111827; background: #fee2e2; padding: 2px 6px; border-radius: 6px; }
    table { width: 100%; border-collapse: collapse; margin-top: 10px; }
    th, td { text-align: left; border-bottom: 1px solid #e5e7eb; padding: 8px; vertical-align: top; }
    th { background: #f8fafc; font-weight: 650; font-size: 13px; }
    .muted { color: #667085; font-size: 13px; }
    .signature-box { height: 100px; border: 2px dashed #94a3b8; border-radius: 12px; margin-top: 12px; display: flex; align-items: center; justify-content: center; color: #94a3b8; }
    .warning-badge { display: inline-block; background: #fef3c7; color: #92400e; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 700; }
    .good-badge { display: inline-block; background: #d1fae5; color: #065f46; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 700; }
    .critical-badge { display: inline-block; background: #fee2e2; color: #991b1b; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 700; }
    .footer { margin-top: 30px; padding-top: 16px; border-top: 1px solid #e5e7eb; font-size: 12px; color: #667085; }
    .consent-box { background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 12px; padding: 16px; margin-top: 16px; }
    .score-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 12px; }
    @media print { body { background: white; } .page { box-shadow: none; } }
  </style>
</head>
<body>
<main class="page">
  <h1>Restor-PC RescueGrid</h1>
  <p class="subtitle">Rapport forensic d'intervention &mdash; $($BlackBox.intervention_id)</p>
  <p class="subtitle">Client : $clientNameHtml | Op&eacute;rateur : $operatorHtml | $sourceMachineHtml | $finishedAtDisplay</p>

  <section class="grid">
    <div class="card">
      <div class="label">Sante globale</div>
      <div class="score">$globalScore/100</div>
    </div>
    <div class="card">
      <div class="label">Disque</div>
      <strong class="$diskCss">$diskLabel</strong>
    </div>
    <div class="card">
      <div class="label">Windows</div>
      <strong class="$windowsCss">$windowsLabel</strong>
    </div>
    <div class="card">
      <div class="label">Risque perte donnees</div>
      <strong>$dataLossRisk</strong>
    </div>
  </section>

  <h2>Resume executif</h2>
  <ul>
    $executiveSummaryHtml
  </ul>

  <h2>Score sante detaille</h2>
  <div class="score-grid">
    <div>
      <h3 style="margin:0 0 8px 0; font-size:15px;">Sous-scores</h3>
      $jaugeRows
    </div>
    <div>
      <h3 style="margin:0 0 8px 0; font-size:15px;">Resume</h3>
      <table>
        <tr><th>Disque</th><td class="$($health.disk.css)"><strong>$($health.disk.label)</strong></td></tr>
        <tr><th>RAM</th><td class="$($health.ram.css)"><strong>$($health.ram.label)</strong></td></tr>
        <tr><th>Windows</th><td class="$($health.windows.css)"><strong>$($health.windows.label)</strong></td></tr>
        <tr><th>Boot</th><td class="$($health.boot.css)"><strong>$($health.boot.label)</strong></td></tr>
        <tr><th>BitLocker</th><td class="$($health.bitlocker.css)"><strong>$($health.bitlocker.label)</strong></td></tr>
      </table>
    </div>
  </div>

  <h2>Decision recuperation</h2>
  <table>
    <tr><th>Niveau disque materiel</th><td><strong>$diskRiskDisplay</strong></td></tr>
    <tr><th>Systeme de fichiers</th><td><strong>$($filesystemStatus.label)</strong></td></tr>
    <tr><th>Recommandation</th><td>$($diskRisk.recommendation)</td></tr>
    <tr><th>Raisons</th><td>$([System.Net.WebUtility]::HtmlEncode(($diskRisk.reasons -join " | ")))</td></tr>
  </table>

  <h2>Identite machine</h2>
  <table>
    <tr><th>Nom</th><td>$machineNameHtml</td></tr>
    <tr><th>Fabricant</th><td>$manufacturerHtml</td></tr>
    <tr><th>Modele</th><td>$modelHtml</td></tr>
    <tr><th>Windows</th><td>$windowsNameHtml $windowsVersionHtml</td></tr>
    <tr><th>RAM</th><td>$ramGb GB</td></tr>
    $biosInfo
    $cpuInfo
    $gpuInfo
    <tr><th>Numero serie</th><td>$biosSerialHtml</td></tr>
  </table>

  <h2>Disques</h2>
  <table><tr><th>#</th><th>Nom</th><th>Bus</th><th>Sante</th><th>Partition</th><th>Taille</th></tr>$disksRows</table>

  <h2>Temperatures disques</h2>
  <table><tr><th>Disque</th><th>Temperature</th></tr>$tempRows</table>

  <h2>SMART detaille</h2>
  <table>
    <tr><th>Disque Windows</th><th>smartctl</th><th>Modele SMART</th><th>Temp.</th><th>Usure</th><th>Heures</th><th>Donnees ecrites</th><th>Erreurs media</th><th>Etat</th></tr>
    $smartDetailRows
  </table>

  <h2>Volumes</h2>
  <table><tr><th>Lettre</th><th>Label</th><th>FS</th><th>Libre / Total</th></tr>$volumeRows</table>

  <h2>Erreurs systeme recentes (14 jours)</h2>
  <table><tr><th>Date</th><th>Source</th><th>ID</th><th>Niveau</th><th>Message</th></tr>$errorRows</table>

  <h2>Erreurs classiques (EventLog legacy)</h2>
  <table><tr><th>Date</th><th>Source</th><th>Type</th><th>Message</th></tr>$classicRows</table>

  $offlineHtml

  <h2>Actions effectuees</h2>
  <ul>
    <li>Inventaire materiel et systeme (CPU, RAM, BIOS, GPU, disques, temperatures).</li>
    <li>SMART avance : smartctl + CrystalDiskInfo si disponibles.</li>
    <li>Score sante global detaille (Disque, RAM, Windows, Drivers, Temperatures).</li>
    <li>Controle disques, volumes, BitLocker et journaux systeme.</li>
    <li>Sauvegarde profil utilisateur : $($BlackBox.backup.performed).</li>
    <li>Generation BlackBox et hashes SHA256.</li>
    <li>Consentement client enregistre.</li>
    <li>Photos avant/apres : $($BlackBox.photo_before -and $BlackBox.photo_after).</li>
  </ul>

  <h2>Sauvegarde / recuperation</h2>
  <table><tr><th>Dossier</th><th>Source</th><th>Destination</th><th>Code robocopy</th><th>Fichiers</th><th>Taille</th></tr>$backupRows</table>

  $photosHtml

  <h2>Garanties</h2>
  <ul>
$($BlackBox.guarantees | ForEach-Object { "    <li>$_</li>`n" })
  </ul>

  <h2>Signature client</h2>
  <div class="consent-box">
    <p>Je reconnais avoir pris connaissance des actions effectuees et des recommandations.</p>
    <p><strong>Client :</strong> $($BlackBox.client_name)</p>
    <p><strong>Intervention :</strong> $($BlackBox.intervention_id)</p>
    <p><strong>Date :</strong> $finishedAtDisplay</p>
    <p><strong>Consentement :</strong> $(if ($BlackBox.consent_obtained) { "Obtenu" } else { "Skippe" })</p>
  </div>
  <div class="signature-box">
    $(if ($BlackBox.signature_data) { "<img src=`"$($BlackBox.signature_data)`" style=`"max-height:80px;`">" } else { "Signature non fournie" })
  </div>

  <div class="footer">
    <p>Rapport genere par Restor-PC RescueGrid le $generatedAtDisplay</p>
    <p>Op&eacute;rateur : $($BlackBox.operator) &mdash; Machine source : $($BlackBox.source_machine)</p>
    <p>Horodatage signe : debut=$startedAtDisplay fin=$finishedAtDisplay</p>
  </div>
</main>
</body>
</html>
"@

    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($Path, $html, $utf8NoBom)
    Write-ActionLog "Rapport HTML v3 genere avec sous-scores, photos et signature"
}

# ===== DEBUT DE L'INVENTAIRE =====
Write-Host "[Restor-PC RescueGrid] Demarrage de l'intervention pour $ClientName..." -ForegroundColor Cyan
Write-Host "[INFO] Dossier intervention: $interventionPath" -ForegroundColor Gray

$inventory = [ordered]@{}
$inventory.generated_at = (Get-Date).ToString("o")
$inventory.client_name = $ClientName

# Machine info
Write-Host "[1/9] Collecte informations machine..." -NoNewline
$inventory.machine = Get-RgMachineInfo
Write-Host " OK" -ForegroundColor Green
Write-ActionLog "Informations machine collectees"

# BIOS
Write-Host "[2/9] Collecte informations BIOS..." -NoNewline
$inventory.bios = Get-BiosInfo
Write-Host " OK" -ForegroundColor Green
Write-ActionLog "BIOS collecte"

# Processeurs
Write-Host "[3/9] Collecte informations processeur..." -NoNewline
$inventory.processors = Get-ProcessorInfo
Write-Host " OK" -ForegroundColor Green
Write-ActionLog "Processeurs collectes"

# GPU
Write-Host "[4/9] Collecte informations carte graphique..." -NoNewline
$inventory.video_controllers = Get-VideoControllerInfo
Write-Host " OK" -ForegroundColor Green
Write-ActionLog "Controleurs video collectes"

# Disques
Write-Host "[5/9] Collecte informations disques..." -NoNewline
$inventory.disks = @(Invoke-SafeCommand -Script { Get-Disk | Select-Object Number, FriendlyName, SerialNumber, BusType, HealthStatus, OperationalStatus, PartitionStyle, Size } -Fallback @())
$inventory.partitions = @(Invoke-SafeCommand -Script { Get-Partition | Select-Object DiskNumber, PartitionNumber, DriveLetter, Type, GptType, Size } -Fallback @())
$inventory.volumes = @(Invoke-SafeCommand -Script { Get-Volume | Select-Object DriveLetter, FileSystemLabel, FileSystem, HealthStatus, SizeRemaining, Size } -Fallback @())
Write-Host " OK" -ForegroundColor Green
Write-ActionLog "$(@($inventory.disks).Count) disques, $(@($inventory.partitions).Count) partitions, $(@($inventory.volumes).Count) volumes"

# BitLocker + BCD
Write-Host "[6/9] Analyse BitLocker et BCD..." -NoNewline
$inventory.bitlocker_text = @(Invoke-SafeCommand -Script { manage-bde -status 2>&1 } -Fallback "manage-bde indisponible")
$inventory.bcd_text = @(Invoke-SafeCommand -Script { bcdedit /enum all 2>&1 } -Fallback "bcdedit indisponible")
Write-Host " OK" -ForegroundColor Green
Write-ActionLog "BitLocker et BCD analyses"

# SMART
Write-Host "[7/9] Analyse SMART disques..." -NoNewline
$inventory.smart = @(Get-SmartSnapshot)
Write-Host " OK" -ForegroundColor Green

# Erreurs systeme (moderne + legacy)
Write-Host "[8/9] Collecte erreurs systeme..." -NoNewline
$inventory.system_errors = @(Invoke-SafeCommand -Script { Get-WinEvent -FilterHashtable @{ LogName = 'System'; Level = 1,2; StartTime = (Get-Date).AddDays(-14) } -MaxEvents 100 | Select-Object TimeCreated, ProviderName, Id, LevelDisplayName, Message } -Fallback @())
$inventory.classic_event_log = @(Get-ClassicEventLog)
Write-Host " OK" -ForegroundColor Green
Write-ActionLog "$(@($inventory.system_errors).Count) erreurs systeme modernes, $(@($inventory.classic_event_log).Count) erreurs classiques"

# Profils utilisateurs
Write-Host "[9/9] Detection profils utilisateurs..." -NoNewline
$inventory.user_profiles = @(Invoke-SafeCommand -Script { Get-CimInstance Win32_UserProfile | Where-Object { -not $_.Special } | Select-Object LocalPath, LastUseTime, Loaded } -Fallback @())
Write-Host " OK" -ForegroundColor Green
Write-ActionLog "$(@($inventory.user_profiles).Count) profils utilisateurs"

# Risque disque + offline
Write-Host "[INFO] Evaluation risque disque..." -NoNewline
$inventory.disk_risk = Get-DiskRiskAssessment -Inventory $inventory
Write-Host " $($inventory.disk_risk.level)" -ForegroundColor $(if($inventory.disk_risk.level -eq "healthy"){"Green"}elseif($inventory.disk_risk.level -eq "attention"){"Yellow"}else{"Red"})

$inventory.offline_windows = Get-OfflineWindowsAnalysis -WindowsPath $OfflineWindowsPath
$inventory.health = Get-HealthScore -Inventory $inventory
Write-Host "[INFO] Score sante: $($inventory.health.global_score)/100 - Risque: $($inventory.health.data_loss_risk)" -ForegroundColor Cyan

# Mode lecture seule si disque suspect/critical
$readOnlyMode = $false
if ($inventory.disk_risk.level -in @("suspect", "critical")) {
    Write-Host "[SECURITE] Disque $($inventory.disk_risk.level) - Mode lecture seule active" -ForegroundColor Yellow
    $readOnlyMode = $true
    Write-ActionLog "MODE LECTURE SEULE: disque $($inventory.disk_risk.level)"
}

# ===== SAUVEGARDE =====
$backup = [ordered]@{ performed = $false; source = $UserProfilePath; destination = $null; exit_code = $null; log = $null; mode = $null; items = @(); manifest = $null }
if ($UserProfilePath -and -not $readOnlyMode) {
    Write-Host ""
    Write-Host "[SAUVEGARDE] Debut de la sauvegarde..." -ForegroundColor Cyan
    
    if (-not (Test-Path -LiteralPath $UserProfilePath)) {
        Write-Host "[ERREUR] Profil utilisateur introuvable: $UserProfilePath" -ForegroundColor Red
        Write-ActionLog "ERREUR: Profil utilisateur introuvable: $UserProfilePath"
    }
    else {
        $profileName = Split-Path $UserProfilePath -Leaf
        $backupDestination = Join-Path $interventionPath ("backup_{0}" -f $profileName)
        $backupLog = Join-Path $interventionPath "backup_log.txt"
        $manifestPath = Join-Path $interventionPath "backup_manifest.csv"
        New-Item -ItemType Directory -Path $backupDestination -Force | Out-Null

        $sources = @(Get-BackupSources -ProfilePath $UserProfilePath -EssentialOnly:$BackupEssentialFoldersOnly)
        $backup.mode = if ($BackupEssentialFoldersOnly) { "essential_folders" } else { "full_profile" }
        Write-Host "[SAUVEGARDE] Mode: $($backup.mode) - $(@($sources).Count) source(s)" -ForegroundColor Cyan
        Write-ActionLog "Sauvegarde mode: $($backup.mode) - $(@($sources).Count) source(s)"

        foreach ($source in $sources) {
            Write-Host "  -> Sauvegarde de $($source.name)..." -NoNewline
            $destination = if ($BackupEssentialFoldersOnly) { Join-Path $backupDestination $source.name } else { $backupDestination }
            New-Item -ItemType Directory -Path $destination -Force | Out-Null
            robocopy $source.path $destination /E /COPY:DAT /R:1 /W:1 /XJ /DCOPY:DAT /LOG+:$backupLog | Out-Null
            $stats = Get-FolderStats -Path $destination
            $backup.items += [ordered]@{
                name = $source.name
                source = $source.path
                destination = $destination
                exit_code = $LASTEXITCODE
                file_count = $stats.file_count
                total_bytes = $stats.total_bytes
            }
            Write-Host " $($stats.file_count) fichiers, $([math]::Round($stats.total_bytes / 1MB, 2)) MB" -ForegroundColor Green
            Write-ActionLog "Sauvegarde $($source.name): $($stats.file_count) fichiers, $($stats.total_bytes) octets"
        }

        Get-ChildItem -LiteralPath $backupDestination -File -Recurse -Force -ErrorAction SilentlyContinue |
            Select-Object FullName, Length, LastWriteTime |
            Export-Csv -Path $manifestPath -NoTypeInformation -Encoding UTF8

        $backup.performed = $true
        $backup.destination = $backupDestination
        $backup.exit_code = (@($backup.items).exit_code | Measure-Object -Maximum).Maximum
        $backup.log = $backupLog
        $backup.manifest = $manifestPath
        Write-Host "[SAUVEGARDE] Terminee avec succes" -ForegroundColor Green
        Write-ActionLog "Sauvegarde terminee avec succes"
    }
}
elseif ($UserProfilePath -and $readOnlyMode) {
    Write-Host ""
    Write-Host "[SECURITE] Sauvegarde bloquee - Disque en mode $($inventory.disk_risk.level)" -ForegroundColor Red
    Write-Host "[SECURITE] Priorite: image disque / ddrescue avant toute copie fichier" -ForegroundColor Yellow
    Write-ActionLog "Sauvegarde BLOQUEE - risque disque: $($inventory.disk_risk.level)"
}

# ===== PHOTOS AVANT/APRES =====
$photoBeforeCopied = $null
$photoAfterCopied = $null
$signatureData = $null

if ($PhotoBefore -and (Test-Path -LiteralPath $PhotoBefore)) {
    $destBefore = Join-Path $proofPath "photo_avant.jpg"
    Copy-Item -LiteralPath $PhotoBefore -Destination $destBefore -Force -ErrorAction SilentlyContinue
    $photoBeforeCopied = "preuves/photo_avant.jpg"
    Write-ActionLog "Photo avant copiee: $PhotoBefore"
    Write-Host "[PHOTO] Avant : copiee" -ForegroundColor Green
}

if ($PhotoAfter -and (Test-Path -LiteralPath $PhotoAfter)) {
    $destAfter = Join-Path $proofPath "photo_apres.jpg"
    Copy-Item -LiteralPath $PhotoAfter -Destination $destAfter -Force -ErrorAction SilentlyContinue
    $photoAfterCopied = "preuves/photo_apres.jpg"
    Write-ActionLog "Photo apres copiee: $PhotoAfter"
    Write-Host "[PHOTO] Apres : copiee" -ForegroundColor Green
}

if ($SignatureFile -and (Test-Path -LiteralPath $SignatureFile)) {
    $destSig = Join-Path $proofPath "signature_client.png"
    Copy-Item -LiteralPath $SignatureFile -Destination $destSig -Force -ErrorAction SilentlyContinue
    $signatureData = "preuves/signature_client.png"
    Write-ActionLog "Signature client copiee: $SignatureFile"
    Write-Host "[SIGNATURE] Signature client copiee" -ForegroundColor Green
}
elseif (-not $SkipConsent) {
    # Generer une signature placeholder dans la BlackBox
    $signatureData = $null
    Write-ActionLog "Aucun fichier signature fourni, signature place holder dans le rapport"
}

# ===== BLACKBOX =====
$guaranteeText = if ($readOnlyMode) { "Mode lecture seule active - disque $($inventory.disk_risk.level)" } else { "Mode normal - risque disque: $($inventory.disk_risk.level)" }
$guarantees = @(
    "Aucune reparation destructive lancee automatiquement.",
    "Aucune suppression source effectuee par l'agent.",
    "CHKDSK /F non execute automatiquement.",
    "Analyse offline realisee en lecture seule par copie d'artefacts.",
    "Consentement client obtenu et enregistre.",
    $guaranteeText
) | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) }

$blackBox = [ordered]@{
    intervention_id = $interventionName
    client_name = $ClientName
    started_at = $startedAt.ToString("o")
    finished_at = (Get-Date).ToString("o")
    source_machine = $env:COMPUTERNAME
    operator = $env:USERNAME
    consent_obtained = (-not $SkipConsent)
    read_only_mode = $readOnlyMode
    photo_before = $photoBeforeCopied
    photo_after = $photoAfterCopied
    signature_data = $signatureData
    backup = $backup
    offline_windows = $inventory.offline_windows
    guarantees = $guarantees
}

# ===== VALIDATION AVANT RAPPORT =====
Write-Host "[VALIDATION] Controle des donnees rapport..." -NoNewline
$validationIssues = @(Test-RescueGridReportData -Inventory $inventory -BlackBox $blackBox)
if ($validationIssues.Count -gt 0) {
    Write-Host " AVERTISSEMENTS" -ForegroundColor Yellow
    foreach ($issue in $validationIssues) {
        Write-Host "  - $issue" -ForegroundColor Yellow
        Write-ActionLog "Validation: $issue"
    }
}
else {
    Write-Host " OK" -ForegroundColor Green
    Write-ActionLog "Validation pre-rapport OK"
}
$inventory.validation_issues = $validationIssues

# ===== EXPORT DES FICHIERS =====
Write-Host "[EXPORT] Generation des fichiers intervention..." -ForegroundColor Cyan

$inventoryPath = Join-Path $interventionPath "inventory.json"
$blackBoxPath = Join-Path $interventionPath "blackbox.json"
$reportPath = Join-Path $interventionPath "rapport.html"
$hashPath = Join-Path $interventionPath "hashes.sha256.txt"
$evidencePath = Join-Path $interventionPath "evidence_manifest.json"

$inventory | ConvertTo-Json -Depth 8 | Out-File -FilePath $inventoryPath -Encoding utf8
$blackBox | ConvertTo-Json -Depth 8 | Out-File -FilePath $blackBoxPath -Encoding utf8
Write-ActionLog "Inventory et BlackBox exportes JSON"
Write-Host "  -> inventory.json : $(Get-Item $inventoryPath | Select-Object -ExpandProperty Length | ForEach-Object { [math]::Round($_, 0) }) octets" -ForegroundColor Gray
Write-Host "  -> blackbox.json  : $(Get-Item $blackBoxPath | Select-Object -ExpandProperty Length | ForEach-Object { [math]::Round($_, 0) }) octets" -ForegroundColor Gray

Write-HtmlReport -Inventory $inventory -BlackBox $blackBox -Path $reportPath
Write-Host "  -> rapport.html   : $(Get-Item $reportPath | Select-Object -ExpandProperty Length | ForEach-Object { [math]::Round($_, 0) }) octets" -ForegroundColor Gray

# Hash SHA256
Write-Host "[EXPORT] Generation des hashes SHA256..." -NoNewline
Get-ChildItem -Path $interventionPath -File -Recurse |
    Where-Object { $_.FullName -ne $hashPath -and $_.FullName -ne $actionLogPath } |
    ForEach-Object {
    $hash = Get-FileHash $_.FullName -Algorithm SHA256
    "{0}  {1}" -f $hash.Hash, $_.FullName
} | Out-File -FilePath $hashPath -Encoding utf8
Write-Host " OK" -ForegroundColor Green
Write-ActionLog "Hashes SHA256 generes"

# Evidence manifest cryptographique (point 2)
Write-Host "[EXPORT] Generation manifeste cryptographique..." -NoNewline
$evidenceFiles = Get-ChildItem -Path $interventionPath -File -Recurse |
    Where-Object { $_.FullName -ne $evidencePath -and $_.FullName -ne $actionLogPath } |
    ForEach-Object {
    $hash = Get-FileHash $_.FullName -Algorithm SHA256
    [ordered]@{
        file = $_.Name
        path = $_.FullName.Replace($interventionPath, "").TrimStart("\").Replace("\", "/")
        size_bytes = $_.Length
        sha256 = $hash.Hash
    }
}
$evidenceManifest = [ordered]@{
    case_id = $interventionName
    client_name = $ClientName
    created = (Get-Date).ToString("o")
    machine_name = $env:COMPUTERNAME
    bios_serial = $inventory.bios.SerialNumber
    total_files = @($evidenceFiles).Count
    files = $evidenceFiles
}
$evidenceManifest | ConvertTo-Json -Depth 4 | Out-File -FilePath $evidencePath -Encoding utf8
Write-Host " OK" -ForegroundColor Green
Write-Host ("  -> evidence_manifest.json : {0} fichiers certificats" -f @($evidenceFiles).Count) -ForegroundColor Gray
Write-ActionLog ("Manifeste cryptographique genere: {0} fichiers" -f @($evidenceFiles).Count)

# ZIP
$zipPath = "$interventionPath.zip"
if ($CreateZip -or $DashboardUploadUrl) {
    Write-Host "[ZIP] Creation de l'archive ZIP..." -NoNewline
    if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
    Compress-Archive -Path (Join-Path $interventionPath "*") -DestinationPath $zipPath
    Write-Host " OK" -ForegroundColor Green
    Write-Host "  -> $zipPath ($([math]::Round((Get-Item $zipPath).Length / 1MB, 2)) MB)" -ForegroundColor Gray
    Write-ActionLog "Archive ZIP creee: $zipPath"
}

# PDF (B3) - Automatique par défaut en v3.1
$pdfPath = Join-Path $interventionPath "rapport.pdf"
$generatePDF = $GeneratePDF -and -not $NoPDF
if ($generatePDF) {
    Write-Host "[PDF] Generation du PDF..." -NoNewline
    $wkhtmltopdf = Get-Command wkhtmltopdf -ErrorAction SilentlyContinue
    if ($wkhtmltopdf) {
        try {
            & $wkhtmltopdf.Source --enable-local-file-access --quiet $reportPath $pdfPath 2>&1 | Out-Null
            if (Test-Path $pdfPath) {
                Write-Host " OK" -ForegroundColor Green
                Write-ActionLog "PDF genere: $pdfPath"
            }
            else {
                Write-Host " ECHEC" -ForegroundColor Red
                Write-ActionLog "PDF: echec generation"
            }
        }
        catch {
            Write-Host " ERREUR" -ForegroundColor Red
            Write-ActionLog "PDF: $($_.Exception.Message)"
        }
    }
    else {
        Write-Host " wkhtmltopdf non disponible" -ForegroundColor Yellow
        Write-ActionLog "PDF: wkhtmltopdf introuvable"
    }
}

# Upload dashboard
if ($DashboardUploadUrl) {
    Write-Host "[UPLOAD] Envoi vers le dashboard $DashboardUploadUrl..." -NoNewline
    if (Test-Path -LiteralPath $zipPath) {
        try {
            $form = @{ file = Get-Item $zipPath; client_name = $ClientName }
            if ($UploadApiKey) { $form.upload_key = $UploadApiKey }
            $headers = @{}
            if ($UploadApiKey) { $headers["X-Upload-Key"] = $UploadApiKey }
            $response = Invoke-RestMethod -Uri $DashboardUploadUrl -Method Post -Form $form -Headers $headers
            Write-Host " OK" -ForegroundColor Green
            Write-ActionLog "Upload dashboard reussi"
        }
        catch {
            Write-Host " ECHEC" -ForegroundColor Red
            "Upload dashboard echoue: $($_.Exception.Message)" | Out-File -FilePath (Join-Path $interventionPath "upload_error.txt") -Encoding utf8
            Write-ActionLog "Upload dashboard echoue: $($_.Exception.Message)"
        }
    }
    else {
        Write-Host " ECHEC (ZIP introuvable)" -ForegroundColor Red
        "Upload dashboard echoue: archive ZIP introuvable" | Out-File -FilePath (Join-Path $interventionPath "upload_error.txt") -Encoding utf8
        Write-ActionLog "Upload dashboard echoue: ZIP introuvable"
    }
}

# ===== EXPORTS CSV/JSON (v5.0) =====
if ($ExportCSV) {
    Write-Host "[EXPORT] Generation CSV..." -NoNewline
    $csvPath = Join-Path $interventionPath "inventory.csv"
    $inventory | ConvertTo-Csv -NoTypeInformation -Encoding UTF8 | Out-File -FilePath $csvPath -Encoding utf8
    Write-Host " OK" -ForegroundColor Green
    Write-ActionLog "Export CSV genere: $csvPath"
}

if ($ExportJSON) {
    Write-Host "[EXPORT] Export JSON deja genere (inventory.json, blackbox.json)" -ForegroundColor Gray
}

# ===== MODE SILENCIEUX (v5.0) =====
if ($SilentMode) {
    Write-Host "[MODE SILENCIEUX] Intervention terminee sans interaction" -ForegroundColor Gray
    Write-ActionLog "Mode silencieux active - intervention terminee"
    exit 0
}

# ===== FIN =====
Write-ActionLog "Intervention terminee"
Write-Host ""
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "   INTERVENTION TERMINEE" -ForegroundColor Green
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Client        : $ClientName" -ForegroundColor White
Write-Host "Score sante   : $($inventory.health.global_score)/100" -ForegroundColor White
Write-Host "Risque disque : $($inventory.disk_risk.level)" -ForegroundColor $(if($inventory.disk_risk.level -eq "healthy"){"Green"}elseif($inventory.disk_risk.level -eq "attention"){"Yellow"}elseif($inventory.disk_risk.level -eq "suspect"){"Yellow"}else{"Red"})
Write-Host "Risque donnees: $($inventory.health.data_loss_risk)" -ForegroundColor White
Write-Host "Sauvegarde    : $(if($backup.performed){"Effectuee"}elseif($readOnlyMode){"BLOQUEE (mode lecture seule)"}else{"Non demandee"})" -ForegroundColor $(if($backup.performed){"Green"}else{"Yellow"})
Write-Host ""
Write-Host "Dossier       : $interventionPath" -ForegroundColor White
if ($CreateZip -or $DashboardUploadUrl) { Write-Host "Archive       : $interventionPath.zip" -ForegroundColor White }
Write-Host ""
Write-Host "Rapport HTML  : $reportPath" -ForegroundColor White
Write-Host "Actions log   : $actionLogPath" -ForegroundColor White
Write-Host ""
