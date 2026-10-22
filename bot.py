import os
import re
import asyncio
import urllib.parse
import urllib.request
import json
import discord
from discord.ext import commands
from dotenv import load_dotenv
import yt_dlp

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
ALLOWED_GUILD_ID = os.getenv("ALLOWED_GUILD_ID")  # opsional, isi ID server private biar cuma jalan di situ
if ALLOWED_GUILD_ID:
    try:
        ALLOWED_GUILD_ID = int(ALLOWED_GUILD_ID)
    except ValueError:
        ALLOWED_GUILD_ID = None

if not TOKEN:
    print("Isi dulu DISCORD_TOKEN di file .env")
    exit(1)

# Spotify API opsional — kalau ada keys dipake, kalau nggak pake oEmbed gratis
def _is_placeholder(v: str | None) -> bool:
    return not v or v.startswith("isi_")

sp = None
if not _is_placeholder(SPOTIFY_CLIENT_ID) and not _is_placeholder(SPOTIFY_CLIENT_SECRET):
    try:
        import spotipy
        from spotipy.oauth2 import SpotifyClientCredentials
        sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=SPOTIFY_CLIENT_SECRET
        ))
        # test auth langsung biar ketauan kalau keys salah
        print("Spotify API aktif.")
    except Exception as e:
        print(f"Spotify API gagal, pake mode tanpa keys: {e}")
        sp = None
else:
    print("Mode tanpa Spotify keys (pake oEmbed, cukup buat link track).")

