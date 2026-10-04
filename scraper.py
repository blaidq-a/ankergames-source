import json
import time
import cloudscraper
from bs4 import BeautifulSoup

scraper = cloudscraper.create_scraper(
    browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
)

def update_download_links():
    try:
        with open("source.json", "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"source.json okunamadı: {e}")
        return

    downloads = data.get("downloads", [])
    total = len(downloads)
    print(f"Toplam {total} oyun taranıyor...\n")

    updated_count = 0

    for index, item in enumerate(downloads, 1):
        uris = item.get("uris", [])
        if not uris:
            continue
            
        page_url = uris[0]

        # Sadece oyun detay sayfalarını (/game/) tara
        if "/game/" in page_url:
            try:
                res = scraper.get(page_url, timeout=12)
                if res.status_code == 200:
                    soup = BeautifulSoup(res.text, "html.parser")
                    download_links = []

                    for a in soup.find_all("a", href=True):
                        href = a["href"]
                        if "/download/" in href or any(servis in href.lower() for servis in ["qiwi", "pixeldrain", "gofile", "buzzheavier", "torrent", "magnet:"]):
                            if href.startswith("/"):
                                href = "https://ankergames.net" + href
                            download_links.append(href)

                    if download_links:
                        item["uris"] = list(set(download_links))
                        updated_count += 1
                        print(f"[{index}/{total}] {item['title']} -> Bağlantı eklendi.")
            except Exception as e:
                print(f"[{index}/{total}] {item['title']} hata: {e}")

            time.sleep(0.05)

    with open("source.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\nİşlem tamamlandı! Toplam {updated_count} oyun güncellendi.")

if __name__ == "__main__":
    update_download_links()