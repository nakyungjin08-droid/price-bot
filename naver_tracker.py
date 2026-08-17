import os
import json
import re
import requests
from bs4 import BeautifulSoup

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

EXCLUDE_KEYWORDS = [
    "해외", "직구", "아랍", "병행", "중고", "리퍼", "개봉", "전시", "공기계",
    "보호필름", "스트랩", "파우치", "호환", "액세서리", "악세사리", "구독", "렌탈", "약정"
]

TARGETS = [
    {
        "id": "naver_tab_s11",
        "name": "[네이버] 갤럭시 탭 S11 기본 (Wi-Fi, 256GB)",
        "query": "갤럭시탭 S11 256GB",
        "target_price": 900000,
        "min_price": 500000,
        "must_include": ["S11"],
        "must_exclude": ["울트라", "플러스", "+", "5g", "lte"]
    },
    {
        "id": "naver_buds4_pro",
        "name": "[네이버] 갤럭시 버즈4 프로",
        "query": "갤럭시 버즈4 프로",
        "target_price": 280000,
        "min_price": 100000,
        "must_include": ["버즈", "프로"],
        "must_exclude": []
    }
]

def get_naver_lowest_price(item_config):
    query = item_config["query"]
    url = f"https://search.shopping.naver.com/search/all?query={requests.utils.quote(query)}"
    
    session = requests.Session()
    
    # 네이버 418 보안 차단을 우회하기 위한 정밀 브라우저 헤더 설정
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Sec-Ch-Ua": '"Not-A.Brand";v="99", "Chromium";v="124", "Google Chrome";v="124"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1"
    }

    try:
        res = session.get(url, headers=headers, timeout=15)
        if res.status_code != 200:
            print(f"네이버 접속 실패 (상태 코드: {res.status_code})")
            return None

        soup = BeautifulSoup(res.text, "html.parser")
        
        # Next.js 데이터 태그 파싱
        next_data_script = soup.find("script", id="__NEXT_DATA__")
        if not next_data_script:
            print("네이버 데이터 구조 파싱 실패")
            return None

        data_json = json.loads(next_data_script.string)
        
        products = []
        try:
            list_items = data_json["props"]["pageProps"]["initialState"]["products"]["list"]
            for entry in list_items:
                item = entry.get("item", {})
                if not item:
                    continue
                
                title = item.get("productTitle", "")
                price = int(item.get("price", 0))
                link = item.get("crUrl", "") or f"https://cr.shopping.naver.com/adcr.nhn?x={item.get('id')}"

                products.append({"title": title, "price": price, "link": link})
        except KeyError:
            print("네이버 JSON 구조 변경으로 인한 항목 추출 실패")
            return None

        for prod in products:
            title = prod["title"]
            price = prod["price"]

            if price < item_config.get("min_price", 0):
                continue

            if any(kw in title for kw in EXCLUDE_KEYWORDS):
                continue

            title_no_space = title.lower().replace(" ", "")

            if any(kw.lower() in title_no_space for kw in item_config.get("must_exclude", [])):
                continue

            if any(kw.lower().replace(" ", "") not in title_no_space for kw in item_config["must_include"]):
                continue

            return prod

    except Exception as e:
        print(f"크롤링 에러: {e}")
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
    history_file = "naver_price_history.json"
    if os.path.exists(history_file):
        with open(history_file, "r", encoding="utf-8") as f:
            history = json.load(f)
    else:
        history = {}

    updated_history = history.copy()
    alerts_sent = 0
    daily_status_list = []

    for target in TARGETS:
        item_id = target["id"]
        result = get_naver_lowest_price(target)
        
        if not result:
            daily_status_list.append(f"• <b>{target['name']}</b>: 최저가 검색 실패")
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
                reason.append("🔍 <b>네이버 최초 가격 등록</b>")
            if is_target_reached:
                reason.append(f"🎯 <b>목표가 달성</b> ({target_price:,}원 이하)")
            if is_price_dropped_10k:
                diff = prev_price - curr_price
                reason.append(f"📉 <b>전일 대비 {diff:,}원 하락!</b>")

            msg = (
                f"🟢 <b>[네이버 최저가 알림] {target['name']}</b>\n\n"
                f"📌 <b>상태:</b> {', '.join(reason)}\n"
                f"💵 <b>현재 최저가:</b> {curr_price:,}원\n"
                f"📦 <b>상품명:</b> {result['title']}\n\n"
                f"🔗 <a href='{result['link']}'>네이버 쇼핑 바로가기</a>"
            )
            send_telegram_msg(msg)
            alerts_sent += 1
        else:
            daily_status_list.append(f"• <b>{target['name']}</b>: {curr_price:,}원 (변동 없음)")

        updated_history[item_id] = {
            "name": target["name"],
            "price": curr_price,
            "title": result["title"]
        }

    if alerts_sent == 0 and daily_status_list:
        status_msg = (
            f"ℹ️ <b>[네이버 쇼핑 일일 점검 완료]</b>\n\n"
            f"오늘 네이버 최저가 변동 사항이 없습니다.\n\n"
            f"<b>[현재 네이버 가격 현황]</b>\n" + "\n".join(daily_status_list)
        )
        send_telegram_msg(status_msg)

    with open(history_file, "w", encoding="utf-8") as f:
        json.dump(updated_history, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
