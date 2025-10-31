import os
import json
import gspread
import logging
import pytz
import asyncio
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes,
    filters
)

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Config
BOT_TOKEN = os.environ.get("BOT_TOKEN")
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS")
GOOGLE_SHEET_NAME = "Pengaduan Global"
ADMIN_IDS = [5704050846, 8388423519, 5048153064]

# Timezone Jakarta
JAKARTA_TZ = pytz.timezone('Asia/Jakarta')

# Website configuration dengan kode yang FIXED
WEBSITES = {
    'jokerbola': {'code': 'JB', 'name': 'JokerBola'},
    'nagabola': {'code': 'NB', 'name': 'NagaBola'}, 
    'macanbola': {'code': 'MB', 'name': 'MacanBola'},
    'ligapedia': {'code': 'LP', 'name': 'LigaPedia'},
    'pasarliga': {'code': 'PL', 'name': 'PasarLiga'}
}

# Setup Google Sheets
try:
    gc = gspread.service_account_from_dict(json.loads(GOOGLE_CREDENTIALS_JSON))
    sh = gc.open(GOOGLE_SHEET_NAME)
    worksheet = sh.sheet1
    logger.info("✅ Google Sheets connected successfully")
except Exception as e:
    logger.error(f"❌ Google Sheets connection failed: {e}")
    worksheet = None

# Helper functions
def get_jakarta_time():
    """Dapatkan waktu Jakarta sekarang"""
    return datetime.now(JAKARTA_TZ).strftime("%d/%m/%Y %H:%M:%S")

def generate_ticket_number(website_code):
    """Generate ticket number dengan format: CODE-DDMMYYYY-NOMOR"""
    try:
        all_data = worksheet.get_all_records()
        today = datetime.now(JAKARTA_TZ).strftime("%d%m%Y")  # DDMMYYYY
        
        # Hitung tiket hari ini untuk website tertentu
        count_today = sum(1 for row in all_data 
                         if str(row.get('Ticket ID', '')).startswith(f"{website_code}-{today}"))
        
        return f"{website_code}-{today}-{count_today+1:03d}"
    except Exception as e:
        logger.error(f"Error generating ticket: {e}")
        return f"{website_code}-{datetime.now(JAKARTA_TZ).strftime('%d%m%Y')}-001"

def escape_html(text):
    """Escape karakter khusus HTML"""
    if not text:
        return ""
    escape_chars = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
    }
    return ''.join(escape_chars.get(char, char) for char in str(text))

def main_menu_keyboard():
    """Keyboard menu utama dengan tombol MENU di sebelah kiri"""
    return ReplyKeyboardMarkup([
        ['📝 Buat Pengaduan', '🔍 Cek Status'],
        ['ℹ️ Bantuan', 'MENU']
    ], resize_keyboard=True)

def cancel_keyboard():
    """Keyboard untuk pembatalan dengan tombol MENU"""
    return ReplyKeyboardMarkup([
        ['❌ Batalkan', 'MENU']
    ], resize_keyboard=True)

# ===== STATE MANAGEMENT =====
user_states = {}
user_website_history = {}  # Untuk melacak website yang pernah digunakan user

def get_user_state(user_id):
    """Dapatkan state user dengan default values"""
    if user_id not in user_states:
        user_states[user_id] = {
            "mode": None,
            "step": None,
            "data": {}
        }
    return user_states[user_id]

def clear_user_state(user_id):
    """Clear state user"""
    if user_id in user_states:
        del user_states[user_id]

def update_user_website_history(user_id, website_name):
    """Update history website user"""
    user_website_history[user_id] = website_name

# ===== HANDLERS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command - reset semua state dan tampilkan menu"""
    user_id = update.message.from_user.id
    clear_user_state(user_id)
    
    await update.message.reply_text(
        "🤖 <b>Selamat datang di Layanan Pengaduan</b>\n\n"
        "Kami siap untuk melayani pengaduan anda.\n\n"
        "Silakan pilih menu di bawah:",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard()
    )

