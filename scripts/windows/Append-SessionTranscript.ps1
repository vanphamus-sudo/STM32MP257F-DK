[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$SessionPath,
    [Parameter(Mandatory=$true)][string]$DocumentPath,
    [Parameter(Mandatory=$true)][string]$PhotoPath,
    [string]$CutoffText = 'Copy all the Codex conversations in this session and append them to AI helper.docx'
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
Add-Type -AssemblyName System.Drawing
$target = (Resolve-Path -LiteralPath $DocumentPath).Path
$photo = (Resolve-Path -LiteralPath $PhotoPath).Path
$records = Get-Content -Encoding UTF8 -LiteralPath $SessionPath | ForEach-Object { $_ | ConvertFrom-Json }
$messages = [Collections.Generic.List[object]]::new()
$started = $false
$cutoffFound = $false
foreach ($record in $records) {
    if ($record.type -ne 'response_item') { continue }
    $payload = $record.payload
    if ($started -and $payload.type -eq 'function_call' -and $payload.name -eq 'request_user_input_async') {
        $questions = ($payload.arguments | ConvertFrom-Json).questions
        foreach ($question in $questions) {
            $messages.Add([pscustomobject]@{Speaker='Codex - question';Text=$question.title;Photo=$false})
        }
        continue
    }
    if ($payload.type -ne 'message' -or $payload.role -notin @('user','assistant')) { continue }
    if ($payload.channel -eq 'analysis' -or $payload.phase -eq 'analysis') { continue }
    $text = (($payload.content | Where-Object { $_.type -in @('input_text','output_text') } | ForEach-Object {$_.text}) -join "`n").Trim()
    if (-not $started) {
        if ($payload.role -eq 'user' -and $text.StartsWith('I want to start the router software project')) { $started = $true }
        else { continue }
    }
    $hasPhoto = @($payload.content | Where-Object { $_.type -eq 'input_image' }).Count -gt 0
    if ($text.StartsWith('<send_user_message_question_reply>')) {
        $json = $text -replace '(?s)^<send_user_message_question_reply>\s*','' -replace '\s*</send_user_message_question_reply>\s*$',''
        $text = (($json | ConvertFrom-Json) | ForEach-Object { $_.answer }) -join "`n"
    }
    if ($hasPhoto) {
        # Strip application attachment wrappers, retaining the user's words and attachment name.
        $match = [regex]::Match($text, '(?s)## My request:\s*(.*?)\s*<image')
        if ($match.Success) { $text = $match.Groups[1].Value.Trim() }
        $text += "`n`nAttachment: 20260923_110308.jpg"
    }
    $text = [Net.WebUtility]::HtmlDecode($text)
    $speaker = if ($payload.role -eq 'user') { 'User' } elseif ($payload.phase -eq 'commentary') { 'Codex - progress update' } else { 'Codex' }
    $messages.Add([pscustomobject]@{Speaker=$speaker;Text=$text;Photo=$hasPhoto})
    if ($payload.role -eq 'user' -and $text.Trim() -eq $CutoffText) { $cutoffFound = $true; break }
}
if (-not $started -or -not $cutoffFound) { throw 'Could not identify the complete requested conversation boundary.' }
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$folder = Split-Path -Parent $target
$backupFolder = Join-Path $folder 'backups'
New-Item -ItemType Directory -Path $backupFolder -Force | Out-Null
$backup = Join-Path $backupFolder "AI helper.before-codex-session-$stamp.docx"
$pending = Join-Path $folder "AI helper.append-pending-$stamp.docx"
$manifest = Join-Path $folder 'logs\codex-session-transcript.json'
New-Item -ItemType Directory -Path (Split-Path $manifest) -Force | Out-Null
$messages | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 -LiteralPath $manifest

# Keep an immutable original and edit a separate ZIP package before replacement.
Copy-Item -LiteralPath $target -Destination $backup
Copy-Item -LiteralPath $target -Destination $pending
$zip = [IO.Compression.ZipFile]::Open($pending, [IO.Compression.ZipArchiveMode]::Update)
function Read-ZipXml([string]$name) {
    $entry = $zip.GetEntry($name)
    $reader = [IO.StreamReader]::new($entry.Open(), [Text.Encoding]::UTF8)
    try { $doc = [xml]::new(); $doc.PreserveWhitespace=$true; $doc.LoadXml($reader.ReadToEnd()); return ,$doc }
    finally { $reader.Dispose() }
}
function Write-ZipXml([string]$name, [xml]$doc) {
    $old = $zip.GetEntry($name)
    if ($old) { $old.Delete() }
    $entry = $zip.CreateEntry($name)
    $stream = $entry.Open()
    $settings = [Xml.XmlWriterSettings]::new()
    $settings.Encoding = [Text.UTF8Encoding]::new($false)
    $writer = [Xml.XmlWriter]::Create($stream, $settings)
    try { $doc.Save($writer) } finally { $writer.Dispose(); $stream.Dispose() }
}
$wns = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
try {
    $document = Read-ZipXml 'word/document.xml'
    $body = $document.SelectSingleNode('/*[local-name()="document"]/*[local-name()="body"]')
    $originalNodes = @($body.ChildNodes | ForEach-Object { $_.OuterXml })
    $section = $body.SelectSingleNode('./*[local-name()="sectPr"]')
    function Add-BodyNode($node) {
        if ($section) { [void]$body.InsertBefore($node,$section) } else { [void]$body.AppendChild($node) }
    }
    function Add-Paragraph([string]$text, [bool]$bold=$false, [int]$size=22) {
        $p = $document.CreateElement('w','p',$wns)
        $run = $document.CreateElement('w','r',$wns)
        $props = $document.CreateElement('w','rPr',$wns)
        if ($bold) { [void]$props.AppendChild($document.CreateElement('w','b',$wns)) }
        $sz = $document.CreateElement('w','sz',$wns); [void]$sz.SetAttribute('val',$wns,[string]$size); [void]$props.AppendChild($sz)
        [void]$run.AppendChild($props)
        $t = $document.CreateElement('w','t',$wns)
        [void]$t.SetAttribute('space','http://www.w3.org/XML/1998/namespace','preserve')
        $t.InnerText = $text
        [void]$run.AppendChild($t); [void]$p.AppendChild($run)
        Add-BodyNode $p
    }
    $pageBreak = $document.CreateElement('w','p',$wns)
    $r = $document.CreateElement('w','r',$wns)
    $br = $document.CreateElement('w','br',$wns); [void]$br.SetAttribute('type',$wns,'page')
    [void]$r.AppendChild($br); [void]$pageBreak.AppendChild($r); Add-BodyNode $pageBreak
    Add-Paragraph 'Codex session transcript - 23 September 2026' $true 32
    Add-Paragraph 'STM32MP257F-DK LTE router project' $true 26
    Add-Paragraph 'Chronological user messages, Codex replies and progress updates, through the request to append this transcript. Original Markdown notation is retained. The attached board photo is included.'
    Add-Paragraph ''

    $relationships = Read-ZipXml 'word/_rels/document.xml.rels'
    $relNs = 'http://schemas.openxmlformats.org/package/2006/relationships'
    $imageRel = 'rIdCodexSessionPhoto' + $stamp.Replace('-','')
    $imageName = 'codex-session-board-' + $stamp + '.jpg'
    $imageEntry = $zip.CreateEntry('word/media/' + $imageName)
    $photoStream = [IO.File]::OpenRead($photo); $destStream = $imageEntry.Open()
    try { $photoStream.CopyTo($destStream) } finally { $photoStream.Dispose(); $destStream.Dispose() }
    $rel = $relationships.CreateElement('Relationship',$relNs)
    $rel.SetAttribute('Id',$imageRel)
    $rel.SetAttribute('Type','http://schemas.openxmlformats.org/officeDocument/2006/relationships/image')
    $rel.SetAttribute('Target','media/' + $imageName)
    [void]$relationships.DocumentElement.AppendChild($rel)
    $types = Read-ZipXml '[Content_Types].xml'
    if (-not $types.SelectSingleNode('/*[local-name()="Types"]/*[local-name()="Default" and @Extension="jpg"]')) {
        $item = $types.CreateElement('Default','http://schemas.openxmlformats.org/package/2006/content-types')
        $item.SetAttribute('Extension','jpg'); $item.SetAttribute('ContentType','image/jpeg')
        [void]$types.DocumentElement.AppendChild($item)
    }
    $bitmap = [Drawing.Image]::FromFile($photo)
    try { $width = $bitmap.Width; $height = $bitmap.Height } finally { $bitmap.Dispose() }
    $cx = 5000000; $cy = [long]($cx * $height / $width)
    $drawingId = 1
    foreach ($node in $document.SelectNodes('//*[local-name()="docPr"]')) { $drawingId = [Math]::Max($drawingId, [int]$node.GetAttribute('id') + 1) }
    $index = 0
    foreach ($message in $messages) {
        $index++
        Add-Paragraph ("{0}. {1}" -f $index,$message.Speaker) $true 24
        foreach ($line in ($message.Text -split "`r?`n")) { Add-Paragraph $line }
        if ($message.Photo) {
            $photoXml = @"
<w:p xmlns:w="$wns" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><w:r><w:drawing><wp:inline xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" distT="0" distB="0" distL="0" distR="0"><wp:extent cx="$cx" cy="$cy"/><wp:docPr id="$drawingId" name="Board photo from Codex session"/><wp:cNvGraphicFramePr/><a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:nvPicPr><pic:cNvPr id="0" name="20260923_110308.jpg"/><pic:cNvPicPr/></pic:nvPicPr><pic:blipFill><a:blip r:embed="$imageRel"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="$cx" cy="$cy"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>
"@
            $fragment = $document.CreateDocumentFragment(); $fragment.InnerXml = $photoXml
            Add-BodyNode $fragment
        }
        Add-Paragraph ''
    }
    Write-ZipXml 'word/document.xml' $document
    Write-ZipXml 'word/_rels/document.xml.rels' $relationships
    Write-ZipXml '[Content_Types].xml' $types
} finally { $zip.Dispose() }

# Validate that the document opens as XML and original body nodes remain intact.
$check = [IO.Compression.ZipFile]::OpenRead($pending)
try {
    $reader = [IO.StreamReader]::new($check.GetEntry('word/document.xml').Open())
    try { $verified = [xml]::new(); $verified.PreserveWhitespace=$true; $verified.LoadXml($reader.ReadToEnd()) } finally { $reader.Dispose() }
    $verifiedBody = $verified.SelectSingleNode('/*[local-name()="document"]/*[local-name()="body"]')
    $newNodes = @($verifiedBody.ChildNodes | ForEach-Object {$_.OuterXml})
    $originalWithoutSection = @($originalNodes | Where-Object { $_ -notmatch '^<w:sectPr\b' })
    for ($n=0; $n -lt $originalWithoutSection.Count; $n++) {
        if ($originalWithoutSection[$n] -ne $newNodes[$n]) { throw "Original document content changed at node $n" }
    }
    $plain = ($verified.SelectNodes('//*[local-name()="t"]') | ForEach-Object {$_.InnerText}) -join "`n"
    if (-not $plain.Contains($CutoffText) -or -not $plain.Contains('53.3 Mbps')) { throw 'Transcript validation failed.' }
    if (-not $check.GetEntry('word/media/' + $imageName)) { throw 'Attached photo missing.' }
} finally { $check.Dispose() }
[IO.File]::Replace($pending, $target, $backup)
[pscustomobject]@{Document=$target;Backup=$backup;Messages=$messages.Count;OriginalBodyNodes=$originalNodes.Count;Bytes=(Get-Item $target).Length;TranscriptJson=$manifest} | ConvertTo-Json
