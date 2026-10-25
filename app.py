import os, re, uuid
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl
import yt_dlp

BASE = Path(__file__).resolve().parent
OUT = BASE / "downloads"
OUT.mkdir(exist_ok=True)
MAX_MB = int(os.getenv("MAX_AUDIO_MB", "80"))
MAX_SECONDS = int(os.getenv("MAX_DURATION_SECONDS", "900"))
# Add/remove hosts to match sources you are authorized to download.
ALLOWED_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be",
    "tiktok.com", "www.tiktok.com", "vm.tiktok.com",
    "facebook.com", "www.facebook.com", "m.facebook.com", "fb.watch",
    "snackvideo.com", "www.snackvideo.com", "sck.io"
}
app = FastAPI(title="AUDIOX ULTRA")
class ConvertRequest(BaseModel):
    url: HttpUrl

def validate_url(raw: str):
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(400, "Tautan harus menggunakan HTTP atau HTTPS.")
    # Exact host match prevents accepting lookalike domains.
    if host not in ALLOWED_HOSTS:
        raise HTTPException(400, "Domain ini belum diizinkan. Backend contoh hanya mendukung domain yang tercantum di README.")
    if parsed.username or parsed.password:
        raise HTTPException(400, "Tautan dengan kredensial tidak diizinkan.")

@app.post("/api/convert")
def convert(body: ConvertRequest):
    raw = str(body.url)
    validate_url(raw)
    job = uuid.uuid4().hex
    template = str(OUT / f"{job}.%(ext)s")
    opts = {
        "format": "bestaudio/best",
        "outtmpl": template,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 20,
        "retries": 1,
        "max_filesize": MAX_MB * 1024 * 1024,
        "match_filter": yt_dlp.utils.match_filter_func(f"duration > {MAX_SECONDS}"),
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(raw, download=True)
            if info.get("duration") and info["duration"] > MAX_SECONDS:
                raise HTTPException(413, f"Durasi maksimal {MAX_SECONDS // 60} menit.")
        output = OUT / f"{job}.mp3"
        if not output.exists():
            candidates = list(OUT.glob(f"{job}.*"))
            if not candidates:
                raise RuntimeError("File audio tidak ditemukan setelah konversi.")
            output = candidates[0]
        return {"filename": "audiox.mp3", "download_url": f"/api/download/{job}"}
    except HTTPException:
        raise
    except Exception as exc:
        # Avoid exposing server internals in public responses.
        raise HTTPException(422, "Tautan gagal diproses. Video mungkin tidak didukung, dibatasi, privat, terlalu panjang, atau unduhan diblokir platform.") from exc

@app.get("/api/download/{job}")
def download(job: str):
    if not re.fullmatch(r"[0-9a-f]{32}", job):
        raise HTTPException(400, "ID unduhan tidak valid.")
    matches = list(OUT.glob(f"{job}.mp3"))
    if not matches:
        matches = [p for p in OUT.glob(f"{job}.*") if p.is_file()]
    if not matches:
        raise HTTPException(404, "File unduhan sudah tidak tersedia.")
    return FileResponse(matches[0], media_type="audio/mpeg", filename="audiox.mp3")

# Mount frontend last so /api routes are matched first.
app.mount("/", StaticFiles(directory=str(BASE), html=True), name="static")
