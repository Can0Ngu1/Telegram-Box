import logging
import time
import asyncio
import os
import json
from datetime import datetime
from urllib.parse import quote_plus
import requests
from telegram import Bot
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from bs4 import BeautifulSoup
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# === CẤU HÌNH ===
NOTIFIED_FILE = "notified_biddings.json"
BIDDINGS_FILE = "biddings.json"

# Lấy config từ environment variables cho Render
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN', '7413526182:AAHbqSltL84gIp3xL60B2RKtu5_zbXk1C-8')
CHAT_ID = int(os.getenv('CHAT_ID', '-4788707953'))
CHECK_INTERVAL_MINUTES = int(os.getenv('CHECK_INTERVAL_MINUTES', '10'))

# === SETUP LOGGING ===
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler()  # Chỉ output ra console cho Render
    ]
)
logger = logging.getLogger(__name__)

# === Các hàm tiện ích ===
def load_notified_biddings():
    """Load danh sách các gói thầu đã thông báo"""
    if os.path.exists(NOTIFIED_FILE):
        try:
            with open(NOTIFIED_FILE, 'r', encoding='utf-8') as f:
                return set(json.load(f))
        except Exception as e:
            logger.error(f"Lỗi đọc file notified_biddings: {e}")
            return set()
    return set()

def save_notified_biddings(notified_set):
    """Lưu danh sách các gói thầu đã thông báo"""
    try:
        with open(NOTIFIED_FILE, 'w', encoding='utf-8') as f:
            json.dump(list(notified_set), f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Lỗi lưu file notified_biddings: {e}")

def save_biddings(biddings):
    """Lưu danh sách gói thầu"""
    try:
        with open(BIDDINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(biddings, f, ensure_ascii=False, indent=2)
        logger.info(f"Đã lưu {len(biddings)} gói thầu vào {BIDDINGS_FILE}")
    except Exception as e:
        logger.error(f"Lỗi lưu file biddings: {e}")

def get_chrome_options():
    """Cấu hình Chrome options cho môi trường server"""
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-web-security")
    options.add_argument("--disable-features=VizDisplayCompositor")
    options.add_argument("--blink-settings=imagesEnabled=false")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--remote-debugging-port=9222")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Linux; x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    
    # Cấu hình cho Render (Linux environment)
    if os.getenv('RENDER'):
        options.binary_location = "/usr/bin/google-chrome"
    
    return options

def build_bidding_url():
    """Xây dựng URL tìm kiếm gói thầu"""
    today = datetime.now().strftime("%d/%m/%Y")
    base_url = "https://dauthau.asia/thongbao/moithau/?"
    params = [
        "q=Chiếu+sáng",
        "type_search=1",
        "type_info=1",
        "type_info3=1",
        f"sfrom={quote_plus('15/08/2025')}",
        f"sto={quote_plus(today)}",
        "is_advance=0",
        "is_province=0",
        "is_kqlcnt=0",
        "type_choose_id=0",
        "search_idprovincekq=1",
        "search_idprovince_khtt=1",
        "goods_2=0",
        "searchkind=0",
        "type_view_open=0",
        "sl_nhathau=0",
        "sl_nhathau_cgtt=0",
        "search_idprovince=1",
        "type_org=1",
        "goods=0",
        "cat=0",
        "keyword_id_province=0",
        "oda=-1",
        "khlcnt=0",
        "search_rq_province=-1",
        "search_rq_province=1",
        "rq_form_value=0",
        "searching=1"
    ]
    url = base_url + "&".join(params)
    logger.info(f"URL kiểm tra: {url}")
    return url

async def check_new_biddings():
    """Kiểm tra gói thầu mới"""
    logger.info("🔍 Bắt đầu kiểm tra gói thầu mới...")
    notified = load_notified_biddings()
    logger.info(f"📋 Đã có {len(notified)} gói thầu được thông báo trước đó")
    
    options = get_chrome_options()
    driver = None
    new_biddings = []
    
    try:
        # Khởi tạo Chrome driver
        if os.getenv('RENDER'):
            # Trên Render, Chrome đã được cài sẵn
            driver = webdriver.Chrome(options=options)
        else:
            # Local development
            from webdriver_manager.chrome import ChromeDriverManager
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
        
        url = build_bidding_url()
        logger.info("🌐 Đang truy cập trang web...")
        driver.get(url)
        
        # Chờ trang load
        time.sleep(5)
        
        try:
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.CLASS_NAME, "bidding-code"))
            )
            logger.info("✅ Trang web đã load thành công, bắt đầu thu thập dữ liệu...")
        except Exception as e:
            logger.warning(f"⚠️ Không tìm thấy element gói thầu: {e}")
            return []
        
        # Parse HTML
        soup = BeautifulSoup(driver.page_source, "html.parser")
        rows = soup.find_all("tr")
        logger.info(f"📊 Tìm thấy {len(rows)} hàng dữ liệu để xử lý")
        
        for row in rows:
            try:
                code_tag = row.select_one("span.bidding-code")
                title_tag = row.select_one("td[data-column='Gói thầu'] a")
                post_date_tag = row.select_one("td[data-column='Ngày đăng tải']")
                close_date_tag = row.select_one("td[data-column='Ngày đóng thầu']")
                org_tag = row.select_one("td[data-column='Bên mời thầu']")
                
                if code_tag and title_tag and post_date_tag:
                    code = code_tag.text.strip()
                    title = title_tag.get_text(strip=True)
                    link = "https://dauthau.asia" + title_tag["href"] if title_tag.get("href") else ""
                    post_date = post_date_tag.get_text(strip=True)
                    close_date = close_date_tag.get_text(strip=True) if close_date_tag else "Chưa có thông tin"
                    org = org_tag.get_text(strip=True) if org_tag else "Không rõ"
                    
                    if code not in notified and code and title:
                        logger.info(f"🆕 Phát hiện gói thầu mới: {code}")
                        new_biddings.append({
                            'code': code,
                            'title': title,
                            'post_date': post_date,
                            'close_date': close_date,
                            'link': link,
                            'org': org,
                            'timestamp': datetime.now().isoformat()
                        })
                        notified.add(code)
                        
            except Exception as e:
                logger.warning(f"⚠️ Lỗi khi xử lý hàng: {e}")
                continue
        
        # Lưu danh sách đã thông báo
        save_notified_biddings(notified)
        logger.info(f"✅ Kết thúc kiểm tra: Tìm thấy {len(new_biddings)} gói thầu mới")
        return new_biddings
        
    except Exception as e:
        logger.error(f"❌ Lỗi kiểm tra gói thầu: {e}")
        return []
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass

