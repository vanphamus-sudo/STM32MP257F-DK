[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$SessionPath,
    [Parameter(Mandatory=$true)][string]$DocumentPath
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem
Add-Type -AssemblyName System.IO.Compression
$target = (Resolve-Path -LiteralPath $DocumentPath).Path
$messages = [Collections.Generic.List[object]]::new()
$started = $false
$finished = $false
$cutoff = 'Append current Codex conversations to AI helper.docx'
foreach ($line in (Get-Content -LiteralPath $SessionPath -Encoding UTF8)) {
    $record = $line | ConvertFrom-Json
    if ($record.type -ne 'response_item') { continue }
    $p = $record.payload
    if ($started -and $p.type -eq 'function_call' -and $p.name -like '*request_user_input_async') {
        foreach ($question in ($p.arguments | ConvertFrom-Json).questions) {
            $text = $question.title
            if ($question.options) { $text += "`nOptions:`n" + (($question.options | ForEach-Object { '- ' + $_ }) -join "`n") }
            $messages.Add([pscustomobject]@{Speaker='Codex - question';Text=$text})
        }
        continue
    }
    if ($p.type -ne 'message' -or $p.role -notin @('user','assistant') -or $p.channel -eq 'analysis' -or $p.phase -eq 'analysis') { continue }
    $text = (($p.content | Where-Object {$_.type -in @('input_text','output_text')} | ForEach-Object {$_.text}) -join "`n").Trim()
    if (-not $started) {
        if ($p.role -eq 'user' -and $text -eq 'NetworkManager, DHCP and firewall services') { $started=$true }
        else { continue }
    }
    if ($text.StartsWith('<send_user_message_question_reply>')) {
        $json = $text -replace '(?s)^<send_user_message_question_reply>\s*','' -replace '\s*</send_user_message_question_reply>\s*$',''
        $text = (($json | ConvertFrom-Json | ForEach-Object { $_.answer }) -join "`n")
    }
    if (-not $text) { continue }
    $speaker = if ($p.role -eq 'user') {'User'} elseif ($p.channel -eq 'commentary' -or $p.phase -eq 'commentary') {'Codex - progress update'} else {'Codex'}
    $messages.Add([pscustomobject]@{Speaker=$speaker;Text=$text})
    if ($p.role -eq 'user' -and $text -eq $cutoff) { $finished=$true; break }
}
if (-not $started -or -not $finished) { throw 'Conversation boundaries were not found.' }
$folder = Split-Path $target
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path $folder "backups/AI helper.before-conversation-$stamp.docx"
$pending = Join-Path $folder "AI helper.pending-$stamp.docx"
$manifest = Join-Path $folder "logs/conversation-$stamp.json"
$messages | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $manifest -Encoding UTF8
Copy-Item -LiteralPath $target -Destination $backup
Copy-Item -LiteralPath $target -Destination $pending
$zip = [IO.Compression.ZipFile]::Open($pending, [IO.Compression.ZipArchiveMode]::Update)
$ns = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
try {
    $entry = $zip.GetEntry('word/document.xml')
    $reader = [IO.StreamReader]::new($entry.Open())
    try { $doc=[xml]::new(); $doc.PreserveWhitespace=$true; $doc.LoadXml($reader.ReadToEnd()) } finally { $reader.Dispose() }
    $body=$doc.SelectSingleNode('/*[local-name()="document"]/*[local-name()="body"]')
    $section=$body.SelectSingleNode('./*[local-name()="sectPr"]')
    $original=@($body.ChildNodes | Where-Object {$_.LocalName -ne 'sectPr'} | ForEach-Object {$_.OuterXml})
    function Add-Paragraph([string]$text, [bool]$bold=$false, [bool]$pageBreak=$false) {
        $p=$doc.CreateElement('w','p',$ns)
        if ($pageBreak) { $pr=$doc.CreateElement('w','pPr',$ns); [void]$pr.AppendChild($doc.CreateElement('w','pageBreakBefore',$ns)); [void]$p.AppendChild($pr) }
        $r=$doc.CreateElement('w','r',$ns)
        if ($bold) { $pr=$doc.CreateElement('w','rPr',$ns); [void]$pr.AppendChild($doc.CreateElement('w','b',$ns)); [void]$r.AppendChild($pr) }
        $t=$doc.CreateElement('w','t',$ns); $t.SetAttribute('space','http://www.w3.org/XML/1998/namespace','preserve') | Out-Null; $t.InnerText=$text
        [void]$r.AppendChild($t); [void]$p.AppendChild($r)
        if ($section) { [void]$body.InsertBefore($p,$section) } else { [void]$body.AppendChild($p) }
    }
    Add-Paragraph 'Codex conversation - 24 September 2026' $true $true
    Add-Paragraph 'STM32MP257F-DK: router services, web settings and Wi-Fi hotspot' $true
    Add-Paragraph 'Chronological user messages, Codex replies, progress updates and interactive questions through the append request. Markdown notation is retained. Internal reasoning and tool execution logs are omitted.'
    $index=0
    foreach ($message in $messages) {
        $index++
        Add-Paragraph ("{0}. {1}" -f $index,$message.Speaker) $true
        foreach ($line in ($message.Text -split "`r?`n")) { Add-Paragraph $line }
        Add-Paragraph ''
    }
    $entry.Delete()
    $entry=$zip.CreateEntry('word/document.xml')
    $settings=[Xml.XmlWriterSettings]::new(); $settings.Encoding=[Text.UTF8Encoding]::new($false)
    $writer=[Xml.XmlWriter]::Create($entry.Open(),$settings)
    try { $doc.Save($writer) } finally { $writer.Dispose() }
} finally { $zip.Dispose() }
$check=[IO.Compression.ZipFile]::OpenRead($pending)
try {
    $reader=[IO.StreamReader]::new($check.GetEntry('word/document.xml').Open())
    try { $verified=[xml]::new(); $verified.PreserveWhitespace=$true; $verified.LoadXml($reader.ReadToEnd()) } finally {$reader.Dispose()}
    $nodes=@($verified.SelectSingleNode('/*[local-name()="document"]/*[local-name()="body"]').ChildNodes)
    for ($i=0;$i -lt $original.Count;$i++) { if ($original[$i] -ne $nodes[$i].OuterXml) {throw "Original content changed at paragraph $i"} }
    $plain=($verified.SelectNodes('//*[local-name()="t"]') | ForEach-Object {$_.InnerText}) -join "`n"
    foreach ($message in $messages) {
        if (-not $plain.Contains(($message.Text -replace "`r`n","`n"))) {throw 'Transcript content verification failed.'}
    }
} finally {$check.Dispose()}
[IO.File]::Replace($pending,$target,$backup)
[pscustomobject]@{Document=$target;Backup=$backup;Messages=$messages.Count;OriginalNodesPreserved=$original.Count;Bytes=(Get-Item $target).Length;Transcript=$manifest} | ConvertTo-Json
