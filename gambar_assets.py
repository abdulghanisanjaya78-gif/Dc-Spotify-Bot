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
