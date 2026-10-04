import json
import time
import re
import cloudscraper

scraper = cloudscraper.create_scraper(
    browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
)

def get_livewire_download_link(page_url):
    try:
        # 1. Sayfayı çek
        res = scraper.get(page_url, timeout=12)
        
        # Cloudflare veya IP engeli kontrolü
        if res.status_code != 200:
            print(f" (HTTP {res.status_code} Engeli)", end="")
            return None

        html_text = res.text

        # 2. Sayfada doğrudan /download/ linki varsa al
        direct_links = re.findall(r'https?://ankergames\.net/download/[A-Za-z0-9_=-]+', html_text)
        if direct_links:
            return list(set(direct_links))

        # 3. generateDownloadUrl(ID) fonksiyonundaki Oyun ID'sini yakala
        game_id_match = re.search(r'generateDownloadUrl\(["\']?(\d+)["\']?\)', html_text)
        game_id = int(game_id_match.group(1)) if game_id_match else None

        # 4. Livewire snapshot ve CSRF Token verilerini ayıkla
        wire_match = re.search(r'wire:snapshot="([^"]+)"', html_text)
        csrf_match = re.search(r'name="csrf-token"\s+content="([^"]+)"', html_text) or re.search(r'csrf-token":\s*"([^"]+)"', html_text)

        if not wire_match:
            return None

        snapshot = wire_match.group(1).replace('&quot;', '"')
        csrf_token = csrf_match.group(1) if csrf_match else ""

        # Livewire istek parametreleri
        params = [game_id] if game_id is not None else []

        headers = {
            'Content-Type': 'application/json',
            'X-Livewire': 'true',
            'X-CSRF-TOKEN': csrf_token,
            'Referer': page_url,
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36'
        }

        payload = {
            "components": [
                {
                    "snapshot": snapshot,
                    "updates": {},
                    "calls": [
                        {
                            "path": "",
                            "method": "generateDownloadUrl",
                            "params": params
                        }
                    ]
                }
            ]
        }

        # 5. Livewire POST isteği gönder
        post_res = scraper.post("https://ankergames.net/livewire/update", json=payload, headers=headers, timeout=12)
        
        if post_res.status_code == 200:
            download_urls = re.findall(r'https?://ankergames\.net/download/[A-Za-z0-9_=-]+|/download/[A-Za-z0-9_=-]+', post_res.text)
            valid_urls = []
            for url in download_urls:
                if url.startswith("/"):
                    url = "https://ankergames.net" + url
                valid_urls.append(url)
            return list(set(valid_urls)) if valid_urls else None

    except Exception as e:
        pass
    return None

def update_download_links():
    try:
        with open("source.json", "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"source.json okunamadı: {e}")
        return

    downloads = data.get("downloads", [])
    total = len(downloads)
    print(f"Toplam {total} kayıt işleniyor...\n")

    updated_count = 0

    for index, item in enumerate(downloads, 1):
        uris = item.get("uris", [])
        if not uris:
            continue

        page_url = uris[0]

        if "/download/" in page_url:
            continue

        if "/game/" in page_url:
            print(f"[{index}/{total}] {item['title']}", end="")
            links = get_livewire_download_link(page_url)
            
            if links:
                item["uris"] = links
                updated_count += 1
                print(f" -> BAĞLANTI YAKALANDI: {links[0][:45]}...")
            else:
                print(f" -> Bağlantı bulunamadı.")

            time.sleep(0.15)

    with open("source.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\nİşlem completed! Toplam {updated_count} kayıt güncellendi.")

if __name__ == "__main__":
    update_download_links()