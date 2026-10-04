import json
import re
import time
from urllib.parse import urljoin, urlparse

import cloudscraper
from bs4 import BeautifulSoup

SOURCE_FILE = "source.json"
DOWNLOAD_KEYWORDS = (
    "/download/",
    "qiwi",
    "pixeldrain",
    "gofile",
    "buzzheavier",
    "torrent",
    "magnet:",
    ".zip",
    ".rar",
    ".7z",
    ".exe",
    ".iso",
    ".apk",
)

def normalize_url(raw_url, base_url=""):
    if not raw_url or not isinstance(raw_url, str):
        return None
    value = raw_url.strip()
    if not value or value.lower() in {"javascript:void(0)", "#"}:
        return None
    
    if value.startswith("//"):
        value = "https:" + value
    elif value.startswith("/") and base_url:
        value = urljoin(base_url, value)

    try:
        parsed = urlparse(value)
        # Sadece http/https veya magnet linkleri
        if parsed.scheme not in {"http", "https", "magnet"}:
            return None
        return value
    except Exception:
        return None

def looks_like_download_url(url):
    text = url.lower()
    return any(keyword in text for keyword in DOWNLOAD_KEYWORDS)

def extract_download_links(html_text, source_url=""):
    soup = BeautifulSoup(html_text, "html.parser")
    found = set()

    for tag in soup.find_all(["a", "link", "iframe"], href=True):
        href = tag.get("href")
        cleaned = normalize_url(href, source_url)
        if cleaned and looks_like_download_url(cleaned):
            found.add(cleaned)

    for tag in soup.find_all(["iframe", "script"], src=True):
        src = tag.get("src")
        cleaned = normalize_url(src, source_url)
        if cleaned and looks_like_download_url(cleaned):
            found.add(cleaned)

    # Regex fallback
    for match in re.findall(r"(https?://[^\s\"'<>]+|magnet:\?xt=urn:[a-z0-9]+:[^\s\"'<>]+)", html_text):
        cleaned = normalize_url(match.rstrip(").,;"), source_url)
        if cleaned and looks_like_download_url(cleaned):
            found.add(cleaned)

    return sorted(found)

def main():
    try:
        with open(SOURCE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"{SOURCE_FILE} bulunamadı, boş bir veri ile başlanıyor.")
        data = {"name": "Game Source", "downloads": []}
    except Exception as e:
        print(f"Hata oluştu: {e}")
        return

    scraper = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "windows", "desktop": True})
    downloads = data.get("downloads", [])
    
    print(f"Toplam {len(downloads)} kayıt kontrol edilecek...")
    
    updated_count = 0
    for idx, item in enumerate(downloads, 1):
        uris = item.get("uris", [])
        if not uris:
            continue
            
        all_found_links = set()
        
        for uri in uris:
            normalized_uri = normalize_url(uri)
            if not normalized_uri or not normalized_uri.startswith("http"):
                # Eger zaten bir dosya linki ya da magnet ise doğrudan ekleyelim
                if looks_like_download_url(uri):
                    all_found_links.add(uri)
                continue
            
            try:
                response = scraper.get(normalized_uri, timeout=15)
                response.raise_for_status()
                extracted = extract_download_links(response.text, normalized_uri)
                all_found_links.update(extracted)
            except Exception as e:
                print(f"[{idx}/{len(downloads)}] '{item.get('title', 'Unknown')}' kaynağı okunamadı: {normalized_uri} - Hata: {e}")
                
            time.sleep(1) # Rate limit korumasi
            
        if all_found_links:
            item["uris"] = sorted(all_found_links)
            updated_count += 1
            print(f"[{idx}/{len(downloads)}] '{item.get('title', 'Unknown')}' güncellendi. ({len(all_found_links)} link bulundu)")

    with open(SOURCE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        
    print(f"\nİşlem bitti. Toplam {updated_count} kayıt güncellendi.")

if __name__ == "__main__":
    main()
