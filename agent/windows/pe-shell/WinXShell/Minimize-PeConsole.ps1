# Minimise la fenetre CMD session WinPE (parent), sans la fermer.
$ErrorActionPreference = "SilentlyContinue"
try {
    Add-Type -Namespace PeUi -Name Native -MemberDefinition @"
[DllImport("user32.dll")] public static extern bool ShowWindowAsync(System.IntPtr hWnd, int nCmdShow);
"@
    $ppid = (Get-CimInstance Win32_Process -Filter "ProcessId=$PID").ParentProcessId
    if ($ppid) {
        $h = (Get-Process -Id $ppid -EA Stop).MainWindowHandle
        if ($h -ne [IntPtr]::Zero) {
            [PeUi.Native]::ShowWindowAsync($h, 2) | Out-Null  # SW_MINIMIZE
        }
    }
} catch {}