def format_bidding_message(biddings):
    """Format tin nhắn thông báo gói thầu"""
    if not biddings:
        return "ℹ️ Không có gói thầu mới trong lần kiểm tra này."
    
    message = f"🔔 **PHÁT HIỆN {len(biddings)} GÓI THẦU MỚI**\n\n"
    
    for i, bidding in enumerate(biddings[:5], 1):
        message += f"**{i}. 🆔 {bidding['code']}**\n"
        
        title = bidding['title'][:120] + "..." if len(bidding['title']) > 120 else bidding['title']
        message += f"📦 **{title}**\n"
        message += f"🏢 **Bên mời thầu:** {bidding['org']}\n"
        message += f"📅 **Ngày đăng:** {bidding['post_date']}\n"
        message += f"⏰ **Ngày đóng thầu:** {bidding['close_date']}\n"
        
        if bidding['link']:
            message += f"🔗 [Xem chi tiết]({bidding['link']})\n"
        
        message += "\n" + "─" * 40 + "\n\n"
    
    if len(biddings) > 5:
        message += f"📋 *...và còn {len(biddings) - 5} gói thầu khác nữa*\n\n"
    
    now = datetime.now().strftime("%H:%M:%S - %d/%m/%Y")
    message += f"🕐 *Cập nhật lúc: {now}*"
    
    return message

async def send_telegram_notification(message):
    """Gửi thông báo qua Telegram"""
    try:
        bot = Bot(TELEGRAM_TOKEN)
        await bot.send_message(
            chat_id=CHAT_ID,
            text=message,
            parse_mode='Markdown',
            disable_web_page_preview=True
        )
        logger.info("📤 Đã gửi thông báo Telegram thành công")
        return True
    except Exception as e:
        logger.error(f"❌ Lỗi gửi thông báo Telegram: {e}")
        return False

async def check_and_notify():
    """Kiểm tra và thông báo gói thầu mới"""
    logger.info("=" * 50)
    logger.info(f"🚀 Bắt đầu kiểm tra: {datetime.now().strftime('%H:%M:%S - %d/%m/%Y')}")
    
    try:
        # Kiểm tra gói thầu mới
        new_biddings = await check_new_biddings()
        
        if new_biddings:
            logger.info(f"🎉 Tìm thấy {len(new_biddings)} gói thầu mới!")
            
            # Lưu dữ liệu
            try:
                existing_biddings = []
                if os.path.exists(BIDDINGS_FILE):
                    with open(BIDDINGS_FILE, 'r', encoding='utf-8') as f:
                        existing_biddings = json.load(f)
                
                all_biddings = new_biddings + existing_biddings
                save_biddings(all_biddings)
            except Exception as e:
                logger.error(f"Lỗi lưu dữ liệu: {e}")
            
            # Gửi thông báo
            message = format_bidding_message(new_biddings)
            success = await send_telegram_notification(message)
            
            if success:
                logger.info("✅ Đã thông báo thành công về gói thầu mới")
            else:
                logger.error("❌ Thông báo thất bại")
                
        else:
            logger.info("📝 Không có gói thầu mới")
            
    except Exception as e:
        logger.error(f"❌ Lỗi trong quá trình kiểm tra: {e}")
        
        # Gửi thông báo lỗi
        error_message = f"⚠️ **LỖI BOT KIỂM TRA GÓI THẦU**\n\n"
        error_message += f"🕐 Thời gian: {datetime.now().strftime('%H:%M:%S - %d/%m/%Y')}\n"
        error_message += f"❌ Lỗi: {str(e)}\n\n"
        error_message += "Bot sẽ tiếp tục thử trong lần kiểm tra tiếp theo."
        
        try:
            await send_telegram_notification(error_message)
        except:
            logger.error("Không thể gửi thông báo lỗi")
    
    logger.info(f"🏁 Kết thúc kiểm tra: {datetime.now().strftime('%H:%M:%S')}")
    logger.info("=" * 50)

