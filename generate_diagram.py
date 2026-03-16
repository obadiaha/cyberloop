#!/usr/bin/env python3
"""
CyberLoop Architecture Diagram v6
Layout: Row 1 = Frontend | Backend | Gemini Live (wide)
        Below Gemini Live: Flash (stacked), then Data below that
        All arrows horizontal or diagonal, no crossing through cards
"""

from PIL import Image, ImageDraw, ImageFont
import os

W, H = 2800, 1500
BG = "#0D1117"
CARD_BG = "#161B22"
CARD_BORDER = "#30363D"

GEMINI_BLUE = "#4285F4"
GEMINI_RED = "#EA4335"
GEMINI_YELLOW = "#FBBC04"
GEMINI_GREEN = "#34A853"

C_FE = "#58A6FF"
C_BE = "#3FB950"
C_GL = "#BC8CFF"
C_GF = "#D29922"
C_DA = "#39D2C0"
C_TL = "#F97583"

TW = "#E6EDF3"
TS = "#8B949E"
TM = "#6E7681"

img = Image.new("RGB", (W, H), BG)
dr = ImageDraw.Draw(img)

def gf(sz, bold=False):
    for fp in (["/System/Library/Fonts/SFPro-Bold.otf"] if bold else ["/System/Library/Fonts/SFPro-Regular.otf"]) + ["/System/Library/Fonts/Helvetica.ttc"]:
        try: return ImageFont.truetype(fp, sz)
        except: pass
    return ImageFont.load_default()

FT=gf(38,True); FS=gf(22,True); FB=gf(18); FSM=gf(15); FBG=gf(14,True); FTN=gf(13); FN=gf(24,True)

def tw(t, f): b=dr.textbbox((0,0),t,font=f); return b[2]-b[0]
def rr(x,y,w,h,r,fill,ol,ow=2): dr.rounded_rectangle([(x,y),(x+w,y+h)],radius=r,fill=fill,outline=ol,width=ow)

def badge(x,y,t,bg,fg="#FFF"):
    b=dr.textbbox((0,0),t,font=FBG); bw,bh=b[2]-b[0],b[3]-b[1]
    dr.rounded_rectangle([(x,y),(x+bw+20,y+bh+8)],radius=8,fill=bg)
    dr.text((x+10,y+4),t,fill=fg,font=FBG)
    return bw+20

def gdots(x,y,s=6):
    for i,c in enumerate([GEMINI_BLUE,GEMINI_RED,GEMINI_YELLOW,GEMINI_GREEN]):
        dr.ellipse([(x+i*s*2.5-s,y-s),(x+i*s*2.5+s,y+s)],fill=c)

def arr(x1,y1,x2,y2,col,w=2,dash=False):
    dx,dy=x2-x1,y2-y1; L=(dx*dx+dy*dy)**.5
    if L<1: return
    nx,ny=dx/L,dy/L
    if dash:
        p=0
        while p<L-14:
            dr.line([(x1+nx*p,y1+ny*p),(x1+nx*min(p+10,L-14),y1+ny*min(p+10,L-14))],fill=col,width=w)
            p+=18
    else:
        dr.line([(x1,y1),(x2-nx*2,y2-ny*2)],fill=col,width=w)
    a=14;px,py=-ny,nx
    dr.polygon([(x2,y2),(x2-nx*a+px*a*.4,y2-ny*a+py*a*.4),(x2-nx*a-px*a*.4,y2-ny*a-py*a*.4)],fill=col)

def bidir(x1,y1,x2,y2,col,w=3):
    dr.line([(x1,y1),(x2,y2)],fill=col,width=w)
    dx,dy=x2-x1,y2-y1;L=(dx*dx+dy*dy)**.5
    if L<1:return
    nx,ny=dx/L,dy/L;a=14;px,py=-ny,nx
    dr.polygon([(x2,y2),(x2-nx*a+px*a*.4,y2-ny*a+py*a*.4),(x2-nx*a-px*a*.4,y2-ny*a-py*a*.4)],fill=col)
    dr.polygon([(x1,y1),(x1+nx*a+px*a*.4,y1+ny*a+py*a*.4),(x1+nx*a-px*a*.4,y1+ny*a-py*a*.4)],fill=col)

