import os
import re
import json
import base64
import gspread
import logging
import pytz
import asyncio
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes,
    filters, JobQueue
)

# =========================================================
# LOGGING
# =========================================================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# =========================================================
# ENV CONFIG (Railway)
# =========================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
GOOGLE_SHEET_NAME = os.environ.get("GOOGLE_SHEET_NAME", "Pengaduan JokerBola")
GOOGLE_CREDENTIALS_B64 = os.environ.get("GOOGLE_CREDENTIALS_B64", "")
ADMIN_IDS = [
    int(x.strip()) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip().isdigit()
] or [5704050846, 8388423519]  # default fallback

# Timezone Jakarta (pytz)
JAKARTA_TZ = pytz.timezone("Asia/Jakarta")

# =========================================================
# GOOGLE SHEETS SETUP (via ENV base64)
# =========================================================
worksheet = None
try:
    if not GOOGLE_CREDENTIALS_B64:
        raise RuntimeError("Missing env GOOGLE_CREDENTIALS_B64")

    creds_dict = json.loads(base64.b64decode(GOOGLE_CREDENTIALS_B64).decode("utf-8"))
    gc = gspread.service_account_from_dict(creds_dict)
    sh = gc.open(GOOGLE_SHEET_NAME)
    worksheet = sh.sheet1
    logger.info("✅ Google Sheets connected successfully")
except Exception as e:
    logger.error(f"❌ Google Sheets connection failed: {e}")
    worksheet = None

# =========================================================
# HELPERS
# =========================================================
def get_jakarta_time() -> str:
    """Waktu Jakarta sekarang (string)."""
    return datetime.now(JAKARTA_TZ).strftime("%Y-%m-%d %H:%M:%S")

def escape_html(text):
    """Escape karakter HTML biar aman di Telegram."""
    if not text:
        return ""
    escape_chars = {
        "&": "&amp;", "<": "&lt;", ">": "&gt;",
        '"': "&quot;", "'": "&#39;"
    }
    return "".join(escape_chars.get(ch, ch) for ch in str(text))

def norm_key(k: str) -> str:
    return str(k).strip().lower().replace(" ", "_")

def pick(row_map: dict, *aliases):
    for a in aliases:
        if a in row_map and row_map[a] not in [None, ""]:
            return row_map[a]
    return ""

def read_sheet_all_values():
    """Ambil seluruh sel; log ukuran untuk debug."""
    vals = worksheet.get_all_values()
    logger.info(f"📄 Sheet rows loaded: {len(vals)}")
    return vals

def generate_ticket_number() -> str:
    """
    Generate nomor tiket unik per hari dengan scan SELURUH SEL di sheet.
    Tidak bergantung header/kolom. Aman walau struktur sheet berubah.
    """
    try:
        today = datetime.now(JAKARTA_TZ).strftime("%Y%m%d")
        pattern = re.compile(rf"^JB-{today}-(\d+)$")

        all_values = read_sheet_all_values()
        max_suffix = 0

        for row in all_values:
            for cell in row:
                val = str(cell).strip()
                m = pattern.match(val)
                if m:
                    try:
                        max_suffix = max(max_suffix, int(m.group(1)))
                    except ValueError:
                        pass

        next_num = max_suffix + 1
        return f"JB-{today}-{next_num:03d}"

    except Exception as e:
        logger.error(f"Error generating ticket: {e}")
        # Fallback aman pakai HHMMSS supaya tetap unik
        return f"JB-{datetime.now(JAKARTA_TZ).strftime('%Y%m%d')}-{datetime.now(JAKARTA_TZ).strftime('%H%M%S')}"

def ensure_unique_ticket_id(ticket_id: str) -> str:
    """Jika (karena race) tiket sudah ada, generate ulang sampai unik."""
    all_values = read_sheet_all_values()
    used = set()
    for row in all_values:
        for cell in row:
            used.add(str(cell).strip())
    if ticket_id not in used:
        return ticket_id
    logger.warning("🔁 Ticket ID collision detected, regenerating...")
    return generate_ticket_number()