def spotify_oembed_title(spotify_url: str) -> str | None:
    """Ambil judul via oEmbed tanpa keys. Return judul aja atau None."""
    try:
        api = "https://open.spotify.com/oembed?url=" + urllib.parse.quote(spotify_url)
        req = urllib.request.Request(api, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
            return data.get("title")
    except Exception as e:
        print(f"oEmbed gagal: {e}")
        return None

def _itunes_get(path: str):
    try:
        req = urllib.request.Request("https://itunes.apple.com" + path, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print(f"iTunes gagal: {e}")
        return None

def itunes_song_query(song_title: str) -> str:
    """Perkaya 'Infrunami' jadi 'Infrunami Steve Lacy audio' via iTunes (gratis, tanpa keys)."""
    data = _itunes_get("/search?term=" + urllib.parse.quote(song_title) + "&entity=song&limit=3")
    if data and data.get("results"):
        t = data["results"][0]
        return f"{t.get('trackName', song_title)} {t.get('artistName', '')} audio".strip()
    return f"{song_title} audio"

def itunes_album_tracks(album_title: str, limit: int = 20) -> list[tuple[str, str]]:
    """Cari tracklist album via iTunes (gratis). Return [(display, yt_query)]."""
    data = _itunes_get("/search?term=" + urllib.parse.quote(album_title) + "&entity=album&limit=5")
    if not data or not data.get("results"):
        return []
    # pilih album yang judulnya paling mirip
    best = None
    at = album_title.lower()
    for a in data["results"]:
        name = (a.get("collectionName") or "").lower()
        if at in name or name in at:
            best = a
            break
    best = best or data["results"][0]
    cid = best.get("collectionId")
    if not cid:
        return []
    d2 = _itunes_get(f"/lookup?id={cid}&entity=song&limit={limit + 5}")
    if not d2 or not d2.get("results"):
        return []
    out = []
    for t in d2["results"][1:limit + 1]:
        if t.get("wrapperType") != "track":
            continue
        title = f"{t.get('trackName')} - {t.get('artistName')}"
        out.append((title, f"{title} audio"))
    return out

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

import os as _os
YTDL_OPTS = {
    "format": "bestaudio/best",
    "quiet": True,
    "noplaylist": True,
    "default_search": "ytsearch",
    "extract_flat": False,
    "nocheckcertificate": True,
    "retries": 3,
    "fragment_retries": 3,
    "skip_unavailable_fragments": True,
    "force_ipv4": True,
    "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
}
# kalau YouTube nongol "Sign in to confirm you're not a bot", export cookies.txt dari Chrome via extension
# Get cookies.txt LOCALLY + taruh sebelahan sama bot.py, otomatis kepake
if _os.path.exists("cookies.txt"):
    YTDL_OPTS["cookiefile"] = "cookies.txt"
    print("Pake cookies.txt buat YouTube.")

FFMPEG_OPTS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin",
    "options": "-vn",
}

queues: dict[int, list[tuple[str, str]]] = {}  # guild_id -> [(title, yt_query)]
now_playing: dict[int, str] = {}  # guild_id -> "Judul - Artis" yang lagi muter
now_playing: dict[int, str] = {}  # guild_id -> "Judul - Artis" yang lagi muter

SPOTIFY_RE = re.compile(r"open\.spotify\.com/(track|playlist|album)/([A-Za-z0-9]+)")

def get_spotify_tracks(url: str) -> list[tuple[str, str]]:
    """Return list of (title, search_query) dari link Spotify. Kalau bukan link Spotify, anggap judul biasa."""
    m = SPOTIFY_RE.search(url)
    if not m:
        # bukan link spotify, cari langsung judulnya
        return [(url, url)]
    kind, sid = m.groups()
    # kalau ada Spotify API keys, pake itu (support playlist/album)
    global sp
    if sp is not None:
        try:
            if kind == "track":
                t = sp.track(sid)
                title = f"{t['name']} - {', '.join(a['name'] for a in t['artists'])}"
                return [(title, f"{title} audio")]
            elif kind == "playlist":
                items = sp.playlist_tracks(sid, limit=20)["items"]
                out = []
                for it in items:
                    t = it.get("track")
                    if not t:
                        continue
                    title = f"{t['name']} - {', '.join(a['name'] for a in t['artists'])}"
                    out.append((title, f"{title} audio"))
                return out
            elif kind == "album":
                items = sp.album_tracks(sid, limit=20)["items"]
                out = []
                for t in items:
                    title = f"{t['name']} - {', '.join(a['name'] for a in t['artists'])}"
                    out.append((title, f"{title} audio"))
                return out
        except Exception as e:
            print(f"Spotify error, fallback ke oEmbed: {e}")
            # akun Free kena 403 (Spotify wajibin Premium buat API) → matiin API sekalian biar nggak lemot tiap lagu
            if "403" in str(e) or "premium" in str(e).lower():
                sp = None
                print("Spotify API dimatiin (butuh akun Premium). Pake mode tanpa keys.")
            # jatuh ke fallback oEmbed di bawah, jangan langsung return []
            pass
        else:
            return []
    # mode tanpa keys / fallback: oEmbed + iTunes (gratis)
    clean_url = url.split("?")[0]
    if kind == "track":
        title = spotify_oembed_title(clean_url) or spotify_oembed_title(url)
        if title:
            return [(title, itunes_song_query(title))]
        return [(url, url)]
    elif kind == "album":
        title = spotify_oembed_title(clean_url) or spotify_oembed_title(url)
        if not title:
            return []
        tracks = itunes_album_tracks(title, limit=20)
        if tracks:
            return tracks
        # fallback: putar sebagai 1 item full album
        return [(title, f"{title} full album audio")]
    else:
        # playlist user butuh Spotify keys (tracklist user nggak ada di iTunes)
        return []

def search_youtube(query: str) -> tuple[str, str]:
    """Return (audio_url, video_title) dari query."""
    with yt_dlp.YoutubeDL(YTDL_OPTS) as ydl:
        info = ydl.extract_info(f"ytsearch1:{query}", download=False)
        entries = info.get("entries") if isinstance(info, dict) else None
        if not entries:
            raise RuntimeError("YouTube kosong (kemungkinan kena bot-check, butuh cookies.txt). Coba update: pip install -U yt-dlp")
        entry = entries[0]
        url = entry.get("url")
        if not url:
            raise RuntimeError("Dapet judul tapi nggak dapet audio URL (YouTube nolak).")
        return url, entry.get("title", query)

async def ensure_voice(ctx) -> discord.VoiceClient | None:
    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.send("Kamu harus join voice channel dulu.")
        return None
    channel = ctx.author.voice.channel
    try:
        if ctx.voice_client is None:
            vc = await channel.connect()
        elif ctx.voice_client.channel != channel:
            await ctx.voice_client.move_to(channel)
            vc = ctx.voice_client
        else:
            vc = ctx.voice_client
    except Exception as e:
        await ctx.send(f"Gagal join VC: {e} (cek permission Connect/Speak bot).")
        return None
    # tunggu handshake voice kelar (connect() return belum tentu connected)
    for _ in range(100):
        if vc.is_connected():
            return vc
        await asyncio.sleep(0.1)
    await ctx.send("Bot lama connect ke VC (timeout). Coba `!leave` terus `!play` lagi.")
    return None

async def play_next(ctx):
    gid = ctx.guild.id
    q = queues.get(gid, [])
    vc = ctx.voice_client
    if not q:
        now_playing.pop(gid, None)
        return
    if vc is None or not vc.is_connected():
        await ctx.send("⚠️ Bot ke-disconnect dari VC. Join VC lagi terus `!play` ulang.")
        return
    title, query = q.pop(0)
    try:
        loop = asyncio.get_running_loop()
        audio_url, yt_title = await loop.run_in_executor(None, lambda: search_youtube(query))
    except Exception as e:
        msg = str(e)
        if "bot" in msg.lower() or "sign in" in msg.lower() or "403" in msg:
            await ctx.send(f"⛔ YouTube nolak (`{title}`). Fix: update yt-dlp (`pip install -U yt-dlp`), restart bot. Kalau masih, perlu cookies.txt.")
        else:
            await ctx.send(f"Gagal cari `{title}`: {msg}")
        if q:
            await play_next(ctx)
        return

    try:
        source = discord.FFmpegPCMAudio(audio_url, **FFMPEG_OPTS)
    except Exception as e:
        await ctx.send(f"FFmpeg error (cek FFmpeg kepasang?): {e}")
        return

    ch = ctx.channel
    def after(err):
        if err:
            print(f"Player error: {err}")
            try:
                bot.loop.call_soon_threadsafe(ch.send, f"⚠️ Audio putus: {err}. Coba `!play` ulang / update yt-dlp.")
            except Exception:
                pass
        try:
            coro = play_next(ctx)
            fut = asyncio.run_coroutine_threadsafe(coro, bot.loop)
            fut.result()
        except Exception as e:
            print(f"after error: {e}")

    try:
        vc.play(source, after=after)
    except Exception as e:
        await ctx.send(f"Gagal muter: {e}")
        return
    now_playing[gid] = title
    await ctx.send(f"▶️ Now playing: **{title}**\n({yt_title})\nMau liriknya? Ketik `!lirik`")

@bot.event
async def on_ready():
    print(f"Login sebagai {bot.user} - siap buat call pribadi!")

@bot.event
async def on_guild_join(guild):
    # kalau sudah dikunci ke 1 server, langsung leave dari server lain
    if ALLOWED_GUILD_ID and guild.id != ALLOWED_GUILD_ID:
        await guild.leave()

def is_allowed_guild():
    async def predicate(ctx):
        if ctx.guild is None:
            return False
        if ALLOWED_GUILD_ID and ctx.guild.id != ALLOWED_GUILD_ID:
            await ctx.send("Bot ini dikunci buat server private aja.")
            return False
        return True
    return commands.check(predicate)

@bot.command(name="play")
@is_allowed_guild()
async def play(ctx, *, url: str):
    """!play <link spotify / judul> — bisa multi-link sekaligus (pisahin pake spasi/enter)"""
    vc = await ensure_voice(ctx)
    if vc is None:
        return
    # dukung multi-link: ambil semua URL spotify, sisa teks jadi 1 query judul
    urls = re.findall(r"https?://open\.spotify\.com/\S+", url)
    tracks: list[tuple[str, str]] = []
    failed_playlist = False
    if urls:
        for u in urls:
            t = get_spotify_tracks(u.rstrip(".,)>"))
            if not t and "playlist" in u:
                failed_playlist = True
            tracks.extend(t)
        leftover = SPOTIFY_RE.sub("", url)
        leftover = re.sub(r"https?://\S+", "", leftover).strip(" ,\n")
        if leftover:
            tracks.extend(get_spotify_tracks(leftover))
    else:
        tracks = get_spotify_tracks(url)
    if not tracks:
        if failed_playlist or "playlist" in url:
            await ctx.send("Playlist nggak bisa dibaca (API Spotify nolak, walau Premium — app baru kena limit). Paste aja 2-3 link track sekaligus di `!play`, misal:\n`!play <link1> <link2> <link3>`")
        else:
            await ctx.send("Link Spotify nggak kebaca. Coba link track/album public.")
        return
    gid = ctx.guild.id
    queues.setdefault(gid, []).extend(tracks)
    if len(tracks) == 1:
        await ctx.send(f"➕ Antri: **{tracks[0][0]}**")
    else:
        await ctx.send(f"➕ Antri {len(tracks)} lagu dari Spotify.")
    if not vc.is_playing() and not vc.is_paused():
        await play_next(ctx)

@bot.command(name="skip")
async def skip(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.send("⏭️ Skip.")
    else:
        await ctx.send("Lagi nggak muter apa-apa.")

@bot.command(name="stop")
async def stop(ctx):
    gid = ctx.guild.id
    queues[gid] = []
    now_playing.pop(gid, None)
    if ctx.voice_client and (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
        ctx.voice_client.stop()
    await ctx.send("⏹️ Berhenti + queue dikosongin.")

@bot.command(name="leave")
async def leave(ctx):
    gid = ctx.guild.id
    queues[gid] = []
    now_playing.pop(gid, None)
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("Bot cabut dari call. 👋")
    else:
        await ctx.send("Bot lagi nggak di call.")

@bot.command(name="queue")
async def show_queue(ctx):
    q = queues.get(ctx.guild.id, [])
    if not q:
        await ctx.send("Queue kosong.")
        return
    txt = "\n".join(f"{i+1}. {t}" for i, (t, _) in enumerate(q[:10]))
    await ctx.send(f"📜 Queue:\n{txt}")

def _fetch_lyrics(query_text: str) -> tuple[str, str] | None:
    """Return (judul_tampil, lirik) via lrclib (gratis), fallback lyrics.ovh. None kalau nggak ketemu."""
    text = query_text.replace(" audio", "").strip()
    artist, track = "", text
    if " - " in text:
        track, artist = [s.strip() for s in text.split(" - ", 1)]
    # 1. coba direct get kalau ada artis
    if artist:
        try:
            url = ("https://lrclib.net/api/get?artist_name=" + urllib.parse.quote(artist)
                   + "&track_name=" + urllib.parse.quote(track))
            req = urllib.request.Request(url, headers={"User-Agent": "dc-bot"})
            d = json.loads(urllib.request.urlopen(req, timeout=10).read().decode())
            if d.get("plainLyrics"):
                disp = f"{d.get('trackName', track)} - {d.get('artistName', artist)}"
                return disp, d["plainLyrics"].strip()
        except Exception as e:
            print(f"lrclib get gagal: {e}")
    # 2. search
    try:
        url = "https://lrclib.net/api/search?q=" + urllib.parse.quote(text)
        req = urllib.request.Request(url, headers={"User-Agent": "dc-bot"})
        data = json.loads(urllib.request.urlopen(req, timeout=10).read().decode())
        for r in data if isinstance(data, list) else []:
            if r.get("plainLyrics"):
                return f"{r.get('trackName')} - {r.get('artistName')}", r["plainLyrics"].strip()
    except Exception as e:
        print(f"lrclib search gagal: {e}")
    # 3. fallback lyrics.ovh (butuh artis + judul)
    if artist:
        try:
            url = ("https://api.lyrics.ovh/v1/" + urllib.parse.quote(artist)
                   + "/" + urllib.parse.quote(track))
            req = urllib.request.Request(url, headers={"User-Agent": "dc-bot"})
            d = json.loads(urllib.request.urlopen(req, timeout=10).read().decode())
            if d.get("lyrics"):
                return f"{track} - {artist}", d["lyrics"].strip()
        except Exception as e:
            print(f"lyrics.ovh gagal: {e}")
    return None

@bot.command(name="lirik")
@is_allowed_guild()
async def lirik_cmd(ctx, *, query: str = ""):
    """!lirik — lirik lagu yang lagi muter. !lirik <judul> — cari lirik lagu lain."""
    target = query.strip() or now_playing.get(ctx.guild.id, "")
    if not target:
        await ctx.send("Lagi nggak muter apa-apa. Pake `!lirik <judul>` atau putar dulu `!play`.")
        return
    await ctx.send(f"🔎 Nyari lirik **{target}**...")
    try:
        loop = asyncio.get_running_loop()
        res = await loop.run_in_executor(None, lambda: _fetch_lyrics(target))
    except Exception as e:
        await ctx.send(f"Gagal ambil lirik: {e}")
        return
    if not res:
        await ctx.send(f"😅 Lirik **{target}** nggak ketemu. Coba `!lirik <judul - artis>` yang lebih spesifik.")
        return
    disp, lyrics = res
    # potong per 1900 char biar muat limit Discord
    chunks, cur = [], ""
    for line in lyrics.split("\n"):
        if len(cur) + len(line) + 1 > 1900:
            chunks.append(cur)
            cur = line
            if len(chunks) >= 3:
                cur += "\n... (dipotong, kepanjangan)"
                break
        else:
            cur += ("\n" if cur else "") + line
    if cur:
        chunks.append(cur)
    await ctx.send(f"🎤 **Lirik: {disp}**")
    for c in chunks[:4]:
        await ctx.send(c)

# ===== QUIZ DUEL BERDUA =====
import random
QUIZ_QUESTIONS = [
    ("Ibukota Indonesia?", "jakarta"),
    ("Kota hujan di Indonesia?", "bogor"),
    ("Hewan berkantung dari Australia?", "kanguru"),
    ("Warna campuran merah + putih?", "pink"),
    ("Planet terdekat dari matahari?", "merkurius"),
    ("Lagu 'Infrunami' dinyanyiin siapa?", "steve lacy"),
    ("Hari kemerdekaan Indonesia tanggal berapa?", "17 agustus"),
    ("Air mendidih suhu berapa celcius?", "100"),
    ("Kebalikan kata 'panas'?", "dingin"),
    ("Jumlah kaki laba-laba?", "8"),
    ("Bahasa Inggrisnya 'kucing'?", "cat"),
    ("Sungai terpanjang di Mesir?", "nil"),
    ("Nama hewan peliharaan paling umum di Indonesia?", "kucing"),
    ("Es mencair jadi apa?", "air"),
    ("Tahun sekarang?", "2026"),
    ("1 minggu ada berapa hari?", "7"),
    ("Warna langit pas cerah?", "biru"),
    ("Nasi goreng berasal dari negara mana?", "indonesia"),
    ("Lawan kata 'besar'?", "kecil"),
    ("Benda buat dengerin musik di telinga?", "earphone"),
    ("Ibukota Jepang?", "tokyo"),
    ("Ibukota Korea Selatan?", "seoul"),
    ("Benua terbesar di dunia?", "asia"),
    ("Samudra terbesar?", "pasifik"),
    ("Gunung tertinggi di dunia?", "everest"),
    ("Gunung tertinggi di Indonesia?", "jaya wijaya"),
    ("Pulau terbesar di Indonesia?", "papua"),
    ("Mata uang Jepang?", "yen"),
    ("Mata uang Korea Selatan?", "won"),
    ("Mata uang Amerika?", "dolar"),
    ("Pulau dewata?", "bali"),
    ("Makanan khas Jepang mentah?", "sushi"),
    ("Spongebob tinggal di mana?", "bikini bottom"),
    ("Musuh Mario kura-kura besar?", "bowser"),
    ("Kota pahlawan di Indonesia?", "surabaya"),
    ("Hewan tercepat di darat?", "cheetah"),
    ("Hewan terbesar di dunia?", "paus biru"),
    ("Burung nggak bisa terbang di Antartika?", "pinguin"),
    ("Jumlah kaki gurita?", "8"),
    ("Makanan favorit panda?", "bambu"),
    ("Warna bendera Indonesia?", "merah putih"),
    ("Lagu kebangsaan Indonesia?", "indonesia raya"),
    ("Presiden pertama Indonesia?", "soekarno"),
    ("Candi terbesar di Indonesia?", "borobudur"),
    ("Danau terbesar di Indonesia?", "toba"),
    ("Sungai terpanjang di Indonesia?", "kapuas"),
    ("Bahasa Inggrisnya 'anjing'?", "dog"),
    ("Bahasa Inggrisnya 'makan'?", "eat"),
    ("Bahasa Inggrisnya 'minum'?", "drink"),
    ("Bahasa Inggrisnya 'rumah'?", "house"),
    ("Planet merah?", "mars"),
    ("Planet terbesar?", "jupiter"),
    ("Planet ada cincinnya?", "saturnus"),
    ("Benda langit yang bersinar di malam hari?", "bintang"),
    ("Air beku jadi apa?", "es"),
    ("Minyak + air, yang ngambang?", "minyak"),
    ("Alat buat motret?", "kamera"),
    ("Alat buat nelpon?", "hp"),
    ("Kendaraan roda dua?", "motor"),
    ("Kendaraan roda empat?", "mobil"),
    ("Ibukota Jawa Barat?", "bandung"),
    ("Ibukota Jawa Timur?", "surabaya"),
    ("Makanan khas Padang?", "rendang"),
    ("Minuman dari kopi + susu?", "latte"),
    ("Buah warna kuning panjang?", "pisang"),
    ("Buah isinya air, kulit hijau?", "semangka"),
    ("Sayur warna oranye disuka kelinci?", "wortel"),
    ("Game battle royale paling rame?", "pubg"),
    ("Game balok kotak-kotak?", "minecraft"),
    ("Konsol buatan Sony?", "playstation"),
    ("Pokemon api warna merah?", "charmander"),
    ("Hokage ke-7 Naruto siapa?", "naruto"),
    ("Bajak laut topi jerami siapa?", "luffy"),
    ("Anime robot kucing dari masa depan?", "doraemon"),
    ("Ibukota Thailand?", "bangkok"),
    ("Menara miring ada di negara?", "italia"),
    ("Piramida ada di negara?", "mesir"),
    ("Tembok besar ada di negara?", "cina"),
    ("Jumlah pemain sepak bola 1 tim?", "11"),
    ("Olahraga pake raket + kok?", "badminton"),
    ("Jumlah sisi dadu?", "6"),
    ("Hari setelah Senin?", "selasa"),
    ("Bulan puasa umat Islam?", "ramadhan"),
    ("Hari Natal tanggal berapa?", "25 desember"),
    ("Tahun baru tanggal berapa?", "1 januari"),
    ("Ibukota Bali?", "denpasar"),
    ("Ibukota Sumatera Utara?", "medan"),
    ("Ibukota Malaysia?", "kuala lumpur"),
    ("Ibukota Filipina?", "manila"),
    ("Ibukota Vietnam?", "hanoi"),
    ("Ibukota Australia?", "canberra"),
    ("Ibukota Inggris?", "london"),
    ("Ibukota Perancis?", "paris"),
    ("Ibukota Jerman?", "berlin"),
    ("Ibukota Belanda?", "amsterdam"),
    ("Jam Gadang ada di kota?", "bukittinggi"),
    ("Malioboro ada di kota?", "yogyakarta"),
    ("Kota apel di Indonesia?", "malang"),
    ("Pulau komodo ada di?", "flores"),
    ("Danau tiga warna ada di?", "ende"),
    ("Selat antara Jawa-Sumatera?", "sunda"),
    ("Selat antara Bali-Lombok?", "lombok"),
    ("Negara tetangga timur Indonesia?", "timor leste"),
    ("Sungai Amazon di benua?", "amerika selatan"),
    ("Gurun terbesar di dunia?", "sahara"),
    ("Sate paling terkenal dari?", "madura"),
    ("Gudeg dari kota?", "yogyakarta"),
    ("Pempek dari kota?", "palembang"),
    ("Papeda dari daerah?", "papua"),
    ("Kerak telor dari?", "betawi"),
    ("Lumpia dari kota?", "semarang"),
    ("Soto lamongan dari?", "lamongan"),
    ("Rawon kuahnya warna?", "hitam"),
    ("Nasi liwet dari?", "solo"),
    ("Ayam betutu dari?", "bali"),
    ("Coto makassar dari kota?", "makassar"),
    ("Minuman jahe hangat dari Jawa?", "wedang jahe"),
    ("Tempe terbuat dari?", "kedelai"),
    ("Hewan leher panjang?", "jerapah"),
    ("Hewan hidung panjang belalai?", "gajah"),
    ("Raja hutan?", "singa"),
    ("Burung terbesar nggak bisa terbang?", "burung unta"),
    ("Hewan belang hitam putih?", "zebra"),
    ("Hewan bisa ganti warna kulit?", "bunglon"),
    ("Hewan tidur gantung?", "kelelawar"),
    ("Serangga bikin madu?", "lebah"),
    ("Hewan cangkang keras jalan lambat?", "kura-kura"),
    ("Ular terbesar?", "anaconda"),
    ("Hiu bernapas pake?", "insang"),
    ("Hewan malam mata besar?", "tarsius"),
    ("Hewan hidung besar di Kalimantan?", "bekantan"),
    ("Komodo termasuk hewan?", "biawak"),
    ("Gas yang kita hirup?", "oksigen"),
    ("Gas yang kita hembuskan?", "karbon dioksida"),
    ("Proses masak makanan tumbuhan?", "fotosintesis"),
    ("Organ buat napas?", "paru-paru"),
    ("Organ pompa darah?", "jantung"),
    ("Tulang melindungi otak?", "tengkorak"),
    ("Indera pengecap?", "lidah"),
    ("Pelangi muncul habis?", "hujan"),
    ("Air laut rasanya?", "asin"),
    ("Gula rasanya?", "manis"),
    ("Jeruk nipis rasanya?", "asam"),
    ("Tumbuhan butuh cahaya buat?", "fotosintesis"),
    ("Pembuat Minecraft?", "mojang"),
    ("Landak biru cepat?", "sonic"),
    ("Kuning listrik Pokemon?", "pikachu"),
    ("Saudara Mario baju hijau?", "luigi"),
    ("Konsol genggam Nintendo?", "switch"),
    ("Game bola EA?", "fifa"),
    ("Game horror zombie Capcom?", "resident evil"),
    ("Monster hijau Minecraft meledak?", "creeper"),
    ("Game MOBA mobile 5v5?", "mobile legends"),
    ("Senjata Jedi?", "lightsaber"),
    ("Sekolah Harry Potter?", "hogwarts"),
    ("Mobil Batman?", "batmobile"),
    ("Planet asal Superman?", "krypton"),
    ("Ramen kesukaan Naruto di?", "ichiraku"),
    ("Bola naga jumlahnya?", "7"),
    ("Pangeran Saiyan rival Goku?", "vegeta"),
    ("Koki kapal Topi Jerami?", "sanji"),
    ("Rubah ekor sembilan namanya?", "kurama"),
    ("Guru Tim 7?", "kakashi"),
    ("Doraemon takut sama?", "tikus"),
    ("Adik Doraemon?", "dorami"),
    ("Spongebob kerja di?", "krusty krab"),
    ("Sahabat Patrick?", "spongebob"),
    ("Trofi sepak bola paling bergengsi?", "piala dunia"),
    ("Lapangan badminton dibagi?", "net"),
    ("Papan catur warna?", "hitam putih"),
    ("Lempar cakram masuk cabang?", "atletik"),
    ("Gaya renang tercepat?", "bebas"),
    ("Lampu merah artinya?", "berhenti"),
    ("Lampu hijau artinya?", "jalan"),
    ("Rambu P coret artinya?", "dilarang parkir"),
    ("Upacara bendera hari?", "senin"),
    ("Libur tiap minggu hari?", "minggu"),
    ("Lambang negara Indonesia?", "garuda"),
    ("Alat musik 6 senar petik?", "gitar"),
    ("Piano mini ditiup?", "pianika"),
    ("Alat musik pukul kulit?", "drum"),
    ("Penyanyi Shape of You?", "ed sheeran"),
    ("Vokalis Coldplay?", "chris martin"),
    ("Indonesia Raya ciptaan?", "wr supratman"),
    ("Boneka kayu hidung panjang?", "pinokio"),
    ("Putri tidur Disney?", "aurora"),
    ("Teman Snow White?", "kurcaci"),
    ("Koboi mainan Toy Story?", "woody"),
    ("Mobil balap merah Pixar?", "mcqueen"),
    ("Ayah Nemo?", "marlin"),
    ("Burung beo bisa?", "meniru"),
    ("Ibukota Kalimantan Timur?", "samarinda"),
    ("Bandara Soekarno Hatta di?", "tangerang"),
    ("Makanan fermentasi Korea pedas?", "kimchi"),
    ("Teh susu topping bola kenyal?", "boba"),
    ("Olahraga raket di meja?", "tenis meja"),
    ("Film alien naik sepeda terbang?", "et"),
    ("Robot raksasa Jepang?", "gundam"),
    ("Penyanyi Bad Guy?", "billie eilish"),
    ("Kue kering lebaran keju?", "kastengel"),
]

pending_duel: dict[int, dict] = {}
active_quiz: dict[int, dict] = {}
last_quiz: dict[int, dict] = {}

@bot.command(name="quizduel")
@is_allowed_guild()
async def quizduel(ctx, opponent: discord.Member, total: int = 5):
    """!quizduel @temen 5 — tantang duel quiz"""
    if opponent.bot:
        await ctx.send("Jangan lawan bot, lawan temen lu.")
        return
    if opponent.id == ctx.author.id:
        await ctx.send("Masa lawan diri sendiri bre.")
        return
    if ctx.guild.id in active_quiz:
        await ctx.send("Lagi ada quiz jalan, selesain dulu.")
        return
    total = max(3, min(20, total))
    pending_duel[ctx.guild.id] = {"p1": ctx.author, "p2": opponent, "total": total, "channel": ctx.channel}
    await ctx.send(f"⚔️ {ctx.author.mention} nantang {opponent.mention} quiz duel {total} soal!\n{opponent.mention} ketik `!accept` buat mulai. (Rematch +5, max 20)")

@bot.command(name="accept")
@is_allowed_guild()
async def accept_quiz(ctx):
    gid = ctx.guild.id
    if gid not in pending_duel:
        await ctx.send("Nggak ada tantangan, bikin dulu pake `!quizduel @temen`.")
        return
    d = pending_duel[gid]
    if ctx.author.id != d["p2"].id:
        await ctx.send(f"Yang ditantang {d['p2'].mention}, bukan lu.")
        return
    del pending_duel[gid]
    await ctx.send(f"🔥 Duel mulai! {d['p1'].mention} vs {d['p2'].mention} — jawab pake `!jawab <jawaban>`, tercepat dapet poin!")
    bot.loop.create_task(run_quiz(ctx, d["p1"], d["p2"], d["total"]))

async def run_quiz(ctx, p1, p2, total):
    gid = ctx.guild.id
    soal = random.sample(QUIZ_QUESTIONS, min(total, len(QUIZ_QUESTIONS)))
    scores = {p1.id: 0, p2.id: 0}
    names = {p1.id: p1.display_name, p2.id: p2.display_name}
    active_quiz[gid] = {"p1": p1.id, "p2": p2.id, "scores": scores, "answer": None, "event": asyncio.Event(), "active": True, "lock": asyncio.Lock(), "qid": 0, "skipped": False}
    try:
        for i, (q, a) in enumerate(soal, 1):
            st = active_quiz.get(gid)
            if not st or not st["active"]:
                break
            async with st["lock"]:
                st["qid"] += 1
                st["answer"] = None  # kunci dulu biar jawaban nyasar nggak kepake
                st["event"].clear()
            await ctx.send(f"❓ Soal {i}/{len(soal)}: **{q}**\nJawab pake `!jawab ...` (30 detik)")
            await asyncio.sleep(1)  # kasih jeda biar urutan chat Discord rapi + anti spam
            async with st["lock"]:
                st["answer"] = a.lower().strip()
            try:
                await asyncio.wait_for(st["event"].wait(), timeout=30)
                async with st["lock"]:
                    if st.get("skipped"):
                        st["skipped"] = False
                        await ctx.send(f"⏭️ Dilewati! Jawabannya: **{a}**")
            except asyncio.TimeoutError:
                async with st["lock"]:
                    # kalau udah dijawab pas timeout bareng, jangan double timeout
                    if st["event"].is_set():
                        continue
                await ctx.send(f"⏰ Waktu habis! Jawabannya: **{a}**")
            await asyncio.sleep(1)  # jeda antar soal biar nggak numpuk
        st = active_quiz.get(gid)
        if st:
            s1, s2 = st["scores"][p1.id], st["scores"][p2.id]
            if s1 > s2:
                win = p1.mention
            elif s2 > s1:
                win = p2.mention
            else:
                win = "Seri! 🤝"
            await ctx.send(f"🏁 Selesai! Skor {names[p1.id]}: {s1} — {names[p2.id]}: {s2}\nPemenang: {win}")
            last_quiz[gid] = {"p1": p1, "p2": p2, "total": total}
            if total < 20:
                await ctx.send(f"🔁 Mau rematch? Ketik `!rematch` → next {min(total+5, 20)} soal!")
            else:
                await ctx.send("🔁 Max 20 soal, ketik `!rematch` buat ulang 20 soal!")
    finally:
        active_quiz.pop(gid, None)

@bot.command(name="rematch")
@is_allowed_guild()
async def quiz_rematch(ctx):
    """Tantang ulang, soal +5 (max 20)."""
    gid = ctx.guild.id
    if gid in active_quiz:
        await ctx.send("Lagi ada quiz jalan, selesain dulu.")
        return
    if gid in pending_duel:
        await ctx.send("Udah ada tantangan, `!accept` dulu.")
        return
    last = last_quiz.get(gid)
    if not last:
        await ctx.send("Belum ada duel. Bikin dulu `!quizduel @temen`.")
        return
    # tentuin lawan: kalau yang ngetik salah satu pemain kemarin, lawannya yang satunya
    if ctx.author.id == last["p1"].id:
        opponent = last["p2"]
    elif ctx.author.id == last["p2"].id:
        opponent = last["p1"]
    else:
        await ctx.send("Kamu nggak ikut duel terakhir, bikin baru `!quizduel @temen`.")
        return
    total = min(last["total"] + 5, 20)
    pending_duel[gid] = {"p1": ctx.author, "p2": opponent, "total": total, "channel": ctx.channel}
    await ctx.send(f"🔁 {ctx.author.mention} nantang rematch {opponent.mention} {total} soal! (+5, max 20)\n{opponent.mention} ketik `!accept` buat mulai.")

@bot.command(name="jawab")
@is_allowed_guild()
async def jawab(ctx, *, teks: str):
    gid = ctx.guild.id
    st = active_quiz.get(gid)
    if not st or not st["active"]:
        return
    if ctx.author.id not in (st["p1"], st["p2"]):
        return
    async with st["lock"]:
        if st["event"].is_set():
            return  # udah ada yang bener, kunci pake lock biar nggak dobel poin
        if st["answer"] is None:
            return  # soal belum kebuka penuh, abaikan jawaban nyasar
        if teks.lower().strip() == st["answer"]:
            st["scores"][ctx.author.id] += 1
            s1, s2 = st["scores"][st["p1"]], st["scores"][st["p2"]]
            st["event"].set()
        else:
            return
    await ctx.send(f"✅ {ctx.author.mention} bener! (+1) Skor sekarang: {s1} - {s2}")
    # kalau salah diem aja biar seru, kasih kesempatan yang lain

@bot.command(name="stopquiz")
@is_allowed_guild()
async def stopquiz(ctx):
    st = active_quiz.get(ctx.guild.id)
    if st:
        st["active"] = False
        st["event"].set()
        await ctx.send("🛑 Quiz dihentikan.")
    else:
        pending_duel.pop(ctx.guild.id, None)
        await ctx.send("Nggak ada quiz jalan.")

@bot.command(name="lewat")
@is_allowed_guild()
async def quiz_skip(ctx):
    """Skip soal quiz aktif (salah satu pemain)."""
    st = active_quiz.get(ctx.guild.id)
    if not st or not st["active"]:
        return
    if ctx.author.id not in (st["p1"], st["p2"]):
        return
    async with st["lock"]:
        if st["event"].is_set():
            return
        st["skipped"] = True
        st["event"].set()
    await ctx.send(f"⏭️ {ctx.author.mention} skip soal.")

# ===== TRUTH OR DARE BERDUA =====
TRUTH_LIST = [
    "Apa hal paling receh yang bikin kamu seneng akhir-akhir ini?",
    "Game apa yang paling bikin kamu emosi?",
    "Pernah pura-pura lag pas main biar nggak kalah? Kapan?",
    "Apa makanan yang kamu pura-pura suka padahal enggak?",
    "Kapan terakhir begadang? Karena apa?",
    "Apa chat paling kocak yang pernah kamu kirim?",
    "Kalau bisa ngulang 1 hari, hari apa yang mau diulang?",
    "Apa kebiasaan jelek kamu pas main game?",
    "Pernah ketiduran pas VC? Ceritain.",
    "Apa lagu yang paling sering kamu dengerin minggu ini?",
    "Kalau dikasih 10 juta sekarang, mau dipake buat apa?",
    "Apa yang paling kamu takutin?",
    "Apa nickname paling alay yang pernah kamu pake?",
    "Game apa yang bikin kamu begadang?",
    "Momen paling malu-maluin pas main game apa?",
    "Pernah salah kirim chat ke orang yang salah? Isinya apa?",
    "Map / karakter favorit kamu apa?",
    "Berapa jam sehari kamu main HP?",
    "Film / anime terakhir yang kamu tonton apa?",
    "Kalau jadi streamer, mau stream game apa?",
]

DARE_LIST = [
    "Kirim voice note nyanyi 10 detik lagu apa aja.",
    "Ganti nickname Discord jadi 'Tukang Begadang' selama 10 menit.",
    "Kirim foto ekspresi paling jelek kamu sekarang.",
    "Kirim voice note ngomong pake suara robot.",
    "Spam 5 emoji random ke channel ini.",
    "Ceritain mimpi paling aneh yang pernah kamu inget.",
    "Tiruin suara kucing 3x di voice channel.",
    "Putar 1 lagu Spotify random dari playlist kamu sekarang.",
    "Push up 10x terus foto buktinya (boleh ngibul gaya).",
    "Gambar karakter game favorit pake paint sejelek mungkin terus kirim sini.",
    "Ngomong pake bahasa alay selama 5 menit ke depan.",
    "VC 1 menit cuma buat bilang hal random.",
    "Kirim screenshot wallpaper HP kamu sekarang.",
    "Pura-pura jadi bot, jawab 3 pesan berikutnya dengan format 'BIP BOP: ...'.",
    "Ketik dengan mata ketutup 1 kalimat panjang.",
    "Kasih 3 fakta random tentang diri kamu sekarang juga.",
    "Main 1 ronde suit via chat.",
    "Play 1 lagu random dari Spotify dan dengerin bareng 1 menit.",
    "Ganti foto profil jadi foto meme selama 10 menit.",
    "Tulis nickname temen main kamu huruf besar 3x di channel.",
]

@bot.command(name="truth")
@is_allowed_guild()
async def truth(ctx):
    await ctx.send(f"🙊 Truth buat {ctx.author.mention}:\n**{random.choice(TRUTH_LIST)}**")

@bot.command(name="dare")
@is_allowed_guild()
async def dare(ctx):
    await ctx.send(f"🔥 Dare buat {ctx.author.mention}:\n**{random.choice(DARE_LIST)}**")

@bot.command(name="tod")
@is_allowed_guild()
async def tod(ctx, target: discord.Member = None):
    """!tod @temen — kasih truth/dare random ke target"""
    who = target.mention if target else ctx.author.mention
    if random.random() < 0.5:
        await ctx.send(f"🙊 Truth buat {who}:\n**{random.choice(TRUTH_LIST)}**")
    else:
        await ctx.send(f"🔥 Dare buat {who}:\n**{random.choice(DARE_LIST)}**")

# ===== 6. MIND READER (Cooperate / Betray / Protect) =====
# C-C: 3,3 | C-B: -2,5 | C-P: 2,2 | B-B: 0,0 | B-P: 1,1 | P-P: 1,1
MIND_PAYOFF = {
    ("coop", "coop"): (3, 3),
    ("coop", "betray"): (-2, 5),
    ("coop", "protect"): (2, 2),
    ("betray", "coop"): (5, -2),
    ("betray", "betray"): (0, 0),
    ("betray", "protect"): (1, 1),
    ("protect", "coop"): (2, 2),
    ("protect", "betray"): (1, 1),
    ("protect", "protect"): (1, 1),
}
MIND_EMOJI = {"coop": "🤝", "betray": "🗡️", "protect": "🛡️"}
MIND_ROUNDS = 10

pending_mind: dict[int, dict] = {}  # guild_id -> {p1, p2, channel}
active_mind: dict[int, dict] = {}  # guild_id -> game state

def _find_mind_by_user(user_id: int):
    for gid, g in active_mind.items():
        if user_id in (g["p1_id"], g["p2_id"]):
            return gid, g
    return None, None

@bot.command(name="mindreader")
@is_allowed_guild()
async def mindreader(ctx, opponent: discord.Member):
    """!mindreader @temen — tantang Mind Reader 10 ronde"""
    if opponent.bot or opponent.id == ctx.author.id:
        await ctx.send("Lawan harus temen lu yang asli.")
        return
    if ctx.guild.id in active_mind:
        await ctx.send("Lagi ada Mind Reader jalan.")
        return
    pending_mind[ctx.guild.id] = {"p1": ctx.author, "p2": opponent, "channel": ctx.channel}
    await ctx.send(
        f"🧠 {ctx.author.mention} nantang {opponent.mention} Mind Reader ({MIND_ROUNDS} ronde)!\n"
        f"{opponent.mention} ketik `!mindaccept`.\n"
        f"Aturan: 🤝=kerja sama, 🗡️=khianat gede kalo lawan kooperatif, 🛡️=aman dari khianat."
    )

@bot.command(name="mindaccept")
@is_allowed_guild()
async def mindaccept(ctx):
    gid = ctx.guild.id
    if gid not in pending_mind:
        await ctx.send("Nggak ada tantangan. Bikin dulu `!mindreader @temen`.")
        return
    d = pending_mind.pop(gid)
    if ctx.author.id != d["p2"].id:
        await ctx.send(f"Yang ditantang {d['p2'].mention}.")
        return
    p1, p2 = d["p1"], d["p2"]
    active_mind[gid] = {
        "p1_id": p1.id, "p2_id": p2.id,
        "p1_mention": p1.mention, "p2_mention": p2.mention,
        "names": {p1.id: p1.display_name, p2.id: p2.display_name},
        "scores": {p1.id: 0, p2.id: 0},
        "round": 1, "choices": {}, "channel": d["channel"],
        "history": [],
    }
    await d["channel"].send(
        f"🔥 Mind Reader mulai! {p1.mention} vs {p2.mention} — {MIND_ROUNDS} ronde.\n"
        f"Ronde 1: **DM bot** masing-masing `!coop` / `!betray` / `!protect`.\n"
        f"Payoff: C-C +3/+3, C-B -2/+5, B-B 0/0, kena Protect jadi +1/+1, P-P +1/+1, P-C +2/+2."
    )
    # coba DM dua-duanya biar gampang
    for u in (p1, p2):
        try:
            await u.send(f"🧠 Mind Reader Ronde 1 — balas di sini: `!coop` / `!betray` / `!protect`")
        except Exception:
            pass

async def _mind_choose(ctx, move: str):
    # bisa dari DM maupun channel
    if ctx.guild is None:
        gid, g = _find_mind_by_user(ctx.author.id)
        if g is None:
            await ctx.send("Nggak ada game Mind Reader buat kamu.")
            return
        channel = g["channel"]
    else:
        gid = ctx.guild.id
        g = active_mind.get(gid)
        if g is None:
            await ctx.send("Nggak ada game jalan. Bikin dulu `!mindreader @temen`.")
            return
        if ctx.author.id not in (g["p1_id"], g["p2_id"]):
            return
        channel = ctx.channel
        # kalau pilih di channel publik, ingetin biar DM aja (tetep dihitung biar simpel)
        if ctx.channel.id != channel.id:
            channel = ctx.channel

    if ctx.author.id in g["choices"]:
        await ctx.send("Pilihan ronde ini udah dikunci, tunggu lawan.")
        return

    g["choices"][ctx.author.id] = move
    # konfirmasi rahasia
    try:
        await ctx.send(f"🔒 Terkunci: {MIND_EMOJI[move]} {move} (Ronde {g['round']}). Tunggu lawan...")
    except Exception:
        pass

    if len(g["choices"]) == 2:
        p1, p2 = g["p1_id"], g["p2_id"]
        m1, m2 = g["choices"][p1], g["choices"][p2]
        s1, s2 = MIND_PAYOFF[(m1, m2)]
        g["scores"][p1] += s1
        g["scores"][p2] += s2
        g["history"].append((g["round"], m1, m2, s1, s2))
        r = g["round"]
        await channel.send(
            f"🎭 Ronde {r}: {g['names'][p1]} {MIND_EMOJI[m1]} ({m1}) vs {MIND_EMOJI[m2]} ({m2}) {g['names'][p2]}\n"
            f"Hasil: `{s1:+d}` / `{s2:+d}` → Skor: **{g['names'][p1]} {g['scores'][p1]} — {g['scores'][p2]} {g['names'][p2]}**"
        )
        g["choices"] = {}
        g["round"] += 1
        if g["round"] > MIND_ROUNDS:
            s1f, s2f = g["scores"][p1], g["scores"][p2]
            if s1f > s2f:
                win = g["p1_mention"]
            elif s2f > s1f:
                win = g["p2_mention"]
            else:
                win = "Seri! 🤝"
            pola = "\n".join(f"R{h}: {MIND_EMOJI[a]}vs{MIND_EMOJI[b]} ({x:+d}/{y:+d})" for h, a, b, x, y in g["history"])
            await channel.send(f"🏁 Mind Reader selesai!\nSkor akhir: **{g['names'][p1]} {s1f} — {s2f} {g['names'][p2]}**\nPemenang: {win}\nRiwayat:\n{pola}")
            active_mind.pop(gid, None)
        else:
            await channel.send(f"➡️ Ronde {g['round']}: DM bot `!coop` / `!betray` / `!protect`.")

@bot.command(name="coop")
async def mind_coop(ctx):
    await _mind_choose(ctx, "coop")

@bot.command(name="betray")
async def mind_betray(ctx):
    await _mind_choose(ctx, "betray")

@bot.command(name="protect")
async def mind_protect(ctx):
    await _mind_choose(ctx, "protect")

@bot.command(name="mindstop")
async def mindstop(ctx):
    gid = ctx.guild.id if ctx.guild else None
    if gid and gid in active_mind:
        active_mind.pop(gid, None)
        pending_mind.pop(gid, None)
        await ctx.send("🛑 Mind Reader dihentikan.")
    else:
        _, g = _find_mind_by_user(ctx.author.id)
        if g:
            # cari gid-nya
            for k, v in list(active_mind.items()):
                if v is g:
                    active_mind.pop(k, None)
                    try:
                        await v["channel"].send("🛑 Mind Reader dihentikan dari DM.")
                    except Exception:
                        pass
                    break
            await ctx.send("🛑 Mind Reader dihentikan.")
        else:
            await ctx.send("Nggak ada game jalan.")

@bot.command(name="mindscore")
async def mindscore(ctx):
    g = active_mind.get(ctx.guild.id) if ctx.guild else None
    if not g:
        await ctx.send("Nggak ada game jalan.")
        return
    await ctx.send(f"🧠 Ronde {g['round']}/{MIND_ROUNDS} — Skor: **{g['names'][g['p1_id']]} {g['scores'][g['p1_id']]} — {g['scores'][g['p2_id']]} {g['names'][g['p2_id']]}**")

@bot.command(name="games")
async def games_list(ctx):
    await ctx.send(
        "🎮 **LIST GAME**\n"
        "1. 🎵 Musik — `!play <link>` / `!skip` / `!stop` / `!leave` / `!queue` / `!lirik`\n"
        "2. ❓ Quiz Duel — `!quizduel @temen 5` → `!accept` → `!jawab ...`\n"
        "3. 🙊 Truth or Dare — `!truth` / `!dare` / `!tod @temen`\n"
        "4. 🧠 Mind Reader — `!mindreader @temen` → `!mindaccept`\n"
        "5. 💣 Bomb Defusal — `!bomb @temen` → `!bombaccept` → `!cut <nomor>`\n"
        "6. 🔤 Tebak Kata — `!tebakkata` → `!tebak <huruf/kata>` → `!nyerah`\n"
        "Ketik `!rules <musik|quiz|tod|mind|bomb|kata>` buat aturan lengkap."
    )

# ===== 4. BOMB DEFUSAL (Co-op 2 pemain + UI 2D) =====
try:
    import bomb_assets
except Exception as e:
    bomb_assets = None
    print(f"bomb_assets gagal load: {e}")

pending_bomb: dict[int, dict] = {}
active_bomb: dict[int, dict] = {}

BOMB_COLORS = ["merah", "biru", "kuning", "putih", "hijau", "ungu"]
BOMB_SYMBOLS = ["▲", "●", "★", "◆", "■", "✖"]

def _bomb_correct_order(wires, serial, symbols):
    """Algoritma urutan potong — HARUS sama dengan manual yang dikirim ke P2."""
    n = len(wires)
    order = []
    used = set()
    # 1. bintang -> kuning pertama dulu
    if "★" in symbols:
        for i, w in enumerate(wires):
            if w == "kuning":
                order.append(i + 1)
                used.add(i + 1)
                break
    # 2. serial genap/ganjil
    try:
        last_digit = int(serial[-1])
    except Exception:
        last_digit = 0
    if last_digit % 2 == 0:
        for i in range(n):
            pos = i + 1
            if pos not in used and pos % 2 == 0:
                order.append(pos)
                used.add(pos)
    else:
        for i in range(n - 1, -1, -1):
            pos = i + 1
            if pos not in used:
                # ganjil: dari kanan, tapi skip yang udah dipake
                order.append(pos)
                used.add(pos)
        # kalau ganjil, aturan 3 udah ke-cover (sisa kosong), return dengan aturan merah di bawah
        pass
    # 3. sisa dari kiri
    if last_digit % 2 == 0:
        for i in range(n):
            pos = i + 1
            if pos not in used:
                order.append(pos)
                used.add(pos)
    # 4. kalau 2+ merah, merah terakhir pindah ke ujung
    reds = [i + 1 for i, w in enumerate(wires) if w == "merah"]
    if len(reds) >= 2:
        last_red = reds[-1]
        if last_red in order:
            order.remove(last_red)
            order.append(last_red)
    return order

def _bomb_manual_lines(serial):
    try:
        last_digit = int(serial[-1])
    except Exception:
        last_digit = 0
    parity = "GENAP" if last_digit % 2 == 0 else "GANJIL"
    return [
        f"Serial bom: {serial} (digit terakhir {last_digit} = {parity}).",
        "1. Kalau panel bom ada simbol ★, potong KABEL KUNING pertama dulu.",
        "2. GENAP: lanjut nomor genap dari kiri (2,4...). GANJIL: lanjut dari kanan ke kiri.",
        "3. (GENAP saja) Potong sisanya dari kiri ke kanan (1..N).",
        "4. Kalau kabel MERAH ada 2 atau lebih, MERAH terakhir dipotong PALING AKHIR.",
        "Salah 3x = MELEDAK. Waktu 3 menit. Perintah di channel: !cut <nomor> cth !cut 2",
    ]

@bot.command(name="bomb")
@is_allowed_guild()
async def bomb_start(ctx, partner: discord.Member):
    """!bomb @temen — co-op jinakin bom 3 menit"""
    if bomb_assets is None:
        await ctx.send("Modul gambar belum kepasang (pillow). Install dulu: pip install pillow")
        return
    if partner.bot or partner.id == ctx.author.id:
        await ctx.send("Partner harus temen asli.")
        return
    if ctx.guild.id in active_bomb:
        await ctx.send("Lagi ada misi jalan.")
        return
    pending_bomb[ctx.guild.id] = {"p1": ctx.author, "p2": partner, "channel": ctx.channel}
    await ctx.send(
        f"💣 {ctx.author.mention} ngajak {partner.mention} jinakin bom!\n"
        f"{partner.mention} ketik `!bombaccept`.\n"
        f"P1 ({ctx.author.mention}) = liat kabel. P2 ({partner.mention}) = pegang manual. Wajib VC!"
    )

@bot.command(name="bombaccept")
@is_allowed_guild()
async def bomb_accept(ctx):
    gid = ctx.guild.id
    if gid not in pending_bomb:
        await ctx.send("Nggak ada ajakan. Bikin dulu `!bomb @temen`.")
        return
    d = pending_bomb.pop(gid)
    if ctx.author.id != d["p2"].id:
        await ctx.send(f"Yang diajak {d['p2'].mention}.")
        return
    p1, p2 = d["p1"], d["p2"]
    channel = d["channel"]
    wires = [random.choice(BOMB_COLORS) for _ in range(4)]
    serial = f"{random.choice('ABCDEF')}{random.randint(10,99)}{random.choice('XYZ')}{random.randint(0,9)}"
    symbols = random.sample(BOMB_SYMBOLS, 3)
    correct = _bomb_correct_order(wires, serial, symbols)
    game = {
        "p1_id": p1.id, "p2_id": p2.id,
        "p1_mention": p1.mention, "p2_mention": p2.mention,
        "wires": wires, "serial": serial, "symbols": symbols,
        "correct": correct, "idx": 0, "strikes": 0,
        "channel": channel, "active": True,
    }
    active_bomb[gid] = game

    # bikin gambar 2D
    try:
        bom_img = bomb_assets.make_bomb_image(wires, serial, symbols, strikes=0, time_left="3:00")
        man_img = bomb_assets.make_manual_image(_bomb_manual_lines(serial))
    except Exception as e:
        await channel.send(f"Gagal bikin gambar: {e}")
        active_bomb.pop(gid, None)
        return

    # kirim rahasia via DM
    try:
        await p1.send(f"💣 KAMU = DEFUSER. Jangan kasih liat ke {p2.display_name}!\nKabel (kiri→kanan): {', '.join(f'{i+1}={w}' for i, w in enumerate(wires))}", file=discord.File(fp=bom_img, filename="bom.png"))
    except Exception:
        await channel.send(f"{p1.mention} DM-nya ketutup, buka DM dulu! Misi batal.")
        active_bomb.pop(gid, None)
        return
    try:
        await p2.send(f"📖 KAMU = EXPERT. Jangan kasih liat ke {p1.display_name}!\nTuntun dia via VC pakai aturan ini:", file=discord.File(fp=man_img, filename="manual.png"))
    except Exception:
        await channel.send(f"{p2.mention} DM-nya ketutup, buka DM dulu! Misi batal.")
        active_bomb.pop(gid, None)
        return

    await channel.send(
        f"🚨 MISI MULAI! {p1.mention} (bom) + {p2.mention} (manual) — 3 menit!\n"
        f"Kabel ada {len(wires)}. Potong berurutan pake `!cut <nomor>` di sini.\n"
        f"Salah 3x meledak. Gl!"
    )
    bot.loop.create_task(_bomb_timer(gid, channel, 180))

async def _bomb_timer(gid, channel, seconds):
    try:
        for mark in (120, 60, 30, 10):
            await asyncio.sleep(seconds - mark if mark == 120 else (120-60 if mark==60 else (60-30 if mark==30 else 20)))
            g = active_bomb.get(gid)
            if not g or not g["active"]:
                return
            if mark == 10:
                await channel.send("⏳ 10 detik!")
            else:
                await channel.send(f"⏳ Sisa {mark//60}:{mark%60:02d}!")
            seconds = mark
        await asyncio.sleep(seconds)
    except asyncio.CancelledError:
        return
    g = active_bomb.get(gid)
    if g and g["active"]:
        g["active"] = False
        active_bomb.pop(gid, None)
        await channel.send(f"💥 BOOM! Waktu habis. Urutan bener: {g['correct']}. Misi gagal.")

@bot.command(name="cut")
@is_allowed_guild()
async def bomb_cut(ctx, nomor: int):
    gid = ctx.guild.id
    g = active_bomb.get(gid)
    if not g or not g["active"]:
        return
    if ctx.author.id not in (g["p1_id"], g["p2_id"]):
        return
    if not 1 <= nomor <= len(g["wires"]):
        await ctx.send(f"Nomor 1-{len(g['wires'])} aja.")
        return
    expected = g["correct"][g["idx"]]
    if nomor == expected:
        g["idx"] += 1
        left = len(g["correct"]) - g["idx"]
        if left == 0:
            g["active"] = False
            active_bomb.pop(gid, None)
            await ctx.send(f"✅ Kabel {nomor} ({g['wires'][nomor-1]}) BENAR! 🎉 BOM JINAK! {g['p1_mention']} + {g['p2_mention']}GG!")
        else:
            await ctx.send(f"✅ Kabel {nomor} benar! Sisa {left} kabel. Lanjut!")
    else:
        g["strikes"] += 1
        if g["strikes"] >= 3:
            g["active"] = False
            active_bomb.pop(gid, None)
            await ctx.send(f"💥 BOOM! Salah 3x (potong {nomor}, harusnya {expected}). Urutan bener: {g['correct']}.")
        else:
            await ctx.send(f"❌ Salah! Potong {nomor}, harusnya {expected} (kabel ke-{g['idx']+1}). Strike {g['strikes']}/3!")

@bot.command(name="bombstop")
@is_allowed_guild()
async def bomb_stop(ctx):
    g = active_bomb.get(ctx.guild.id)
    if g:
        g["active"] = False
        active_bomb.pop(ctx.guild.id, None)
        await ctx.send("🛑 Misi dibatalkan.")
    else:
        pending_bomb.pop(ctx.guild.id, None)
        await ctx.send("Nggak ada misi jalan.")

@bot.command(name="rules")
async def game_rules(ctx, nama: str = ""):
    nama = nama.lower().strip()
    if nama in ("musik", "music", "play"):
        await ctx.send("🎵 **MUSIK**\nJoin voice dulu → `!play <link spotify track / judul>` → bot join + muter.\n`!skip` skip, `!stop` berhenti+clear, `!leave` cabut, `!queue` liat antrian.\n`!lirik` lirik lagu yang lagi muter, `!lirik <judul>` cari lirik lain.")
    elif nama in ("quiz", "quizduel"):
        await ctx.send("❓ **QUIZ DUEL**\n`!quizduel @temen 5` → lawan `!accept` → bot kasih 5 soal.\nJawab pake `!jawab <jawaban>`, tercepat bener +1. Timeout 30 dtk/soal. `!lewat` skip soal, `!stopquiz` berhenti.")
    elif nama in ("tod", "truth", "dare", "truthordare"):
        await ctx.send("🙊🔥 **TRUTH OR DARE**\n`!truth` random pertanyaan, `!dare` random tantangan, `!tod @temen` random salah satu buat target. Boleh pass kalau nggak nyaman.")
    elif nama in ("mind", "mindreader"):
        await ctx.send(
            "🧠 **MIND READER (10 ronde)**\n"
            "Tiap ronde DM bot: `!coop` 🤝 / `!betray` 🗡️ / `!protect` 🛡️.\n"
            "C-C +3/+3, C-B -2/+5, P kena B +1/+1, B-B 0/0, P-P 1/1, P-C +2/+2.\n"
            "Khianat 1 ronde cuan gede, tapi bikin lawan protect terus. Menang total 10 ronde."
        )
    elif nama in ("bomb", "bom", "defusal"):
        await ctx.send(
            "💣 **BOMB DEFUSAL (co-op)**\n"
            "`!bomb @temen` → `!bombaccept` → P1 dapet gambar BOM via DM, P2 dapet MANUAL via DM.\n"
            "Ngobrol di VC, potong berurutan pake `!cut <nomor>` di channel. 3 menit, 3x salah meledak.\n"
            "P1 jangan share gambar bom, P2 jangan share manual — komunikasi mulut aja!"
        )
    else:
        await ctx.send("Pilih: `!rules musik` / `!rules quiz` / `!rules tod` / `!rules mind` / `!rules bomb` / `!rules kata`")
    if nama in ("kata", "tebakkata", "hangman"):
        await ctx.send(
            "🔤 **TEBAK KATA (co-op)**\n"
            "`!tebakkata` mulai → bot milih kata rahasia + kasih clue kategori + buka 1 huruf gratis.\n"
            "Tebak bareng pake `!tebak <huruf>` atau langsung `!tebak <kata>`.\n"
            "Nyawa per orang 6 — salahmu nggak ngurangin nyawa temen. Gugur sendiri-sendiri, game kalah kalau semua gugur. `!nyerah` liat jawaban."
        )

# ===== 5. TEBAK KATA (hangman co-op berdua) =====
KATA_LIST = [  # (kata, clue kategori)
    ("kucing", "Hewan"), ("anjing", "Hewan"), ("gajah", "Hewan"), ("jerapah", "Hewan"),
    ("kanguru", "Hewan"), ("pinguin", "Hewan"), ("buaya", "Hewan"),
    ("harimau", "Hewan"), ("singa", "Hewan"), ("zebra", "Hewan"), ("beruang", "Hewan"),
    ("serigala", "Hewan"), ("rubah", "Hewan"), ("ular", "Hewan"), ("kadal", "Hewan"),
    ("katak", "Hewan"), ("kupu", "Hewan"), ("lebah", "Hewan"), ("semut", "Hewan"),
    ("pisang", "Buah"), ("semangka", "Buah"), ("durian", "Buah"), ("mangga", "Buah"),
    ("rambutan", "Buah"), ("alpukat", "Buah"),
    ("gitar", "Alat musik"), ("piano", "Alat musik"), ("drum", "Alat musik"),
    ("seruling", "Alat musik"), ("biola", "Alat musik"),
    ("sepeda", "Kendaraan"), ("motor", "Kendaraan"), ("mobil", "Kendaraan"),
    ("pesawat", "Kendaraan"), ("kapal", "Kendaraan"), ("kereta", "Kendaraan"),
    ("gunung", "Alam"), ("pantai", "Alam"), ("hutan", "Alam"), ("sungai", "Alam"),
    ("danau", "Alam"), ("pulau", "Alam"),
    ("hujan", "Alam"), ("petir", "Alam"), ("pelangi", "Alam"), ("angin", "Alam"),
    ("salju", "Alam"), ("badai", "Alam"),
    ("matahari", "Langit"), ("bulan", "Langit"), ("bintang", "Langit"),
    ("awan", "Langit"), ("langit", "Langit"),
    ("komputer", "Elektronik"), ("laptop", "Elektronik"), ("kamera", "Elektronik"),
    ("televisi", "Elektronik"), ("radio", "Elektronik"), ("kipas", "Elektronik"),
    ("buku", "Sekolah"), ("pensil", "Sekolah"), ("penghapus", "Sekolah"),
    ("penggaris", "Sekolah"), ("meja", "Sekolah"), ("kursi", "Sekolah"),
    ("sekolah", "Sekolah"), ("guru", "Sekolah"),
    ("nasi", "Makanan"), ("mie", "Makanan"), ("roti", "Makanan"), ("sate", "Makanan"),
    ("rendang", "Makanan"), ("soto", "Makanan"), ("bakso", "Makanan"),
    ("kopi", "Minuman"), ("teh", "Minuman"), ("susu", "Minuman"),
    ("jus", "Minuman"), ("soda", "Minuman"),
    ("kantor", "Tempat"), ("pasar", "Tempat"), ("rumah", "Tempat"),
    ("sakit", "Tempat"), ("taman", "Tempat"),
    ("bola", "Olahraga"), ("raket", "Olahraga"), ("net", "Olahraga"),
    ("gawang", "Olahraga"), ("peluit", "Olahraga"),
    ("dokter", "Profesi"), ("polisi", "Profesi"), ("pilot", "Profesi"),
    ("nelayan", "Profesi"), ("petani", "Profesi"),
]
HANGMAN = [
    "```\n+---+\n    |\n    |\n    |\n   ===\n```",
    "```\n+---+\nO   |\n    |\n    |\n   ===\n```",
    "```\n+---+\nO   |\n|   |\n    |\n   ===\n```",
    "```\n+---+\nO   |\n/|  |\n    |\n   ===\n```",
    "```\n+---+\nO   |\n/|\\ |\n    |\n   ===\n```",
    "```\n+---+\nO   |\n/|\\ |\n/   |\n   ===\n```",
    "```\n+---+\nO   |\n/|\\ |\n/ \\ |\n   ===\n```",
]
active_kata: dict[int, dict] = {}

def _kata_board(word: str, guessed: set) -> str:
    return " ".join(c if c in guessed else "_" for c in word)

@bot.command(name="tebakkata")
@is_allowed_guild()
async def tebakkata_start(ctx):
    gid = ctx.guild.id
    if gid in active_kata:
        await ctx.send("Lagi ada tebak kata jalan. `!nyerah` dulu kalau mau ganti.")
        return
    word, clue = random.choice(KATA_LIST)
    # buka 1 huruf gratis biar nggak buta total (kata pendek nggak dibuka)
    opening: set = set()
    if len(word) >= 4:
        opening.add(random.choice(word))
    active_kata[gid] = {"word": word, "clue": clue, "guessed": set(opening), "wrong": {}, "dead": set(), "max_wrong": 6, "channel": ctx.channel}
    board = _kata_board(word, opening)
    extra = f"\n🎁 Huruf pembuka: `{''.join(sorted(opening))}`" if opening else ""
    await ctx.send(
        f"🔤 **TEBAK KATA mulai!** 💡 Clue: **{clue}**, {len(word)} huruf.\n"
        f"Nyawa per orang: 6. Gugur sendiri-sendiri!{extra}\n"
        f"`{board}`\n{HANGMAN[0]}\n"
        f"Tebak pake `!tebak <huruf>` atau `!tebak <kata>`."
    )
    if "_" not in board.replace(" ", ""):
        active_kata.pop(gid, None)
        await ctx.send(f"🎉 Langsung kebuka semua! Katanya **{word}**. Hoki!")

@bot.command(name="tebak")
@is_allowed_guild()
async def tebak_guess(ctx, *, teks: str):
    gid = ctx.guild.id
    g = active_kata.get(gid)
    if not g:
        return
    t = teks.lower().strip()
    if not t.isalpha():
        await ctx.send("Huruf/kata aja, tanpa angka.")
        return
    uid = ctx.author.id
    if uid in g["dead"]:
        await ctx.send(f"{ctx.author.mention} udah gugur, tinggal nonton! 👀")
        return
    word = g["word"]
    lives = lambda u: g["max_wrong"] - g["wrong"].get(u, 0)
    foot = f"\n💡 {g['clue']} • {len(word)} huruf • Nyawamu: {lives(uid)}"
    if len(t) == 1:
        if t in g["guessed"]:
            await ctx.send(f"Huruf `{t}` udah ditebak.")
            return
        g["guessed"].add(t)
        if t in word:
            board = _kata_board(word, g["guessed"])
            if "_" not in board.replace(" ", ""):
                active_kata.pop(gid, None)
                await ctx.send(f"🎉 BENER! Katanya **{word}**. GG {ctx.author.mention}!")
            else:
                await ctx.send(f"✅ Ada `{t}`!\n`{board}`{foot}\n{HANGMAN[g['wrong'].get(uid, 0)]}")
        else:
            g["wrong"][uid] = g["wrong"].get(uid, 0) + 1
            if g["wrong"][uid] >= g["max_wrong"]:
                g["dead"].add(uid)
                # kalah total kalau semua yang pernah nebak udah gugur
                if set(g["wrong"]) <= g["dead"]:
                    active_kata.pop(gid, None)
                    await ctx.send(f"💀 {ctx.author.mention} gugur! Semua gugur, katanya **{word}**. {HANGMAN[-1]}")
                else:
                    board = _kata_board(word, g["guessed"])
                    await ctx.send(f"☠️ {ctx.author.mention} GUGUR! Temenmu lanjutin.\n`{board}`{foot}")
            else:
                board = _kata_board(word, g["guessed"])
                await ctx.send(f"❌ Nggak ada `{t}`. Sisa nyawamu: {lives(uid)}\n`{board}`{foot}\n{HANGMAN[g['wrong'][uid]]}")
    else:
        if t == word:
            active_kata.pop(gid, None)
            await ctx.send(f"🎉 BENER! Katanya **{word}**. GG {ctx.author.mention}!")
        else:
            g["wrong"][uid] = g["wrong"].get(uid, 0) + 1
            if g["wrong"][uid] >= g["max_wrong"]:
                g["dead"].add(uid)
                if set(g["wrong"]) <= g["dead"]:
                    active_kata.pop(gid, None)
                    await ctx.send(f"💀 {ctx.author.mention} gugur! Semua gugur, katanya **{word}**. {HANGMAN[-1]}")
                else:
                    board = _kata_board(word, g["guessed"])
                    await ctx.send(f"☠️ {ctx.author.mention} GUGUR! Temenmu lanjutin.\n`{board}`\n💡 {g['clue']} • {len(word)} huruf")
            else:
                board = _kata_board(word, g["guessed"])
                await ctx.send(f"❌ `{t}` salah. Sisa nyawamu: {lives(uid)}\n`{board}`\n💡 {g['clue']} • {len(word)} huruf\n{HANGMAN[g['wrong'][uid]]}")

@bot.command(name="nyerah")
@is_allowed_guild()
async def kata_giveup(ctx):
    g = active_kata.pop(ctx.guild.id, None)
    if g:
        await ctx.send(f"🏳️ Nyerah! Katanya **{g['word']}**.")
    else:
        await ctx.send("Nggak ada game jalan. Mulai `!tebakkata`.")

bot.run(TOKEN)
