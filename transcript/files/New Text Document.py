"""
YouTube Playlist Transkript Çekici (Toplu Versiyon)
------------------------------------------------------
Bir YouTube playlist (kurs) linkindeki TÜM videoların transkriptini sırayla
çeker, her birini ayrı bir Markdown (.md) dosyası olarak kaydeder.

Pratik özellikler:
- Kaldığı yerden devam eder: bir video için dosya zaten varsa, o videoyu
  atlar. Yani 500 videonun 200'ünde script çökerse (internet kopması vs.),
  tekrar çalıştırdığında baştan başlamaz, 201'den devam eder.
- İstekler arasına bekleme koyar: YouTube'u art arda 500 kere yormamak için
  her video arasında birkaç saniye bekliyoruz — aksi halde IP engellenme
  riski (bir önceki versiyonda yaşadığımız sorun) çok daha yüksek olur.
- Hata alan bir video tüm işlemi durdurmaz: o videoyu "başarısız" listesine
  yazar, bir sonrakine geçer.

Kullanım:
    python youtube_playlist_transcript.py "PLAYLIST_URL"
    python youtube_playlist_transcript.py "PLAYLIST_URL" cikti_klasoru
    python youtube_playlist_transcript.py "PLAYLIST_URL" cikti_klasoru 5

Üçüncü parametre (opsiyonel): sadece ilk N videoyu çek. 500 videoluk bir
kursta önce 5 videoyla deneyip her şeyin doğru çalıştığını görmek için kullan.

Kurulum:
    pip install yt-dlp requests
"""

import sys
import re
import os
import glob
import time
import random
import yt_dlp


def sanitize_filename(name: str, fallback: str) -> str:
    """
    Video/playlist başlığını dosya/klasör adı olarak güvenli hale getirir.
    Türkçe karakterler, boşluklar ve özel karakterler dosya sisteminde
    sorun çıkarabildiği için temizliyoruz.
    """
    safe = re.sub(r"[^\w\s-]", "", name, flags=re.UNICODE).strip()
    safe = re.sub(r"[\s]+", "_", safe)[:80]
    return safe or fallback


def get_playlist_entries(playlist_url: str) -> list:
    """
    Playlist içindeki tüm videoların ID ve başlıklarını tek seferde çeker.
    extract_flat=True kullanmamızın sebebi: her videonun TÜM detayını
    (süre, açıklama vs.) çekmek çok yavaş olur — biz sadece ID ve başlık
    istiyoruz, bu yüzden "hafif" bir tarama yapıyoruz.
    """
    ydl_opts = {
        "extract_flat": True,
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(playlist_url, download=False)

    entries = info.get("entries") or []
    playlist_title = info.get("title") or "playlist"
    return playlist_title, entries


def download_subtitle_file(video_id: str, work_dir: str, languages=("tr", "en")) -> str:
    """
    Tek bir video için altyazı .vtt dosyasını indirir (video değil, sadece altyazı).
    """
    ydl_opts = {
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": list(languages),
        "subtitlesformat": "vtt",
        "outtmpl": os.path.join(work_dir, f"_tmp_{video_id}.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
    }
    url = f"https://www.youtube.com/watch?v={video_id}"
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    for lang in languages:
        candidates = glob.glob(os.path.join(work_dir, f"_tmp_{video_id}.{lang}.vtt"))
        if candidates:
            return candidates[0]

    fallback = glob.glob(os.path.join(work_dir, f"_tmp_{video_id}*.vtt"))
    if fallback:
        return fallback[0]

    raise RuntimeError("Bu videoda hiç altyazı bulunamadı.")


def parse_vtt_to_text(vtt_path: str) -> str:
    """
    .vtt altyazısını düz metne çevirir, rolling-caption tekrarlarını temizler
    (bkz. tekil video script'indeki aynı fonksiyonun açıklaması).
    """
    with open(vtt_path, "r", encoding="utf-8") as f:
        content = f.read()

    blocks = re.split(r"\n\s*\n", content.strip())
    lines_in_order = []
    seen_last = None

    for block in blocks:
        for line in block.strip().splitlines():
            if "-->" in line or line.startswith(("WEBVTT", "Kind:", "Language:")):
                continue
            clean_line = re.sub(r"<[^>]+>", "", line).strip()
            if not clean_line:
                continue
            if clean_line != seen_last:
                lines_in_order.append(clean_line)
                seen_last = clean_line

    return " ".join(lines_in_order)


def main():
    if len(sys.argv) < 2:
        print("Kullanım: python youtube_playlist_transcript.py <playlist_url> [cikti_klasoru] [limit]")
        sys.exit(1)

    playlist_url = sys.argv[1]
    output_dir_arg = sys.argv[2] if len(sys.argv) > 2 else None
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else None

    print("Playlist taranıyor (video listesi çekiliyor)...")
    playlist_title, entries = get_playlist_entries(playlist_url)

    if limit:
        entries = entries[:limit]

    output_dir = output_dir_arg or sanitize_filename(playlist_title, "kurs_transkriptleri")
    os.makedirs(output_dir, exist_ok=True)

    total = len(entries)
    print(f"Playlist: {playlist_title}")
    print(f"Toplam video: {total}")
    print(f"Çıktı klasörü: {output_dir}\n")

    failed = []

    for index, entry in enumerate(entries, start=1):
        video_id = entry.get("id")
        title = entry.get("title") or video_id

        # Sıra numarasıyla dosya adı oluşturuyoruz ki klasörde kurs sırasına
        # göre dizilsinler (001_, 002_, ... 500_ gibi — bu yüzden 3 haneli
        # sıfır dolgulu numara kullanıyoruz)
        safe_title = sanitize_filename(title, video_id)
        target_path = os.path.join(output_dir, f"{index:03d}_{safe_title}.md")

        # KALDIĞI YERDEN DEVAM: dosya zaten varsa bu videoyu atla
        if os.path.exists(target_path):
            print(f"[{index}/{total}] Zaten var, atlanıyor: {title}")
            continue

        print(f"[{index}/{total}] Çekiliyor: {title}")

        try:
            vtt_path = download_subtitle_file(video_id, work_dir=output_dir)
            transcript_text = parse_vtt_to_text(vtt_path)
            os.remove(vtt_path)

            with open(target_path, "w", encoding="utf-8") as f:
                f.write(f"# {title}\n\n")
                f.write(f"Kaynak: https://www.youtube.com/watch?v={video_id}\n\n")
                f.write("---\n\n")
                f.write(transcript_text)

        except Exception as error:
            print(f"  Hata: {error}")
            failed.append((video_id, title, str(error)))

        # YouTube'u art arda çok fazla istekle yormamak için her videodan
        # sonra rastgele 1.5-3.5 saniye bekliyoruz. Sabit bir süre yerine
        # rastgele aralık kullanmamızın sebebi: sabit aralıklar bot
        # davranışına benzer, rastgele olan daha "insan gibi" görünür.
        time.sleep(random.uniform(1.5, 3.5))

    print(f"\nBitti. {total - len(failed)}/{total} video başarıyla çekildi.")

    if failed:
        log_path = os.path.join(output_dir, "_basarisiz_videolar.txt")
        with open(log_path, "w", encoding="utf-8") as f:
            for video_id, title, error in failed:
                f.write(f"{title} — https://www.youtube.com/watch?v={video_id}\n  Hata: {error}\n\n")
        print(f"{len(failed)} video başarısız oldu, detaylar: {log_path}")


if __name__ == "__main__":
    main()