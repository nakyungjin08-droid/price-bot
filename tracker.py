import os
import json
import re
import requests
from bs4 import BeautifulSoup

# 텔레그램 설정값 (GitHub Secrets에서 불러옴)
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 직구, 아랍판, 중고, 악세사리 차단 키워드
EXCLUDE_KEYWORDS = [
    "해외", "직구", "아랍", "병행", "중고", "리퍼", "개봉", "전시", "공기계",
    "케이스", "커버", "보호필름", "스트랩", "파우치", "단품", "호환", "액세서리", "악세사리"
]

# 추적 대상 설정
TARGETS = [
    {
        "id": "tab_s11",
        "name": "갤럭시 탭 S11 기본 (Wi-Fi, 256GB)",
        "query": "갤럭시탭 S11 256GB",
        "target_price": 900000,
        "must_include": ["256GB"]
    },
    {
        "id": "buds4_pro",
        "name": "갤럭시 버즈4 프로 (국내정품)",
        "query": "갤럭시 버즈4 프로",
        "target_price": 280000,
        "must_include": ["버즈4", "프로"]
    }
]

def get_danawa_lowest_price(item_config):
    query = item_config["query"]
    url = f"https://search.danawa.com/dsearch.php?query={requests.utils.quote(query)}"
    
    # 일반 브라우저로 위장하기 위한 헤더 설정
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.danawa.com/"
    }
    
    try:
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code != 200:
            print(f"[다나와] 서버 응답 오류 (상태 코드: {res.status_code})")
            return None

        soup = BeautifulSoup(res.text, "html.parser")
        items = soup.select("li.prod_item")
        
        if not items:
            print(f"[다나와] '{query}' 검색 결과 목록을 찾지 못함 (차단 가능성 또는 페이지 구조 변경)")
            return None

        for item in items:
            # 광고 상품 및 기획전 스킵
            classes = item.get("class", [])
            if "prod_ad_item" in classes or "product-pot" in classes:
                continue

            # 상품명 파싱
            title_elem = item.select_one(".prod_name a")
            if not title_elem:
                continue
            
            title = title_elem.text.strip()
            link = title_elem.get("href", "")
            if link and not link.startswith("http"):
                link = "https:" + link

            # 가격 파싱
            price_elem = item.select_one(".price_sect strong")
            if not price_elem:
                continue

            price_raw = re.sub(r"[^0-9]", "", price_elem.text)
            if not price_raw:
                continue
            
            price = int(price_raw)

            # 제외 키워드 검사 (직구, 아랍판, 중고, 케이스 등 차단)
            if any(keyword in title for keyword in EXCLUDE_KEYWORDS):
                continue

            # 필수 포함 키워드 검사
            if not all(keyword.lower() in title.lower() for keyword in item_config["must_include"]):
                continue

            return {
                "title": title,
                "price": price,
                "link": link,
                "mall": "다나와 최저가"
            }

    except Exception as e:
        print(f"[다나와] 크롤링 도중 예외 발생: {e}")
        return None

    return None

def send_telegram_msg(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    requests.post(url, json=payload)

def main():
    history_file = "price_history.json"
    if os.path.exists(history_file):
        with open(history_file, "r", encoding="utf-8") as f:
            history = json.load(f)
    else:
        history = {}

    updated_history = history.copy()

    for target in TARGETS:
        item_id = target["id"]
        result = get_danawa_lowest_price(target)
        
        if not result:
            print(f"[{target['name']}] 조건에 맞는 최저가 상품을 찾지 못했습니다.")
            continue

        curr_price = result["price"]
        prev_price = history.get(item_id, {}).get("price", None)
        target_price = target["target_price"]

        is_target_reached = curr_price <= target_price
        is_price_dropped_10k = (prev_price is not None) and ((prev_price - curr_price) >= 10000)

        # 알림 전송 조건
        if is_target_reached or is_price_dropped_10k:
            reason = []
            if is_target_reached:
                reason.append(f"🎯 <b>목표가 달성</b> ({target_price:,}원 이하)")
            if is_price_dropped_10k:
                diff = prev_price - curr_price
                reason.append(f"📉 <b>전일 대비 {diff:,}원 하락!</b>")

            msg = (
                f"🚨 <b>[다나와 최저가 알림] {target['name']}</b>\n\n"
                f"📌 <b>사유:</b> {', '.join(reason)}\n"
                f"💵 <b>현재 최저가:</b> {curr_price:,}원\n"
                f"📦 <b>상품명:</b> {result['title']}\n\n"
                f"🔗 <a href='{result['link']}'>다나와 비교 페이지 바로가기</a>"
            )
            send_telegram_msg(msg)

        updated_history[item_id] = {
            "name": target["name"],
            "price": curr_price,
            "title": result["title"]
        }

    with open(history_file, "w", encoding="utf-8") as f:
        json.dump(updated_history, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
