[CmdletBinding()]
param(
    [ValidatePattern('^COM[0-9]+$')][string]$Port = 'COM6',
    [ValidateRange(1, 300)][int]$Seconds = 15,
    [ValidateRange(1200, 3000000)][int]$BaudRate = 115200,
    [switch]$SendEnter
)
$ErrorActionPreference = 'Stop'
$serial = [System.IO.Ports.SerialPort]::new($Port, $BaudRate, 'None', 8, 'One')
$serial.Handshake = 'None'
$serial.DtrEnable = $false
$serial.RtsEnable = $false
$received = $false
try {
    $serial.Open()
    if ($SendEnter) { $serial.Write("`r") }
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    while ($timer.Elapsed.TotalSeconds -lt $Seconds) {
        $data = $serial.ReadExisting()
        if ($data.Length -gt 0) {
            $received = $true
            [Console]::Write($data)
        }
        Start-Sleep -Milliseconds 100
    }
    if (-not $received) {
        Write-Warning "No console output on $Port. Check board power, boot media and console mapping."
    }
} finally {
    if ($serial.IsOpen) { $serial.Close() }
    $serial.Dispose()
}
