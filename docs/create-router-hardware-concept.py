"""Generate the one-page architecture schematic. Requires reportlab and pymupdf."""
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A3, landscape

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'lte-router-hardware-concept.pdf'
c = canvas.Canvas(str(OUT), pagesize=landscape(A3))
W,H = landscape(A3)
c.setTitle('STM32MP257F LTE router - preliminary system schematic')
ink=HexColor('#16324a'); blue=HexColor('#176b8a'); pale=HexColor('#edf5f8')
def txt(x,y,s,size=9,bold=False,color=ink):
    c.setFillColor(color); c.setFont('Helvetica-Bold' if bold else 'Helvetica',size); c.drawString(x,y,s)
def box(x,y,w,h,title,lines):
    c.setFillColor(pale); c.setStrokeColor(blue); c.setLineWidth(.8)
    c.roundRect(x,y,w,h,5,fill=1,stroke=1)
    txt(x+10,y+h-19,title,11,True)
    for i,line in enumerate(lines): txt(x+10,y+h-38-i*14,line,9)
def wire(points,label=None,lx=0,ly=0):
    c.setStrokeColor(blue); c.setLineWidth(1.15)
    p=c.beginPath(); p.moveTo(*points[0])
    for pt in points[1:]: p.lineTo(*pt)
    c.drawPath(p)
    for x,y in [points[0],points[-1]]:
        c.setFillColor(blue); c.circle(x,y,2,fill=1,stroke=0)
    if label: txt(lx,ly,label,8,True)

txt(30,H-34,'STM32MP257F LTE ROUTER',23,True)
txt(30,H-55,'PRELIMINARY SYSTEM SCHEMATIC  |  A3 landscape  |  18 Nov 2026  |  Rev A',10,True)
txt(30,H-74,'Functional connections only. Component pinout, power budget, UART mux and PCB implementation require detailed design.',10)

box(30,615,300,135,'J1 / POWER INPUT + PROTECTION',[
    'Proposed: 12 V DC nominal, locking 2-pin + / GND',
    'Fuse -> reverse-polarity FET -> TVS -> EMI filter',
    'Buck -> 5 V_SYS -> STPMIC25APQR (U26 reference)',
    'Separate modem regulator + load switch + bulk caps',
    'Input range / TVS / current ratings: TO BE SPECIFIED',
    'No backfeed from USB VBUS or external ST-Link'])
box(420,595,350,155,'U1 / STM32MP257FAK3 + REQUIRED CORE',[
    'Preserve MB1605 power domains, sequencing and decoupling',
    'STPMIC25: I2C7, PWR_ON, PWR_CPU_ON, NRST',
    'Keep NRSTC1MS reset distribution to storage',
    'LPDDR4: MT53E1G32D2FW-046 WT:C reference',
    'eMMC: THGBMUG6C1LBAIL reference; A/B boot layout',
    '40 MHz HSE + 32.768 kHz LSE / load networks',
    'DDR timing / training and PMIC boot config must match'])
wire([(330,680),(420,680)],'POWER',350,689)
box(860,615,300,135,'J2 / 1 x 10/100/1000BASE-T',[
    'ETH1 MAC -> RGMII -> RTL8211F-CG PHY',
    'MDIO/MDC + PHY reset + interrupt; PHY address 1',
    '25 MHz crystal; PHY rails / straps / RGMII delays',
    '4 MDI pairs -> magnetics -> shielded RJ45 + ESD',
    'Reference: MB1605 sheet 8; link/activity LEDs',
    '1 Gbit/s link rate; routed throughput unverified'])
wire([(770,680),(860,680)],'ETH1',795,689)

box(30,405,300,170,'U2 / LTE WAN (REQUIRED ADDITION)',[
    'Quectel EM060K-GL, M.2 B-key socket',
    'Dedicated USB host D+ / D- from MPU USBH_HS',
    'Separate from external management USB controller',
    'USB2422 hub optional; retain if USB topology needed',
    'SIM socket: USIM_VDD / DATA / CLK / RST + ESD',
    'LTE RF ports -> specified antennas / coax connectors',
    'GPIO -> level adaptation -> power/reset/control pins',
    'Regulator voltage and peak current per modem guide',
    'MBIM + ModemManager matches existing firmware'])
wire([(330,500),(380,500),(380,625),(420,625)],'USB HOST',337,510)
box(420,405,350,150,'J3 / USB-C MANAGEMENT + ROM BOOT',[
    'USB3DR_DP / DM -> low-capacitance ESD -> D+ / D-',
    'Self-powered USB 2.0 device-only proposal (no SS)',
    'CC1 -> 5.1k -> GND; CC2 -> 5.1k -> GND',
    'VBUS -> protected, voltage-safe detect; no board supply tie',
    'Linux USB Ethernet gadget + ROM USB download',
    'BOOT straps select ROM recovery; adapt BSP/Type-C config',
    'If retaining DK DRP: retain its TCPP/UCPD circuitry instead'])
