import os
import json
import re
import requests
from bs4 import BeautifulSoup

# 텔레그램 설정값
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 정품을 가리지 않도록 정제한 공통 차단 키워드
EXCLUDE_KEYWORDS = [
    "해외", "직구", "아랍", "병행", "중고", "리퍼", "개봉", "전시", "공기계",
    "보호필름", "스트랩", "파우치", "호환", "액세서리", "악세사리",
    "구독", "렌탈", "약정"
]

# 추적 대상 설정
TARGETS = [
    {
        "id": "tab_s11",
        "name": "갤럭시 탭 S11 기본 (Wi-Fi, 256GB)",
        "query": "갤럭시탭 S11 256GB",
        "target_price": 900000,
        "min_price": 500000,
        "must_include": ["S11"],
        # 기본 Wi-Fi 모델만 찾기 위해 울트라, 플러스, 5G/LTE 제외
        "must_exclude": ["울트라", "플러스", "+", "5g", "lte"]
    },
    {
        "id": "buds4_pro",
        "name": "갤럭시 버즈4 프로 (국내정품)",
        "query": "갤럭시 버즈4 프로",
        "target_price": 280000,
        "min_price": 100000,
        "must_include": ["버즈", "프로"],
        "must_exclude": []
    }
]

def get_danawa_lowest_price(item_config):
    query = item_config["query"]
    url = f"https://search.danawa.com/dsearch.php?query={requests.utils.quote(query)}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://www.danawa.com/"
    }
    
    try:
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code != 200:
            print(f"[{item_config['name']}] 서버 응답 실패: {res.status_code}")
            return None

        soup = BeautifulSoup(res.text, "html.parser")
        items = soup.select("li.prod_item")
        
        print(f"\n--- [{item_config['name']}] 다나와 검색결과 검사 시작 (총 {len(items)}개) ---")

        for item in items:
            classes = item.get("class", [])
            if "prod_ad_item" in classes or "product-pot" in classes:
                continue

            title_elem = item.select_one(".prod_name a")
            if not title_elem:
                continue
            
            title = title_elem.text.strip()
            link = title_elem.get("href", "")
            if link and not link.startswith("http"):
                link = "https:" + link

            price_elem = item.select_one(".price_sect strong")
            if not price_elem:
                continue

            price_raw = re.sub(r"[^0-9]", "", price_elem.text)
            if not price_raw:
                continue
            
            price = int(price_raw)

            # 1. 최소 가격 제한 검사
            if price < item_config.get("min_price", 0):
                print(f"❌ 제외(최저가 미달): {title} ({price:,}원)")
                continue

            # 2. 공통 제외 키워드 검사
            matched_exclude = [kw for kw in EXCLUDE_KEYWORDS if kw in title]
            if matched_exclude:
                print(f"❌ 제외(키워드 '{matched_exclude[0]}'): {title}")
                continue

            clean_title = title.lower().replace(" ", "")

            # 3. 개별 상품 전용 제외 키워드 검사 (울트라, +, 5G 등)
            matched_target_exclude = [kw for kw in item_config.get("must_exclude", []) if kw.lower() in clean_title]
            if matched_target_exclude:
                print(f"❌ 제외(상위/통신사모델 '{matched_target_exclude[0]}'): {title}")
                continue

            # 4. 필수 키워드 검사 (S11 등)
            missing_keywords = [kw for kw in item_config["must_include"] if kw.lower().replace(" ", "") not in clean_title]
            if missing_keywords:
                print(f"❌ 제외(필수단어 '{missing_keywords[0]}' 누락): {title}")
                continue

            # 모든 조건을 통과한 최저가 상품 선택
            print(f"✅ 최종 선택된 최저가: {title} ({price:,}원)")
            return {
                "title": title,
                "price": price,
                "link": link
            }

    except Exception as e:
        print(f"오류 발생: {e}")
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
            print(f"⚠️ [{target['name']}] 조건에 맞는 상품을 찾지 못했습니다.\n")
            continue

        curr_price = result["price"]
        prev_price = history.get(item_id, {}).get("price", None)
        target_price = target["target_price"]

        is_target_reached = curr_price <= target_price
        is_price_dropped_10k = (prev_price is not None) and ((prev_price - curr_price) >= 10000)
        is_first_run = prev_price is None

        if is_target_reached or is_price_dropped_10k or is_first_run:
            reason = []
            if is_first_run:
                reason.append("🔍 <b>최초 가격 등록 완료</b>")
            if is_target_reached:
                reason.append(f"🎯 <b>목표가 달성</b> ({target_price:,}원 이하)")
            if is_price_dropped_10k:
                diff = prev_price - curr_price
                reason.append(f"📉 <b>전일 대비 {diff:,}원 하락!</b>")

            msg = (
                f"🚨 <b>[다나와 최저가 알림] {target['name']}</b>\n\n"
                f"📌 <b>상태:</b> {', '.join(reason)}\n"
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