def get_header_map():
    """Kembalikan dict {normalized_header: index} dari baris pertama sheet."""
    all_values = read_sheet_all_values()
    if not all_values:
        return {}, [], []
    headers = all_values[0]
    header_map = {norm_key(h): i for i, h in enumerate(headers)}
    return header_map, headers, all_values

# =========================================================
# UI KEYBOARDS
# =========================================================
def main_menu_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["📝 Buat Pengaduan", "🔍 Cek Status"],
            ["ℹ️ Bantuan"]
        ],
        resize_keyboard=True
    )

def cancel_keyboard():
    return ReplyKeyboardMarkup([["❌ Batalkan"]], resize_keyboard=True)

# =========================================================
# STATE
# =========================================================
user_states = {}

def get_user_state(user_id):
    if user_id not in user_states:
        user_states[user_id] = {"mode": None, "step": None, "data": {}}
    return user_states[user_id]

def clear_user_state(user_id):
    if user_id in user_states:
        del user_states[user_id]

# =========================================================
# HANDLERS
# =========================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    clear_user_state(user_id)

    await update.message.reply_text(
        "🤖 <b>Selamat datang di Layanan Pengaduan JokerBola</b>\n\nSilakan pilih menu di bawah:",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard()
    )

async def handle_buat_pengaduan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    clear_user_state(user_id)
    user_state = get_user_state(user_id)
    user_state["mode"] = "pengaduan"
    user_state["step"] = "nama"

    await update.message.reply_text(
        "📝 <b>Membuat Pengaduan Baru</b>\n\nSilakan kirim <b>Nama Lengkap</b> Anda:\n\nKetik ❌ Batalkan untuk membatalkan",
        parse_mode="HTML",
        reply_markup=cancel_keyboard()
    )

async def handle_cek_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    clear_user_state(user_id)
    user_state = get_user_state(user_id)
    user_state["mode"] = "cek_status"
    user_state["step"] = "input_tiket"

    await update.message.reply_text(
        "🔍 <b>Cek Status Tiket</b>\n\nSilakan kirim <b>Nomor Tiket</b> Anda:\nContoh: <code>JB-20241219-001</code>\n\nKetik ❌ Batalkan untuk membatalkan",
        parse_mode="HTML",
        reply_markup=cancel_keyboard()
    )

async def handle_bantuan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ <b>Bantuan Penggunaan</b>\n\n"
        "📝 <b>Cara Buat Pengaduan:</b>\n"
        "1. Klik '📝 Buat Pengaduan'\n"
        "2. Isi nama lengkap\n"
        "3. Isi username JokerBola\n"
        "4. Jelaskan keluhan\n"
        "5. Kirim bukti (opsional)\n\n"
        "🔍 <b>Cek Status:</b>\n"
        "1. Klik '🔍 Cek Status'\n"
        "2. Masukkan nomor tiket\n\n"
        "💡 <b>Tips:</b>\n"
        "• Simpan nomor tiket dengan baik\n"
        "• Bisa buat pengaduan berkali-kali\n"
        "• Setiap pengaduan punya nomor unik\n\n"
        "❌ <b>Batalkan proses kapan saja</b> dengan klik '❌ Batalkan'",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard()
    )

