"""Aset pixel-art buat Tebak Gambar + render 3 tahap (makin jelas)."""
import io
from PIL import Image, ImageDraw, ImageFont

PALETTE = {
    ".": (18, 18, 24),      # background
    "R": (220, 50, 50),     # merah
    "G": (50, 180, 80),     # hijau
    "Y": (230, 200, 50),    # kuning
    "B": (50, 120, 220),    # biru
    "W": (235, 235, 235),   # putih
    "O": (230, 130, 40),    # oranye
    "P": (230, 120, 180),   # pink
    "N": (140, 95, 55),     # coklat
    "K": (10, 10, 10),      # hitam
    "C": (80, 200, 200),    # cyan
    "U": (150, 100, 220),   # ungu
}

# tiap item: (jawaban, clue, grid 8x8)
GAMBAR_LIST = [
    ("apel", "Buah", [
        "...RR...",
        "..RRRR..",
        ".RRRRRR.",
        ".RRRRRR.",
        ".RRRRRR.",
        "..RRRR..",
        "...GG...",
        "...N....",
    ]),
    ("rumah", "Bangunan", [
        "...RR...",
        "..RRRR..",
        ".RRRRRR.",
        "RRRRRRRR",
        "WWWWWWWW",
        "WWWKWWWW",
        "WWWKWWWW",
        "WWWKWWWW",
    ]),
    ("matahari", "Alam", [
        "Y..YY..Y",
        "...YY...",
        ".YYYYYY.",
        ".YYYYYY.",
        ".YYYYYY.",
        "...YY...",
        "Y..YY..Y",
        "........",
    ]),
    ("kucing", "Hewan", [
        "O.O..O.O",
        "OOOOOOOO",
        "OWKOOWKO",
        "OOOOOOOO",
        ".OOOOOO.",
        "..OYYO..",
        "...YY...",
        "........",
    ]),
    ("mobil", "Kendaraan", [
        "........",
        "..RRRR..",
        ".RRRRRR.",
        "RBRRRRBR",
        "RRRRRRRR",
        ".KK..KK.",
        ".KK..KK.",
        "........",
    ]),
    ("pohon", "Alam", [
        "...GG...",
        "..GGGG..",
        ".GGGGGG.",
        ".GGGGGG.",
        "..GGGG..",
        "...NN...",
        "...NN...",
        "..NNNN..",
    ]),
    ("bunga", "Alam", [
        ".P..P...",
        ".PPPP...",
        "..PPP...",
        "PPPPPPYY",
        "..PPPPY.",
        ".P..PY..",
        ".....G..",
        "....GG..",
    ]),
    ("ikan", "Hewan", [
        "........",
        "...OOO..",
        "..OOOOKO",
        ".OOOOOOO",
        "BOOOOOOO",
        ".OOOOOOO",
        "..OOOO..",
        "........",
    ]),
    ("hati", "Benda", [
        ".RR..RR.",
        "RRRRRRRR",
        "RRRRRRRR",
        "RRRRRRRR",
        ".RRRRRR.",
        "..RRRR..",
        "...RR...",
        "....R...",
    ]),
    ("bintang", "Langit", [
        "...Y....",
        "...Y....",
        ".YYYYY..",
        "YYYYYYYY",
        ".YYYYY..",
        "...Y....",
        "...Y....",
        "........",
    ]),
    ("jamur", "Makanan", [
        "..RRRR..",
        ".RWWRRW.",
        "RRRRRRRR",
        ".WWWWWW.",
        "..WWWW..",
        "..WWWW..",
        "........",
        "........",
    ]),
    ("kapal", "Kendaraan", [
        "...WW...",
        "...WW...",
        "...WW...",
        ".BBBBBB.",
        "BBBBBBBB",
        ".BBBBBB.",
        "..B..B..",
        "........",
    ]),
]

def _font(size=26):
    try:
        return ImageFont.truetype("arial.ttf", size)
    except Exception:
        return ImageFont.load_default()

