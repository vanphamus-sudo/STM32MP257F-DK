"""Generate the review PDF; requires reportlab and pymupdf. No hardware changes."""
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.colors import HexColor, white
from reportlab.platypus import Table, TableStyle, Paragraph
from reportlab.lib.styles import ParagraphStyle
from xml.sax.saxutils import escape
import csv
import pymupdf

D=Path(__file__).resolve().parent
OUT=D/'lte-router-detailed-concept.pdf'
TMP=D/'lte-router-detailed-concept-body.pdf'
W,H=landscape(A3)
c=canvas.Canvas(str(TMP),pagesize=(W,H))
c.setTitle('STM32MP257F LTE router - concept and pin connection review')
INK=HexColor('#17334b'); BLUE=HexColor('#176b8a'); PALE=HexColor('#edf5f8'); RED=HexColor('#9d352d')
page=0; nets=[]
def text(x,y,s,size=11,bold=False,color=INK):
    c.setFillColor(color);c.setFont('Helvetica-Bold' if bold else 'Helvetica',size);c.drawString(x,y,s)
def start(title,sub=''):
    global page
    page+=1
    text(32,H-37,title,23,True)
    text(32,H-59,sub,10)
    c.setStrokeColor(BLUE);c.line(32,H-72,W-32,H-72)
def end():
    c.setStrokeColor(BLUE);c.line(32,45,W-32,45)
    text(32,28,'REV B | 18 Nov 2026 | Engineering concept - pin connections reviewed against sources; no ERC, PCB or hardware validation.',9)
    text(W-130,28,f'DESIGN {page:02}',10,True);c.showPage()
def para(x,y,w,s,size=11):
    p=Paragraph(s,ParagraphStyle('p',fontName='Helvetica',fontSize=size,leading=size*1.4,textColor=INK))
    _,h=p.wrap(w,H);p.drawOn(c,x,y-h);return y-h-12