wire([(595,595),(595,555)],'USB DRD',605,572)
box(860,405,300,170,'U3 / Wi-Fi 2.4 GHz + 5 GHz',[
    'SDMMC3 SDIO -> Murata LBEE5KL1YN-814 reference',
    '3.3 V / VIO, WL_REG_ON, WL_HOST_WAKE, LPO',
    'RF matching -> dual-band antenna; RF keepout',
    'Verify driver/firmware + AP mode + country/DFS rules',
    'Assumption: select 2.4 OR 5 GHz on one radio',
    'Simultaneous 2.4 AND 5 GHz requires verified DBDC',
    'hardware or a second radio + BSP/UI changes',
    'USART1 is Bluetooth on DK; disable BT if repurposed',
    'Reference: MB1605 sheet 12'])
wire([(770,625),(820,625),(820,500),(860,500)],'SDIO',823,560)

box(30,190,350,175,'J4 / COM1: DE-9 RS232, DTE PROPOSAL',[
    'UART TX/RX + RTS/CTS -> RS232 line drivers/receivers',
    'Full modem signals: 3 drivers + 5 receivers total',
    'DTR / DSR / DCD / RI via suitable UART signals or GPIO',
    'DE-9: 1 DCD, 2 RXD, 3 TXD, 4 DTR, 5 signal GND,',
    '6 DSR, 7 RTS, 8 CTS, 9 RI; shell -> chassis strategy',
    'Charge-pump capacitors + decoupling + connector TVS',
    'Logic voltage must match chosen MPU VDDIO bank',
    'COM1 is a port name; MPU UART instance/pins TBD',
    'Current serial bridge uses TX/RX, no modem handshake'])
box(410,190,350,175,'J5 / COM2: 3-PIN RS485, HALF DUPLEX',[
    'UART TX -> DI; RO -> UART RX; RTS/DE -> DE + /RE',
    '3.3 V fail-safe RS485 transceiver; power-on receive default',
    'J5: D+ / D- / signal GND; document polarity vs A/B names',
    'Switchable 120 ohm across D+ and D- at bus end only',
    'Optional single-point bias; size for load and receiver limits',
    'Connector TVS / surge protection matched to environment',
    'Isolation + isolated DC/DC if ground differences require it',
    'Native UART / Linux RS485 direction support must be added',
    'Current firmware selects one serial service/device'])
box(790,190,370,175,'BOOT / DEBUG / RESET AND RECOVERY',[
    'BOOT0..3 -> individual straps + test pads; known default',
    'ROM USB: BOOT[3:0]=0000; eMMC code verify from table',
    'Pads: VTref, GND, JTMS/SWDIO, JTCK/SWCLK,',
    'JTDI, JTDO/SWO, NJTRST, NRST; keyed fixture pin map TBD',
    'External ST-Link only; remove embedded ST-Link circuitry',
    'B_RESET: dedicated NRST-to-GND switch / reference RC',
    'B_USER: VDDIO -> switch -> 330R -> PC5, 100k pulldown,',
    '100nF to GND; PH6 -> indicator driver (reference sheet 17)',
    'Linux press <8s: reboot; >=8s: access recovery on release'])

txt(30,166,'SCHEMATIC CONVENTION: matching named interfaces are connected; boxes contain required subcircuits, not complete component wiring.',9,True)
txt(30,147,'RECOVERY: USER button is separate from NRST. Long press restores Ethernet/USB access, not all factory settings; Linux must be running.',9)
txt(30,132,'BSP WORK: validate two independent UART pin groups; reserve console; update DT, boot firmware, USB, watchdog and serial service mapping.',9)
txt(30,117,'OPEN DECISIONS: input voltage/range; simultaneous Wi-Fi bands; full RS232 handshaking; isolation/surge class; RAM/eMMC capacity and BOM.',9)
txt(30,96,'REFERENCES: local MB1605-MP257F-C01 sheets 3-8, 12-14, 17-18; docs/recovery-button.md; docs/serial-tcp.md; README.md.',8)
txt(30,82,'ST UM3385: st.com/resource/en/user_manual/um3385-discovery-kit-with-stm32mp257f-mpu-stmicroelectronics.pdf',8)
txt(30,68,'Modem: quectel.com/content/uploads/2024/02/Quectel_EM060K_SeriesEM120K-GL_Hardware_Design_V1.1.pdf',8)
c.setStrokeColor(blue); c.line(30,52,W-30,52)
txt(30,34,'DESIGN REVIEW ONLY - NOT FOR PCB FABRICATION. Final schematic needs component values, pin-level ERC and layout constraints.',9,True)
txt(W-110,34,'SHEET 1 / 1',10,True)
c.showPage(); c.save()
print(OUT)
