import os
import json
import time
import asyncio
from datetime import datetime
from urllib.parse import quote_plus
from apscheduler.schedulers.blocking import BlockingScheduler
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
from telegram import Bot
import logging
from datetime import timezone
import pytz

# Thiết lập logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Biến môi trường
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')
CHECK_INTERVAL_MINUTES = int(os.getenv('CHECK_INTERVAL_MINUTES', 10))
RENDER = os.getenv('RENDER', 'false').lower() == 'true'

# Đường dẫn lưu trữ dữ liệu
BIDDINGS_FILE = 'biddings.json'
NOTIFIED_BIDDINGS_FILE = 'notified_biddings.json'

# Múi giờ Việt Nam
VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')

# Hàm kiểm tra khung giờ làm việc (GMT+7)
def is_within_working_hours():
    now = datetime.now(VIETNAM_TZ)
    hour = now.hour
    return 8 <= hour < 20  # True nếu trong 8:00 - 19:59 GMT+7

# Hàm xây dựng URL tìm kiếm
def build_bidding_url():
    sfrom = quote_plus('15/08/2025')  # Ngày bắt đầu tìm kiếm
    keyword = quote_plus('Chiếu sáng')
    return f"https://dauthau.asia/tenders/?sfrom={sfrom}&keyword={keyword}"

# Hàm gửi tin nhắn Telegram bất đồng bộ
async def send_telegram_message(bot, chat_id, message):
    try:
        await bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Lỗi khi gửi tin nhắn Telegram: {str(e)}")

# Hàm kiểm tra gói thầu
def check_biddings():
    logger.info("Bắt đầu kiểm tra gói thầu...")
    
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    
    driver = webdriver.Chrome(options=chrome_options)
    url = build_bidding_url()
    
    try:
        driver.get(url)
        time.sleep(5)  # Đợi trang tải
        soup = BeautifulSoup(driver.page_source, 'lxml')
        
        # Giả định cấu trúc HTML
        biddings = []
        bidding_elements = soup.select('div.bidding-item')  # Điều chỉnh selector
        
        for elem in bidding_elements:
            bidding = {
                'id': elem.get('data-id', ''),
                'title': elem.select_one('h3').text.strip() if elem.select_one('h3') else '',
                'issuer': elem.select_one('.issuer').text.strip() if elem.select_one('.issuer') else '',
                'published_date': elem.select_one('.published-date').text.strip() if elem.select_one('.published-date') else '',
                'closing_date': elem.select_one('.closing-date').text.strip() if elem.select_one('.closing-date') else '',
                'link': elem.select_one('a')['href'] if elem.select_one('a') else ''
            }
            biddings.append(bidding)
        
        # Lưu danh sách gói thầu
        with open(BIDDINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(biddings, f, ensure_ascii=False, indent=2)
        
        # Đọc danh sách đã thông báo
        notified_biddings = []
        if os.path.exists(NOTIFIED_BIDDINGS_FILE):
            with open(NOTIFIED_BIDDINGS_FILE, 'r', encoding='utf-8') as f:
                notified_biddings = json.load(f)
        
        notified_ids = {b['id'] for b in notified_biddings}
        new_biddings = [b for b in biddings if b['id'] not in notified_ids]
        
        # Gửi thông báo cho gói thầu mới
        if new_biddings:
            bot = Bot(token=TELEGRAM_TOKEN)
            message = "🔔 PHÁT HIỆN {} GÓI THẦU MỚI\n".format(len(new_biddings))
            for i, bidding in enumerate(new_biddings, 1):
                message += (
                    f"{i}. 🆔 {bidding['id']}\n"
                    f"📦 {bidding['title']}\n"
                    f"🏢 Bên mời thầu: {bidding['issuer']}\n"
                    f"📅 Ngày đăng: {bidding['published_date']}\n"
                    f"⏰ Ngày đóng thầu: {bidding['closing_date']}\n"
                    f"🔗 [Xem chi tiết]({bidding['link']})\n\n"
                )
            asyncio.run(send_telegram_message(bot, CHAT_ID, message))
            
            # Cập nhật danh sách đã thông báo
            notified_biddings.extend(new_biddings)
            with open(NOTIFIED_BIDDINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(notified_biddings, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Tìm thấy {len(new_biddings)} gói thầu mới")
    
    except Exception as e:
        logger.error(f"Lỗi khi kiểm tra gói thầu: {str(e)}")
    
    finally:
        driver.quit()

# Hàm gửi heartbeat
def send_heartbeat():
    bot = Bot(token=TELEGRAM_TOKEN)
    message = (
        f"💓 HEARTBEAT BOT\n"
        f"🕐 {datetime.now(VIETNAM_TZ).strftime('%H:%M:%S - %d/%m/%Y')}\n"
        f"📊 Đã theo dõi: {len(json.load(open(BIDDINGS_FILE))) if os.path.exists(BIDDINGS_FILE) else 0} gói thầu\n"
        f"🔄 Kiểm tra tiếp theo: {CHECK_INTERVAL_MINUTES} phút\n"
        f"✅ Bot đang hoạt động bình thường"
    )
    asyncio.run(send_telegram_message(bot, CHAT_ID, message))

# Hàm công việc định kỳ
def scheduled_job():
    if is_within_working_hours():
        logger.info("Đang kiểm tra gói thầu...")
        check_biddings()
    else:
        logger.info("Bot nghỉ - ngoài khung giờ 8:00 - 20:00")

def main():
    # Gửi thông báo khởi động
    bot = Bot(token=TELEGRAM_TOKEN)
    message = (
        f"🤖 BOT THEO DÕI GÓI THẦU ĐÃ KHỞI ĐỘNG\n"
        f"🕐 Thời gian khởi động: {datetime.now(VIETNAM_TZ).strftime('%H:%M:%S - %d/%m/%Y')}\n"
        f"⏱️ Kiểm tra mỗi: {CHECK_INTERVAL_MINUTES} phút\n"
        f"🎯 Từ khóa tìm kiếm: Chiếu sáng\n"
        f"✅ Bot đang hoạt động và sẵn sàng theo dõi gói thầu mới!"
    )
    asyncio.run(send_telegram_message(bot, CHAT_ID, message))
    
    # Khởi tạo scheduler
    scheduler = BlockingScheduler(timezone=VIETNAM_TZ)
    
    # Thêm công việc kiểm tra gói thầu
    scheduler.add_job(scheduled_job, 'interval', minutes=CHECK_INTERVAL_MINUTES)
    
    # Thêm công việc heartbeat (mỗi 12 giờ)
    scheduler.add_job(send_heartbeat, 'interval', hours=12)
    
    # Bắt đầu scheduler
    logger.info("Khởi động scheduler...")
    scheduler.start()

if __name__ == "__main__":
    main()
