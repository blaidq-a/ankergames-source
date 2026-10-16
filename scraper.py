import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from xml.etree import ElementTree as ET
import requests
from playwright.async_api import async_playwright

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)

CDP_URL = "http://localhost:9222"
IS_GITHUB_ACTIONS = os.getenv("GITHUB_ACTIONS", "false").lower() == "true"
FORCE_REFRESH = os.getenv("FORCE_REFRESH", "false").lower() == "true"


def load_existing_source():
    """Var olan source.json dosyasını okuyarak URL hafızasına alır."""
    if FORCE_REFRESH:
        return {}

    if os.path.exists("source.json"):
        try:
            with open("source.json", "r", encoding="utf-8") as f:
                data = json.load(f)
                downloads = data.get("downloads", [])
                
                url_dict = {}
                for item in downloads:
                    match = re.search(r'href=["\'](https?://[^"\']+)["\']', item.get("descriptionHtml", ""))
                    if match:
                        game_url = match.group(1).rstrip('/')
                        url_dict[game_url] = item
                return url_dict
        except Exception:
            pass
    return {}


async def cancel_download_handler(download):
    """Otomatik başlayan dosya indirmelerini iptal eder."""
    try:
        await download.cancel()
        print("   -> [X] Otomatik dosya indirmesi engellendi.")
    except Exception:
        pass


async def check_and_handle_rate_limit(page):
    """Cloudflare Error 1015 kontrolü ve F5 yenilemesi."""
    for attempt in range(3):
        try:
            title = await page.title()
            h1_el = await page.query_selector("h1")
            h1_text = await h1_el.inner_text() if h1_el else ""

            if "Error 1015" in title or "You are being rate limited" in h1_text:
                print("   -> [!] Cloudflare Rate Limit (Error 1015) algılandı! 5 saniye beklenip F5 atılıyor...")
                await page.wait_for_timeout(5000)
                await page.reload(wait_until="domcontentloaded")
                await page.wait_for_timeout(2000)
            else:
                break
        except Exception:
            break


