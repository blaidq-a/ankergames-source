import json
import time
import re
import cloudscraper

scraper = cloudscraper.create_scraper(
    browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
)

def get_livewire_download_link(page_url):
    try:
        # 1. Oyun sayfasını çek
        res = scraper.get(page_url, timeout=10)
        if res.status_code != 200:
            return None

        # Sayfada doğrudan /download/ linki hazır varsa al
        direct_links = re.findall(r'https?://ankergames\.net/download/[A-Za-z0-9_=-]+', res.text)
        if direct_links:
            return list(set(direct_links))

        # 2. Livewire snapshot ve CSRF Token verilerini ayıkla
        wire_match = re.search(r'wire:snapshot="([^"]+)"', res.text)
        csrf_match = re.search(r'name="csrf-token"\s+content="([^"]+)"', res.text) or re.search(r'csrf-token":\s*"([^"]+)"', res.text)

        if not wire_match:
            return None

        snapshot = wire_match.group(1).replace('&quot;', '"')
        csrf_token = csrf_match.group(1) if csrf_match else ""

        # Livewire güncelleme isteği için hazırlık
        headers = {
            'Content-Type': 'application/json',
            'X-Livewire': 'true',
            'X-CSRF-TOKEN': csrf_token,
            'Referer': page_url
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
                            "params": []
                        }
                    ]
                }
            ]
        }

        # 3. Livewire endpoint'ine POST isteği atarak gerçek /download/ token'ını al
        post_res = scraper.post("https://ankergames.net/livewire/update", json=payload, headers=headers, timeout=10)
        
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
            links = get_livewire_download_link(page_url)
            if links:
                item["uris"] = links
                updated_count += 1
                print(f"[{index}/{total}] {item['title']} -> Bağlantı yakalandı: {links[0][:40]}...")
            else:
                print(f"[{index}/{total}] {item['title']} -> İndirme bağlantısı bulunamadı.")

            time.sleep(0.1)

    with open("source.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\nİşlem completed! Toplam {updated_count} kayıt güncellendi.")

if __name__ == "__main__":
    update_download_links()