def table(x,y,width,headers,rows,widths=None,size=10):
    style=ParagraphStyle('cell',fontName='Helvetica',fontSize=size,leading=size*1.3,textColor=INK)
    def cell(v):
        s=escape(str(v)).replace('\n','<br/>')
        if str(v).startswith('https://'):s=f'<link href="{escape(str(v))}" color="#176b8a">{s}</link>'
        return Paragraph(s,style)
    data=[[cell(v) for v in row] for row in [headers]+rows]
    t=Table(data,colWidths=[width*z for z in widths] if widths else [width/len(headers)]*len(headers))
    t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),HexColor('#d7e9ef')),('VALIGN',(0,0),(-1,-1),'TOP'),('GRID',(0,0),(-1,-1),.45,HexColor('#b1c8d0')),('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)]))
    _,h=t.wrap(width,H);assert y-h>57,(page,y,h);t.drawOn(c,x,y-h);return y-h-16
def box(x,y,w,h,title,lines=()):
    c.setFillColor(PALE);c.setStrokeColor(BLUE);c.roundRect(x,y,w,h,5,fill=1,stroke=1)
    text(x+12,y+h-23,title,12,True)
    for i,s in enumerate(lines):text(x+12,y+h-43-i*17,s,10)
def line(points,label='',x=0,y=0):
    c.setStrokeColor(BLUE);c.setLineWidth(1)
    p=c.beginPath();p.moveTo(*points[0])
    for a in points[1:]:p.lineTo(*a)
    c.drawPath(p)
    if label:text(x,y,label,9,True)
def resistor(x1,y,x2,label):
    mid=(x1+x2)/2;line([(x1,y),(mid-16,y)]);line([(mid+16,y),(x2,y)])
    c.setStrokeColor(BLUE);c.rect(mid-16,y-5,32,10);text(mid-34,y+13,label,9)
def cap(x,y,label):
    line([(x,y),(x,y-18)]);line([(x-9,y-18),(x+9,y-18)]);line([(x-9,y-23),(x+9,y-23)]);line([(x,y-23),(x,y-47)])
    ground(x,y-47);text(x+12,y-25,label,9)
def ground(x,y):
    line([(x,y),(x,y-6)]);line([(x-10,y-6),(x+10,y-6)]);line([(x-6,y-10),(x+6,y-10)]);line([(x-2,y-14),(x+2,y-14)])
def net(name,a,b,notes=''):
    nets.append([name,a,b,notes]);return [name,a,b,notes]

start('STM32MP257F LTE router - concept + detailed connections','Scope: custom board based on MB1605 C01; retain 4 GB LPDDR4 + 8 GB eMMC. LTE socket is M.2 B-key.')
box(415,485,355,205,'STM32MP257FAK3',[
    'Same RAM, eMMC, PMIC and oscillator circuits',
    'ETH1 -> 1 x gigabit Ethernet',
    'USB host -> LTE; USB DRD -> management/boot',
    'USART1 -> RS232 TX / RX / GND',
    'USART6 -> half-duplex RS485 D+ / D- / GND',
    'Independent hardware RESET + USER recovery',
    'External ST-Link debug pads; no onboard ST-Link'])
box(32,600,290,105,'12 V DC input (proposed)', ['Fuse / input TVS / reverse protection', '5 V system + separate 3.7 V LTE rails'])
box(32,420,290,135,'M.2 LTE: TE 2199119-3 socket',['Quectel EM060K-GL reference card','USB 2.0 + SIM + open-drain controls','MAIN + DIV cables connect to card RF ports','No LTE RF routing through motherboard'])
box(865,600,290,105,'Gigabit LAN',['RTL8211F-CG + 48F-01GYDXNL MagJack','Replicate dev-kit RGMII + rail circuits'])
box(865,420,290,135,'USB-C management / boot',['Retain DK DRP circuit on CN15','Independent of LTE host USB','Linux gadget + ROM download','Externally powered router'])
for pts in [[(322,650),(415,650)],[(322,490),(365,490),(365,540),(415,540)],[(770,650),(865,650)],[(770,540),(815,540),(815,490),(865,490)]]:line(pts)
box(32,190,350,160,'Concurrent Wi-Fi implementation A',['Radio A: original Murata 1YN, 2.4 GHz','Radio B: Murata 2AE, fixed to 5 GHz','SDMMC3 + repurposed SDMMC1 respectively','Two independent antennas, one per radio','Removes microSD; retains eMMC on SDMMC2','Single-module implementation B discussed on D13'])
box(415,190,355,160,'Serial / buttons / debug',['COM1 = port name, uses MPU USART1','COM2 = port name, uses MPU USART6','USART2 reserved as boot/debug console','No UART sharing with Bluetooth','PC5 recovery; PH6 orange indicator','BOOT[3:0]: 0010 eMMC / 0000 UART-USB'])
box(805,190,350,160,'Document conventions',['Solid wiring + pin tables define new connections','Original ST circuits follow as reference appendices','Same labels across sheets are electrically joined','DNP = footprint present, not populated','Candidate values require layout / load validation','Radio A/B option is not a verified firmware build'])
para(32,155,1120,'<b>Correction to Rev A:</b> the original Murata LBEE5KL1YN-814 is 2.4 GHz only. Concurrent operation needs additional radio hardware. A single concurrent Wi-Fi module is also possible; see D13. This package supplies reviewable circuits and inherited reference schematics, not a manufacturing release.',11)
end()

start('D02 - retained core, interfaces and pin allocation','Pin names / package balls below come from MB1605 sheet 3. VDDIO banks used here must stay at 3.3 V.')
rows=[
['U1','STM32MP257FAK3','VFBGA424; same processor / boot chain as kit'],
['U2','MT53E1G32D2FW-046 WT:C','32 Gbit = 4 GB LPDDR4; copy ST sheet 6 including power/termination'],
['U37','THGBMUG6C1LBAIL','64 Gbit = 8 GB eMMC; copy sheet 7 eMMC half; preserve A/B layout'],
['U26','STPMIC25APQR','Copy PMIC + all MPU power networks, sheets 4-5; do not simplify rails'],
['X1 / X2','32.768 kHz / 40 MHz','Same crystals and load networks as sheet 3; LPO output is PI8, not crystal pin'],
['U38 / J_ETH','RTL8211F-CG / 48F-01GYDXNL','Copy sheet 8; this RJ45 includes magnetics'],
['U40','LBEE5KL1YN-814','Retained 2.4 GHz SDIO radio; Bluetooth disabled'],
['U_WIFI5','Murata Type 2AE (LBEE5PK2AE family)','New 5 GHz SDIO radio; orderable suffix / firmware to qualify']]
y=table(32,742,1120,['Reference','Component','Implementation'],rows,[.12,.33,.55])
rows=[['COM1 TX / RX','USART1 PG14 N1 / PG15 K6','Was Bluetooth; remove BT UART connection'],['COM2 TX / RX / DE','USART6 PF13 P2 / PF14 P3 / PG5 R3','Remove expansion header ownership; use RTS/DE alternate function'],['Console TX / RX','USART2 PA4 AG17 / PA8 AA17','Retain as logic-level service pads; not either serial terminal'],['LTE OFF / RESET','PB7 C11 / PB8 D8','Freed camera pins -> MOSFET gates; asserted high'],['5 GHz EN / IRQ','PB9 F10 / PB10 B11','Freed camera pins; power domain and GPIO ownership review'],['Recovery / LED','PC5 AD10 / PH6 AF19','Preserve USER1 / LD9 firmware behavior']]
table(32,y,1120,['Function','MPU peripheral / ball','Change from kit'],rows,[.2,.42,.38],9)
end()

start('D03 - external power and regulator module connections','Prototype-level power implementation uses real regulator assemblies; production PCB can replace them after power design validation.')
box(40,545,210,120,'J_PWR / protected input',['1: +12 V nominal (9-16 V assumed)','2: GND; keyed locking connector','F1: 5 A time-delay, candidate','D_IN: SMBJ18CA after fuse'])
box(390,555,310,130,'PWR1: Pololu D24V90F5',['VIN -> protected input; GND -> GND','VOUT -> +5V_SYS; FB open (5 V)','ENABLE open (internally enabled)','PG: test pad only; no MCU direct tie','Internal reverse-polarity protection'])
box(825,555,310,130,'PWR2: Pololu D24V90F5',['VIN -> protected input; GND -> GND','VOUT -> +3V7_LTE','FB -> 36.0k 1% -> small VOUT pad','ENABLE open; PG -> test pad','Approx. 3.69 V; measure before LTE fit'])
line([(250,615),(390,615)]);line([(305,615),(305,720),(970,720),(970,685)])
cap(325,720,'C_IN 220uF / 35V')
line([(545,555),(545,495),(175,495)]);text(175,506,'+5V_SYS -> ST reference 5V_STLK net',11,True)
line([(980,555),(980,495),(760,495)]);text(760,506,'+3V7_LTE -> M.2 VCC banks',11,True)
cap(410,495,'C_SYS 100uF / 10V');cap(900,495,'C_LTE 2 x 220uF / 10V')
y=table(32,388,1120,['Circuit','Pin-level routing / sizing requirement'],[
['Power reference names','All inherited 5V_STLK labels become +5V_SYS. Omit onboard ST-Link power source. Do not connect USB cable VBUS to +5V_SYS. Retain DK power sequencing and PMIC interconnects.'],
['Prototype regulator connections','Use manufacturer pad labels VIN / GND / VOUT / FB / ENABLE / PG; no invented pin numbering. Use high-current output pads, not small feedback-adjacent VOUT pad.'],
['LTE local bypass','At socket pins 2/4 and 70/72/74: each bank has 220uF + 1uF + 100nF + 33pF + 10pF to GND. Fit 5.1V TVS footprint per modem reference; verify clamp/rail limits.'],
['Current / thermal validation','LTE rail design target >=3A continuous, >=4A burst. +5V_SYS target 5A capacity; actual core and radio loads must be measured. Regulator headline current is not a guaranteed enclosed-box rating.'],
['Input assumptions','12V / 5A regulated adapter is a starting point, not a measured consumption claim. Fuse, TVS pulse rating, connector and wiring must be coordinated. This is not a 24V industrial input design.'],
['New radio load','Check spare capacity of STPMIC25 3V3 / VDDIO outputs before attaching second radio. If margin is insufficient, add a qualified dedicated 3.3V regulator and its enable sequencing.']],[.2,.8],10)
end()

start('D04 - M.2 B-key LTE socket, SIM and direct RF connections','J_LTE: TE Connectivity 2199119-3, 3.2 mm B-key socket; reference card EM060K-GL (3042). Review standoff/thermal clearance.')
box(40,545,280,150,'U1 host / controls',['USBH_HS_DP AF21 -> J_LTE.7','USBH_HS_DM AG21 -> J_LTE.9','Keep TXRTUNE calibration resistor network','PB7 -> Q_OFF gate; PB8 -> Q_RST gate','USB 2.0 supports existing MBIM mode'])
box(450,525,290,185,'J_LTE / EM060K-GL',['2,4,70,72,74 -> +3V7_LTE','3,5,11,27,33,39,45,51,57,71,73 -> GND','7 USB_DP; 9 USB_DM; 67 RESET#','6 FULL_CARD_POWER_OFF#','30 RST / 32 CLK / 34 DATA / 36 VDD','MAIN -> LTE MAIN antenna cable','DRX/DIV -> LTE DIV antenna cable'])
box(870,545,270,150,'J_SIM / ISO 7816 contacts',['C1 VCC <-36; C5 GND -> GND','C2 RST <-30 through 22R','C3 CLK <-32 through 22R','C7 I/O <->34 through 22R','C6 VPP open; detection unused'])
line([(320,635),(450,635)]);line([(740,635),(870,635)])
y=table(32,475,1120,['Net','From','To / support'],[
net('LTE_USB_P/N','U1 AF21 / AG21','J_LTE 7 / 9','')[:3],
['USB protection','Host D+ / D-','Keep short test pads; use low-C USB ESD array footprint, no long stubs. Preserve host calibration from ST sheet 13.'],
['LTE_OFF','PB7 ->100R -> Q_OFF gate; 100k gate-GND','BSS138: pin1 G, pin2 S=GND, pin3 D=J_LTE.6. 10k from pin6 to 3.3V; high gate holds modem off.'],
['LTE_RESET','PB8 ->100R -> Q_RST gate; 100k gate-GND','BSS138: pin1 G, pin2 S=GND, pin3 D=J_LTE.67. Use internal 1.8V pull-up; no 3.3V pull-up on RESET#.'],
['SIM support','SIM DATA at socket','20k to USIM_VDD; 100nF VCC-GND; 33pF each DATA/CLK/RST to GND near socket. Low-C TVS array: qualify exact pin/package.'],
['Unused socket pins','1,8,10,20-26,28,29,31,35,37,38,40-65,66,68,69,75','Leave unused pins open, excluding GND/VCC/SIM/reset above. Pin60 coexistence is specifically unresolved; see D12. Pins12-19 are key notch, not contacts.']],[.16,.34,.5],9)
para(32,y,1120,'<b>Socket compatibility:</b> M.2 describes the connector, not universal electrical interchangeability. This 3.7V USB2 profile is for EM060K-GL. Other LTE cards require a card-specific supply/control review; do not insert arbitrary M.2 SSDs or WLAN cards. SIM socket mechanical part / contact-number mapping remains a BOM selection item.',10)
end()

start('D05 - external USB-C management and ROM recovery','Use original MB1605 USB3 DRP implementation to preserve known boot/gadget routing; reference appendix A08 carries complete support wiring.')
rows=[net('USB_DRD_P','U1 AF22 USB3DR_DP','U42 ECMF2-40A100N6 D+ IC','U42 D+ connector -> CN15 A6/B6'),net('USB_DRD_N','U1 AG22 USB3DR_DM','U42 ECMF2-40A100N6 D- IC','U42 D- connector -> CN15 A7/B7'),net('USB_HOST_P','U1 AF21 USBH_HS_DP','J_LTE.7','Direct host: USB2422 hub omitted'),net('USB_HOST_N','U1 AG21 USBH_HS_DM','J_LTE.9','Direct host: USB2422 hub omitted'),['USB Type-C / CC','CN15 A5 CC1 / B5 CC2','TCPP03-M20 + UCPD','Retain U50, FETs, current sense, protection, I2C and CC networks from sheet13'],['USB super-speed','U1 COMBOPHY TX1/RX1','FUSB340TMX -> CN15','Implementation A retains DK SS routing; reserved for management port, no LTE SS'],['VBUS sensing','CN15 VBUS / VBUSc','R219 140k / R220 10k -> PF10 AE5','Retain reference divider/filter and voltage limits'],['CN15 VBUS','DK source/sink power paths','Original switched +5V_SYS source path','External supply required; verify sink/source role and no input backfeed']]
y=table(32,742,1120,['Net / function','Source','Destination','Support / implementation'],rows,[.16,.27,.27,.3],10)
para(32,y,1120,'<b>ROM download path:</b> set BOOT[3:0]=0000, then press hardware RESET. CN15 is the MPU USB port, not the removed ST-Link USB port. USB boot also requires correct rail/clock/startup state. The installed image provides Linux USB Ethernet management on this controller.',12)
para(32,y-90,1120,'<b>If implementing the single PCIe Wi-Fi module:</b> COMBOPHY is reassigned to PCIe. External USB management then becomes USB 2.0 only, using USB3DR_DP/DM. Remove unused SuperSpeed mux/routing and validate bootloader/Type-C/device-tree changes. Do not connect the same COMBOPHY pins to both PCIe and USB3.',12)
end()

start('D06 - 3-pin RS232: real line transceiver and support capacitors','COM1 is TX / RX / GND, with no RTS/CTS or modem handshaking. Logic-level service console stays separate.')
box(50,505,250,140,'U1 / USART1',['PG14 / N1 = TX','PG15 / K6 = RX','3.3V I/O; remove Bluetooth UART','USART1 Linux console disabled'])
box(455,465,290,220,'U_RS232: MAX3232IPWR',['11 DIN1 <- TX; 14 DOUT1 -> TX terminal','13 RIN1 <- RX terminal; 12 ROUT1 -> RX','16 VCC=3V3; 15 GND','C1 100nF: pin1 to pin3','C2 100nF: pin4 to pin5','C3 100nF: pin2 to GND','C4 100nF: pin6 to GND','C5 100nF: pin16 to pin15'])
box(900,505,230,140,'J_RS232 (3 terminals)',['1 TX: output from router','2 RX: input to router','3 GND: signal reference','Cross TX/RX at peer'])
line([(300,595),(455,595)],'TX -> pin11',330,609);line([(455,550),(300,550)],'RX <- pin12',330,564)
line([(745,595),(900,595)],'pin14 -> TX',773,609);line([(900,550),(745,550)],'pin13 <- RX',773,564)
rows=[net('RS232_TX_LOGIC','U1 PG14 / N1','MAX3232.11 DIN1'),net('RS232_RX_LOGIC','MAX3232.12 ROUT1','U1 PG15 / K6'),net('RS232_TX_LINE','MAX3232.14 DOUT1','J_RS232.1 TX'),net('RS232_RX_LINE','J_RS232.2 RX','MAX3232.13 RIN1'),['Unused channel','MAX3232 pin10 DIN2','GND','Pin7 DOUT2 / pin9 ROUT2 open; pin8 RIN2 may open'],['Capacitor rating','Five 100nF X7R, >=16V','Place close to IC','Use non-polar caps, including V- to GND'],['Connector protection','TVS footprints on TX and RX','To signal/chassis return strategy','Use RS232-compatible bipolar standoff; ordinary 3.3V TVS is unsuitable']]
table(32,405,1120,['Net / support','From','To','Notes'],rows,[.2,.27,.27,.26],10)
end()

start('D07 - 3-pin RS485: half-duplex transceiver, direction and termination','COM2: D+ / D- / GND. Non-isolated base design; isolation needed if application ground offsets exceed transceiver rating.')
box(40,535,260,130,'U1 / USART6',['PF13 / P2 = TX','PF14 / P3 = RX','PG5 / R3 = RTS/DE','RS485 mode: DE active high'])
box(430,500,310,205,'U_RS485: THVD1450DR',['8 VCC=3V3; 5 GND','4 D <- TX; 1 R -> RX','2 /RE + 3 DE -> direction net','Direction ->10k -> GND','6 A (D+) ->10R -> J.1','7 B (D-) ->10R -> J.2','100nF bypass: pin8 to pin5'])
box(890,530,250,145,'J_RS485 (3 terminals)',['1 D+ (TI A / non-inverting)','2 D- (TI B / inverting)','3 signal GND','120R + jumper across J.1/J.2','At cable end only'])
line([(300,615),(430,615)],'TX / RX / DE',317,630);line([(740,615),(890,615)],'D+ / D-',787,630)
y=table(32,450,1120,['Net / part','From','To / value','Notes'],[
net('485_TX','U1 PF13 P2','U_RS485.4 D'),net('485_RX','U_RS485.1 R','U1 PF14 P3'),net('485_DIR','U1 PG5 R3','U_RS485.2 + .3','10k pulldown; driver disabled during reset'),
['485_D+','U_RS485.6 A','10R pulse-rated -> J_RS485.1','CDSOT23-SM712 pin1 at connector-side node'],['485_D-','U_RS485.7 B','10R pulse-rated -> J_RS485.2','CDSOT23-SM712 pin2 at connector-side node'],['D_TVS','CDSOT23-SM712.3','GND short return','TVS example, not a system surge certification'],['R_TERM + JP_TERM','J.1 ->120R -> jumper -> J.2','Fit jumper at bus end only','No external bias by default; receiver has fail-safe behavior'],['Optional slow-edge variant','THVD1410DR, pin-compatible','Qualify baud / rise time','Prefer for modest Modbus baud rates after BOM confirmation']],[.18,.24,.3,.28],10)
para(32,y,1120,'<b>Firmware requirement:</b> configure Linux serial RS485 (TIOCSRS485 / appropriate device-tree properties) so the UART controls direction through the last stop bit. A generic software GPIO toggle around writes is not a validated replacement. Current software defaults to a USB converter; add native-port selection and separate service ownership.',11)
end()

start('D08 - concurrent Wi-Fi A: two independent SDIO radios','Keep 2.4 GHz 1YN; add 5 GHz 2AE on the former microSD bus. eMMC stays on SDMMC2.')
rows=[['Radio','MPU ball / signal','Module pin','Support'],['2.4 GHz 1YN','A26 CLK / B26 CMD','20 / 22','Retain ST sheet12'],['2.4 GHz 1YN','C27 D0 / D25 D1 / C26 D2 / B27 D3','24 / 26 / 23 / 25','Original SDMMC3 bus'],['5 GHz 2AE','C21 SDMMC1_CK / C20 CMD','33 / 28','Series damping footprint; start 22R, tune'],['5 GHz 2AE','B21 D0 / C22 D1 / B19 D2 / C19 D3','30 / 29 / 32 / 31','47k CMD and D0..D3 pull-ups to3V3'],['5 GHz control','PB9 F10 / PB10 B11','4 WL_REG_EN / 52 WL_HOST_WAKE','Enable 100k pulldown; IRQ input'],['Low power clock','PI8 U5, LPO_32','2AE.5 LPO_IN + existing1YN.37','Validate output drive and timing with two loads']]
y=table(32,742,1120,rows[0],rows[1:],[.17,.38,.22,.23],10)
box(55,245,305,185,'U_WIFI24 / Murata 1YN',['LBEE5KL1YN-814; 2.4 GHz AP','VBAT30 / VIN_LDO31 / VIO36','Original caps and L9/L10 from sheet12','WL_REG_ON28 <- PG8 / L5','WL_HOST_WAKE27 -> PG11 / N2','BT_REG_ON14 -> GND (Bluetooth off)','ANT41 -> original match -> antenna A'])
box(440,245,305,185,'U_WIFI5 / Murata Type2AE',['CYW4373E; SDIO mode, fixed 5 GHz AP','VBAT3 ->3V3; VDDIO42 ->3V3','10uF +100nF at each supply','SR_VLX2 ->2.2uH ->VIN_LDO43','VIN_LDO43 ->4.7uF ->GND','WL_ANT22 -> RF network -> antenna B','Full straps and unused pins: D09'])
box(825,245,305,185,'Two Wi-Fi antennas',['A: 2.4 GHz capable, dedicated to1YN','B: 5 GHz capable, dedicated to2AE','Example: Molex146187 family','Each 50-ohm RF path / U.FL pigtail','Keep both away from LTE antennas','Gain/cable/enclosure must match approvals','No direct short or passive T of antenna ports'])
para(32,203,1120,'<b>Bus change:</b> omit microSD socket, card-detect and card protection load. Keep SDMMC1 I/O rail at fixed 3.3V; remove voltage-switching behavior and configure a non-removable SDIO device. Confirm bank rail and all alternate functions in TF-A / OP-TEE / U-Boot / Linux. Two radios do not imply two bands work in the existing firmware without driver and hostapd changes.',11)
end()

start('D09 - 5 GHz Type2AE support circuitry and straps','Source: Murata Type2AE hardware application note, July 2025 Rev4, figure2; use matching module revision / pin drawing.')
box(420,455,350,245,'U_WIFI5 / Type2AE, SDIO 3.3V',['3 VBAT ->3V3','42 VDDIO ->3V3','2 SR_VLX -> L_W5 ->43 VIN_LDO','L_W5: DFE201612E-2R2M, 2.2uH','4 WL_REG_EN <- PB9; 52 IRQ -> PB10','5 LPO_IN <- LPO_32','55 STRAP2 high; 54 STRAP1 low','56 STRAP0 low; 53 JTAG_SEL low','68 BT_REG_EN low; unused Bluetooth off','22 WL_ANT -> approved matching / antenna'])
line([(200,655),(420,655)],'3V3 -> pin3',260,669);cap(260,655,'10uF +100nF')
line([(200,535),(420,535)],'3V3 -> pin42',260,549);cap(260,535,'10uF +100nF')
line([(770,655),(990,655)],'pin43 VIN_LDO',800,669);cap(950,655,'4.7uF')
resistor(790,560,1100,'STRAP2:10k to3V3');text(795,530,'STRAP1 / STRAP0: each10k toGND',10)
rows=[['Ground pins','1,14,16,21,23,24,27,34,41,57,69-77','Solid GND plane and via pattern from module land pattern'],['Mode straps','[STRAP2:STRAP1:STRAP0] =100','3.3V SDIO host. Sampled at startup; do not copy 1.8V strap configuration.'],['USB pins46-50','Leave floating in SDIO mode','Do not add USB pulldowns or route to external connector'],['Remaining unconnected pins','Bluetooth PCM/UART and unused module signals','Leave per matching Murata pin table; no random tie-offs. Exact ordering suffix must be frozen before CAD.'],['RF path','Pin22 -> matching footprints -> 50-ohm trace -> connector','Copy vendor RF layout. Matching values depend on antenna/enclosure measurement; not finalized here.'],['BSP / firmware','CYW4373 SDIO firmware + module NVRAM / regulatory data','Use Type2AE-qualified binary/data. Confirm 5GHz AP firmware, DFS behavior and brcmfmac support on exact kernel.']]
table(32,405,1120,['Circuit','Connections','Implementation / limit'],rows,[.18,.38,.44],10)
end()

start('D10 - boot straps, separate buttons and external ST-Link pads','Default A35 eMMC boot: BOOT[3:0]=0010. Recovery download:0000. Signals referenced to target VDDIO, not probe power.')
rows=[['BOOT0 / BOOT1 / BOOT2 / BOOT3','Y3 / AA3 / AB1 / AB2','Each10k default pull; BOOT1 high, others low; each3-pad override selects GND or VDDIO through1k'],['HW_RESET: B1','U1 AE1 NRST + U26.31 RSTn','10k toVDDIO, 10nF toGND, momentary switch toGND; ESDZL5-1F4 as reference'],['NRSTC1MS','U1 W3 -> R59(0R) -> U26.54 PWRCTRL3; U37 K5 RSTn','Retain original sheet3/4/7 network and R27210k toPWR_CPU_ON; do not merge with NRST'],['SW_RECOVERY: B5','VDDIO -> button -> raw node ->330R -> PC5 AD10','Raw node100k toGND and ESD; PC5 side100nF toGND; copy ST sheet17 topology'],['Recovery indicator','PH6 AF19 -> Si1062X gate1','Gate100k toGND; source2 GND; drain3 LED cathode; LED anode via300R to3V3'],['PMIC power button','STPMIC25.1 PONKEYn','Retain B2 toGND and PMIC behavior; it is separate from PC5 recovery and NRST']]
y=table(32,742,1120,['Function','Pins','Support'],rows,[.23,.32,.45],10)
rows=[['1','VTref','Target3.3V VDDIO; sense only'],['2','GND','TargetGND'],['3','SWDIO / JTMS','U1 AE2'],['4','SWCLK / JTCK','U1 AA5'],['5','JTDI','U1 AE3'],['6','JTDO / SWO','U1 AC2'],['7','NJTRST','U1 AF3; ensure external probe exposes this signal'],['8','NRST','U1 AE1'],['9 / 10','ConsoleTX / RX','USART2 PA4 AG17 / PA8 AA17; optional separate pads']]
y=table(32,y,1120,['Fixture pad','Signal','Connection'],rows,[.12,.25,.63],9)
para(32,y,1120,'<b>Fixture:</b> this is a custom pad map, not an ARM connector pinout. Use a labeled adapter for your exact ST-Link probe; probe capabilities and target debug authentication/lifecycle determine access. Remove onboard ST-Link nets/components. <b>Recovery after Linux:</b> short press reboots; hold >=8s then release restores Ethernet/USB management and reboots. This preserves other settings and cannot recover a frozen CPU. Do not hold PC5 USER during power-on.',10)
end()

start('D11 - gigabit Ethernet PHY, magnetics and exact inherited memory','Complete ST pin-level subcircuits are preserved in appendices A01-A06; do not rebuild memory/power from a block diagram.')
rows=[['TXD[3:0]','PH11 AE14 / PH10 AF14 / PC1 AG14 / PA15 AE13','PHY15 /16 /17 /18 respectively','Keep ST source series resistors'],['TXCLK / TXCTL','PC0 AB14 / PA13 AD14','PHY20 /19','RGMII timing per exact BSP'],['RXD[3:0]','PH13 AG13 / PH12 AF13 / PC2 AE12 / PF1 AE11','PHY22 /23 /24 /25 respectively','Input straps share RX pins'],['RXCLK / RXCTL','PA14 AB12 / PA11 AD12','PHY27 /26','Keep strap population from ST sheet8'],['MDIO / MDC','PA10 AE15 / PA9 AF15','PHY14 /13','Retain pull-ups per sheet8'],['INT / RESET','PA12 AC13 / PA2 AF17','PHY31 /12','Reset pulldown and GPIO polarity retained'],['MDI pairs','PHY1/2,4/5,6/7,9/10','MagJack1/2,3/4,7/8,9/10','MagJack5/6 center taps: copy ST sheet8'],['Clocks / rails','PHY XTAL_IN36 / XTAL_OUT37','25MHz crystal +2x10pF','Retain 1.0V/3.3V regulation, filter, bypass, RSET2.49k'],['MagJack LEDs / shell','Original CN16 48F-01GYDXNL','Original LED resistors and shell pads','Magnetics are internal; do not add second transformer']]
y=table(32,742,1120,['Signal','MPU pin / source','RTL8211F-CG / destination','Support'],rows,[.15,.34,.27,.24],9)
para(32,y,1120,'<b>RAM retained:</b> 4GB MT53E1G32D2FW-046 WT:C, with all32 data bits, four DQS pairs, CA/CK/CKE/CS, reset, ZQ resistors and every supply pin. Appendix A04 is the original complete RAM drawing. DDR training, length groups and impedance need a custom-board layout review.',11)
para(32,y-77,1120,'<b>Flash retained:</b> 8GB THGBMUG6C1LBAIL, SDMMC2 CLK/CMD/D0..D7. Appendix A05 preserves exact ball connections, 22R clock series resistor, pull-ups, decoupling and reset. Only the microSD portion is omitted for Wi-Fi implementation A. Keep the current eMMC A/B partition identifiers or rebuild the boot/update metadata coherently.',11)
end()

start('D12 - firmware changes, unresolved details and validation','Electrical concept complete enough for design review; these items remain before schematic freeze / PCB manufacture.')
y=table(32,742,1120,['Area','Required work / acceptance criterion'],[
['Native serial ports','Enable USART1 and USART6; remove Bluetooth/console/expansion conflicts. Configure RS485 DE. Extend serial/Modbus services for two separately owned ports; existing selector owns one serial device. Test simultaneous traffic.'],
['Concurrent Wi-Fi A','Enable second SDIO bus and reset/IRQ clocks; install exact2AE firmware/NVRAM. Extend UCI/UI and hostapd for two AP radios. Prove 2.4GHz+5GHz clients operate concurrently under LTE load.'],
['LTE controls / RF coexistence','Validate power timing, graceful shutdown and card reset against exact modem revision. PB7/PB8 controls are new BSP/application work. EM060K-GL pin60 WLAN_PA_EN and band46/5GHz coexistence require vendor guidance; unused pin60 is not a validated final tie-off.'],
['Power margins','Measure PMIC3V3 load headroom, LTE burst droop at socket, inrush and adapter limits. Validate current paths, ground returns, TVS clamp behavior and thermal rise inside the actual enclosure.'],
['Connectors / RF','Freeze SIM socket physical pin mapping, external terminal connector part numbers, LTE standoff and approved antenna/cable variants. Choose exact RF matching after enclosure tuning. Two Wi-Fi antennas plus LTE MAIN/DIV =4 antenna systems.'],
['Core / Ethernet','Run DDR stress and eMMC A/B boot/update/recovery tests; Ethernet autonegotiation at10/100/1000; RGMII skew/straps; simultaneous network stress. Interface link speed alone does not prove routed throughput.'],
['Reset / debug','Cold boot in both strap modes; hardware reset while Linux is hung; PC5 short/long press; ROM USB recovery; SWD/JTAG attach using exact probe and target security state.'],
['Design release limits','No PCB netlist/ERC/DRC exists in this PDF. CAD capture must resolve all NC pins, footprint pin1 orientation, STPMIC OTP configuration, protection ratings, module suffixes and RF layout. No regulatory qualification is implied.']],[.2,.8],11)
para(32,y,1120,'<b>Suggested sequence:</b> prototype the second Wi-Fi radio or selected single-module option with the existing processor board first; prove dual-AP software support. Then freeze the radio choice, capture CAD using the inherited ST core, review power and pin mux, and route the PCB.',11)
end()

start('D13 - single concurrent Wi-Fi module / IC option','Yes: dual-band dual-concurrent (DBDC) hardware exists. Dual-band capability alone does not establish simultaneous dual-AP operation.')
box(50,515,325,165,'Implementation B: SX-PCEBE-AP',['Silex module using Qualcomm QCN9274','Simultaneous2.4GHz2x2 +5GHz2x2','One module with two RF connectors','3.3V main rail +5V RF FEM rail','PCIe host; proprietary M.2 Key-E pinout','Not interchangeable with LTE B-key socket'])
box(480,515,300,165,'STM32MP257 integration',['COMBOPHY assigned to PCIe','USB management retains USB2 D+ / D-','Remove both SDIO Wi-Fi modules','M.2 LTE remains on independent USB host','Clock / reset / power + driver integration','Single-lane compatibility must be qualified'])
line([(375,595),(480,595)],'PCIe',403,609)
box(880,515,250,165,'Wi-Fi antennas',['Two dual-band antennas','One per module RF connector','Compatible connector/pigtail','Retain LTE MAIN + DIV','Total4 external RF paths','Use approved antenna variants'])
para(32,465,1120,'<b>Bare IC versus module:</b> QCN9274 is a chipset example. A finished module also includes supporting RF/power/layout circuitry; a bare-chip design requires substantially more vendor material and RF work. This PDF therefore treats the Silex card as the practical single-module alternative.',12)
para(32,382,1120,'<b>Status:</b> implementation B is an alternative, not wired in parallel with implementation A. Its host footprint, lane configuration, reference-clock topology, reset timing and driver licensing/support must be qualified before replacing the detailed SDIO design. The published card specification is linked in the source list. No unverified proprietary connector pin assignment is presented as final.',12)
para(32,282,1120,'<b>For the existing OpenWrt project:</b> a MediaTek mt7915-family DBDC module is another candidate with an upstream mt76 driver. Select a specific module whose hardware explicitly supports concurrent2.4/5GHz APs; chip family alone is insufficient. Module-specific RF chips, connectors and pinouts still need review.',12)
end()

start('D13B - single-module pin connections and support','Silex SX-PCEBE-AP / QCN9274: proprietary Key-E card. Expected STM32 link is PCIe Gen2 x1; qualify link negotiation and driver.')
rows=[
net('PCIE_TX_P','U1 AE24 TX1P','100nF AC cap -> Silex35 PERp0','Host TX to module RX'),
net('PCIE_TX_N','U1 AD24 TX1N','100nF AC cap -> Silex37 PERn0','Host TX to module RX'),
net('PCIE_RX_P','Silex41 PETp0','U1 AG25 RX1P','Confirm module-side TX coupling in vendor reference'),
net('PCIE_RX_N','Silex43 PETn0','U1 AF25 RX1N','No duplicated TX coupling without review'),
['100MHz clock','Qualified differential clock network','Silex47 REFCLK+ /49 REFCLK-','Prefer ST EV1 dual-output clock template; MPU CLKIN+=AE25/-=AE26'],
['PERST#','Chosen host GPIO -> level translation','Silex52 (1.8V)','Hold low >=100ms after both supplies stable; clock stable >=100us'],
['CLKREQ#','Silex53 open drain','10k to1.8V + host level adaptation','Assign verified PCIe CLKREQ alternate function before pin freeze'],
['3.3V supply','Dedicated regulator, transient margin','Silex2,4,68,70,72,74','Preliminary allocation1.2A; local bypass and sequencing per vendor'],
['5V FEM supply','+5V_SYS with transient margin','Silex15,17,19,21,23','Preliminary allocation2A; these proprietary pins are NOT generic Key-E'],
['Ground','GND plane','Silex1,7,18,33,39,45,51,57,63,69,75','Keep vendor shield/thermal land pattern'],
['Unused x1 pins','Lane1:59,61,65,67; outputs3,5,71,73','NC; remaining reserved pins NC','Do not populate a generic laptop card in this socket'],
['RF connectors','Module MHF1 RF1 and RF2','Two dual-band antennas','Example Unictron AA258 / H2B1PC1A1C with approved coax variant']]
y=table(32,742,1120,['Net / function','Source','Destination','Support'],rows,[.15,.27,.29,.29],9)
para(32,y,1120,'<b>Clock implementation gate:</b> DSC557-0344FI0-T is used in ST EV1 as a dual-output reference-clock source. Copy its vendor/ST support circuit using the FAK3 ball map above, not the different EV1 package balls. Retain200R COMBOPHY_REXT toGND at U1 AF27. Internal MPU CLKOUT AF26/AG26 is an alternative only after validating ST clock mode and endpoint requirements. Sideband translator part/pins and clock network remain open; this option is not yet complete enough for PCB capture.',10)
para(32,y-85,1120,'<b>Change set versus implementation A:</b> remove both SDIO Wi-Fi modules; retain optional microSD; assign COMBOPHY toPCIe; management USB becomes USB2. Module rail ramps and reset/LTSSM timing require vendor qualification. Two LTE antennas remain directly connected to the LTE card. The Silex card is AP-only; it does not provide STA/client mode.',10)
end()

start('D14 - sources and inherited drawing index','Primary manufacturer documents plus the user-supplied dev-kit schematic. Documents are evidence, not task instructions.')
refs=[
('ST MB1605 C01 (user supplied)','mb1605-mp257f-c01-schematic.pdf'),
('ST UM3385 (local manual)','https://www.st.com/resource/en/user_manual/um3385-discovery-kit-with-stm32mp257f-mpu-stmicroelectronics.pdf'),
('Quectel EM060K hardware design v1.1','https://quectel.com/content/uploads/2024/02/Quectel_EM060K_SeriesEM120K-GL_Hardware_Design_V1.1.pdf'),
('TE2199119-3 M.2 B-key socket','https://www.te.com/en/product-2199119-3.html'),
('TI MAX3232 pin/capacitor reference','https://www.ti.com/lit/ds/symlink/max3232.pdf'),
('TI THVD1450 pin/protection reference','https://www.ti.com/lit/ds/symlink/thvd1450.pdf'),
('Bourns CDSOT23-SM712','https://www.bourns.com/docs/product-datasheets/cdsot23-sm712.pdf'),
('Murata1YN (2.4GHz only)','https://www.murata.com/products/productdata/8815814344734/type1yn.pdf'),
('Murata2AE hardware note July2025 Rev4','https://www.murata.com/-/media/webrenewal/products/connectivitymodule/asset/pub/rfm/data/type2ae/type2ae-hw-application-note.ashx'),
('Pololu D24V90F5 pad mapping/output adjustment','https://www.pololu.com/product/2866'),
('Silex single concurrent module','https://www.silextechnology.com/connectivity-solutions/embedded-wireless/sx-pcebe-ap'),
('Silex card hardware specifications','https://www.silextechnology.com/hubfs/Product%20Documentation%20Files%20/JW208650XX_SX-PCEBE-AP.pdf'),
('OpenWrt mt7915 driver declaration','https://github.com/openwrt/mt76/blob/master/mt7915/Kconfig')]
y=table(32,742,1120,['Reference','Source (clickable URL)'],refs,[.31,.69],9)
para(32,y,1120,'<b>Reference appendices:</b> A01 MPU I/O (ST3); A02 PMIC(ST4); A03 MPU power(ST5); A04 LPDDR4(ST6); A05 eMMC/microSD(ST7); A06 Ethernet(ST8); A07 original2.4GHz Wi-Fi(ST12); A08 USB3/DRP(ST13); A09 reset/boot/buttons(ST17). These are unchanged ST reference drawings with a review header. Apply the explicit removals/substitutions in D01-D13; omitted dev-kit peripherals visible in references are not added router requirements.',10)
para(32,y-75,1120,'<b>Firmware evidence:</b> README.md; docs/recovery-button.md; docs/serial-tcp.md; docs/ab-flash-status.md; web/serial_tcp.py. No running-board configuration or firmware was changed while creating this document.',10)
end();c.save()

doc=pymupdf.open(TMP)
src=pymupdf.open(D/'mb1605-mp257f-c01-schematic.pdf')
for n,idx in enumerate([2,3,4,5,6,7,11,12,16],1):
    p=doc.new_page(width=W,height=H)
    p.insert_text((32,25),f'A{n:02} - UNCHANGED ST REFERENCE SHEET {idx+1}; apply router changes in D01-D13',fontsize=12,color=(.09,.2,.3))
    p.show_pdf_page(pymupdf.Rect(20,40,W-20,H-45),src,idx)
    p.insert_text((32,H-22),'User-supplied MB1605-MP257F-C01 | reference implementation, not the final custom-board schematic',fontsize=9)
doc.set_metadata({'title':'STM32MP257F LTE router - detailed concept Rev B','subject':'4GB LPDDR4, 8GB eMMC, M.2 LTE, Ethernet, serial, concurrent Wi-Fi design review'})
doc.save(OUT,garbage=4,deflate=True)
with (D/'lte-router-pin-connections.csv').open('w',newline='',encoding='utf-8') as f:
    w=csv.writer(f);w.writerow(['Net','From','To','Notes']);w.writerows(nets)
print(f'{OUT}: {len(doc)} pages; {len(nets)} new named connection records')