async def handle_site_download_rate_limit(page):
    """Sitenin 'Rate Limited' pop-up'ını algılar, 66s bekler ve F5 atar."""
    try:
        modal_limit = page.locator("div:has-text('Rate Limited'), div:has-text('Too many download requests')").first
        if await modal_limit.count() > 0 and await modal_limit.is_visible():
            print("   -> [!] Site İndirme Limiti (Rate Limited) algılandı! 66 saniyelik sayaç bekleniyor...")
            await page.wait_for_timeout(66000)
            print("   -> [!] Sayaç bitti, F5 (reload) atılıyor ve işlem tekrarlanıyor...")
            await page.reload(wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            return True
    except Exception:
        pass
    return False


async def get_all_ankergames_links(page):
    """Anker Games sitemap'lerini Playwright tarayıcısı ile tara."""
    print("Anker Games TÜM oyun listesi çekiliyor...")
    game_links = set()

    sitemap_candidates = [
        "https://ankergames.net/sitemap_index.xml",
        "https://ankergames.net/sitemap.xml",
        "https://ankergames.net/post-sitemap.xml",
        "https://ankergames.net/post-sitemap1.xml",
        "https://ankergames.net/post-sitemap2.xml",
        "https://ankergames.net/game-sitemap.xml"
    ]

    sub_sitemaps = set(sitemap_candidates)

    for s_url in sitemap_candidates:
        try:
            await page.goto(s_url, wait_until="domcontentloaded", timeout=15000)
            content = await page.content()
            found_sitemaps = re.findall(r'https?://ankergames\.net/[^"\'>\s]+\.xml', content)
            sub_sitemaps.update(found_sitemaps)
        except Exception:
            pass

    for s_url in list(sub_sitemaps):
        try:
            await page.goto(s_url, wait_until="domcontentloaded", timeout=15000)
            content = await page.content()
            found_games = re.findall(r'https?://ankergames\.net/game/[a-zA-Z0-9\-_]+', content)
            for g_url in found_games:
                game_links.add(g_url.rstrip('/'))
        except Exception:
            pass

    if len(game_links) < 50:
        try:
            await page.goto("https://ankergames.net/games-list", wait_until="domcontentloaded", timeout=30000)
            await check_and_handle_rate_limit(page)
            await page.wait_for_timeout(2000)

            for _ in range(25):
                await page.mouse.wheel(0, 5000)
                await page.wait_for_timeout(500)

            extracted = await page.evaluate("""
                () => Array.from(document.querySelectorAll("a[href*='/game/']"))
                    .map(a => a.href)
                    .filter(href => href.includes("ankergames.net/game/"))
            """)
            for g in extracted:
                game_links.add(g.rstrip('/'))
        except Exception:
            pass

    return sorted(list(game_links))


async def scrape_game_details(page, game_url, existing_dict):
    """Sürüm bilgili, reklam temizlemeli ve limit beklemeli akış."""
    clean_url = game_url.rstrip('/')
    direct_link = None

    def handle_response(response):
        nonlocal direct_link
        r_url = response.url
        if ("dlproxy" in r_url or "sig=" in r_url) and "/download/" in r_url:
            direct_link = r_url

    page.on("response", handle_response)

    try:
        await page.goto(game_url, wait_until="domcontentloaded", timeout=30000)
        await check_and_handle_rate_limit(page)

        # 1. Başlık Tespiti
        title_el = await page.query_selector("h1")
        raw_title = (await title_el.inner_text()).strip() if title_el else ""
        if not raw_title:
            return existing_dict.get(clean_url)

        clean_title = re.sub(r'\s*Free\s*Download.*$', '', raw_title, flags=re.IGNORECASE).strip()

        # 2. Oyun Sürüm (Version) Tespiti
        game_version = await page.evaluate("""
            () => {
                const elements = Array.from(document.querySelectorAll("span, div, a, p, button"));
                for (const el of elements) {
                    const txt = (el.innerText || "").trim();
                    if (/^(v|b)\s*\d+[\d\.]*/i.test(txt) && txt.length < 25) {
                        return txt;
                    }
                }
                return "";
            }
        """)

        if game_version:
            clean_title = f"{clean_title} ({game_version})"

        # 3. Dosya Boyutu Tespiti
        file_size = await page.evaluate("""
            () => {
                const txt = document.body.innerText || '';
                const match = txt.match(/([0-9.,]+\\s*(?:GB|MB))/i);
                return match ? match[1].toUpperCase() : "N/A";
            }
        """)

        target_page = page

        # Limit durumlarına karşı 3 deneme döngüsü
        for attempt in range(3):
            main_dl = page.locator("button:has-text('Download'), a:has-text('Download')").first
            if await main_dl.count() > 0:
                await main_dl.click(no_wait_after=True, force=True)

            await page.wait_for_timeout(2000)

            if "google.com" in page.url or "ankergames.net" not in page.url:
                await page.goto(game_url, wait_until="domcontentloaded", timeout=20000)

            try:
                async with page.expect_popup(timeout=3500) as popup_info:
                    await page.evaluate("""
                        () => {
                            const listItems = Array.from(document.querySelectorAll("li, div.flex"));
                            for (const item of listItems) {
                                const txt = (item.innerText || "").trim();
                                if ((txt.startsWith("Direct") || txt.startsWith("DataNodes")) && !txt.includes("Online Fix") && !txt.includes("Torrent")) {
                                    const btn = item.querySelector("a.download-button, button.download-button, a, button");
                                    if (btn) {
                                        btn.click();
                                        return true;
                                    }
                                }
                            }
                            const firstBtn = document.querySelector("ul > li:first-child a.download-button, a.download-button");
                            if (firstBtn) {
                                firstBtn.click();
                                return true;
                            }
                            return false;
                        }
                    """)
                popup = await popup_info.value
                await popup.wait_for_load_state("domcontentloaded")
                if "google.com" in popup.url or ("ankergames.net" not in popup.url and "dlproxy" not in popup.url):
                    await popup.close()
                else:
                    target_page = popup
                    target_page.on("response", handle_response)
            except Exception:
                target_page = page

            await page.wait_for_timeout(1500)

            hit_limit = await handle_site_download_rate_limit(page)
            if not hit_limit:
                break

        if target_page.is_closed():
            return None

        await check_and_handle_rate_limit(target_page)

        await target_page.add_init_script("""
            window.__captured_link = null;
            if (navigator.clipboard) {
                const orig = navigator.clipboard.writeText;
                navigator.clipboard.writeText = async (text) => {
                    window.__captured_link = text;
                    return true;
                };
            }
        """)

        try:
            await target_page.wait_for_selector(
                "button:has-text('Copy Link'), a:has-text('Download Now')", 
                timeout=35000
            )
        except Exception:
            pass

        if not target_page.is_closed():
            try:
                copy_btn = target_page.locator("button:has-text('Copy Link')").first
                if await copy_btn.count() > 0:
                    await copy_btn.click(no_wait_after=True, force=True)
                    await target_page.wait_for_timeout(1000)

                    captured_clip = await target_page.evaluate("window.__captured_link")
                    if captured_clip and ("dlproxy" in captured_clip or "sig=" in captured_clip or "http" in captured_clip):
                        direct_link = captured_clip
            except Exception:
                pass

        if not direct_link and not target_page.is_closed():
            try:
                dl_now_btn = target_page.locator("a:has-text('Download Now')").first
                if await dl_now_btn.count() > 0:
                    href = await dl_now_btn.get_attribute("href")
                    if href and ("dlproxy" in href or "sig=" in href or "http" in href):
                        direct_link = href
            except Exception:
                pass

        if target_page != page and not target_page.is_closed():
            await target_page.close()

        if not direct_link:
            return existing_dict.get(clean_url)

        return {
            "title": clean_title,
            "uris": [direct_link],
            "uploadDate": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "fileSize": file_size,
            "descriptionHtml": f'<a href="{game_url}">Website with instructions for launching the game</a>'
        }

    except Exception as err:
        print(f"   -> Hata ({game_url}): {err}")
        return existing_dict.get(clean_url)
    finally:
        try:
            page.remove_listener("response", handle_response)
        except Exception:
            pass


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--part", type=int, default=1, help="Parça numarası")
    parser.add_argument("--total-parts", type=int, default=1, help="Toplam parça sayısı")
    args = parser.parse_args()

    existing_dict = load_existing_source()

    async with async_playwright() as p:
        browser = None
        context = None

        if IS_GITHUB_ACTIONS:
            browser = await p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-setuid-sandbox"]
            )
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                permissions=['clipboard-read', 'clipboard-write']
            )
        else:
            try:
                browser = await p.chromium.connect_over_cdp(CDP_URL)
                context = browser.contexts[0]
            except Exception:
                browser = await p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
                context = await browser.new_context(permissions=['clipboard-read', 'clipboard-write'])

        init_page = context.pages[0] if context.pages else await context.new_page()
        all_urls = await get_all_ankergames_links(init_page)

        if not all_urls:
            print("Taranacak oyun bulunamadı.")
            return

        total_games = len(all_urls)
        chunk_size = (total_games + args.total_parts - 1) // args.total_parts
        start_idx = (args.part - 1) * chunk_size
        end_idx = min(start_idx + chunk_size, total_games)

        target_urls = all_urls[start_idx:end_idx]
        print(f"\n[Part {args.part}/{args.total_parts}] TARAMA BAŞLADI ({len(target_urls)} Oyun: Index {start_idx} - {end_idx})\n")

        downloads = []
        page = await context.new_page()
        page.on("download", lambda d: asyncio.create_task(cancel_download_handler(d)))

        for idx, url in enumerate(target_urls, start_idx + 1):
            game_data = await scrape_game_details(page, url, existing_dict)
            if game_data:
                downloads.append(game_data)
                print(f"[Part {args.part}] [{idx}/{total_games}] BAŞARILI: {game_data['title']} | Boyut: {game_data['fileSize']}")
            else:
                print(f"[Part {args.part}] [{idx}/{total_games}] LİNK BULUNAMADI: {url}")

            await asyncio.sleep(2.5)

        await page.close()

    output_filename = f"source_part_{args.part}.json" if args.total_parts > 1 else "source.json"
    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump({"name": "AnkerGames Source", "downloads": downloads}, f, ensure_ascii=False, indent=2)

    print(f"\n[Part {args.part}] Tamamlandı! '{output_filename}' dosyasına yazıldı.")


def run_scraper():
    asyncio.run(main())


if __name__ == "__main__":
    run_scraper()