def pill(cx,cy,text,col,f=FTN):
    b=dr.textbbox((0,0),text,font=f);lw,lh=b[2]-b[0],b[3]-b[1];p=6
    rr(int(cx-lw/2-p),int(cy-lh/2-p),lw+p*2,lh+p*2,5,BG,col,1)
    dr.text((int(cx-lw/2),int(cy-lh/2)),text,fill=col,font=f)

def card_header(x,y,w,h,bg,accent,icon_type,title,badge_text,badge_bg):
    """Draw a card with header bar"""
    rr(x,y,w,h,12,bg,accent,2)
    header_h = 40
    rr(x,y,w,header_h,12, bg.replace("11","1C").replace("1D","2D"),accent,2)
    dr.rectangle([(x+1,y+header_h-12),(x+w-1,y+header_h)],fill=bg.replace("11","1C").replace("1D","2D"))
    if icon_type == "dot":
        dr.ellipse([(x+14,y+10),(x+32,y+28)],fill=accent)
    elif icon_type == "gdots":
        gdots(x+18,y+20,5)
    dr.text((x+(42 if icon_type=="dot" else 62),y+8),title,fill=TW,font=FS)
    badge(x+w-tw(badge_text,FBG)-22,y+9,badge_text,badge_bg)
    return y + header_h + 8


# ═══ TITLE ══════════════════════════════════════════════════════
dr.rectangle([(0,0),(W,68)],fill="#141922")
gdots(40,34,7)
dr.text((110,13),"CyberLoop",fill=TW,font=FT)
dr.text((110,49),"Real-Time AI Cybersecurity Interview Prep Platform",fill=TS,font=FSM)
dr.text((W-tw("Google Cloud + Gemini",FB)-40,23),"Google Cloud + Gemini",fill=GEMINI_BLUE,font=FB)

# Modes
my=82; dr.text((40,my),"Modes:",fill=TS,font=FB)
bx=120
bx+=badge(bx,my-2,"Technical","#1F3D5C",C_FE)+8
bx+=badge(bx,my-2,"Behavioral","#3D1F5C",C_GL)+8
badge(bx,my-2,"Hands-On Coding (screen share + vision)","#1F5C3D",C_BE)


# ═══ FRONTEND ═══════════════════════════════════════════════════
FX,FY,FW,FH = 40, 112, 480, 430
cy = card_header(FX,FY,FW,FH,"#111927",C_FE,"dot","Frontend","React + Vite (TS)","#1F3D5C")

