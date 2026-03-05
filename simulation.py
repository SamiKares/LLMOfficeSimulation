import pygame
import requests
import threading
import time
import random
import os
import shutil
import math
import re
from google import genai

# ═══════════════════════════════════════════════════════════
#  CONFIGURATION
# ═══════════════════════════════════════════════════════════
LM_STUDIO_URL        = "http://localhost:1234/v1/chat/completions"
MAX_ITERATIONS       = 5
HR_COMMENT_INTERVAL  = 180   # seconds
IT_CHECK_INTERVAL    = 60    # seconds

# ═══════════════════════════════════════════════════════════
#  WORKSPACE
# ═══════════════════════════════════════════════════════════
def init_workspace():
    for folder in ("workspace", "exports", "tickets"):
        if not os.path.exists(folder):
            os.makedirs(folder)
    for filename in os.listdir("workspace"):
        fp = os.path.join("workspace", filename)
        try:
            if os.path.isfile(fp) or os.path.islink(fp):
                os.unlink(fp)
            elif os.path.isdir(fp):
                shutil.rmtree(fp)
        except Exception as e:
            print(f"Workspace cleanup: {fp} — {e}")

def get_loaded_model():
    try:
        r = requests.get("http://localhost:1234/v1/models", timeout=5)
        if r.status_code == 200:
            return r.json()["data"][0]["id"]
    except Exception:
        pass
    return "local-model"

# ═══════════════════════════════════════════════════════════
#  DISPLAY
# ═══════════════════════════════════════════════════════════
WIDTH, HEIGHT = 1400, 900
FPS           = 60

COLOR_BG1        = (18, 22, 30)
COLOR_BG2        = (22, 28, 38)
COLOR_FLOOR1     = (28, 34, 46)
COLOR_FLOOR2     = (24, 30, 42)
COLOR_DESK_TOP   = (200, 120, 40)
COLOR_DESK_FRONT = (140,  80, 20)
COLOR_DESK_SHADE = (100,  55, 10)
COLOR_SCREEN_ON  = (0, 255, 100)
COLOR_WALL       = (30, 36, 50)
COLOR_SKIRTING   = (45, 52, 70)
COLOR_CEILING    = (20, 24, 34)
WHITE            = (255, 255, 255)
BLACK            = (0,   0,   0)
AMBER            = (255, 180,   0)
RED_ALERT        = (255,  60,  60)
GREEN_OK         = (0,   220,  80)
PINK_MKTG        = (255,  80, 180)
CYAN_IT          = (0,   200, 255)

# shirt, hair, skin, accent
TEAM_COLORS = {
    "Charlie": ((220, 180,  50), ( 80,  50,  20), (255, 210, 160), (255, 220,  80)),
    "Alex":    (( 30, 160, 255), (200, 100,  50), (255, 200, 150), (  0, 210, 255)),
    "Eve":     (( 40, 200, 100), (255, 200,  50), (255, 220, 180), (  0, 255, 130)),
    "Karen":   ((140,  40, 160), ( 60,   0,  80), (240, 200, 170), (200,  80, 220)),
    "Mika":    ((255,  80, 160), (255, 220,  80), (255, 195, 155), (255, 100, 200)),
    "Teppo":   (( 60,  80, 110), ( 30,  30,  30), (200, 170, 130), (  0, 200, 255)),
    "Gemini":  ((66, 133, 244), (40, 40, 40),  (255, 210, 160), (138, 43, 226)),
}

# ═══════════════════════════════════════════════════════════
#  PIPELINE STATE — lock-protected
# ═══════════════════════════════════════════════════════════
_state_lock         = threading.Lock()
_global_instruction = ""
_global_iteration   = 1
_pipeline_done      = False
_total_tokens       = 0

_tickets       = []
_tickets_lock  = threading.Lock()
_marketing_art      = ""
_marketing_art_lock = threading.Lock()
_marketing_timestamp = 0

def get_state():
    with _state_lock:
        return _global_instruction, _global_iteration, _pipeline_done

def get_total_tokens():
    with _state_lock:
        return _total_tokens

def add_tokens(amount):
    global _total_tokens
    with _state_lock:
        _total_tokens += amount

def set_instruction(new_instr):
    global _global_instruction, _global_iteration, _pipeline_done, _total_tokens
    with _state_lock:
        _global_instruction = new_instr
        _global_iteration   = 1
        _pipeline_done      = False
        _total_tokens       = 0

def bump_iteration():
    global _global_iteration, _pipeline_done
    with _state_lock:
        if _global_iteration >= MAX_ITERATIONS:
            _pipeline_done = True
            return None
        _global_iteration += 1
        return _global_iteration

def mark_pipeline_done():
    global _pipeline_done
    with _state_lock:
        _pipeline_done = True

def add_ticket(text):
    with _tickets_lock:
        _tickets.append({"time": time.strftime("%H:%M:%S"), "text": text, "timestamp": time.time()})
    ts   = time.strftime("%Y%m%d_%H%M%S")
    path = f"tickets/ticket_{ts}.txt"
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"[Teppo] Ticket: {path}")
    except Exception as e:
        print(f"[Teppo] Ticket write failed: {e}")

def get_tickets():
    with _tickets_lock:
        return list(_tickets)

def set_marketing_art(art):
    global _marketing_art, _marketing_timestamp
    with _marketing_art_lock:
        _marketing_art = art
        _marketing_timestamp = time.time()

def get_marketing_art():
    with _marketing_art_lock:
        return _marketing_art

# ═══════════════════════════════════════════════════════════
#  PARTICLES
# ═══════════════════════════════════════════════════════════
_particles      = []
_particles_lock = threading.Lock()

def spawn_particles(x, y, color, count=8, speed=2.5):
    pts = []
    for _ in range(count):
        a   = random.uniform(0, math.pi*2)
        spd = random.uniform(0.6, speed)
        lf  = random.randint(25, 55)
        pts.append({"x":x,"y":y,"vx":math.cos(a)*spd,
                    "vy":math.sin(a)*spd-random.uniform(0.5,1.8),
                    "color":color,"life":lf,"max_life":lf,"size":random.randint(2,4)})
    with _particles_lock:
        _particles.extend(pts)

def update_draw_particles(screen):
    alive = []
    with _particles_lock:
        snap = list(_particles)
        _particles.clear()
    for p in snap:
        p["x"] += p["vx"]; p["y"] += p["vy"]; p["vy"] += 0.09; p["life"] -= 1
        if p["life"] > 0:
            alpha = int(255*p["life"]/p["max_life"])
            r,g,b = p["color"][:3]; sz = p["size"]
            s = pygame.Surface((sz*2,sz*2), pygame.SRCALPHA)
            pygame.draw.circle(s,(r,g,b,alpha),(sz,sz),sz)
            screen.blit(s,(int(p["x"])-sz,int(p["y"])-sz))
            alive.append(p)
    with _particles_lock:
        _particles.extend(alive)

# ═══════════════════════════════════════════════════════════
#  PIXEL ART
# ═══════════════════════════════════════════════════════════
def _px(surf, color, rects):
    for r in rects:
        pygame.draw.rect(surf, color, r)

