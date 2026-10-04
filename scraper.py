import json
import time
import cloudscraper
from bs4 import BeautifulSoup

# Cloudflare engelini aşmak için istemci
scraper = cloudscraper.create_scraper(
    browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
)

def update_download_links():
    try:
        with open("source.json", "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"source.json dosyası okunamadı: {e}")
        return

    downloads = data.get("downloads", [])
    total = len(downloads)
    print(f"Toplam {total} oyunun detay sayfaları taranıyor...\n")

    updated_count = 0

    for index, item in enumerate(downloads, 1):
        uris = item.get("uris", [])
        if not uris:
            continue
            
        page_url = uris[0]

        # Eğer adres zaten indirme servisine aitse atla
        if any(domain in page_url.lower() for domain in ["qiwi", "pixeldrain", "gofile", "buzzheavier", "magnet:", "torrent", "mega.nz"]):
            continue

        try:
            res = scraper.get(page_url, timeout=12)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, "html.parser")
                found_links = []

                # Detay sayfasındaki indirme bağlantılarını ayıkla
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    href_lower = href.lower()

                    if any(servis in href_lower for servis in ["qiwi", "pixeldrain", "gofile", "buzzheavier", "torrent", "magnet:", "mega.nz", "1fichier", "drive.google"]):
                        found_links.append(href)

                if found_links:
                    item["uris"] = list(set(found_links))
                    updated_count += 1
                    print(f"[{index}/{total}] {item['title']} -> {len(found_links)} link eklendi.")
                else:
                    print(f"[{index}/{total}] {item['title']} -> Detay sayfasında ek link bulunamadı.")

        except Exception as e:
            print(f"[{index}/{total}] {item['title']} işlenirken hata: {e}")

        time.sleep(0.05)

    # Güncellenmiş veriyi kaydet
    with open("source.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\nİşlem tamamlandı! Toplam {updated_count} oyunun linkleri güncellendi.")

if __name__ == "__main__":
    update_download_links()