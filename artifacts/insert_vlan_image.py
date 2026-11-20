from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from xml.dom import minidom
import shutil
import struct

root = Path(__file__).resolve().parent.parent
target = root / 'AI helper.docx'
image = root / 'artifacts/vlan-port-types.png'
backup = root / 'backups/AI helper.before-vlan-image-20261117.docx'
with ZipFile(target) as z:
    parts = {i.filename: (i, z.read(i.filename)) for i in z.infolist()}
doc = minidom.parseString(parts['word/document.xml'][1])
ns = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
ps = doc.getElementsByTagNameNS(ns, 'p')
matches = [p for p in ps if ''.join(t.firstChild.data for t in p.getElementsByTagNameNS(ns, 't') if t.firstChild).startswith('The connection between the switch and STM32 is called a')]
assert len(matches) == 1
rels = minidom.parseString(parts['word/_rels/document.xml.rels'][1])
ids = {e.getAttribute('Id') for e in rels.documentElement.childNodes if e.nodeType == e.ELEMENT_NODE}
rid = 'rIdVlanPortTypes'
assert rid not in ids
rel = rels.createElement('Relationship')
for k,v in {'Id':rid, 'Type':'http://schemas.openxmlformats.org/officeDocument/2006/relationships/image', 'Target':'media/vlan-port-types.png'}.items(): rel.setAttribute(k,v)
rels.documentElement.appendChild(rel)
data = image.read_bytes()
w,h = struct.unpack('>II', data[16:24])
section = doc.getElementsByTagNameNS(ns, 'sectPr')[-1]
size = section.getElementsByTagNameNS(ns, 'pgSz')[0]
margin = section.getElementsByTagNameNS(ns, 'pgMar')[0]
width = min(6*914400, (int(size.getAttribute('w:w')) - int(margin.getAttribute('w:left')) - int(margin.getAttribute('w:right'))) * 635)
height = round(width*h/w)
existing_ids = [int(e.getAttribute('id')) for e in doc.getElementsByTagNameNS('http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing','docPr')]
did = max(existing_ids+[0])+1
xml = f'''<w:p xmlns:w="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><w:pPr><w:jc w:val="center"/><w:spacing w:before="120" w:after="120"/></w:pPr><w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{width}" cy="{height}"/><wp:docPr id="{did}" name="VLAN Port Types: Trunk vs. Access" descr="Diagram comparing access ports carrying untagged traffic for one VLAN with trunk ports carrying tagged traffic for multiple VLANs."/><wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic><pic:nvPicPr><pic:cNvPr id="0" name="vlan-port-types.png"/><pic:cNvPicPr/></pic:nvPicPr><pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{width}" cy="{height}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>'''
node = doc.importNode(minidom.parseString(xml).documentElement, True)
p = matches[0]
p.parentNode.insertBefore(node, p.nextSibling)
ct = minidom.parseString(parts['[Content_Types].xml'][1])
if not any(e.getAttribute('Extension') == 'png' for e in ct.documentElement.childNodes if e.nodeType == e.ELEMENT_NODE):
    e = ct.createElement('Default'); e.setAttribute('Extension','png'); e.setAttribute('ContentType','image/png'); ct.documentElement.appendChild(e)
shutil.copy2(target, backup)
temp = target.with_suffix('.vlan-tmp.docx')
changes = {'word/document.xml': doc.toxml(encoding='UTF-8'), 'word/_rels/document.xml.rels': rels.toxml(encoding='UTF-8'), '[Content_Types].xml': ct.toxml(encoding='UTF-8')}
with ZipFile(temp, 'w', ZIP_DEFLATED) as z:
    for name,(info,content) in parts.items(): z.writestr(info, changes.get(name,content))
    z.writestr('word/media/vlan-port-types.png',data)
with ZipFile(temp) as z:
    assert z.testzip() is None
    assert z.read('word/media/vlan-port-types.png') == data
    for name in changes: minidom.parseString(z.read(name))
temp.replace(target)
print(f'Inserted image after trunk explanation; size {width/914400:.2f} x {height/914400:.2f} inches. Backup: {backup}')