async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk tombol MENU - kembali ke menu utama"""
    user_id = update.message.from_user.id
    clear_user_state(user_id)
    
    await update.message.reply_text(
        "📱 <b>Menu Utama</b>\n\n"
        "Silakan pilih opsi yang Anda butuhkan:",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard()
    )

async def handle_buat_pengaduan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Memulai pengaduan baru - LANGSUNG MULAI DENGAN NAMA WEBSITE"""
    user_id = update.message.from_user.id
    clear_user_state(user_id)
    user_state = get_user_state(user_id)
    user_state["mode"] = "pengaduan"
    user_state["step"] = "nama_website"
    
    await update.message.reply_text(
        "📝 <b>Membuat Pengaduan Baru</b>\n\n"
        "Silakan tulis <b>nama website</b> yang ingin Anda laporkan:\n\n"
        "Ketik ❌ Batalkan untuk membatalkan",
        parse_mode="HTML",
        reply_markup=cancel_keyboard()
    )

async def handle_cek_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cek status tiket"""
    user_id = update.message.from_user.id
    clear_user_state(user_id)
    user_state = get_user_state(user_id)
    user_state["mode"] = "cek_status"
    user_state["step"] = "input_tiket"
    
    # Berikan contoh tiket berdasarkan website history user jika ada
    example_ticket = ""
    if user_id in user_website_history:
        website_name = user_website_history[user_id]
        website_code = None
        for key, info in WEBSITES.items():
            if info['name'] == website_name:
                website_code = info['code']
                break
        
        if website_code:
            example_ticket = f"\n<b>Contoh:</b> <code>{website_code}-31102025-001</code>"
    
    await update.message.reply_text(
        f"🔍 <b>Cek Status Tiket</b>\n\n"
        f"Silakan kirim <b>Nomor Tiket</b> Anda:{example_ticket}\n\n"
        "Ketik ❌ Batalkan untuk membatalkan",
        parse_mode="HTML",
        reply_markup=cancel_keyboard()
    )

async def handle_bantuan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu bantuan - DISEDERHANAKAN"""
    await update.message.reply_text(
        "ℹ️ <b>Bantuan Penggunaan</b>\n\n"
        "📝 <b>Cara Buat Pengaduan:</b>\n"
        "1. Klik '📝 Buat Pengaduan'\n"
        "2. Tulis nama website\n"
        "3. Isi nama lengkap\n"
        "4. Isi username website\n"
        "5. Jelaskan keluhan\n"
        "6. Kirim bukti (opsional)\n\n"
        "🔍 <b>Cek Status:</b>\n"
        "1. Klik '🔍 Cek Status'\n"
        "2. Masukkan nomor tiket\n\n"
        "💡 <b>Tips:</b>\n"
        "• Simpan nomor tiket dengan baik\n"
        "• Bisa buat pengaduan berkali-kali\n\n"
        "❌ <b>Batalkan proses kapan saja</b> dengan klik '❌ Batalkan'\n"
        "📱 <b>Kembali ke menu utama</b> dengan klik 'MENU'",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard()
    )

async def handle_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle cancel dari button"""
    user_id = update.message.from_user.id
    clear_user_state(user_id)
    
    await update.message.reply_text(
        "❌ <b>Proses dibatalkan</b>\n\n"
        "Kembali ke menu utama.",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard()
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle semua pesan text dengan state management yang lebih baik"""
    user_message = update.message.text.strip()
    user_id = update.message.from_user.id
    
    user_state = get_user_state(user_id)
    logger.info(f"User {user_id} message: {user_message}, state: {user_state}")
    
    # Handle MENU terlebih dahulu (selalu kembali ke menu utama)
    if user_message == "MENU":
        await handle_menu(update, context)
        return
    
    # Handle cancel terlebih dahulu
    if user_message.lower() == "❌ batalkan":
        await handle_cancel(update, context)
        return
    
    # Handle menu utama
    if not user_state["mode"]:
        if user_message == "📝 Buat Pengaduan":
            await handle_buat_pengaduan(update, context)
            return
        elif user_message == "🔍 Cek Status":
            await handle_cek_status(update, context)
            return
        elif user_message == "ℹ️ Bantuan":
            await handle_bantuan(update, context)
            return
        else:
            await show_menu(update, context)
            return
    
    # Handle berdasarkan mode
    mode = user_state["mode"]
    step = user_state.get("step", "")
    
    if mode == "pengaduan":
        await handle_pengaduan_flow(update, context, user_message, user_state)
    elif mode == "cek_status" and step == "input_tiket":
        await proses_cek_status(update, context, user_message, user_state)
    else:
        logger.warning(f"Unknown state for user {user_id}: {user_state}")
        clear_user_state(user_id)
        await show_menu(update, context)

