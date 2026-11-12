const fs = require('fs');
const path = require('path');
const base = path.resolve(__dirname, '../docs/windows-ethernet-usb-lte-private-network');
const lines = fs.readFileSync(base + '.md', 'utf8').split(/\r?\n/);
const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const inline = s => esc(s).replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>').replace(/\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g, '<a href="$2">$1</a>');
let body = '', i = 0;
while (i < lines.length) {
  const s = lines[i];
  if (!s.trim()) { i++; continue; }
  if (s.startsWith('```')) {
    const code = []; i++;
    while (i < lines.length && !lines[i].startsWith('```')) code.push(lines[i++]);
    i++; body += '<pre><code>' + esc(code.join('\n')) + '</code></pre>'; continue;
  }
  if (/^#{1,6} /.test(s)) {
    const n = s.match(/^#+/)[0].length;
    body += `<h${n}>${inline(s.slice(n + 1))}</h${n}>`; i++; continue;
  }
  if (s.startsWith('|')) {
    const rows = [];
    while (i < lines.length && lines[i].startsWith('|')) rows.push(lines[i++].split('|').slice(1,-1).map(x => x.trim()));
    body += '<table><thead><tr>' + rows[0].map(x => '<th>' + inline(x) + '</th>').join('') + '</tr></thead><tbody>';
    for (const row of rows.slice(2)) body += '<tr>' + row.map(x => '<td>' + inline(x) + '</td>').join('') + '</tr>';
    body += '</tbody></table>'; continue;
  }
  if (s.startsWith('- ')) {
    body += '<ul>';
    while (i < lines.length && lines[i].startsWith('- ')) body += '<li>' + inline(lines[i++].slice(2)).replace(/^\[ \]/, '☐') + '</li>';
    body += '</ul>'; continue;
  }
  const para = [s]; i++;
  while (i < lines.length && lines[i].trim() && !/^(#|\||```|- )/.test(lines[i])) para.push(lines[i++]);
  body += '<p>' + inline(para.join(' ')) + '</p>';
}
fs.writeFileSync(base + '.html', `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Windows Ethernet and USB LTE Private Network Setup</title><style>
@page {size:A4; margin:17mm 15mm 18mm;}
body {font-family:Arial,sans-serif;font-size:10pt;line-height:1.45;color:#202b36;}
h1 {font-size:23pt;line-height:1.2;color:#143e60;margin:0 0 16pt;}
h2 {font-size:15pt;color:#143e60;margin:22pt 0 9pt;border-bottom:1px solid #c4d4df;padding-bottom:5pt;break-after:avoid;}
h3 {font-size:11pt;margin:15pt 0 6pt;break-after:avoid;}
p {margin:7pt 0;} li {margin:4pt 0;} ul {padding-left:18pt;}
code {font-family:Consolas,monospace;font-size:8.4pt;}
pre {background:#f0f4f7;border:1px solid #d4dfe7;border-left:3px solid #42789c;padding:9pt;white-space:pre-wrap;overflow-wrap:anywhere;break-inside:avoid;line-height:1.4;}
table {border-collapse:collapse;width:100%;font-size:8.5pt;margin:10pt 0;}
thead {display:table-header-group;} tr {break-inside:avoid;} th,td {border:1px solid #c9d4dd;padding:6pt;text-align:left;vertical-align:top;overflow-wrap:anywhere;}
th {background:#e6eef4;color:#143e60;} a {color:#155e91;text-decoration:none;}
</style></head><body>${body}</body></html>`);
console.log(base + '.html');