items = [
    ("MIC","Audio Capture","16kHz PCM via AudioWorklet"),
    ("SPK","Audio Playback","24kHz PCM via Web Audio API"),
    ("SCR","Screen Share","getDisplayMedia, JPEG every 3s"),
    ("CAM","Webcam Capture","getUserMedia, JPEG every 10s"),
    ("WS", "WebSocket Client","Real-time bidirectional channel"),
]
for abbr,title,desc in items:
    rr(FX+14,cy,FW-28,54,7,"#0C131E","#1E2A3A")
    dr.rounded_rectangle([(FX+22,cy+8),(FX+54,cy+26)],radius=4,fill=C_FE+"25",outline=C_FE)
    aw=tw(abbr,FBG); dr.text((FX+38-aw//2,cy+8),abbr,fill=C_FE,font=FBG)
    dr.text((FX+64,cy+6),title,fill=TW,font=FB)
    dr.text((FX+64,cy+28),desc,fill=TS,font=FSM)
    cy+=60

rr(FX+140,cy+4,200,26,7,"#0D1117",C_FE)
dr.text((FX+156,cy+7),"Cybersecurity Candidate",fill=TW,font=FSM)


# ═══ BACKEND ════════════════════════════════════════════════════
BX,BY,BW,BH = 640, 112, 560, 430
cy = card_header(BX,BY,BW,BH,"#111916",C_BE,"dot","Backend - Cloud Run","FastAPI + Uvicorn","#1F5C3D")

# WS endpoint
rr(BX+14,cy,BW-28,42,7,"#0C130C","#1E2A1E")
dr.text((BX+28,cy+4),"WS:",fill=TS,font=FB)
dr.text((BX+62,cy+4),"/interview-adk/{session_id}",fill=C_BE,font=FB)
dr.text((BX+28,cy+24),"REST: POST /sessions | GET /report/{id}",fill=TS,font=FSM)
cy+=50

# ADK box
rr(BX+14,cy,BW-28,120,8,"#0C160C",C_BE)
dr.text((BX+28,cy+6),"Google ADK (Agent Development Kit)",fill=TW,font=FB)
tools=["get_next_question","score_response","advance_depth_ladder","end_interview"]
tx,ty=BX+28,cy+34
for tool in tools:
    toolw=tw(tool,FTN)+14
    rr(tx,ty,toolw,22,4,"#111D11","#3FB95050")
    dr.text((tx+7,ty+3),tool,fill=C_BE,font=FTN)
    if tx+toolw+8+130>BX+BW-28: tx,ty=BX+28,ty+28
    else: tx+=toolw+6
dr.text((BX+28,cy+96),"runner.run_live() orchestrates Gemini Live",fill=TM,font=FTN)
cy+=128

# Session + Tool Loop
half=(BW-36)//2
rr(BX+14,cy,half,38,7,"#0C130C","#1E2A1E")
dr.text((BX+28,cy+3),"Session State",fill=TW,font=FB)
dr.text((BX+28,cy+21),"In-memory / Firestore",fill=TS,font=FTN)
rr(BX+14+half+8,cy,half,38,7,"#160C0C",C_TL+"50")
dr.text((BX+26+half+8,cy+3),"Tool Call Loop",fill=C_TL,font=FB)
dr.text((BX+26+half+8,cy+21),"Gemini > ADK > Tools",fill=TS,font=FTN)


# ═══ GEMINI LIVE API (wide, top right) ══════════════════════════
GLX,GLY,GLW,GLH = 1500, 112, 1260, 200
cy = card_header(GLX,GLY,GLW,GLH,"#1D1127",C_GL,"gdots","Gemini Live API","gemini-2.5-flash-native-audio-latest","#3D1F5C")

feats=[
    ("Real-Time Bidirectional Audio","Native speech-to-speech, no separate STT/TTS pipeline"),
    ("Function Calling via ADK","Declares and invokes tools (get_next_question, score_response) mid-conversation"),
    ("Multimodal Vision Input","Processes screen share + webcam JPEG frames for Hands-On Coding mode"),
]
for title,desc in feats:
    rr(GLX+14,cy,GLW-28,42,7,"#15091F","#2A1A3D")
    dr.text((GLX+28,cy+4),title,fill=TW,font=FB)
    dr.text((GLX+28,cy+22),desc,fill=TS,font=FSM)
    cy+=48


# ═══ GEMINI FLASH (below Gemini Live, left half) ════════════════
GFX,GFY = GLX, GLY+GLH+20  # 1500, 332
GFW,GFH = 600, 150
cy = card_header(GFX,GFY,GFW,GFH,"#1D1B11",C_GF,"gdots","Gemini Flash","gemini-2.5-flash","#5C3D1F")

for t,desc in [("Response Scoring","Evaluates answers against rubrics"),
                ("Report Generation","Structured reports with recommendations")]:
    rr(GFX+14,cy,GFW-28,42,7,"#151108","#3D3520")
    dr.text((GFX+28,cy+4),t,fill=TW,font=FB)
    dr.text((GFX+28+tw(t,FB)+14,cy+6),desc,fill=TS,font=FSM)
    cy+=50


# ═══ DATA LAYER (below Gemini Live, right half) ═════════════════
DX,DY = GFX+GFW+20, GFY  # 2120, 332
DDW,DDH = 620, 150
cy = card_header(DX,DY,DDW,DDH,"#111D1D",C_DA,"dot","Data Layer","JSON + Structured","#1F5C5C")

for nm,fmt,desc in [("Question Trees","JSON","Depth-ladder Q&A per domain"),
                     ("Calibration Data","JSON","Scoring rubrics & benchmarks"),
                     ("Transcripts","Structured","Full interview logs with timestamps")]:
    rr(DX+14,cy,DDW-28,28,5,"#091515","#1A3030")
    dr.text((DX+24,cy+4),nm,fill=TW,font=FSM)
    bw2=badge(DX+24+tw(nm,FSM)+8,cy+3,fmt,"#1F5C5C")
    dr.text((DX+24+tw(nm,FSM)+8+bw2+8,cy+4),desc,fill=TM,font=FTN)
    cy+=34


# ═══ ARROWS (clean routing, no crossings) ══════════════════════

# 1. Frontend <-> Backend (WebSocket, horizontal)
a1y = 300
bidir(FX+FW+14, a1y, BX-14, a1y, C_FE, 3)
pill((FX+FW+BX)/2, a1y-24, "WebSocket", C_FE, FSM)
det="Audio | Transcripts | State"
dr.text(((FX+FW+BX)/2-tw(det,FTN)/2, a1y+16), det, fill=C_FE+"77", font=FTN)

# 2. Backend <-> Gemini Live (horizontal, in top row area)
a2y = 200
mid2 = (BX+BW+GLX)/2
bidir(BX+BW+14, a2y, GLX-14, a2y, C_GL, 3)
pill(mid2, a2y-24, "Bidirectional Audio + Tool Calls", C_GL, FSM)
dr.text((mid2-tw("via ADK runner.run_live()",FTN)/2, a2y+16), "via ADK runner.run_live()", fill=C_GL+"77", font=FTN)

# 3. Backend -> Gemini Flash (horizontal, at Flash card level)
# Flash is at y=332. Arrow at y=400 (inside Flash card range, hits left edge = correct)
a3y = 400
arr(BX+BW+14, a3y, GFX-14, a3y, C_GF, 2, dash=True)
pill((BX+BW+GFX)/2, a3y-22, "Scoring + Reports", C_GF, FSM)

# 4. Backend -> Data Layer (horizontal, at Data card level, BELOW Flash bottom)
# Flash bottom = GFY+GFH = 482. We route at y=482 which equals Flash bottom.
# Data left = DX = 2120. Arrow goes from BX+BW to DX, at y=482.
# At x=GFX=1500 (Flash left), y=482 = Flash bottom. Arrow passes just below Flash content.
# Actually route at y=GFY+GFH+10 = 492 to be safely below Flash.
a4y = GFY + GFH + 36  # well below Flash card
arr(BX+BW+14, a4y, DX-14, a4y, C_DA, 2, dash=True)
pill((BX+BW+DX)/2, a4y-22, "Read / Write", C_DA, FSM)


# ═══ LEGEND ═════════════════════════════════════════════════════
LY = 530
rr(40,LY,W-80,52,10,CARD_BG,CARD_BORDER,1)
dr.text((70,LY+10),"Flows:",fill=TW,font=FB)
items_l=[
    (C_FE,False,"WebSocket (audio, frames, state)"),
    (C_GL,False,"Gemini Live (audio + tool calls)"),
    (C_GF,True,"Gemini Flash (scoring, reports)"),
    (C_TL,False,"Tool Loop (Gemini > ADK > Tools)"),
]
lx=160
for col,dsh,desc in items_l:
    lly=LY+25
    if dsh:
        for dd in range(0,36,12): dr.line([(lx+dd,lly),(lx+dd+7,lly)],fill=col,width=3)
    else:
        dr.line([(lx,lly),(lx+36,lly)],fill=col,width=3)
    dr.polygon([(lx+42,lly),(lx+36,lly-4),(lx+36,lly+4)],fill=col)
    dr.text((lx+50,lly-8),desc,fill=TS,font=FSM)
    lx+=600


# ═══ SESSION FLOW ═══════════════════════════════════════════════
SFY = 608
rr(40,SFY,W-80,105,10,CARD_BG,CARD_BORDER,1)
dr.text((70,SFY+8),"Interview Session Flow",fill=TW,font=FS)

steps=[
    ("1","Session Start","POST /sessions",C_FE),
    ("2","WS Connect","/interview-adk/{id}",C_FE),
    ("3","ADK Init","runner.run_live()",C_GL),
    ("4","Interview Loop","Audio + tool calls",C_BE),
    ("5","Scoring","Gemini Flash eval",C_GF),
    ("6","Report","GET /report/{id}",C_DA),
]
sx_gap=410; sx_start=120
for i,(num,title,desc,col) in enumerate(steps):
    sx=sx_start+i*sx_gap; sy=SFY+30
    dr.ellipse([(sx,sy),(sx+40,sy+40)],fill=col)
    nw=tw(num,FN); dr.text((sx+20-nw//2,sy+6),num,fill="#FFF",font=FN)
    dr.text((sx+50,sy+2),title,fill=TW,font=FB)
    dr.text((sx+50,sy+24),desc,fill=TS,font=FSM)
    if i<len(steps)-1:
        ax=sx+50+max(tw(title,FB),tw(desc,FSM))+10
        dr.line([(ax,sy+20),(ax+40,sy+20)],fill=col+"40",width=2)
        dr.polygon([(ax+46,sy+20),(ax+38,sy+14),(ax+38,sy+26)],fill=col+"40")


# ═══ TOOL CALL LOOP DETAIL ═════════════════════════════════════
TCY = 740
rr(40,TCY,W-80,200,10,"#120C0C",C_TL+"40",1)
dr.text((70,TCY+10),"Tool Call Loop (Detail)",fill=C_TL,font=FS)

tcf=[
    ("Gemini Live","Requests tool call\n(e.g. get_next_question)",C_GL),
    ("ADK Runner","Intercepts & routes\nto registered handler",C_BE),
    ("Tool Function","Executes business logic\n(question select, scoring)",C_TL),
    ("ADK Runner","Returns result back\nto Gemini Live session",C_BE),
    ("Gemini Live","Incorporates result\ninto conversation flow",C_GL),
]
gap=50; box_w=(W-80-60-gap*4)//5
tcx=70; tcy=TCY+42
for i,(nm,desc,col) in enumerate(tcf):
    rr(tcx,tcy,box_w,85,7,"#0D1117",col+"40")
    dr.text((tcx+12,tcy+8),nm,fill=col,font=FBG)
    for j,ln in enumerate(desc.split("\n")):
        dr.text((tcx+12,tcy+30+j*16),ln,fill=TS,font=FTN)
    if i<4:
        ax=tcx+box_w+4
        dr.line([(ax,tcy+42),(ax+gap-8,tcy+42)],fill=col+"50",width=2)
        dr.polygon([(ax+gap-4,tcy+42),(ax+gap-12,tcy+36),(ax+gap-12,tcy+48)],fill=col+"50")
    tcx+=box_w+gap

dr.text((70,TCY+148),
    "Hands-On Coding: Screen share (3s) + webcam (10s) sent as JPEG via WebSocket, forwarded to Gemini Live for visual analysis.",
    fill=TM,font=FSM)
dr.text((70,TCY+168),
    "Gemini can see the candidate's code, terminal, and face, enabling interactive coding interviews with contextual verbal feedback.",
    fill=TM,font=FSM)


# ═══ FOOTER ═════════════════════════════════════════════════════
dr.line([(40,H-32),(W-40,H-32)],fill=CARD_BORDER,width=1)
ft="CyberLoop  |  Google Cloud Run + Google ADK + Gemini Live API + Gemini Flash"
dr.text((W//2-tw(ft,FSM)//2,H-22),ft,fill=TM,font=FSM)
gdots(W-80,H-16,4)


out=os.path.expanduser(".//architecture-diagram.png")
img.save(out,"PNG",quality=95)
print(f"Saved: {out}  ({W}x{H})")