async def handle_pengaduan_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, user_message: str, user_state: dict):
    """Handle flow pengaduan yang lebih robust"""
    step = user_state.get("step", "")
    user_id = update.message.from_user.id
    
    if step == "nama_website":
        # Cari website berdasarkan input user (case insensitive)
        website_found = None
        website_code = None
        
        for key, info in WEBSITES.items():
            if user_message.lower() in [key.lower(), info['name'].lower()]:
                website_found = info['name']
                website_code = info['code']
                break
        
        if website_found:
            # Update website history
            update_user_website_history(user_id, website_found)
            
            user_state["data"]["website_name"] = website_found
            user_state["data"]["website_code"] = website_code
            user_state["step"] = "nama"
            
            await update.message.reply_text(
                f"<b>{website_found}</b>\n\n"
                "Silakan kirim <b>Nama Lengkap</b> Anda:\n\n"
                "Ketik ❌ Batalkan untuk membatalkan",
                parse_mode="HTML",
                reply_markup=cancel_keyboard()
            )
        else:
            await update.message.reply_text(
                "❌ <b>Website tidak dikenali!</b>\n\n"
                "Silakan tulis kembali nama website:",
                parse_mode="HTML",
                reply_markup=cancel_keyboard()
            )
        
    elif step == "nama":
        user_state["data"]["nama"] = user_message
        user_state["data"]["user_id"] = update.message.from_user.id
        user_state["data"]["username_tg"] = update.message.from_user.username or "-"
        user_state["step"] = "username_website"
        
        website_name = user_state["data"]["website_name"]
        
        await update.message.reply_text(
            f"🆔 <b>Masukkan Username / ID {website_name} Anda:</b>\n\n"
            "Ketik ❌ Batalkan untuk membatalkan",
            parse_mode="HTML",
            reply_markup=cancel_keyboard()
        )
        
    elif step == "username_website":
        user_state["data"]["username_website"] = user_message
        user_state["step"] = "keluhan"
        
        await update.message.reply_text(
            "📋 <b>Jelaskan keluhan Anda:</b>\n\n"
            "Ketik ❌ Batalkan untuk membatalkan",
            parse_mode="HTML",
            reply_markup=cancel_keyboard()
        )
        
    elif step == "keluhan":
        user_state["data"]["keluhan"] = user_message
        user_state["step"] = "bukti"
        
        await update.message.reply_text(
            "📸 <b>Kirim foto bukti (opsional)</b>\n\n"
            "Kirim foto sekarang atau ketik 'lanjut' untuk melanjutkan tanpa bukti.\n\n"
            "Ketik ❌ Batalkan untuk membatalkan",
            parse_mode="HTML",
            reply_markup=cancel_keyboard()
        )
        
    elif step == "bukti" and user_message.lower() == "lanjut":
        user_state["data"]["bukti"] = "Tidak ada"
        await selesaikan_pengaduan(update, context, user_state)
        
    elif step == "bukti":
        await update.message.reply_text(
            "❌ <b>Perintah tidak dikenali</b>\n\n"
            "Untuk melanjutkan tanpa bukti, ketik: <b>lanjut</b>\n"
            "Atau kirim foto sebagai bukti.\n\n"
            "Ketik ❌ Batalkan untuk membatalkan",
            parse_mode="HTML",
            reply_markup=cancel_keyboard()
        )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photo untuk bukti"""
    user_id = update.message.from_user.id
    user_state = get_user_state(user_id)
    
    mode = user_state.get("mode")
    step = user_state.get("step")
    
    if mode == "pengaduan" and step == "bukti":
        file_id = update.message.photo[-1].file_id
        file_obj = await context.bot.get_file(file_id)
        user_state["data"]["bukti"] = file_obj.file_path
        
        await update.message.reply_text(
            "📸 <b>Foto bukti diterima!</b>\n\n"
            "Sedang menyimpan pengaduan...",
            parse_mode="HTML"
        )
        
        await selesaikan_pengaduan(update, context, user_state)
    else:
        await update.message.reply_text(
            "❌ Foto tidak diperlukan saat ini.",
            reply_markup=main_menu_keyboard()
        )

async def selesaikan_pengaduan(update: Update, context: ContextTypes.DEFAULT_TYPE, user_state: dict):
    """Selesaikan pengaduan dan simpan ke Google Sheets"""
    user_id = update.message.from_user.id
    data = user_state["data"]
    timestamp = get_jakarta_time()
    website_code = data["website_code"]
    ticket_id = generate_ticket_number(website_code)
    
    logger.info(f"Processing new complaint from user {user_id}: {ticket_id}")
    
    try:
        # Save to Google Sheets dengan kolom tambahan
        worksheet.append_row([
            timestamp,                           # Timestamp (DD/MM/YYYY HH:MM:SS)
            ticket_id,                           # Ticket ID (CODE-DDMMYYYY-NOMOR)
            data["website_name"],                # Nama Website
            data["nama"],                        # Nama
            data["username_website"],            # Username Website  
            data["keluhan"],                     # Keluhan
            data.get("bukti", "Tidak ada"),      # Bukti
            data["username_tg"],                 # Username_TG
            data["user_id"],                     # User_ID
            "Sedang diproses"                    # Status
        ])
        logger.info(f"✅ Data saved to Google Sheets: {ticket_id}")
    except Exception as e:
        logger.error(f"❌ Failed to save to Google Sheets: {e}")
        await update.message.reply_text(
            "❌ Maaf, terjadi gangguan sistem. Silakan coba lagi nanti.",
            reply_markup=main_menu_keyboard()
        )
        clear_user_state(user_id)
        return

    website_name = data["website_name"]
    
    await update.message.reply_text(
        f"🎉 <b>Pengaduan Berhasil Dikirim!</b>\n\n"
        f"✅ <b>Terima kasih, {escape_html(data['nama'])}!</b>\n\n"
        f"<b>📋 Detail Pengaduan:</b>\n"
        f"• <b>Website:</b> {website_name}\n"
        f"• <b>Nomor Tiket:</b> <code>{ticket_id}</code>\n"
        f"• <b>Status:</b> Sedang diproses\n"
        f"• <b>Waktu:</b> {timestamp}\n\n"
        f"<b>💡 Simpan nomor tiket ini!</b>\n"
        f"Gunakan menu '🔍 Cek Status' untuk memantau perkembangan pengaduan.\n\n"
        f"<b>🔄 Ingin buat pengaduan lagi?</b> Klik '📝 Buat Pengaduan'",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard()
    )

    # Notify admin dengan HTML parsing yang lebih aman
    await kirim_notifikasi_admin_with_retry(context, data, ticket_id, timestamp, user_id)
    
    clear_user_state(user_id)

async def kirim_notifikasi_admin_with_retry(context, data, ticket_id, timestamp, user_id, retry_count=3):
    """Kirim notifikasi ke admin dengan retry mechanism"""
    for attempt in range(retry_count):
        try:
            success = await kirim_notifikasi_admin(context, data, ticket_id, timestamp)
            if success:
                logger.info(f"✅ Notifications sent successfully for ticket {ticket_id}")
                return
            else:
                logger.warning(f"⚠️ Some notifications failed for ticket {ticket_id}, attempt {attempt + 1}")
        except Exception as e:
            logger.error(f"❌ Error sending notifications for ticket {ticket_id}, attempt {attempt + 1}: {e}")
        
        if attempt < retry_count - 1:
            await asyncio.sleep(2)
    
    logger.error(f"❌ All notification attempts failed for ticket {ticket_id}")

async def kirim_notifikasi_admin(context, data, ticket_id, timestamp):
    """Send notification to admin - FIXED VERSION WITH HTML"""
    try:
        # Escape data untuk HTML
        nama_escaped = escape_html(data.get("nama", ""))
        username_website_escaped = escape_html(data.get("username_website", ""))
        keluhan_escaped = escape_html(data.get("keluhan", ""))
        username_tg_escaped = escape_html(data.get("username_tg", ""))
        user_id_escaped = escape_html(data.get("user_id", ""))
        website_name_escaped = escape_html(data.get("website_name", ""))
        
        bukti_text = data.get("bukti", "Tidak ada")
        if bukti_text != "Tidak ada" and bukti_text.startswith("http"):
            bukti_display = f'<a href="{bukti_text}">📎 Lihat Bukti</a>'
        else:
            bukti_display = escape_html(bukti_text)
        
        # Buat message dengan HTML parsing yang lebih aman
        message = (
            f"🚨 <b>PENGADUAN BARU DITERIMA</b> 🚨\n\n"
            f"🎫 <b>Ticket ID:</b> <code>{ticket_id}</code>\n"
            f"🌐 <b>Website:</b> {website_name_escaped}\n"
            f"⏰ <b>Waktu:</b> {timestamp} (WIB)\n\n"
            f"<b>📋 Data Pelapor:</b>\n"
            f"• <b>Nama:</b> {nama_escaped}\n"
            f"• <b>Username {website_name_escaped}:</b> {username_website_escaped}\n"
            f"• <b>Telegram:</b> @{username_tg_escaped}\n"
            f"• <b>User ID:</b> <code>{user_id_escaped}</code>\n\n"
            f"<b>📝 Keluhan:</b>\n{keluhan_escaped}\n\n"
            f"<b>📎 Bukti:</b> {bukti_display}\n\n"
            f"⚠️ <b>Segera tindak lanjuti pengaduan ini!</b>"
        )
        
        success_count = 0
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=message,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
                success_count += 1
                logger.info(f"✅ Notification sent to admin {admin_id}")
            except Exception as e:
                logger.error(f"❌ Failed to send to admin {admin_id}: {e}")
        
        logger.info(f"📊 Notifications sent to {success_count}/{len(ADMIN_IDS)} admins")
        return success_count > 0
        
    except Exception as e:
        logger.error(f"❌ Error in kirim_notifikasi_admin: {e}")
        return False

async def proses_cek_status(update: Update, context: ContextTypes.DEFAULT_TYPE, ticket_id: str, user_state: dict):
    """Proses cek status tiket - DIPERBAIKI UNTUK WEBSITE"""
    current_user_id = update.message.from_user.id
    
    try:
        all_data = worksheet.get_all_records()
        found = False
        user_owns_ticket = False
        ticket_data = None
        
        for row in all_data:
            if row.get('Ticket ID') == ticket_id:
                found = True
                ticket_user_id = row.get('User_ID')
                if str(ticket_user_id) == str(current_user_id):
                    user_owns_ticket = True
                    ticket_data = row
                break
        
        if found and user_owns_ticket and ticket_data:
            status = ticket_data.get('Status', 'Tidak diketahui')
            status_emoji = {
                'Sedang diproses': '🟡',
                'Selesai': '✅',
                'Ditolak': '❌',
                'Menunggu konfirmasi': '🟠'
            }.get(status, '⚪')
            
            nama_escaped = escape_html(ticket_data.get('Nama', 'Tidak ada'))
            username_escaped = escape_html(ticket_data.get('Username Website', 'Tidak ada'))
            keluhan_escaped = escape_html(ticket_data.get('Keluhan', 'Tidak ada'))
            timestamp_escaped = escape_html(ticket_data.get('Timestamp', 'Tidak ada'))
            website_escaped = escape_html(ticket_data.get('Nama Website', 'Tidak ada'))
            
            status_message = (
                f"📋 <b>STATUS PENGADUAN</b>\n\n"
                f"{status_emoji} <b>Status:</b> <b>{status}</b>\n"
                f"🎫 <b>Ticket ID:</b> <code>{ticket_id}</code>\n"
                f"🌐 <b>Website:</b> {website_escaped}\n"
                f"👤 <b>Nama:</b> {nama_escaped}\n"
                f"🆔 <b>Username:</b> {username_escaped}\n"
                f"💬 <b>Keluhan:</b> {keluhan_escaped}\n"
                f"⏰ <b>Waktu:</b> {timestamp_escaped}\n\n"
                f"Terima kasih! 🙏"
            )
            
            await update.message.reply_text(
                status_message,
                parse_mode="HTML",
                reply_markup=main_menu_keyboard()
            )
        else:
            await update.message.reply_text(
                "❌ <b>Tiket tidak ditemukan.</b>\n\n"
                "Pastikan:\n"
                "• Nomor tiket benar\n"
                "• Tidak ada typo\n\n"
                "Klik '🔍 Cek Status' untuk mencoba lagi.",
                parse_mode="HTML",
                reply_markup=main_menu_keyboard()
            )
            
    except Exception as e:
        logger.error(f"Error checking status: {e}")
        await update.message.reply_text(
            "❌ Terjadi error. Silakan coba lagi.",
            reply_markup=main_menu_keyboard()
        )
    
    clear_user_state(current_user_id)

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tampilkan menu utama"""
    await update.message.reply_text(
        "🤖 <b>Layanan Pengaduan</b>\n\n"
        "Kami siap melayani pengaduan Anda.\n\n"
        "Silakan pilih menu:",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard()
    )

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel command"""
    user_id = update.message.from_user.id
    clear_user_state(user_id)
    
    await update.message.reply_text(
        "❌ <b>Semua proses dibatalkan</b>\n\n"
        "Kembali ke menu utama.",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard()
    )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle error"""
    logger.error(f"Error: {context.error}")
    if update and update.message:
        await update.message.reply_text(
            "❌ Terjadi error, silakan coba lagi.",
            reply_markup=main_menu_keyboard()
        )

