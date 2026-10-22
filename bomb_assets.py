"""Generator UI 2D buat Bomb Defusal - murni dari code (Pillow)."""
import io
from PIL import Image, ImageDraw, ImageFont

WIRE_COLORS = {
    "merah": (220, 50, 50),
    "biru": (50, 120, 220),
    "kuning": (230, 200, 50),
    "putih": (230, 230, 230),
    "hijau": (50, 180, 80),
    "ungu": (150, 80, 220),
}

def _font(size=28):
    try:
        return ImageFont.truetype("arial.ttf", size)
    except Exception:
        return ImageFont.load_default()

def make_bomb_image(wires, serial, symbols, strikes=0, time_left="3:00"):
    """wires: list warna ['merah','biru',...], symbols: list emoji/simbol string"""
    W, H = 800, 520
    img = Image.new("RGB", (W, H), (18, 18, 24))
    d = ImageDraw.Draw(img)
    # frame
    d.rounded_rectangle([10, 10, W-10, H-10], radius=18, outline=(80, 80, 100), width=3)
    d.text((30, 20), "💣 BOMB DEFUSAL", font=_font(34), fill=(255, 255, 255))
    d.text((30, 65), f"Serial: {serial}   Timer: {time_left}   Salah: {'X'*strikes}{'·'*(3-strikes)}", font=_font(24), fill=(255, 200, 80))
    y = 130
    for i, w in enumerate(wires, 1):
        col = WIRE_COLORS.get(w, (200, 200, 200))
        # label
        d.text((30, y+8), f"{i}. {w}", font=_font(26), fill=(255, 255, 255))
        # kabel
        d.rounded_rectangle([220, y, 740, y+36], radius=18, fill=col, outline=(0, 0, 0), width=2)
        # konektor
        d.rectangle([210, y+4, 225, y+32], fill=(60, 60, 70))
        d.rectangle([735, y+4, 750, y+32], fill=(60, 60, 70))
        y += 56
    # panel simbol
    d.text((30, y+5), "Simbol panel:", font=_font(24), fill=(180, 220, 255))
    sx = 30
    for s in symbols:
        d.rounded_rectangle([sx, y+35, sx+70, y+95], radius=10, fill=(35, 35, 50), outline=(120, 140, 180), width=2)
        d.text((sx+12, y+48), s, font=_font(32), fill=(255, 255, 255))
        sx += 85
    d.text((30, H-35), "P1 liat bom. P2 JANGAN ngintip. Komunikasi via VC!", font=_font(20), fill=(150, 150, 160))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf

def make_manual_image(rule_lines, symbol_guide="▲ ● ★ ◆ ■"):
    W, H = 800, 520
    img = Image.new("RGB", (W, H), (240, 235, 220))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([10, 10, W-10, H-10], radius=18, outline=(120, 90, 40), width=3)
    d.text((30, 20), "📖 MANUAL PENJINAK (RAHASIA P2)", font=_font(30), fill=(60, 40, 10))
    d.text((30, 60), f"Simbol referensi: {symbol_guide}", font=_font(22), fill=(80, 60, 20))
    y = 110
    for line in rule_lines:
        d.text((30, y), "• " + line, font=_font(22), fill=(30, 30, 30))
        y += 36
        if y > H-60:
            break
    d.text((30, H-35), "P2 pegang ini. P1 JANGAN ngintip. Kasih instruksi via VC!", font=_font(20), fill=(120, 90, 40))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf
