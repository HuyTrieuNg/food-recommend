#!/usr/bin/env python3
"""
Crawler review quán ăn Đà Nẵng trên foody.vn (Playwright).

Cách hoạt động
--------------
Foody tải dữ liệu qua các endpoint JSON nội bộ (/__get/...), nên không cần
parse HTML:
  1. Phase "places":  /__get/Place/HomeListPlace  -> danh sách quán
       - listing bị giới hạn độ sâu (~<200 trang x 12 quán / truy vấn) nên script
         chia nhỏ theo  quận  x  danh mục  rồi dedupe theo place id.
  2. Phase "reviews": /__get/Review/ResLoadMore   -> review của từng quán
       - phân trang kiểu cursor bằng LastId.

GIỚI HẠN ĐÃ KIỂM CHỨNG: endpoint review chỉ trả tối đa 100 review MỚI NHẤT mỗi
quán (quán 199 review chỉ lấy được 100; đổi isLatest hay Count không vượt được),
và mỗi request tối đa 10 review. Nên số review lưu < total_reviews ở quán đông là
bình thường. Muốn đủ hơn thì phải bổ sung nguồn khác (Google Maps, TripAdvisor...).

Playwright dùng để mở trình duyệt thật 1 lần (lấy cookie, UA hợp lệ), sau đó gọi
các endpoint JSON bằng context.request (dùng chung cookie của trình duyệt).

Output (thư mục --out, mặc định ./data):
  places.jsonl           mỗi dòng 1 quán
  reviews.jsonl          mỗi dòng 1 review
  places_progress.json   checkpoint phase places (resume được)
  reviews_progress.json  checkpoint phase reviews (resume được)

Chạy:
  python foody_crawler.py places  --max-pages 200
  python foody_crawler.py reviews
  python foody_crawler.py all
  # thử nhanh:
  python foody_crawler.py all --limit-places 5 --max-pages 2 --headed

Ghi chú: hãy tuân thủ Điều khoản sử dụng của Foody, giữ tốc độ thấp
(--concurrency nhỏ, --delay lớn) và chỉ dùng dữ liệu cho mục đích hợp lệ.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.async_api import APIRequestContext, async_playwright

BASE = "https://www.foody.vn"
CITY_SLUG = "da-nang"
# Tâm Đà Nẵng, chỉ ảnh hưởng tới trường Distance trong kết quả
LAT, LON = 16.051571, 108.214897

# Lấy từ dropdown trên trang https://www.foody.vn/da-nang
DISTRICTS = {
    30: "Quận Cẩm Lệ",
    31: "Quận Hải Châu",
    32: "Quận Liên Chiểu",
    33: "Quận Ngũ Hành Sơn",
    34: "Quận Sơn Trà",
    35: "Quận Thanh Khê",
    158: "Huyện Hòa Vang",
    159: "Huyện Hoàng Sa",
}
CATEGORIES = {
    1: "Nhà hàng",
    2: "Café/Dessert",
    3: "Quán ăn",
    4: "Bar/Pub",
    6: "Tiệm bánh",
    11: "Ăn vặt/vỉa hè",
    12: "Sang trọng",
    27: "Shop Online",
    28: "Giao cơm văn phòng",
    39: "Buffet",
    43: "Beer club",
    44: "Tiệc tận nơi",
    54: "Quán nhậu",
    56: "Ăn chay",
    79: "Khu Ẩm Thực",
}

log = logging.getLogger("foody")


# --------------------------------------------------------------------------
# Tiện ích
# --------------------------------------------------------------------------
def parse_ms_date(value: str | None) -> str | None:
    """'/Date(1571916076383)/' -> ISO 8601 (UTC). Trả None nếu không hợp lệ."""
    if not value:
        return None
    m = re.search(r"/Date\((-?\d+)", value)
    if not m:
        return None
    ms = int(m.group(1))
    if ms <= 0:  # foody dùng 0001-01-01 làm giá trị rỗng
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def abs_url(url: str | None) -> str | None:
    if not url:
        return None
    return url if url.startswith("http") else BASE + url


def append_jsonl(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    log.warning("Bỏ qua dòng JSON lỗi trong %s", path)
    return out


def load_json(path: Path, default: Any) -> Any:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log.warning("Checkpoint %s hỏng, bỏ qua", path)
    return default


def save_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)  # ghi nguyên tử, tránh checkpoint hỏng khi Ctrl+C


# --------------------------------------------------------------------------
# HTTP client (Playwright) có retry + giới hạn tốc độ
# --------------------------------------------------------------------------
class Client:
    def __init__(self, req: APIRequestContext, delay: float, concurrency: int,
                 retries: int = 5):
        self.req = req
        self.delay = delay
        self.retries = retries
        self.sem = asyncio.Semaphore(concurrency)

    async def get_json(self, path: str, params: dict[str, Any],
                       referer: str) -> dict | None:
        """GET JSON với retry/backoff. Trả None nếu hết lượt retry."""
        params = {**params, "t": int(datetime.now().timestamp() * 1000)}
        for attempt in range(1, self.retries + 1):
            async with self.sem:
                await asyncio.sleep(self.delay * random.uniform(0.7, 1.4))
                try:
                    resp = await self.req.get(
                        BASE + path,
                        params=params,
                        headers={
                            "X-Requested-With": "XMLHttpRequest",
                            "Referer": referer,
                            "Accept": "application/json, text/javascript, */*; q=0.01",
                        },
                        timeout=30_000,
                    )
                    status = resp.status
                    if status == 200:
                        try:
                            return await resp.json()
                        except Exception:
                            log.warning("Phản hồi không phải JSON: %s", path)
                    elif status in (403, 429) or status >= 500:
                        log.warning("HTTP %s cho %s (lần %d)", status, path, attempt)
                    else:
                        log.error("HTTP %s cho %s -> bỏ qua", status, path)
                        return None
                except Exception as e:  # lỗi mạng / timeout
                    log.warning("Lỗi mạng %s: %s (lần %d)", path, e, attempt)
            # backoff nằm NGOÀI semaphore để không chặn worker khác
            await asyncio.sleep(min(60, 2 ** attempt) + random.random())
        log.error("Bỏ cuộc sau %d lần: %s %s", self.retries, path, params)
        return None


# --------------------------------------------------------------------------
# Chuẩn hoá dữ liệu
# --------------------------------------------------------------------------
def normalize_place(it: dict) -> dict:
    return {
        "place_id": it.get("Id"),
        "name": it.get("Name"),
        "address": it.get("Address"),
        "lat": it.get("Latitude"),
        "lon": it.get("Longitude"),
        "avg_rating": it.get("AvgRating"),
        "total_reviews": it.get("TotalReviews"),
        "total_pictures": it.get("TotalPictures"),
        "total_favourites": it.get("TotalFavourites"),
        "total_saves": it.get("TotalSaves"),
        "phone": (it.get("Phone") or "").strip() or None,
        "price_min": it.get("PriceMin"),
        "price_max": it.get("PriceMax"),
        "url": abs_url(it.get("Url")),
        "url_path": it.get("Url"),
        "master_category_id": it.get("MasterCategoryId"),
        "has_delivery": it.get("HasDelivery"),
        "has_booking": it.get("HasBooking"),
        "categories": it.get("LstCategory"),
        "cuisines": it.get("LstCuisine"),
        "crawled_at": datetime.now(timezone.utc).isoformat(),
    }


def normalize_review(it: dict, place_id: int) -> dict:
    owner = it.get("Owner") or {}
    return {
        "review_id": it.get("Id"),
        "place_id": it.get("ResId") or place_id,
        "title": it.get("Title"),
        "text": it.get("Description"),
        "rating": it.get("AvgRating"),  # thang 10
        "created_at": parse_ms_date(it.get("CreatedDate")),
        "device": it.get("DeviceName"),
        "total_views": it.get("TotalViews"),
        "total_likes": it.get("TotalLike"),
        "total_comments": it.get("TotalComment"),
        "total_pictures": it.get("TotalPictures"),
        "has_video": bool(it.get("Video")),
        "picture_urls": [
            p.get("Url") or p.get("url") or p.get("Src")
            for p in (it.get("Pictures") or []) if isinstance(p, dict)
        ],
        "user_id": owner.get("Id"),
        "user_name": owner.get("DisplayName"),
        "user_url": abs_url(owner.get("Url")),
        "user_level": owner.get("Level"),
        "user_total_reviews": owner.get("TotalReviews"),
        "url": abs_url(it.get("Url")),
        "crawled_at": datetime.now(timezone.utc).isoformat(),
    }


# --------------------------------------------------------------------------
# Phase 1: danh sách quán
# --------------------------------------------------------------------------
async def crawl_query(client: Client, district: int, cate: int, max_pages: int,
                      seen: set[int], out_path: Path, limit: int | None) -> int:
    """Crawl 1 tổ hợp quận x danh mục. Trả về số quán MỚI."""
    new = 0
    for page in range(1, max_pages + 1):
        data = await client.get_json(
            "/__get/Place/HomeListPlace",
            {
                "page": page, "lat": LAT, "lon": LON, "count": 12,
                "districtId": district, "cateId": cate,
                "cuisineId": "", "isReputation": "", "type": 1,
            },
            referer=f"{BASE}/{CITY_SLUG}",
        )
        items = (data or {}).get("Items") or []
        if not items:
            break  # hết trang (hoặc lỗi — lần chạy lại sẽ thử lại tổ hợp này)
        rows = []
        for it in items:
            pid = it.get("Id")
            if pid is None or pid in seen:
                continue
            seen.add(pid)
            rows.append(normalize_place(it))
        append_jsonl(out_path, rows)
        new += len(rows)
        if limit is not None and len(seen) >= limit:
            break
    return new


async def phase_places(client: Client, out: Path, max_pages: int,
                       limit: int | None) -> None:
    places_path = out / "places.jsonl"
    prog_path = out / "places_progress.json"
    seen = {r["place_id"] for r in read_jsonl(places_path)}
    done: set[str] = set(load_json(prog_path, []))
    log.info("Phase places: đã có %d quán, %d truy vấn hoàn tất", len(seen), len(done))

    for d_id, d_name in DISTRICTS.items():
        for c_id, c_name in CATEGORIES.items():
            key = f"{d_id}:{c_id}"
            if key in done:
                continue
            if limit is not None and len(seen) >= limit:
                log.info("Đạt --limit-places=%d, dừng phase places", limit)
                return
            new = await crawl_query(client, d_id, c_id, max_pages, seen,
                                    places_path, limit)
            done.add(key)
            save_json(prog_path, sorted(done))
            log.info("[%s | %s] +%d quán mới (tổng %d)", d_name, c_name, new, len(seen))


# --------------------------------------------------------------------------
# Phase 2: review
# --------------------------------------------------------------------------
async def crawl_place_reviews(client: Client, place: dict, page_size: int,
                              max_reviews: int | None) -> tuple[list[dict], bool]:
    """Trả về (reviews, hoàn_tất). hoàn_tất=False nếu có lỗi giữa chừng."""
    pid = place["place_id"]
    referer = (place.get("url") or BASE) + "/binh-luan"
    reviews: list[dict] = []
    seen_ids: set[int] = set()
    last_id: int | str = ""
    while True:
        data = await client.get_json(
            "/__get/Review/ResLoadMore",
            {"ResId": pid, "LastId": last_id, "Count": page_size,
             "Type": 1, "isLatest": "true", "ExcludeIds": ""},
            referer=referer,
        )
        if data is None:
            return reviews, False  # lỗi -> không đánh dấu done, lần sau làm lại
        items = data.get("Items") or []
        fresh = [it for it in items if it.get("Id") not in seen_ids]
        if not fresh:
            return reviews, True
        for it in fresh:
            seen_ids.add(it["Id"])
            reviews.append(normalize_review(it, pid))
        if max_reviews is not None and len(reviews) >= max_reviews:
            return reviews, True
        new_last = data.get("LastId") or fresh[-1].get("Id")
        if new_last == last_id:  # cursor không tiến -> tránh lặp vô hạn
            return reviews, True
        last_id = new_last


async def phase_reviews(client: Client, out: Path, page_size: int,
                        limit_places: int | None, max_reviews: int | None) -> None:
    places = read_jsonl(out / "places.jsonl")
    reviews_path = out / "reviews.jsonl"
    prog_path = out / "reviews_progress.json"
    done: dict[str, int] = load_json(prog_path, {})  # place_id -> số review đã lưu

    todo = [p for p in places
            if str(p["place_id"]) not in done and (p.get("total_reviews") or 0) > 0]
    if limit_places is not None:
        todo = todo[:limit_places]
    log.info("Phase reviews: %d quán cần crawl (%d đã xong)", len(todo), len(done))

    write_lock = asyncio.Lock()
    counter = {"n": 0}

    async def worker(p: dict) -> None:
        revs, ok = await crawl_place_reviews(client, p, page_size, max_reviews)
        async with write_lock:  # ghi review + checkpoint cùng lúc, nhất quán
            append_jsonl(reviews_path, revs)
            if ok:
                done[str(p["place_id"])] = len(revs)
                save_json(prog_path, done)
            counter["n"] += 1
            expected = p.get("total_reviews") or 0
            log.info("(%d/%d) %s: %d/%d review%s", counter["n"], len(todo),
                     p["name"], len(revs), expected, "" if ok else "  [LỖI, sẽ thử lại]")

    # Chạy theo lô để Ctrl+C không bỏ rơi hàng nghìn task
    batch = max(client.sem._value * 4, 8)  # noqa: SLF001
    for i in range(0, len(todo), batch):
        await asyncio.gather(*(worker(p) for p in todo[i:i + batch]))


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
async def main_async(args: argparse.Namespace) -> None:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=not args.headed)
        context = await browser.new_context(
            locale="vi-VN",
            timezone_id="Asia/Ho_Chi_Minh",
            viewport={"width": 1366, "height": 800},
        )
        try:
            # Mở trang thật 1 lần để nhận cookie/session như người dùng thường
            page = await context.new_page()
            await page.goto(f"{BASE}/{CITY_SLUG}", wait_until="domcontentloaded",
                            timeout=60_000)
            await page.wait_for_timeout(2000)
            await page.close()

            client = Client(context.request, delay=args.delay,
                            concurrency=args.concurrency)
            if args.command in ("places", "all"):
                await phase_places(client, out, args.max_pages, args.limit_places)
            if args.command in ("reviews", "all"):
                await phase_reviews(client, out, args.page_size,
                                    args.limit_places, args.max_reviews)
        finally:
            await context.close()
            await browser.close()


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Crawl review quán ăn Đà Nẵng từ foody.vn")
    ap.add_argument("command", choices=["places", "reviews", "all"])
    ap.add_argument("--out", default="data", help="thư mục output (mặc định: data)")
    ap.add_argument("--max-pages", type=int, default=200,
                    help="số trang tối đa mỗi truy vấn quận x danh mục (mặc định 200)")
    ap.add_argument("--page-size", type=int, default=10,
                    help="số review mỗi request (mặc định 10)")
    ap.add_argument("--limit-places", type=int, default=None,
                    help="giới hạn số quán (dùng để chạy thử)")
    ap.add_argument("--max-reviews", type=int, default=None,
                    help="giới hạn số review mỗi quán")
    ap.add_argument("--concurrency", type=int, default=2,
                    help="số request song song (mặc định 2, đừng đặt cao)")
    ap.add_argument("--delay", type=float, default=0.8,
                    help="độ trễ trung bình giữa các request, giây (mặc định 0.8)")
    ap.add_argument("--headed", action="store_true", help="hiện cửa sổ trình duyệt")
    ap.add_argument("-v", "--verbose", action="store_true")
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        log.warning("Đã dừng. Chạy lại cùng lệnh để tiếp tục từ checkpoint.")
        sys.exit(130)


if __name__ == "__main__":
    main()
