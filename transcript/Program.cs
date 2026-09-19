// Program.cs
// ------------------------------------------------------------
// YouTube Kanal Takip + Transkript Arşivleme Aracı (C#)
// ------------------------------------------------------------
// Ne yapıyor:
//   1) Belirlediğin YouTube kanallarının RSS beslemesini periyodik kontrol eder
//   2) Daha önce işlenmemiş yeni bir video bulursa, yt-dlp'yi (dış process
//      olarak) çağırıp altyazısını indirir
//   3) Altyazıyı düz metne çevirip .md dosyası olarak KİŞİSEL arşivine kaydeder
//      (yayınlamıyoruz, sadece kendi okuman için — video izlemek yerine
//      transkripti okuyabilesin diye)
//   4) İşlenen video ID'lerini processed_videos.json'da tutar, aynı videoyu
//      tekrar işlemez
//
// NEDEN yt-dlp'yi C#'tan çağırıyoruz: YouTube'un altyazı indirme mekanizması
// sık değişiyor ve engellemelere karşı korunuyor. yt-dlp bu konuda sürekli
// güncellenen, topluluk tarafından bakımı yapılan bir araç — kendi C#
// implementasyonumuzu yazıp bakımını yapmaktansa, üzerine ince bir
// orkestrasyon katmanı kurmak çok daha az bakım gerektiriyor.
//
// ÖN KOŞUL: yt-dlp'nin bilgisayarında kurulu ve PATH'te olması gerekiyor.
//   pip install yt-dlp
//
// Çalıştırma: dotnet run
//
// NOT: Bu kodu .NET SDK kurulu olmayan bir ortamda yazdım, bu yüzden
// derleyip test edemedim — ilk çalıştırmada çıkan hataları birlikte
// çözeriz, syntax'ı standart .NET 8 kalıplarına göre yazdım.

using System.Diagnostics;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Xml.Linq;

// ------------------------------------------------------------
// AYARLAR — kendi kanal listeni buraya yaz. Kanal ID'sini bulmak için:
// kanalın YouTube sayfasına git → sağ tık "Sayfa kaynağını görüntüle" →
// Ctrl+F ile "channelId" ara, orada UC... ile başlayan ID'yi bulursun.
// ------------------------------------------------------------
var channelIds = new[]
{
    "UCawxqixnNSb1gB11p55bJbQ", // Matthew Berman
    "UCNJ1Ymd5yFuUPtnz1xtRbbw", // AI Explained
    // ... buraya kalan 8 kanalı ekle
};

var archiveFolder = "arsiv";
var stateFilePath = "processed_videos.json";
var checkIntervalMinutes = 30; // kaç dakikada bir yeni video kontrolü yapılsın

Directory.CreateDirectory(archiveFolder);

// ------------------------------------------------------------
// DURUM YÖNETİMİ: hangi videoları daha önce işledik?
// HashSet<string> kullanıyoruz çünkü video ID'si benzersiz ve
// Contains() kontrolü O(1) hızında çalışıyor.
// ------------------------------------------------------------
var processedVideoIds = LoadProcessedVideoIds(stateFilePath);
var httpClient = new HttpClient();

Console.WriteLine($"Takip başlıyor. {channelIds.Length} kanal, her {checkIntervalMinutes} dakikada bir kontrol edilecek.");
Console.WriteLine("Durdurmak için Ctrl+C.\n");

// ------------------------------------------------------------
// ANA DÖNGÜ: periyodik olarak tüm kanalları kontrol et.
// Not: gerçek bir üretim sisteminde (örn. NvnStok gibi) bu sonsuz döngü
// yerine Hangfire'ın recurring job mekanizmasını kullanırdık — ama tek
// başına çalışan basit bir araç için bu yeterli.
// ------------------------------------------------------------
while (true)
{
    foreach (var channelId in channelIds)
    {
        try
        {
            await ProcessChannelAsync(channelId);
        }
        catch (Exception ex)
        {
            // Bir kanaldaki hata tüm döngüyü durdurmasın, sıradaki kanala geç
            Console.WriteLine($"[{channelId}] Kanal işlenirken hata: {ex.Message}");
        }
    }

    Console.WriteLine($"\nTur tamamlandı. {checkIntervalMinutes} dakika bekleniyor...\n");
    await Task.Delay(TimeSpan.FromMinutes(checkIntervalMinutes));
}

// ==============================================================
// FONKSİYONLAR
// ==============================================================

async Task ProcessChannelAsync(string channelId)
{
    var videos = await FetchChannelVideosAsync(channelId);
    Console.WriteLine($"[{channelId}] {videos.Count} video bulundu (RSS son 15 videoyu gösterir).");

    foreach (var video in videos)
    {
        if (processedVideoIds.Contains(video.VideoId))
            continue; // zaten işlenmiş, atla

        Console.WriteLine($"  Yeni video: {video.Title}");

        try
        {
            var vttPath = DownloadSubtitle(video.VideoId, archiveFolder);
            var transcriptText = ParseVttToText(vttPath);
            SaveAsMarkdown(video, transcriptText, archiveFolder);
            File.Delete(vttPath);

            Console.WriteLine("    Kaydedildi.");
        }
        catch (Exception ex)
        {
            // Altyazısı olmayan video ya da geçici bir ağ hatası olabilir.
            // Bu videoyu "işlendi" olarak İŞARETLEMİYORUZ ki bir dahaki
            // turda tekrar denensin (belki geçiciydi).
            Console.WriteLine($"    Hata (tekrar denenecek): {ex.Message}");
            continue;
        }

        // İşlendi olarak kaydet ve HER VİDEODAN SONRA dosyaya yaz — sebebi:
        // program ortasında kapanırsa (elektrik kesintisi vs.) o ana kadar
        // işlenenleri kaybetmeyelim.
        processedVideoIds.Add(video.VideoId);
        SaveProcessedVideoIds(stateFilePath, processedVideoIds);

        // YouTube'u art arda çok fazla istekle yormamak için videolar
        // arasında kısa, rastgele bir bekleme koyuyoruz.
        await Task.Delay(TimeSpan.FromSeconds(Random.Shared.Next(3, 7)));
    }
}

