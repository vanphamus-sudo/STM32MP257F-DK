param([int]$Seconds = 75, [string]$OutputFile = 'logs/ab-boot.log', [switch]$Interrupt)
$ErrorActionPreference = 'Stop'
$serial = [IO.Ports.SerialPort]::new('COM6', 115200, 'None', 8, 'One')
$serial.DtrEnable = $false
$serial.RtsEnable = $false
$serial.Handshake = 'None'
$all = [Text.StringBuilder]::new()
$interrupted = $false
try {
    $serial.Open()
    $timer = [Diagnostics.Stopwatch]::StartNew()
    while ($timer.Elapsed.TotalSeconds -lt $Seconds) {
        $chunk = $serial.ReadExisting()
        if ($chunk) {
            [void]$all.Append($chunk)
            if ($Interrupt -and -not $interrupted -and $all.ToString().Contains('Hit any key')) {
                $serial.Write(' ')
                $interrupted = $true
            }
        }
        Start-Sleep -Milliseconds 50
    }
} finally {
    if ($serial.IsOpen) { $serial.Close() }
    $serial.Dispose()
    [IO.File]::WriteAllText((Join-Path (Get-Location) $OutputFile), $all.ToString())
}
$text = $all.ToString()
if ($text.Length -gt 7000) { $text.Substring($text.Length - 7000) } else { $text }