def main():
    """Main function"""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not found!")
        return
    
    if not GOOGLE_CREDENTIALS_JSON:
        logger.error("GOOGLE_CREDENTIALS not found!")
        return

    if not worksheet:
        logger.error("Google Sheets not connected!")
        return

    try:
        application = Application.builder().token(BOT_TOKEN).build()
        
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("cancel", cancel_command))
        application.add_handler(CommandHandler("help", handle_bantuan))
        application.add_handler(CommandHandler("menu", handle_menu))
        
        application.add_handler(MessageHandler(filters.Text(["📝 Buat Pengaduan"]), handle_buat_pengaduan))
        application.add_handler(MessageHandler(filters.Text(["🔍 Cek Status"]), handle_cek_status))
        application.add_handler(MessageHandler(filters.Text(["ℹ️ Bantuan"]), handle_bantuan))
        application.add_handler(MessageHandler(filters.Text(["MENU"]), handle_menu))
        application.add_handler(MessageHandler(filters.Text(["❌ Batalkan"]), handle_cancel))
        
        application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        application.add_error_handler(error_handler)
        
        logger.info("✅ Complaint Bot starting...")
        application.run_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES
        )
        
    except Exception as e:
        logger.error(f"Fatal error: {e}")

if __name__ == '__main__':
    main()