async Task<List<VideoInfo>> FetchChannelVideosAsync(string channelId)
{
    // YouTube her kanal için herkese açık bir RSS beslemesi sunuyor —
    // API key gerekmiyor, bu link her zaman çalışır.
    var rssUrl = $"https://www.youtube.com/feeds/videos.xml?channel_id={channelId}";
    var xml = await httpClient.GetStringAsync(rssUrl);

    var doc = XDocument.Parse(xml);

    // YouTube'un RSS'i standart Atom formatında ama kendi özel alanlarını
    // (yt:videoId gibi) da ekliyor — bu yüzden namespace'leri tanımlamamız gerekiyor
    XNamespace atom = "http://www.w3.org/2005/Atom";
    XNamespace yt = "http://www.youtube.com/xml/schemas/2015";

    var videos = new List<VideoInfo>();
    foreach (var entry in doc.Descendants(atom + "entry"))
    {
        var videoId = entry.Element(yt + "videoId")?.Value;
        var title = entry.Element(atom + "title")?.Value;

        if (videoId is null || title is null)
            continue;

        videos.Add(new VideoInfo(videoId, title));
    }

    return videos;
}

string DownloadSubtitle(string videoId, string workDir)
{
    // yt-dlp'yi dış bir process olarak çağırıyoruz — video indirmiyoruz
    // (--skip-download), sadece altyazı dosyasını indiriyoruz.
    var outputTemplate = Path.Combine(workDir, $"_tmp_{videoId}.%(ext)s");
    var arguments = "--skip-download --write-subs --write-auto-subs " +
                     "--sub-langs \"tr,en\" --sub-format vtt " +
                     $"-o \"{outputTemplate}\" " +
                     $"\"https://www.youtube.com/watch?v={videoId}\"";

    var processInfo = new ProcessStartInfo
    {
        FileName = "yt-dlp",
        Arguments = arguments,
        RedirectStandardOutput = true,
        RedirectStandardError = true,
        UseShellExecute = false,
        CreateNoWindow = true,
    };

    using var process = Process.Start(processInfo)
        ?? throw new InvalidOperationException("yt-dlp process başlatılamadı — PATH'te olduğundan emin ol.");
    process.WaitForExit();

    if (process.ExitCode != 0)
    {
        var stderr = process.StandardError.ReadToEnd();
        throw new InvalidOperationException($"yt-dlp hata verdi: {stderr}");
    }

    var vttFile = Directory.GetFiles(workDir, $"_tmp_{videoId}*.vtt").FirstOrDefault();
    if (vttFile is null)
        throw new FileNotFoundException("Bu video için altyazı bulunamadı.");

    return vttFile;
}

string ParseVttToText(string vttPath)
{
    // .vtt dosyasını satır satır okuyup zaman damgalarını ve tekrar eden
    // (rolling caption) satırları temizliyoruz — Python versiyonundaki
    // aynı mantığın C#'a çevrilmiş hali.
    var lines = File.ReadAllLines(vttPath);
    var resultLines = new List<string>();
    string? lastLine = null;

    foreach (var rawLine in lines)
    {
        var line = rawLine.Trim();

        if (line.Contains("-->") || line.StartsWith("WEBVTT") ||
            line.StartsWith("Kind:") || line.StartsWith("Language:") ||
            string.IsNullOrWhiteSpace(line))
        {
            continue;
        }

        // Satır içi zaman etiketlerini (<00:00:01.200><c>...) temizle
        var cleanLine = Regex.Replace(line, "<[^>]+>", "").Trim();

        if (cleanLine.Length == 0)
            continue;

        if (cleanLine != lastLine)
        {
            resultLines.Add(cleanLine);
            lastLine = cleanLine;
        }
    }

    return string.Join(" ", resultLines);
}

void SaveAsMarkdown(VideoInfo video, string transcriptText, string outputDir)
{
    var safeTitle = Regex.Replace(video.Title, @"[^\w\s-]", "");
    safeTitle = Regex.Replace(safeTitle, @"\s+", "_");
    if (safeTitle.Length > 80) safeTitle = safeTitle[..80];
    if (string.IsNullOrWhiteSpace(safeTitle)) safeTitle = video.VideoId;

    var filePath = Path.Combine(outputDir, $"{safeTitle}.md");

    var content = $"# {video.Title}\n\n" +
                   $"Kaynak: https://www.youtube.com/watch?v={video.VideoId}\n\n" +
                   $"---\n\n{transcriptText}";

    File.WriteAllText(filePath, content);
}

HashSet<string> LoadProcessedVideoIds(string path)
{
    if (!File.Exists(path))
        return new HashSet<string>();

    var json = File.ReadAllText(path);
    return JsonSerializer.Deserialize<HashSet<string>>(json) ?? new HashSet<string>();
}

void SaveProcessedVideoIds(string path, HashSet<string> ids)
{
    var json = JsonSerializer.Serialize(ids, new JsonSerializerOptions { WriteIndented = true });
    File.WriteAllText(path, json);
}

// Video bilgisini taşıyan basit bir record — class yerine record kullanmamızın
// sebebi: bu sadece veri taşıyan, değişmeyen (immutable) bir yapı, record tam
// bunun için var.
record VideoInfo(string VideoId, string Title);