def create_desk_sprite(shirt_color, t=0):
    W,H = 140,110
    s = pygame.Surface((W,H),pygame.SRCALPHA)
    sh = pygame.Surface((W,20),pygame.SRCALPHA)
    pygame.draw.ellipse(sh,(0,0,0,55),(0,0,W,20))
    s.blit(sh,(0,H-20))
    _px(s,COLOR_DESK_SHADE,[(10,72,8,28),(W-18,72,8,28)])
    pygame.draw.rect(s,COLOR_DESK_FRONT,(4,70,W-8,10))
    pygame.draw.rect(s,COLOR_DESK_TOP,(4,8,W-8,64))
    pygame.draw.rect(s,tuple(c//3 for c in shirt_color),(4,8,W-8,3))
    _px(s,(50,50,60),[(54,56,20,12)])
    _px(s,(40,40,50),[(46,66,36,5)])
    pygame.draw.rect(s,(30,32,40),(34,8,56,48))
    pygame.draw.rect(s,(20,20,28),(36,10,52,44))
    sc = pygame.Surface((48,38),pygame.SRCALPHA)
    sc.fill((0,20,10))
    for row in range(0,38,3):
        c = 18+int(14*math.sin(t*0.12+row*0.35))
        pygame.draw.line(sc,(0,c,c//2),(0,row),(47,row))
    lws=[30,22,38,18]; scroll=(t//20)%4
    for i in range(4):
        lc=COLOR_SCREEN_ON if i%2==0 else (0,180,70)
        pygame.draw.rect(sc,lc,(2,4+i*8,lws[(i+scroll)%4],2))
    s.blit(sc,(38,12))
    pygame.draw.rect(s,(60,62,75),(10,62,30,10))
    for ki in range(5):
        for kj in range(3):
            pygame.draw.rect(s,(80,82,95),(12+ki*5,63+kj*2,4,1))
    _px(s,(80,40,20),[(100,54,12,14)])
    _px(s,(180,80,30),[(101,55,10,11)])
    if (t//8)%2==0:
        for si in range(2):
            sy=int(46+3*math.sin(t*0.18+si))
            pygame.draw.rect(s,(180,180,180,100),pygame.Rect(103+si*4,sy,2,3))
    _px(s,(230,225,210),[(95,66,18,12)])
    _px(s,(220,215,200),[(97,64,18,12)])
    for li in range(3):
        pygame.draw.line(s,(170,165,150),(99,67+li*3),(112,67+li*3))
    pygame.draw.line(s,(40,40,50),(62,52),(62,72),2)
    return s

def create_marketing_desk_sprite(shirt_color, t=0):
    W,H = 140,110
    s = pygame.Surface((W,H),pygame.SRCALPHA)
    sh = pygame.Surface((W,20),pygame.SRCALPHA)
    pygame.draw.ellipse(sh,(0,0,0,55),(0,0,W,20))
    s.blit(sh,(0,H-20))
    _px(s,COLOR_DESK_SHADE,[(10,72,8,28),(W-18,72,8,28)])
    pygame.draw.rect(s,COLOR_DESK_FRONT,(4,70,W-8,10))
    pygame.draw.rect(s,COLOR_DESK_TOP,(4,8,W-8,64))
    pygame.draw.rect(s,(80,20,60),(4,8,W-8,3))
    _px(s,(50,50,60),[(54,56,20,12)])
    _px(s,(40,40,50),[(46,66,36,5)])
    pygame.draw.rect(s,(30,32,40),(30,6,64,50))
    pygame.draw.rect(s,(18,18,26),(32,8,60,46))
    for bi,bc in enumerate([(255,60,120),(255,140,0),(255,220,0),(0,200,100),(0,160,255),(160,0,255)]):
        pygame.draw.rect(s,bc,(33+bi*10,9,10,44))
    sx=33+int(27*abs(math.sin(t*0.07))); sy=9+int(20*abs(math.cos(t*0.05)))
    pygame.draw.circle(s,WHITE,(sx,sy),2)
    pygame.draw.rect(s,(60,62,75),(10,62,30,10))
    for ki in range(5):
        for kj in range(3):
            pygame.draw.rect(s,(80,82,95),(12+ki*5,63+kj*2,4,1))
    pygame.draw.rect(s,(60,40,80),(100,54,14,16))
    for pi,pc in enumerate([(255,60,60),(255,200,0),(0,180,255),(0,220,80),(200,0,200)]):
        pygame.draw.line(s,pc,(101+pi*2,42),(101+pi*2,55),2)
    for pi,pc in enumerate([(255,240,80),(255,160,80),(200,240,255)]):
        pygame.draw.rect(s,pc,(12+pi*12,48,10,10))
        pygame.draw.line(s,tuple(max(0,c-40) for c in pc),(14+pi*12,51),(20+pi*12,51))
    return s

def create_it_desk_sprite(shirt_color, t=0):
    W,H = 155,110
    s = pygame.Surface((W,H),pygame.SRCALPHA)
    sh = pygame.Surface((W,20),pygame.SRCALPHA)
    pygame.draw.ellipse(sh,(0,0,0,55),(0,0,W,20))
    s.blit(sh,(0,H-20))
    _px(s,COLOR_DESK_SHADE,[(10,72,8,28),(W-18,72,8,28)])
    pygame.draw.rect(s,COLOR_DESK_FRONT,(4,70,W-8,10))
    pygame.draw.rect(s,(22,28,38),(4,8,W-8,64))
    pygame.draw.rect(s,(0,40,60),(4,8,W-8,3))
    # Monitor 1
    _px(s,(45,48,58),[(16,54,14,10)])
    _px(s,(35,38,48),[(10,62,24,4)])
    pygame.draw.rect(s,(25,28,36),(6,8,44,46))
    pygame.draw.rect(s,(10,12,18),(8,10,40,42))
    sc1=pygame.Surface((36,38),pygame.SRCALPHA); sc1.fill((0,10,20))
    for row in range(0,38,5):
        pygame.draw.rect(sc1,CYAN_IT,(2,row+1,10+(row*3)%24,2))
    if (t//15)%2==0:
        pygame.draw.rect(sc1,CYAN_IT,(2+(t//5)%28,33,6,3))
    s.blit(sc1,(9,11))
    # Monitor 2
    _px(s,(45,48,58),[(94,54,14,10)])
    _px(s,(35,38,48),[(88,62,24,4)])
    pygame.draw.rect(s,(25,28,36),(84,8,44,46))
    pygame.draw.rect(s,(10,12,18),(86,10,40,42))
    sc2=pygame.Surface((36,38),pygame.SRCALPHA); sc2.fill((0,5,15))
    for row in range(0,38,5):
        w3=8+(row*5+12)%26
        pygame.draw.rect(sc2,(0,min(255,200+row*2),80) if row%10==0 else (0,100,50),(2,row+1,w3,2))
    s.blit(sc2,(87,11))
    pygame.draw.rect(s,(50,54,65),(42,64,42,10))
    for ki in range(7):
        for kj in range(3):
            pygame.draw.rect(s,(65,68,80),(44+ki*5,65+kj*2,4,1))
    for ci in range(4):
        pygame.draw.line(s,(20+ci*10,20+ci*8,30+ci*5),(30+ci*20,70),(20+ci*15,80),2)
    _px(s,(50,55,65),[(130,60,12,14)])
    _px(s,(60,65,75),[(131,61,10,11)])
    pygame.draw.rect(s,(255,240,180),(2,50,18,14))
    for li in range(3):
        pygame.draw.line(s,(180,160,100),(4,53+li*4),(4+12-li*2,53+li*4))
    return s

def create_senior_desk_sprite(shirt_color, t=0):
    W, H = 160, 110
    s = pygame.Surface((W, H), pygame.SRCALPHA)
    
    sh = pygame.Surface((W, 20), pygame.SRCALPHA)
    pygame.draw.ellipse(sh, (0, 0, 0, 60), (0, 0, W, 20))
    s.blit(sh, (0, H - 20))
    
    _px(s, COLOR_DESK_SHADE, [(15, 72, 8, 28), (W - 23, 72, 8, 28)])
    pygame.draw.rect(s, COLOR_DESK_FRONT, (5, 70, W - 10, 10))
    pygame.draw.rect(s, (30, 35, 45), (5, 8, W - 10, 64)) 
    
    pygame.draw.rect(s, (138, 43, 226), (5, 8, W - 10, 3))
    
    _px(s, (50, 50, 60), [(65, 50, 30, 15)])
    
    pygame.draw.rect(s, (40, 45, 55), (10, 5, 140, 45), border_radius=4)
    pygame.draw.rect(s, (10, 12, 18), (12, 7, 136, 41), border_radius=4)
    
    sc = pygame.Surface((136, 41), pygame.SRCALPHA)
    sc.fill((5, 10, 20))
    for row in range(0, 41, 4):
        width = 10 + int(20 * abs(math.sin(t * 0.05 + row)))
        offset = int(t * 0.8) % 136
        cx = (offset + row * 3) % 136
        color = (66, 133, 244) if row % 8 == 0 else (180, 100, 255)
        pygame.draw.rect(sc, color, (cx, row + 1, width, 2))
    s.blit(sc, (12, 7))
    
    pygame.draw.rect(s, (20, 20, 25), (45, 62, 70, 12))
    for ki in range(12):
        for kj in range(3):
            r = int(127 + 128 * math.sin(t * 0.1 + ki * 0.5))
            g = int(127 + 128 * math.sin(t * 0.1 + ki * 0.5 + 2))
            b = int(127 + 128 * math.sin(t * 0.1 + ki * 0.5 + 4))
            pygame.draw.rect(s, (r, g, b), (48 + ki * 5, 64 + kj * 3, 4, 2))
    
    pygame.draw.rect(s, (255, 220, 0), (30, 54, 8, 6), border_radius=2)
    pygame.draw.rect(s, (255, 150, 0), (36, 56, 4, 2))
    
    for i in range(4):
        cy = 60 - i * 6
        cx = 125 + (i % 2) * 2
        pygame.draw.rect(s, (220, 220, 230), (cx, cy, 10, 12))
        pygame.draw.rect(s, (150, 100, 50), (cx, cy + 4, 10, 4))
        
    return s

def create_whiteboard_sprite(t=0):
    W,H = 130,110
    s = pygame.Surface((W,H),pygame.SRCALPHA)
    sh = pygame.Surface((W,20),pygame.SRCALPHA)
    pygame.draw.ellipse(sh,(0,0,0,55),(0,0,W,20))
    s.blit(sh,(0,H-18))
    _px(s,(60,60,70),[(30,70,6,32),(94,70,6,32)])
    _px(s,(50,50,60),[(20,98,26,5),(84,98,26,5)])
    pygame.draw.rect(s,(70,70,80),(0,2,W,72))
    pygame.draw.rect(s,(240,238,232),(4,6,W-8,64))
    pygame.draw.rect(s,(100,100,110),(4,68,W-8,6))
    _px(s,(40,100,200),[(20,69,14,3)])
    _px(s,(200,40,40),[(38,69,14,3)])
    pygame.draw.rect(s,(30,80,180),(10,14,30,14),2)
    pygame.draw.rect(s,(180,50,50),(90,14,30,14),2)
    pygame.draw.rect(s,(50,150,80),(50,44,30,14),2)
    pygame.draw.line(s,(100,100,120),(25,28),(65,44),2)
    pygame.draw.line(s,(100,100,120),(105,28),(80,44),2)
    if (t//10)%2==0:
        pygame.draw.circle(s,(30,100,220),(74,32),3)
    for pi,pc in enumerate([(255,240,100),(255,180,100),(180,220,255)]):
        pygame.draw.rect(s,pc,(W-30+pi*2,10+pi*4,16,14))
    return s

def draw_character(shirt,hair,skin,facing_right=True,arms_up=False,scale=2):
    W,H=16,24
    s=pygame.Surface((W,H),pygame.SRCALPHA)
    pygame.draw.ellipse(s,(0,0,0,45),(2,H-4,12,4))
    _px(s,(30,30,35),[(4,H-6,4,4),(8,H-6,4,4)])
    trouser=tuple(max(0,c-60) for c in shirt)
    _px(s,trouser,[(4,14,3,6),(8,14,3,6)])
    _px(s,shirt,[(3,9,10,7)])
    _px(s,tuple(min(255,c+40) for c in shirt),[(6,9,4,2)])
    if arms_up:
        _px(s,shirt,[(0,6,3,5),(13,6,3,5)]); _px(s,skin,[(0,4,3,3),(13,4,3,3)])
    else:
        _px(s,shirt,[(1,9,3,5),(12,9,3,5)]); _px(s,skin,[(1,13,3,3),(12,13,3,3)])
    _px(s,skin,[(6,7,4,3),(4,2,8,7)])
    _px(s,hair,[(4,1,8,3),(3,2,2,3),(11,2,2,3)])
    ex=5 if facing_right else 7
    _px(s,WHITE,[(ex,5,2,2),(ex+4,5,2,2)]); _px(s,(30,30,30),[(ex+1,5,1,1),(ex+5,5,1,1)])
    _px(s,(180,80,80),[(6,8,4,1)])
    if not facing_right: s=pygame.transform.flip(s,True,False)
    return pygame.transform.scale(s,(W*scale,H*scale))

def create_plant_sprite():
    s=pygame.Surface((28,44),pygame.SRCALPHA)
    _px(s,(160,80,30),[(6,30,16,12)]); _px(s,(140,60,20),[(4,28,20,4)])
    _px(s,(120,180,80),[(8,10,12,22)])
    for lx,ly,lw,lh in [(2,8,10,8),(16,6,10,9),(4,16,8,8),(16,18,9,7)]:
        pygame.draw.ellipse(s,(100,160,60),(lx,ly,lw,lh))
    return s

def create_server_rack_sprite(t=0):
    s=pygame.Surface((36,70),pygame.SRCALPHA)
    pygame.draw.rect(s,(30,35,45),(0,0,36,70)); pygame.draw.rect(s,(50,55,70),(2,2,32,66))
    for ui in range(6):
        y=4+ui*10; pygame.draw.rect(s,(20,22,30),(4,y,28,8))
        pygame.draw.circle(s,(0,255,80) if (t//4+ui)%3!=0 else (0,60,20),(8,y+4),2)
        pygame.draw.circle(s,AMBER if (t//6+ui)%5==0 else (60,40,0),(13,y+4),2)
        for di in range(3): pygame.draw.rect(s,(35,38,50),(17+di*4,y+1,3,6))
    for vi in range(4): pygame.draw.rect(s,(20,22,30),(6+vi*6,65,4,2))
    return s

def create_bookshelf_sprite():
    s=pygame.Surface((30,60),pygame.SRCALPHA)
    pygame.draw.rect(s,(100,60,25),(0,0,30,60)); _px(s,(80,48,18),[(0,0,2,60),(28,0,2,60)])
    for bi,bc in enumerate([(180,30,30),(30,80,180),(50,160,80),(220,180,30),(160,30,160),(200,100,30)]):
        x=2+bi*4+(bi%2); pygame.draw.rect(s,bc,(x,4,4,52))
        pygame.draw.rect(s,tuple(min(255,c+40) for c in bc),(x,4,1,52))
    return s

def draw_glow(screen,x,y,w,h,color,intensity=55):
    for i in range(3,0,-1):
        g=pygame.Surface((w+i*14,h+i*14),pygame.SRCALPHA)
        pygame.draw.rect(g,(*color[:3],intensity//(i*2)),(0,0,w+i*14,h+i*14),border_radius=6)
        screen.blit(g,(x-i*7,y-i*7))

def draw_speech_bubble(screen,font,text,x,y,color,t,max_w=230):
    words=text.split(); lines,line=[],""
    for w in words:
        test=(line+" "+w).strip()
        if font.size(test)[0]<max_w: line=test
        else:
            if line: lines.append(line)
            line=w
    if line: lines.append(line)
    lh=font.get_height()+2
    bw=max((font.size(l)[0] for l in lines),default=40)+16
    bh=len(lines)*lh+10; bx=x-bw//2; by=y-bh-22+int(3*math.sin(t*0.055))
    sh=pygame.Surface((bw+4,bh+4),pygame.SRCALPHA)
    pygame.draw.rect(sh,(0,0,0,55),(4,4,bw,bh),border_radius=8); screen.blit(sh,(bx-2,by-2))
    bubble=pygame.Surface((bw,bh),pygame.SRCALPHA)
    pygame.draw.rect(bubble,(14,17,25,215),(0,0,bw,bh),border_radius=8)
    pygame.draw.rect(bubble,(*color[:3],175),(0,0,bw,bh),1,border_radius=8); screen.blit(bubble,(bx,by))
    pts=[(x-5,by+bh),(x+5,by+bh),(x,by+bh+11)]
    pygame.draw.polygon(screen,(14,17,25),pts); pygame.draw.polygon(screen,(*color[:3],175),pts,1)
    for li,ln in enumerate(lines): screen.blit(font.render(ln,True,color),(bx+8,by+5+li*lh))

# ═══════════════════════════════════════════════════════════
#  MARKETING OVERLAY
# ═══════════════════════════════════════════════════════════
def draw_marketing_overlay(screen, art, font_mono, t):
    global _marketing_timestamp
    if not art or time.time() - _marketing_timestamp > 15:
        return
    lines = art.split("\n")[:18]
    box_w = 430; box_h = len(lines)*14+28
    box_x = WIDTH//2-box_w//2; box_y = 62
    pulse = 0.5+0.5*math.sin(t*0.08)
    gc    = (int(255*pulse), int(60+80*pulse), int(180*pulse))
    bg=pygame.Surface((box_w,box_h),pygame.SRCALPHA)
    pygame.draw.rect(bg,(8,4,18,210),(0,0,box_w,box_h),border_radius=6); screen.blit(bg,(box_x,box_y))
    for gi in range(3):
        border=pygame.Surface((box_w+gi*8,box_h+gi*8),pygame.SRCALPHA)
        pygame.draw.rect(border,(*gc,30-gi*8),(0,0,box_w+gi*8,box_h+gi*8),2,border_radius=8)
        screen.blit(border,(box_x-gi*4,box_y-gi*4))
    hdr=font_mono.render("★  MIKA'S MARKETING LAUNCH  ★",True,gc)
    screen.blit(hdr,(box_x+box_w//2-hdr.get_width()//2,box_y+4))
    ascii_colors=[PINK_MKTG,(255,220,80),(255,140,60),(200,80,255),WHITE]
    for li,ln in enumerate(lines):
        screen.blit(font_mono.render(ln,True,ascii_colors[li%len(ascii_colors)]),(box_x+8,box_y+18+li*14))

# ═══════════════════════════════════════════════════════════
#  TICKET PANEL
# ═══════════════════════════════════════════════════════════
def draw_ticket_panel(screen, font_small, t):
    tickets = get_tickets()
    if not tickets: return
    recent_tickets = [tk for tk in tickets if time.time() - tk.get("timestamp", 0) < 15]
    if not recent_tickets: return
    
    show = recent_tickets[-3:]
    panel_w = 360
    panel_h = len(show) * 52 + 28
    px = WIDTH - panel_w - 6
    py = 66
    
    bg = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
    pygame.draw.rect(bg, (5, 10, 20, 200), (0, 0, panel_w, panel_h), border_radius=6)
    screen.blit(bg, (px, py))
    
    pulse = 0.5 + 0.5 * math.sin(t * 0.09)
    bc = (int(80 * pulse), int(180 + 60 * pulse), int(220 + 35 * pulse))
    border = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
    pygame.draw.rect(border, (*bc, 160), (0, 0, panel_w, panel_h), 2, border_radius=6)
    screen.blit(border, (px, py))
    
    screen.blit(font_small.render("⚠  IT TICKETS — TEPPO", True, CYAN_IT), (px + 8, py + 6))
    
    for i, tk in enumerate(show):
        ty2 = py + 22 + i * 52
        tc = pygame.Surface((panel_w - 12, 46), pygame.SRCALPHA)
        pygame.draw.rect(tc, (14, 20, 32, 200), (0, 0, panel_w - 12, 46), border_radius=4)
        pygame.draw.rect(tc, (CYAN_IT[0] // 3, CYAN_IT[1] // 3, CYAN_IT[2] // 3, 120), (0, 0, panel_w - 12, 46), 1, border_radius=4)
        screen.blit(tc, (px + 6, ty2))
        screen.blit(font_small.render(f"[{tk['time']}]", True, (80, 120, 140)), (px + 10, ty2 + 4))
        
        words2 = tk["text"][:140].split()
        tl, tls = "", []
        for w in words2:
            test2 = (tl + " " + w).strip()
            if font_small.size(test2)[0] < panel_w - 22: 
                tl = test2
            else:
                tls.append(tl)
                tl = w
        if tl: tls.append(tl)
        
        for tli, tln in enumerate(tls[:2]):
            screen.blit(font_small.render(tln, True, (200, 220, 240)), (px + 10, ty2 + 16 + tli * 13))

# ═══════════════════════════════════════════════════════════
#  AGENT
# ═══════════════════════════════════════════════════════════
class Agent:
    def __init__(self,name,role,x,y,filename,agent_type):
        self.name=name; self.role=role; self.x=x; self.y=y
        self.filename=filename; self.agent_type=agent_type
        shirt,hair,skin,accent=TEAM_COLORS[name]
        self.shirt=shirt; self.hair=hair; self.skin=skin; self.accent=accent
        self.current_thought="Booting up..."; self.is_thinking=False
        self.completed_instruction=""; self.completed_iteration=0
        self.think_anim_frame=0; self._timer_last_run=0.0

    def _build_context(self,all_agents):
        ctx=""; architect=next((a for a in all_agents if a.agent_type=="architect"),None)
        instr,iteration,_=get_state()
        if self.agent_type in ("coder","validator","hr","it_support","senior_fixer"):
            if architect and os.path.exists(architect.filename):
                try:
                    with open(architect.filename,"r",encoding="utf-8") as f:
                        ctx+=f"--- ARCHITECT BLUEPRINT ---\n{f.read()}\n\n"
                except Exception: pass
        if self.agent_type=="coder" and iteration>1:
            if os.path.exists("workspace/qa_report.txt"):
                try:
                    with open("workspace/qa_report.txt","r",encoding="utf-8") as f:
                        ctx+=f"--- QA FEEDBACK — FIX THESE ---\n{f.read()}\n\n"
                except Exception: pass
        if self.agent_type in ("validator","hr","it_support"):
            for a in all_agents:
                if a.agent_type=="coder" and os.path.exists(a.filename):
                    try:
                        with open(a.filename,"r",encoding="utf-8") as f:
                            ctx+=f"\n{a.name} ({a.filename}):\n{f.read()[:1200]}\n"
                    except Exception: pass
        if self.agent_type=="it_support":
            for fname in ("workspace/qa_report.txt","workspace/hr_report.txt"):
                if os.path.exists(fname):
                    try:
                        with open(fname,"r",encoding="utf-8") as f:
                            ctx+=f"\n--- {os.path.basename(fname).upper()} ---\n{f.read()[:800]}\n"
                    except Exception: pass
        return ctx

    def think(self,all_agents):
        instr,iteration,done=get_state()
        
        if not instr:
            if self.agent_type == "hr":
                self.current_thought = "Checking LinkedIn..."
            elif self.agent_type == "it_support":
                self.current_thought = "Updating Adobe Reader..."
            elif self.agent_type == "senior_fixer":
                self.current_thought = "Sipping espresso..."
            else:
                self.current_thought = "Waiting for project..."
            return False

        if self.agent_type=="architect":
            if self.completed_instruction==instr:
                self.current_thought="Waiting for client..."; return False
            return self._do_llm_call(all_agents,instr,iteration)
        elif self.agent_type=="marketing":
            if self.completed_instruction==instr:
                self.current_thought="Campaign live! ✨"; return False
            return self._do_llm_call(all_agents,instr,iteration)
        elif self.agent_type=="coder":
            arch=next((a for a in all_agents if a.agent_type=="architect"),None)
            if arch and arch.completed_instruction!=instr:
                self.current_thought="Waiting for blueprint..."; return False
            if done:
                self.current_thought="Pipeline complete."; return False
            if self.completed_instruction==instr and self.completed_iteration==iteration:
                self.current_thought="Waiting for QA..."; return False
            return self._do_llm_call(all_agents,instr,iteration)
        elif self.agent_type=="validator":
            arch=next((a for a in all_agents if a.agent_type=="architect"),None)
            if arch and arch.completed_instruction!=instr:
                self.current_thought="Awaiting architecture..."; return False
            coder=next((a for a in all_agents if a.agent_type=="coder"),None)
            if not coder or not(coder.completed_instruction==instr and coder.completed_iteration==iteration):
                self.current_thought="Waiting for dev..."; return False
            if done:
                self.current_thought="Pipeline complete."; return False
            if self.completed_instruction==instr and self.completed_iteration==iteration:
                self.current_thought="Idle."; return False
            return self._do_llm_call(all_agents,instr,iteration)
        elif self.agent_type=="hr":
            now=time.time()
            if now-self._timer_last_run<HR_COMMENT_INTERVAL:
                self.current_thought=random.choice(["Auditing snack budget...","Sipping oat latte...",
                    "Passive-aggressive email...","Updating the vibes...","Re-reading handbook..."])
                return False
            self._timer_last_run=now
            return self._do_llm_call(all_agents,instr,iteration)
        elif self.agent_type=="it_support":
            now=time.time()
            if now-self._timer_last_run<IT_CHECK_INTERVAL:
                self.current_thought=random.choice(["Monitoring logs...","Checking uptime...",
                    "Have you tried off/on?","Reading tickets...","Running diagnostics..."])
                return False
            has_qa=os.path.exists("workspace/qa_report.txt") and os.path.getsize("workspace/qa_report.txt")>10
            has_hr=os.path.exists("workspace/hr_report.txt") and os.path.getsize("workspace/hr_report.txt")>10
            if not has_qa and not has_hr:
                self._timer_last_run=now; self.current_thought="No reports yet..."; return False
            self._timer_last_run=now
            return self._do_llm_call(all_agents,instr,iteration)
        elif self.agent_type == "senior_fixer":
            if not done:
                self.current_thought = "Sipping espresso..."
                return False
            if self.completed_instruction == instr:
                self.current_thought = "Project saved."
                return False
            return self._do_gemini_call(instr)
            
        return False

    def _do_llm_call(self,all_agents,instr,iteration):
        self.is_thinking=True; ctx=self._build_context(all_agents)
        if self.agent_type=="architect":
            sys_p=(f"You are {self.name}, Lead Architect. Write a concise technical Markdown blueprint. "
                   f"Assign ALL work to a SINGLE developer named Alex. "
                   f"Determine what files are actually needed based on the client request. "
                   f"If it's a web app, specify backend.py and frontend.html. If it's just a script, specify only the .py file. "
                   f"Do not invent extra files or agents. Be specific about APIs, functions, or UI features.")
            usr_p=f"Client request: '{instr}'. Write the architecture blueprint."
            temp, max_t = 0.2, 1500
        elif self.agent_type=="marketing":
            sys_p=(f"You are {self.name}, Marketing Manager. A new software project just started. "
                   f"Create an exciting ASCII art marketing launch announcement. "
                   f"Use box-drawing characters (┌┐└┘│─), stars (*), and creative text art. "
                   f"Include product name, a punchy tagline, and ASCII art decoration. "
                   f"Max 16 lines, max 52 chars per line. Output ONLY raw ASCII art, nothing else.")
            usr_p=f"New project: '{instr}'. Create the marketing launch ASCII art now."
            temp, max_t = 0.8, 500
        elif self.agent_type=="coder":
            if iteration>1:
                sys_p=(f"You are {self.name}, Full-Stack Developer. QA rejected your last build. "
                       f"Read the QA feedback and produce fully corrected code based on the blueprint. "
                       f"Output ONLY raw code. Separate files with: ===FILE: <filename>=== No backticks.")
            else:
                sys_p=(f"You are {self.name}, Full-Stack Developer. Follow the Architect's blueprint exactly. "
                       f"Write complete runnable code for the requested files. "
                       f"Output ONLY raw code. Separate files with: ===FILE: <filename>=== No backticks.")
            usr_p=f"Blueprint:\n{ctx}\nWrite the files now."
            temp, max_t = 0.1, 12000
        elif self.agent_type=="validator":
            sys_p=(f"You are {self.name}, QA Lead. Review code vs blueprint. "
                   f"Check: missing features, syntax errors, broken API integrations, incomplete implementations. "
                   f"End your report with EXACTLY one tag on its own line:\n[STATUS: PASS]\n[STATUS: FAIL]\n"
                   f"PASS only if fully correct. Iteration {iteration}/{MAX_ITERATIONS}.")
            usr_p=f"Blueprint and code:\n{ctx}\nWrite the QA report."
            temp, max_t = 0.1, 800
        elif self.agent_type=="hr":
            sys_p=(f"You are {self.name}, HR Manager. In 1-2 sentences give a dry, passive-aggressive "
                   f"observation about the team. Reference the actual work.")
            usr_p=f"Team context:\n{ctx[:800]}\nWrite your observation."
            temp, max_t = 0.7, 150
        elif self.agent_type=="it_support":
            sys_p=(f"You are {self.name}, IT Support Engineer. You reviewed QA and HR reports. "
                   f"Write a formal IT support ticket TO THE CLIENT. Include:\n"
                   f"TICKET #[auto-number]\nPRIORITY: [LOW/MEDIUM/HIGH/CRITICAL]\n"
                   f"SUMMARY: [one sentence]\nDETAILS: [2-4 sentences about the issue]\n"
                   f"ACTION REQUIRED: [what client should do]\n"
                   f"Be professional but slightly dry IT-support tone. Reference actual report issues.")
            usr_p=f"Reports:\n{ctx}\nWrite the ticket now."
            temp, max_t = 0.3, 400
            
        payload={"model":_model_name,
                 "messages":[{"role":"system","content":sys_p},{"role":"user","content":usr_p}],
                 "temperature":temp,"max_tokens":max_t,"stream":False}
        try:
            resp=requests.post(LM_STUDIO_URL,headers={"Content-Type":"application/json"},
                               json=payload,timeout=300)
            if resp.status_code==200:
                data = resp.json()
                usage = data.get("usage", {})
                tokens_used = usage.get("total_tokens", 0)
                add_tokens(tokens_used)
                
                raw=data["choices"][0]["message"]["content"].strip()
                raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
                if raw.startswith("```"):
                    lines=raw.split("\n"); raw="\n".join(lines[1:-1] if len(lines)>2 else lines)
                self._handle_response(raw,instr,iteration)
            else:
                self.current_thought=f"API Error {resp.status_code}"
        except requests.exceptions.Timeout:
            self.current_thought="LM Studio timeout."
        except Exception as e:
            self.current_thought="Server disconnected."; print(f"[{self.name}] {e}")
        self.is_thinking=False; return True

    def _do_gemini_call(self, instr):
        self.is_thinking = True
        self.current_thought = "Fine, I'll do it myself..."
        
        files_to_read = ["architecture.md", "backend.py", "frontend.html", "qa_report.txt"]
        context = f"Project Instruction: {instr}\n\n"
        
        for filename in files_to_read:
            filepath = os.path.join("workspace", filename)
            if os.path.exists(filepath):
                with open(filepath, "r", encoding="utf-8") as f:
                    context += f"\n--- {filename.upper()} ---\n{f.read()}\n"

        sys_prompt = (
            "You are Gemini, the Senior Principal Developer. "
            "The junior dev team failed to deliver. Read the original client instruction, "
            "the architecture blueprint, and the QA report. "
            "Write the flawless, completed, production-ready code to fulfill the client's request. "
            "CRITICAL: Only generate the files required by the instruction and blueprint. "
            "If the request is only for a Python script, DO NOT generate HTML/JS/CSS. "
            "Output ONLY raw code. Separate files with: ===FILE: <filename>=== No markdown code blocks (backticks)."
        )

        try:
            client = genai.Client()
            response = client.models.generate_content(
                model='gemini-2.5-pro',
                contents=[sys_prompt, context],
                config=genai.types.GenerateContentConfig(temperature=0.1)
            )
            
            if response.usage_metadata:
                add_tokens(response.usage_metadata.total_token_count)
                
            raw_output = response.text.strip()
            if raw_output.startswith("```"):
                lines = raw_output.split("\n")
                raw_output = "\n".join(lines[1:-1] if len(lines) > 2 else lines)
                
            self._handle_response(raw_output, instr, 999) 
            self.completed_instruction = instr
            self.current_thought = "Code fixed. You're welcome."
            
        except Exception as e:
            self.current_thought = "API Error."
            print(f"[{self.name}] Gemini API Error: {e}")
            
        self.is_thinking = False
        return True

    def _handle_response(self,raw,instr,iteration):
        if self.agent_type=="marketing":
            set_marketing_art(raw)
            try:
                with open(self.filename,"w",encoding="utf-8") as f: f.write(raw)
            except Exception: pass
            self.current_thought="Campaign launched! 🎉"
            self.completed_instruction=instr; self.completed_iteration=iteration
            spawn_particles(self.x,self.y-30,PINK_MKTG,25,4.0)
            print(f"[Mika] ASCII art created ({len(raw)} chars)")
            return
        if self.agent_type=="hr":
            try:
                with open(self.filename,"a",encoding="utf-8") as f:
                    f.write(f"[{time.strftime('%H:%M:%S')}] {raw}\n\n")
            except Exception: pass
            self.current_thought=raw[:55]+("..." if len(raw)>55 else ""); return
        if self.agent_type=="it_support":
            add_ticket(raw); self.current_thought="Ticket filed! 🎫"
            spawn_particles(self.x,self.y-20,CYAN_IT,14,2.5); return
        if self.agent_type in ("coder", "senior_fixer"):
            sections,cur_file,cur_lines={},None,[]
            for line in raw.splitlines():
                stripped=line.strip()
                if stripped.startswith("===FILE:") and stripped.endswith("==="):
                    if cur_file and cur_lines:
                        sections[cur_file]="\n".join(cur_lines).strip()
                    cur_file=stripped[8:-3].strip(); cur_lines=[]
                else: cur_lines.append(line)
            if cur_file and cur_lines: sections[cur_file]="\n".join(cur_lines).strip()
            if not sections: sections["backend.py" if "flask" in raw.lower() else "app.py"]=raw
            written=[]
            for fname,code in sections.items():
                fpath=os.path.join("workspace",os.path.basename(fname))
                try:
                    with open(fpath,"w",encoding="utf-8") as f: f.write(code)
                    written.append(os.path.basename(fname))
                except Exception as e: print(f"[{self.name}] Write failed {fpath}: {e}")
            if written:
                self.current_thought=f"Wrote: {', '.join(written)}"
                self.completed_instruction=instr; self.completed_iteration=iteration
                spawn_particles(self.x,self.y-20,self.accent,10,2)
            else: self.current_thought="No valid code sections."
        elif self.agent_type=="architect":
            try:
                with open(self.filename,"w",encoding="utf-8") as f: f.write(raw)
            except Exception: self.current_thought="Write error."; return
            self.current_thought="Blueprint ready."
            self.completed_instruction=instr; self.completed_iteration=1
            spawn_particles(self.x,self.y-20,self.accent,12,2.5)
        elif self.agent_type=="validator":
            try:
                with open(self.filename,"w",encoding="utf-8") as f: f.write(raw)
            except Exception: pass
            if "[STATUS: FAIL]" in raw.upper():
                new_iter=bump_iteration()
                if new_iter is None:
                    self.current_thought="Max iters — exporting."
                    self._export(iteration); self.completed_instruction=instr
                    self.completed_iteration=iteration
                    spawn_particles(self.x,self.y-20,RED_ALERT,15,3)
                else:
                    self.current_thought=f"FAILED → iter {new_iter}"
                    self.completed_instruction=instr; self.completed_iteration=iteration
                    spawn_particles(self.x,self.y-20,(255,80,0),12,2.5)
            else:
                self._export(iteration); self.current_thought="PASSED — Exported!"
                self.completed_instruction=instr; self.completed_iteration=iteration
                mark_pipeline_done(); spawn_particles(self.x,self.y-20,GREEN_OK,20,3.5)

    def _export(self,iteration):
        ts=time.strftime("%Y%m%d_%H%M%S")
        export_dir=f"exports/build_{ts}_iter{iteration}"
        try: shutil.copytree("workspace",export_dir); print(f"\n[!!!] EXPORTED: {export_dir}\n")
        except Exception as e: print(f"Export failed: {e}")

# ═══════════════════════════════════════════════════════════
#  THREAD LOOP
# ═══════════════════════════════════════════════════════════
def agent_loop(agent,all_agents,ready_event):
    ready_event.wait()
    while True:
        if not agent.is_thinking:
            agent.think(all_agents)
        time.sleep(random.uniform(3,6))

# ═══════════════════════════════════════════════════════════
#  BACKGROUND
# ═══════════════════════════════════════════════════════════
def draw_office_bg(screen,t):
    pygame.draw.rect(screen,COLOR_CEILING,(0,0,WIDTH,60))
    pygame.draw.rect(screen,COLOR_WALL,(0,60,WIDTH,570))
    pygame.draw.rect(screen,COLOR_SKIRTING,(0,578,WIDTH,14))
    tile=60
    for tx in range(0,WIDTH,tile):
        for ty in range(592,HEIGHT-100,tile):
            c=COLOR_FLOOR1 if ((tx//tile)+(ty//tile))%2==0 else COLOR_FLOOR2
            pygame.draw.rect(screen,c,(tx,ty,tile,tile))
    sh=pygame.Surface((WIDTH,10),pygame.SRCALPHA); sh.fill((255,255,255,10)); screen.blit(sh,(0,592))
    for lx in range(120,WIDTH-100,240):
        pygame.draw.rect(screen,(50,54,68),(lx,36,80,10))
        lg=pygame.Surface((80,70),pygame.SRCALPHA)
        for gi in range(70):
            pygame.draw.rect(lg,(255,240,200,max(0,28-gi//3)),(0,gi,80,1))
        screen.blit(lg,(lx,46))
        for bx in range(4):
            on=(t//28+bx)%22!=0
            pygame.draw.rect(screen,(255,240,180) if on else (70,70,55),(lx+8+bx*20,38,14,5))
    _draw_window(screen,55,75,t); _draw_window(screen,WIDTH-175,75,t)

def _draw_window(screen,x,y,t):
    W,H=120,160
    sky=pygame.Surface((W-8,H-16),pygame.SRCALPHA)
    for sy in range(H-16):
        r2=sy/(H-16)
        pygame.draw.rect(sky,(int(28+38*r2),int(45+55*r2),int(95+75*r2)),(0,sy,W-8,1))
    for si in range(12):
        sx=(si*37+5)%(W-10); sy=(si*19+3)%((H-16)//2)
        pygame.draw.rect(sky,(255,255,200) if math.sin(t*.04+si)>.55 else (180,180,130),(sx,sy,2,2))
    for bx2,by2,bw2,bh2 in [(0,40,18,H-16-40),(18,55,14,H-16-55),(32,35,20,H-16-35),
                              (52,48,16,H-16-48),(68,30,22,H-16-30),(90,50,W-98,H-16-50)]:
        pygame.draw.rect(sky,(14,17,24),(bx2,by2,bw2,bh2))
        for wbx in range(3):
            for wby in range(4):
                lit=(t//18+wbx*3+wby)%7!=0
                pygame.draw.rect(sky,(255,200,80,190) if lit else (18,22,32),(bx2+2+wbx*5,by2+4+wby*8,3,4))
    screen.blit(sky,(x+4,y+8))
    pygame.draw.rect(screen,(58,63,78),(x,y,W,H),4)
    pygame.draw.rect(screen,(58,63,78),(x+W//2-2,y,4,H))
    pygame.draw.rect(screen,(58,63,78),(x,y+H//2-2,W,4))

# ═══════════════════════════════════════════════════════════
#  AGENT DRAW
# ═══════════════════════════════════════════════════════════
def draw_agent_full(screen,agent,t,fn,fr,ft):
    x,y=agent.x,agent.y
    instr,iteration,done=get_state()
    is_idle=(agent.completed_instruction==instr and agent.completed_iteration==iteration and not agent.is_thinking)
    is_think=agent.is_thinking
    if agent.agent_type=="architect": ds=create_whiteboard_sprite(t)
    elif agent.agent_type=="marketing": ds=create_marketing_desk_sprite(agent.shirt,t)
    elif agent.agent_type=="it_support": ds=create_it_desk_sprite(agent.shirt,t)
    elif agent.agent_type=="senior_fixer": ds=create_senior_desk_sprite(agent.shirt,t)
    else: ds=create_desk_sprite(agent.shirt,t)
    screen.blit(ds,(x-ds.get_width()//2+10,y))
    if is_think and agent.agent_type not in ("architect","hr"):
        gc=PINK_MKTG if agent.agent_type=="marketing" else CYAN_IT if agent.agent_type=="it_support" else agent.accent
        draw_glow(screen,x-10,y+10,50,36,gc,45)
    arms_up=is_idle and agent.agent_type not in ("hr",)
    bob_y=int(4*math.sin(t*0.14)) if arms_up else 0
    ch=draw_character(agent.shirt,agent.hair,agent.skin,facing_right=(x<WIDTH//2),arms_up=arms_up)
    cx=x-ch.get_width()//2; cy=y-ch.get_height()+8+bob_y
    screen.blit(ch,(cx,cy))
    if is_think:
        agent.think_anim_frame=(agent.think_anim_frame+1)%60
        for di in range(3):
            alpha=255 if (agent.think_anim_frame//15)==di else 80
            ds2=pygame.Surface((7,7),pygame.SRCALPHA)
            dc=PINK_MKTG if agent.agent_type=="marketing" else CYAN_IT if agent.agent_type=="it_support" else agent.accent
            pygame.draw.circle(ds2,(*dc[:3],alpha),(3,3),3); screen.blit(ds2,(cx+di*11,cy-14))
    screen.blit(fn.render(agent.name,True,WHITE),(x-fn.size(agent.name)[0]//2,y-ch.get_height()-8))
    screen.blit(fr.render(agent.role,True,(135,145,165)),(x-fr.size(agent.role)[0]//2,y-ch.get_height()+6))
    if is_idle and agent.agent_type not in ("hr",): status="Taukojumppa! 1-2!"
    elif is_think:
        dots="."*(1+(t//14)%3)
        status=("Designing"+dots if agent.agent_type=="marketing" else
                "Analysing"+dots if agent.agent_type=="it_support" else "Coding"+dots)
    else: status=agent.current_thought
    bub_col=(PINK_MKTG if (agent.agent_type=="marketing" and is_think) else
             CYAN_IT if (agent.agent_type=="it_support" and is_think) else
             agent.accent if is_think else (150,165,185))
    draw_speech_bubble(screen,ft,status,x+10,y-ch.get_height()-10,bub_col,t)
    if agent.agent_type=="validator" and not is_think:
        _,cur_iter,pdone=get_state()
        if pdone and agent.completed_iteration==cur_iter: bs=fr.render("✓ PASS",True,GREEN_OK)
        elif agent.completed_iteration<cur_iter and agent.completed_iteration>0:
            bs=fr.render(f"✗ FAIL iter {agent.completed_iteration}",True,(255,100,0))
        else: bs=None
        if bs: screen.blit(bs,(x-bs.get_width()//2,y+ds.get_height()-8))

# ═══════════════════════════════════════════════════════════
#  TERMINAL
# ═══════════════════════════════════════════════════════════
def draw_terminal(screen,agents,user_text,input_active,t,fu,fr):
    ty=HEIGHT-150
    pygame.draw.rect(screen,(7,9,13),(0,ty,WIDTH,HEIGHT-ty))
    pygame.draw.line(screen,(0,190,75),(0,ty),(WIDTH,ty),2)
    pygame.draw.rect(screen,(12,14,20),(0,ty,WIDTH,22))
    for di,dc in enumerate([(190,55,55),(190,170,55),(55,170,55)]):
        pygame.draw.circle(screen,dc,(13+di*17,ty+11),5)
    screen.blit(fu.render("terminal — AI Software Agency v3",True,(100,115,140)),(65,ty+4))
    
    instr, iteration, done = get_state()
    tokens = get_total_tokens()
    iter_c = GREEN_OK if done else (AMBER if iteration > 1 else (120, 140, 120))
    status_text = f"  ITER {iteration}/{MAX_ITERATIONS}  |  TOKENS: {tokens:,}  |  {'DONE ✓' if done else 'RUNNING'}  |  {instr[:60]}"
    screen.blit(fu.render(status_text, True, iter_c), (0, ty + 27))
    
    col_w=WIDTH//len(agents)
    for i,ag in enumerate(agents):
        ax=i*col_w+8
        screen.blit(fr.render(ag.name,True,ag.accent),(ax,ty+46))
        st="⚙ thinking" if ag.is_thinking else ag.current_thought[:24]
        screen.blit(fr.render(st,True,ag.accent if ag.is_thinking else (90,100,115)),(ax,ty+58))
    blink=(t//18)%2==0; pc=(0,245,90) if input_active else (70,95,70)
    screen.blit(fu.render(f"  $ {user_text}{'█' if blink and input_active else ' '}",True,pc),(0,ty+74))
    screen.blit(fr.render("  Kirjoita uusi projekti ja paina Enter käynnistääksesi.",True,(45,55,70)),(0,ty+90))

# ═══════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════
def main():
    init_workspace()
    global _model_name
    _model_name=get_loaded_model()
    print(f"Model: {_model_name}")
    pygame.init()
    screen=pygame.display.set_mode((WIDTH,HEIGHT))
    pygame.display.set_caption("AI Software Agency v3")
    clock=pygame.time.Clock()
    fn=pygame.font.SysFont("Courier New",13,bold=True)
    fr=pygame.font.SysFont("Courier New",10)
    ft=pygame.font.SysFont("Courier New",10,bold=True)
    fu=pygame.font.SysFont("Courier New",11,bold=True)
    f_mono=pygame.font.SysFont("Courier New",11)

    agents=[
        Agent("Charlie","Lead Architect", 150,310,"workspace/architecture.md","architect"),
        Agent("Alex",   "Full-Stack Dev", 450,310,"workspace/backend.py",     "coder"),
        Agent("Eve",    "QA Lead",        750,310,"workspace/qa_report.txt",  "validator"),
       # Agent("Gemini", "Senior Fixer",  1250,310,"workspace/backend.py",     "senior_fixer"),
        Agent("Mika",   "Marketing",      215,500,"workspace/marketing.txt",  "marketing"),
        Agent("Karen",  "Cynical HR",     560,500,"workspace/hr_report.txt",  "hr"),
        Agent("Teppo",  "IT Support",     905,500,"workspace/it_tickets.txt", "it_support"),
    ]

    plant=create_plant_sprite(); shelf=create_bookshelf_sprite()
    events={a.name:threading.Event() for a in agents}
    for ag in agents:
        threading.Thread(target=agent_loop,args=(ag,agents,events[ag.name]),daemon=True).start()

    # Wake up threads so they can sit idly
    for ag in agents:
        events[ag.name].set()

    input_active=False; user_text=""; frame=0; running=True

    while running:
        for event in pygame.event.get():
            if event.type==pygame.QUIT: running=False
            if event.type==pygame.MOUSEBUTTONDOWN:
                input_rect=pygame.Rect(0,HEIGHT-76,WIDTH,30)
                input_active=input_rect.collidepoint(event.pos)
            if event.type==pygame.KEYDOWN and input_active:
                if event.key==pygame.K_RETURN and user_text.strip():
                    set_instruction(user_text.strip()); set_marketing_art("")
                    for ag in agents:
                        ag.completed_instruction=""; ag.completed_iteration=0
                        ag.current_thought="New brief received!"
                    user_text=""
                    spawn_particles(WIDTH//2,HEIGHT-160,(0,255,100),22,3)
                    
                    # Fire sequence
                    events["Charlie"].set(); events["Mika"].set()
                    events["Alex"].clear()
                    threading.Timer(5.0,events["Alex"].set).start()
                    
                elif event.key==pygame.K_BACKSPACE: user_text=user_text[:-1]
                else: user_text+=event.unicode

        frame+=1
        draw_office_bg(screen,frame)
        server_s=create_server_rack_sprite(frame)
        screen.blit(server_s,(WIDTH-52,540)); screen.blit(shelf,(10,510))
        screen.blit(plant,(10,390)); screen.blit(plant,(WIDTH-42,380))
        pygame.draw.line(screen,(42,48,62),(0,475),(WIDTH,475),1)
        for ag in agents: draw_agent_full(screen,ag,frame,fn,fr,ft)
        update_draw_particles(screen)
        if get_marketing_art(): draw_marketing_overlay(screen,get_marketing_art(),f_mono,frame)
        draw_ticket_panel(screen,f_mono,frame)
        draw_terminal(screen,agents,user_text,input_active,frame,fu,fr)
        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()

if __name__=="__main__":
    main()