async def handle_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    clear_user_state(user_id)

    await update.message.reply_text(
        "❌ <b>Proses dibatalkan</b>\n\nKembali ke menu utama.",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard()
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text.strip()
    user_id = update.message.from_user.id

    user_state = get_user_state(user_id)
    logger.info(f"User {user_id} message: {user_message}, state: {user_state}")

    if user_message == "❌ Batalkan":
        await handle_cancel(update, context)
        return

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
    step = user_state.get("step", "")

    if step == "nama":
        user_state["data"]["nama"] = user_message
        user_state["data"]["user_id"] = update.message.from_user.id
        user_state["data"]["username_tg"] = update.message.from_user.username or "-"
        user_state["step"] = "username_jb"

        await update.message.reply_text(
            "🆔 <b>Masukkan Username / ID JokerBola Anda:</b>\n\nKetik ❌ Batalkan untuk membatalkan",
            parse_mode="HTML",
            reply_markup=cancel_keyboard()
        )

    elif step == "username_jb":
        user_state["data"]["username_jb"] = user_message
        user_state["step"] = "keluhan"

        await update.message.reply_text(
            "📋 <b>Jelaskan keluhan Anda:</b>\n\nKetik ❌ Batalkan untuk membatalkan",
            parse_mode="HTML",
            reply_markup=cancel_keyboard()
        )

    elif step == "keluhan":
        user_state["data"]["keluhan"] = user_message
        user_state["step"] = "bukti"

        await update.message.reply_text(
            "📸 <b>Kirim foto bukti (opsional)</b>\n\nKirim foto sekarang atau ketik 'lanjut' untuk melanjutkan tanpa bukti.\n\nKetik ❌ Batalkan untuk membatalkan",
            parse_mode="HTML",
            reply_markup=cancel_keyboard()
        )

    elif step == "bukti" and user_message.lower() == "lanjut":
        user_state["data"]["bukti"] = "Tidak ada"
        await selesaikan_pengaduan(update, context, user_state)

    elif step == "bukti":
        await update.message.reply_text(
            "❌ <b>Perintah tidak dikenali</b>\n\nUntuk melanjutkan tanpa bukti, ketik: <b>lanjut</b>\nAtau kirim foto sebagai bukti.\n\nKetik ❌ Batalkan untuk membatalkan",
            parse_mode="HTML",
            reply_markup=cancel_keyboard()
        )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_state = get_user_state(user_id)

    mode = user_state.get("mode")
    step = user_state.get("step")

    if mode == "pengaduan" and step == "bukti":
        file_id = update.message.photo[-1].file_id
        file_obj = await context.bot.get_file(file_id)
        user_state["data"]["bukti"] = file_obj.file_path

        await update.message.reply_text("Sedang menyimpan pengaduan...", parse_mode="HTML")
        await selesaikan_pengaduan(update, context, user_state)
    else:
        await update.message.reply_text("❌ Foto tidak diperlukan saat ini.", reply_markup=main_menu_keyboard())

async def selesaikan_pengaduan(update: Update, context: ContextTypes.DEFAULT_TYPE, user_state: dict):
    user_id = update.message.from_user.id
    data = user_state["data"]
    timestamp = get_jakarta_time()

    # Buat ticket id yang dipastikan unik
    candidate = generate_ticket_number()
    ticket_id = ensure_unique_ticket_id(candidate)

    logger.info(f"Processing new complaint from user {user_id}: {ticket_id}")

    try:
        worksheet.append_row([
            timestamp,            # 0
            ticket_id,            # 1
            data["nama"],         # 2
            data["username_jb"],  # 3
            data["keluhan"],      # 4
            data.get("bukti", "Tidak ada"), # 5
            data["username_tg"],  # 6
            data["user_id"],      # 7
            "Sedang diproses"     # 8
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

    await update.message.reply_text(
        f"🎉 <b>Pengaduan Berhasil Dikirim!</b>\n\n"
        f"✅ <b>Terima kasih, {escape_html(data['nama'])}!</b>\n\n"
        f"<b>📋 Detail Pengaduan:</b>\n"
        f"• <b>Nomor Tiket:</b> <code>{ticket_id}</code>\n"
        f"• <b>Status:</b> Sedang diproses\n"
        f"• <b>Waktu:</b> {timestamp}\n\n"
        f"<b>💡 Simpan nomor tiket ini!</b>\n"
        f"Gunakan menu '🔍 Cek Status' untuk memantau perkembangan pengaduan.\n\n"
        f"<b>🔄 Ingin buat pengaduan lagi?</b> Klik '📝 Buat Pengaduan'",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard()
    )

    await kirim_notifikasi_admin_with_retry(context, data, ticket_id, timestamp, user_id)
    clear_user_state(user_id)

async def kirim_notifikasi_admin_with_retry(context, data, ticket_id, timestamp, user_id, retry_count=3):
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
    try:
        nama_escaped = escape_html(data.get("nama", ""))
        username_jb_escaped = escape_html(data.get("username_jb", ""))
        keluhan_escaped = escape_html(data.get("keluhan", ""))
        username_tg_escaped = escape_html(data.get("username_tg", ""))
        user_id_escaped = escape_html(data.get("user_id", ""))

        bukti_text = data.get("bukti", "Tidak ada")
        if bukti_text != "Tidak ada" and str(bukti_text).startswith("http"):
            bukti_display = f'<a href="{bukti_text}">📎 Lihat Bukti</a>'
        else:
            bukti_display = escape_html(bukti_text)

        message = (
            f"🚨 <b>PENGADUAN BARU DITERIMA</b> 🚨\n\n"
            f"🎫 <b>Ticket ID:</b> <code>{ticket_id}</code>\n"
            f"⏰ <b>Waktu:</b> {timestamp} (WIB)\n\n"
            f"<b>📋 Data Pelapor:</b>\n"
            f"• <b>Nama:</b> {nama_escaped}\n"
            f"• <b>Username JB:</b> {username_jb_escaped}\n"
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
    """
    Cek status tiket:
    - Normalisasi header dan ambil kolom 'Ticket ID' kalau ada.
    - Jika tidak ada, fallback: cari tiket di seluruh kolom baris.
    - Verifikasi kepemilikan bisa diaktifkan dengan STRICT_OWNERSHIP = True.
    """
    current_user_id = str(update.message.from_user.id).strip()
    input_ticket = str(ticket_id).strip()
    STRICT_OWNERSHIP = False  # ubah True jika mau hanya pemilik tiket yang boleh cek

    if not input_ticket.startswith("JB-"):
        await update.message.reply_text(
            "❌ <b>Format tiket tidak valid!</b>\n\n"
            "Format: <code>JB-TANGGAL-NOMOR</code>\n"
            "Contoh: <code>JB-20241219-001</code>\n\n"
            "Silakan masukkan kembali:",
            parse_mode="HTML",
            reply_markup=cancel_keyboard()
        )
        return

    try:
        header_map, headers, all_values = get_header_map()
        if not all_values or len(all_values) <= 1:
            await update.message.reply_text(
                "❌ <b>Tiket tidak ditemukan.</b>\n\n"
                "Klik '🔍 Cek Status' untuk mencoba lagi.",
                parse_mode="HTML",
                reply_markup=main_menu_keyboard()
            )
            return

        # Cari index kolom Ticket ID jika ada
        ticket_col_idx = None
        for key, idx in header_map.items():
            if key in ("ticket_id", "ticketid", "tiket_id", "tiketid"):
                ticket_col_idx = idx
                break

        found_row = None

        # Scan baris demi baris (skip header)
        for r_idx in range(1, len(all_values)):
            row = all_values[r_idx]
            if ticket_col_idx is not None and ticket_col_idx < len(row):
                if str(row[ticket_col_idx]).strip() == input_ticket:
                    found_row = row
                    break
            else:
                # Fallback: cari di seluruh kolom baris
                for cell in row:
                    if str(cell).strip() == input_ticket:
                        found_row = row
                        break
                if found_row:
                    break

        if not found_row:
            await update.message.reply_text(
                "❌ <b>Tiket tidak ditemukan.</b>\n\n"
                "Pastikan:\n"
                "• Nomor tiket benar\n"
                "• Format sesuai: JB-TANGGAL-NOMOR\n"
                "• Tidak ada typo\n\n"
                "Klik '🔍 Cek Status' untuk mencoba lagi.",
                parse_mode="HTML",
                reply_markup=main_menu_keyboard()
            )
            return

        # Bangun map baris berdasar header (kalau header kurang, map seadanya)
        row_map = {}
        for i, h in enumerate(headers):
            if i < len(found_row):
                row_map[norm_key(h)] = found_row[i]

        # Ambil user id beberapa alias / fallback ke kolom 8 (index 7) sesuai append_row kita
        row_user_id = str(pick(row_map, "user_id", "userid", "user__id", "id_user")).strip()
        if not row_user_id and len(found_row) >= 8:
            row_user_id = str(found_row[7]).strip()

        # Verifikasi kepemilikan jika strict
        ownership_ok = (row_user_id == current_user_id) or (str(update.message.from_user.id) in map(str, ADMIN_IDS))
        if STRICT_OWNERSHIP and not ownership_ok:
            await update.message.reply_text(
                "🚫 <b>Tiket ditemukan tapi bukan milik akun Telegram ini.</b>\n"
                "Silakan gunakan akun yang sama saat membuat pengaduan.",
                parse_mode="HTML",
                reply_markup=main_menu_keyboard()
            )
            return

        # Ambil data lain
        status = pick(row_map, "status") or (found_row[8] if len(found_row) > 8 else "Tidak diketahui")
        status_norm = norm_key(str(status))
        status_emoji = {
            "sedang_diproses": "🟡",
            "selesai": "✅",
            "ditolak": "❌",
            "menunggu_konfirmasi": "🟠"
        }.get(status_norm, "⚪")

        nama = escape_html(pick(row_map, "nama", "name") or (found_row[2] if len(found_row) > 2 else ""))
        username_jb = escape_html(pick(row_map, "username_jb", "username", "id_jb") or (found_row[3] if len(found_row) > 3 else ""))
        keluhan = escape_html(pick(row_map, "keluhan", "aduan", "complaint") or (found_row[4] if len(found_row) > 4 else ""))
        timestamp_val = escape_html(pick(row_map, "timestamp", "waktu", "created_at") or (found_row[0] if len(found_row) > 0 else ""))

        status_message = (
            f"📋 <b>STATUS PENGADUAN</b>\n\n"
            f"{status_emoji} <b>Status:</b> <b>{escape_html(str(status))}</b>\n"
            f"🎫 <b>Ticket ID:</b> <code>{input_ticket}</code>\n"
            f"👤 <b>Nama:</b> {nama or 'Tidak ada'}\n"
            f"🆔 <b>Username:</b> {username_jb or 'Tidak ada'}\n"
            f"💬 <b>Keluhan:</b> {keluhan or 'Tidak ada'}\n"
            f"⏰ <b>Waktu:</b> {timestamp_val or 'Tidak ada'}\n"
        )

        await update.message.reply_text(
            status_message,
            parse_mode="HTML",
            reply_markup=main_menu_keyboard()
        )

    except Exception as e:
        logger.error(f"Error checking status: {e}")
        await update.message.reply_text(
            "❌ Terjadi error. Silakan coba lagi.",
            reply_markup=main_menu_keyboard()
        )

    clear_user_state(update.message.from_user.id)

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 <b>Layanan Pengaduan JokerBola</b>\n\nSilakan pilih menu:",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard()
    )

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    clear_user_state(user_id)

    await update.message.reply_text(
        "❌ <b>Semua proses dibatalkan</b>\n\nKembali ke menu utama.",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard()
    )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")
    if update and update.message:
        await update.message.reply_text(
            "❌ Terjadi error, silakan coba lagi.",
            reply_markup=main_menu_keyboard()
        )

# =========================================================
# MAIN
# =========================================================
def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not found!")
        return

    if not worksheet:
        logger.error("Google Sheets not connected!")
        return

    try:
        # JobQueue tanpa arg timezone (aman lintas versi PTB)
        job_queue = JobQueue()

        application = (
            Application.builder()
            .token(BOT_TOKEN)
            .job_queue(job_queue)
            .build()
        )

        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("cancel", cancel_command))
        application.add_handler(CommandHandler("help", handle_bantuan))

        application.add_handler(MessageHandler(filters.Text(["📝 Buat Pengaduan"]), handle_buat_pengaduan))
        application.add_handler(MessageHandler(filters.Text(["🔍 Cek Status"]), handle_cek_status))
        application.add_handler(MessageHandler(filters.Text(["ℹ️ Bantuan"]), handle_bantuan))
        application.add_handler(MessageHandler(filters.Text(["❌ Batalkan"]), handle_cancel))

        application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        application.add_error_handler(error_handler)

        logger.info("✅ Bot starting dengan HTML parsing...")
        application.run_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES
        )

    except Exception as e:
        logger.error(f"Fatal error: {e}")

if __name__ == "__main__":
    main()
