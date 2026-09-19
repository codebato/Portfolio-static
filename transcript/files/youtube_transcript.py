"""
YouTube Video Transkript Çekici
--------------------------------
Bir YouTube video linkinden (veya sadece video ID'sinden) altyazı/transkript
metnini çeker ve okunabilir bir Markdown (.md) dosyası olarak kaydeder.
Amaç: videoyu izlemek yerine, anlatılanları döküman gibi okuyabilmek.

Kullanım:
    python youtube_transcript.py "https://www.youtube.com/watch?v=VIDEO_ID"
    python youtube_transcript.py VIDEO_ID

Kurulum (bir kere yapman yeterli):
    pip install youtube-transcript-api requests
"""

import sys
import re
import requests
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import TextFormatter


def extract_video_id(url_or_id: str) -> str:
    """
    Kullanıcı tam bir YouTube linki de verebilir, sade video ID'sini de.
    Bu fonksiyon her iki durumu da tanıyıp sade video ID'yi (11 karakter) döndürür.
    Regex kullanmamızın sebebi: youtube.com/watch?v=, youtu.be/, /shorts/ gibi
    farklı link formatlarının hepsini tek seferde yakalayabilmek.
    """
    # Zaten 11 karakterlik saf bir ID gibi görünüyorsa (YouTube ID formatı budur), direkt kullan
    if re.fullmatch(r"[a-zA-Z0-9_-]{11}", url_or_id):
        return url_or_id

    # watch?v=..., youtu.be/..., /shorts/... gibi formatları yakalayan genel desen
    match = re.search(r"(?:v=|youtu\.be/|shorts/)([0-9A-Za-z_-]{11})", url_or_id)
    if match:
        return match.group(1)

    raise ValueError(f"Video ID bulunamadı, linki kontrol et: {url_or_id}")


def get_video_title(video_id: str) -> str:
    """
    YouTube'un herkese açık oEmbed servisinden video başlığını çeker.
    Bunun avantajı: API key gerektirmiyor, sadece video linkiyle çalışıyor.
    Başlık çekilemezse (video kaldırılmış, ağ hatası vs.) script durmasın diye
    video ID'sini yedek (fallback) başlık olarak kullanıyoruz.
    """
    oembed_url = (
        f"https://www.youtube.com/oembed?"
        f"url=https://www.youtube.com/watch?v={video_id}&format=json"
    )
    try:
        response = requests.get(oembed_url, timeout=10)
        response.raise_for_status()
        return response.json().get("title", video_id)
    except Exception:
        return video_id


def fetch_transcript_text(video_id: str, languages=("tr", "en")) -> str:
    """
    Video için transkript metnini çeker.
    languages listesi öncelik sırasını belirtir: önce Türkçe altyazı denenir,
    bulunamazsa İngilizce'ye düşer (fallback). Video hiç altyazıya sahip
    değilse (bazı videolarda olur), kütüphane kendi hata fırlatır, biz de
    bunu main() içinde yakalayıp kullanıcıya anlaşılır bir mesaj veririz.
    """
    api = YouTubeTranscriptApi()
    fetched = api.fetch(video_id, languages=list(languages))

    # TextFormatter, her satırdaki zaman damgasını (timestamp) atıp
    # sadece düz, okunabilir metni bırakır — bizim istediğimiz format bu
    formatter = TextFormatter()
    return formatter.format_transcript(fetched)


def save_as_markdown(title: str, video_id: str, transcript_text: str, output_dir: str = ".") -> str:
    """
    Transkripti başlık ve kaynak linkiyle birlikte bir .md dosyasına yazar.
    Dosya adını dosya sisteminde sorun çıkarmayacak karakterlere indirgiyoruz
    (Türkçe karakterler, boşluklar, özel karakterler dosya adında sorun çıkarabilir).
    """
    safe_filename = re.sub(r"[^\w\s-]", "", title, flags=re.UNICODE).strip()
    safe_filename = re.sub(r"[\s]+", "_", safe_filename)[:80] or video_id
    filepath = f"{output_dir}/{safe_filename}.md"

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n")
        f.write(f"Kaynak: https://www.youtube.com/watch?v={video_id}\n\n")
        f.write("---\n\n")
        f.write(transcript_text)

    return filepath


def main():
    if len(sys.argv) < 2:
        print("Kullanım: python youtube_transcript.py <video_url_veya_id>")
        sys.exit(1)

    raw_input_value = sys.argv[1]

    try:
        video_id = extract_video_id(raw_input_value)
        print(f"Video ID: {video_id}")

        title = get_video_title(video_id)
        print(f"Başlık: {title}")

        print("Transkript çekiliyor...")
        transcript_text = fetch_transcript_text(video_id)

        filepath = save_as_markdown(title, video_id, transcript_text)
        print(f"Kaydedildi: {filepath}")

    except Exception as error:
        # Olası hatalar: altyazı kapalı, video özel/kısıtlı, geçersiz link vs.
        # Kullanıcının ne yapması gerektiğini anlayacağı şekilde mesaj veriyoruz.
        print(f"Hata: {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