async def send_startup_notification():
    """Gửi thông báo bot đã khởi động"""
    startup_message = f"🤖 **BOT THEO DÕI GÓI THẦU ĐÃ KHỞI ĐỘNG**\n\n"
    startup_message += f"🕐 Thời gian khởi động: {datetime.now().strftime('%H:%M:%S - %d/%m/%Y')}\n"
    startup_message += f"⏱️ Kiểm tra mỗi: {CHECK_INTERVAL_MINUTES} phút\n"
    startup_message += f"🎯 Từ khóa tìm kiếm: Chiếu sáng\n\n"
    startup_message += "✅ Bot đang hoạt động và sẵn sàng theo dõi gói thầu mới!"
    
    await send_telegram_notification(startup_message)

async def send_heartbeat():
    """Gửi tín hiệu heartbeat định kỳ"""
    try:
        notified = load_notified_biddings()
        heartbeat_message = f"💓 **HEARTBEAT BOT**\n\n"
        heartbeat_message += f"🕐 {datetime.now().strftime('%H:%M:%S - %d/%m/%Y')}\n"
        heartbeat_message += f"📊 Đã theo dõi: {len(notified)} gói thầu\n"
        heartbeat_message += f"🔄 Kiểm tra tiếp theo: {CHECK_INTERVAL_MINUTES} phút\n\n"
        heartbeat_message += "✅ Bot đang hoạt động bình thường"
        
        await send_telegram_notification(heartbeat_message)
        logger.info("💓 Đã gửi heartbeat")
    except Exception as e:
        logger.error(f"Lỗi gửi heartbeat: {e}")

async def main():
    """Hàm chính chạy bot"""
    logger.info("🚀 Khởi động Bot Theo Dõi Gói Thầu cho Render")
    logger.info(f"📱 Telegram Token: {TELEGRAM_TOKEN[:10]}...")
    logger.info(f"💬 Chat ID: {CHAT_ID}")
    logger.info(f"⏱️ Interval: {CHECK_INTERVAL_MINUTES} phút")
    
    # Gửi thông báo khởi động
    await send_startup_notification()
    
    # Tạo scheduler
    scheduler = AsyncIOScheduler()
    
    # Thêm job kiểm tra gói thầu
    scheduler.add_job(
        check_and_notify,
        'interval',
        minutes=CHECK_INTERVAL_MINUTES,
        id='check_biddings'
    )
    
    # Thêm job heartbeat mỗi 12 giờ (để không spam khi check 10 phút/lần)
    scheduler.add_job(
        send_heartbeat,
        'interval',
        hours=12,
        id='heartbeat'
    )
    
    # Bắt đầu scheduler
    scheduler.start()
    logger.info(f"⏰ Scheduler đã bắt đầu - Kiểm tra mỗi {CHECK_INTERVAL_MINUTES} phút")
    
    # Chạy kiểm tra đầu tiên sau 1 phút
    await asyncio.sleep(60)
    await check_and_notify()
    
    try:
        # Giữ bot chạy liên tục
        while True:
            await asyncio.sleep(300)  # Chờ 5 phút để giảm log spam
            logger.info(f"🔄 Bot đang chạy... Next check in {CHECK_INTERVAL_MINUTES} minutes")
            
    except KeyboardInterrupt:
        logger.info("🛑 Nhận tín hiệu dừng bot")
    except Exception as e:
        logger.error(f"❌ Lỗi không mong muốn: {e}")
    finally:
        scheduler.shutdown()
        logger.info("🏁 Bot đã dừng")

# Hàm khởi động cho Render
def start_bot():
    """Entry point cho Render"""
    try:
        asyncio.run(main())
    except Exception as e:
        logger.error(f"❌ Lỗi khởi động bot: {e}")

if __name__ == '__main__':
    start_bot()