# Foto asli (Wikimedia Commons, lisensi bebas). Diambil via Special:FilePath.
FOTO = {
    "apel": "Red Apple.jpg",
    "rumah": "Small wooden house on lake.jpg",
    "matahari": "Mrg sun sky blue.jpg",
    "kucing": "Cat November 2010-1a.jpg",
    "mobil": "Red Smart Car Side View Driveway.jpg",
    "pohon": "Rainfall nourishing the earth under a lone tree in a vibrant green field.jpg",
    "bunga": "Sunflower sky backdrop.jpg",
    "ikan": "Carassius auratus auratus (goldfish) 2.jpg",
    "hati": "Red heart.jpg",
    "bintang": "A starry sky above Death Valley and Orionid.jpg",
    "jamur": "Fly Agaric mushroom 04.jpg",
    "kapal": "OCEAN EXPRESS Clipper ship sailing card.jpg",
}

import os as _os
import urllib.request as _req
import urllib.parse as _parse

def fetch_foto(answer: str) -> bytes | None:
    """Download foto jawaban (cache di .cache/). Return bytes atau None kalau gagal."""
    fname = FOTO.get(answer)
    if not fname:
        return None
    try:
        _os.makedirs(".cache", exist_ok=True)
    except FileExistsError:
        pass
    safe = "".join(c if c.isalnum() else "_" for c in answer) + ".jpg"
    path = _os.path.join(".cache", "gambar_" + safe)
    if _os.path.exists(path) and _os.path.getsize(path) > 1000:
        with open(path, "rb") as f:
            return f.read()
    url = "https://commons.wikimedia.org/wiki/Special:FilePath/" + _parse.quote(fname) + "?width=480"
    try:
        r = _req.Request(url, headers={"User-Agent": "dc-tebakgambar-bot/1.0 (private discord bot)"})
        with _req.urlopen(r, timeout=20) as resp:
            data = resp.read()
        if len(data) < 1000:
            return None
        with open(path, "wb") as f:
            f.write(data)
        return data
    except Exception as e:
        print(f"fetch foto {answer} gagal: {e}")
        return None

def make_foto_image(data: bytes, stage=0):
    """Pixelasi foto asli per tahap: 0 burem banget, 1 lumayan, 2 jelas."""
    from PIL import ImageOps
    img = Image.open(io.BytesIO(data)).convert("RGB")
    # crop tengah jadi kotak
    w, h = img.size
    s = min(w, h)
    img = img.crop(((w - s) // 2, (h - s) // 2, (w + s) // 2, (h + s) // 2))
    tiny = {0: 10, 1: 28, 2: 480}[min(max(stage, 0), 2)]
    if tiny < 480:
        img = img.resize((tiny, tiny), Image.BILINEAR).resize((480, 480), Image.NEAREST)
    else:
        img = ImageOps.fit(img, (480, 480))
    canvas = Image.new("RGB", (520, 580), (18, 18, 24))
    canvas.paste(img, (20, 20))
    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle([10, 10, 510, 570], radius=18, outline=(80, 80, 100), width=3)
    label = ["SANGAT BUREM 🔍", "LUMAYAN 🙂", "JELAS 😎"][min(max(stage, 0), 2)]
    d.text((20, 515), f"TEBAK GAMBAR — {label}", font=_font(28), fill=(255, 255, 255))
    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    buf.seek(0)
    return buf

def make_gambar_image(grid, stage=0):
    """stage 0 = burem banget, 1 = lumayan, 2 = jelas."""
    n = len(grid)
    base = Image.new("RGB", (n, n))
    px = base.load()
    for y, row in enumerate(grid):
        for x, ch in enumerate(row[:n]):
            px[x, y] = PALETTE.get(ch, (18, 18, 24))
    tiny = {0: 3, 1: 5, 2: n}[min(max(stage, 0), 2)]
    small = base.resize((tiny, tiny), Image.BILINEAR)
    big = small.resize((480, 480), Image.NEAREST)
    img = Image.new("RGB", (520, 580), (18, 18, 24))
    img.paste(big, (20, 20))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([10, 10, 510, 570], radius=18, outline=(80, 80, 100), width=3)
    label = ["SANGAT BUREM 🔍", "LUMAYAN 🙂", "JELAS 😎"][min(max(stage, 0), 2)]
    d.text((20, 515), f"TEBAK GAMBAR — {label}", font=_font(28), fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf
