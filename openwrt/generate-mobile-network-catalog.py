"""Generate the offline E.212 catalog from positioned ITU OB1280 table text.

Usage: python openwrt/generate-mobile-network-catalog.py POSITIONED_JSON PDF OUTPUT
Positioned JSON is a list of pages (PDF pages 3-73), each containing pypdf
visitor_text records {text,x,y}; ignore blank fragments. Positions retain table
columns and wrapped names. This parser is specific to the cited 2023 edition.
"""
import json,re,hashlib,sys
from pathlib import Path
pages=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
networks={};countries={};country=None;cparts=[];parts=[];code=[];code_y=None

def flush():
 global code
 if not code:return
 digits=''.join(code).replace(' ','');code=[]
 if not re.fullmatch(r'\d{5,6}',digits):raise ValueError(digits)
 mcc,mnc=digits[:3],digits[3:]
 name=' '.join(parts);parts.clear()
 if not country or not name:raise ValueError((digits,country,name))
 countries.setdefault(mcc,set()).add(country)
 if digits in networks and networks[digits]['name']!=name:name=networks[digits]['name']+' / '+name
 networks[digits]=dict(mcc=mcc,mnc=mnc,name=name)
for page in pages:
 footnote=False
 for t in page:
  text=t['text'].strip();x,y=t['x'],t['y']
  if y<50 or not text or text.startswith(('Country or','Geographical Area','Networks','MCC + MNC','Mobile Network Codes')):continue
  if x>=430 and re.fullmatch(r'[0-9 ]+',text):
   if code and abs(y-code_y)>1:flush()
   code.append(text);code_y=y;continue
  flush()
  if x<150:
   if text.startswith('*'):footnote=True
   if not footnote:cparts.append(text)
  elif 150<=x<430:
   if cparts:country=' '.join(cparts);cparts=[]
   parts.append(text)
 flush()
print('records',len(networks))
assert networks['50501']['name']=='Telstra Corporation Ltd.'
assert networks['50557']['name']=='CiFi Pty Ltd'
assert networks['310260']['mnc']=='260'
result=dict(version=1,source=dict(url='https://www.itu.int/dms_pub/itu-t/opb/sp/T-SP-E.212B-2023-PDF-E.pdf',edition='2023-11-15',retrieved='2026-11-12',sha256=hashlib.sha256(Path(sys.argv[2]).read_bytes()).hexdigest()),countries=[dict(mcc=mcc,name=' / '.join(sorted(names)),networks=[dict(mnc=n['mnc'],name=n['name']) for n in sorted(networks.values(),key=lambda n:n['mnc']) if n['mcc']==mcc]) for mcc,names in sorted(countries.items(),key=lambda x:(' / '.join(sorted(x[1])),x[0]))])
Path(sys.argv[3]).write_text(json.dumps(result,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
print(json.dumps(dict(mcc_entries=len(countries),networks=len(networks),australia=[n for n in result['countries'] if n['mcc']=='505'][0]['name'])))
