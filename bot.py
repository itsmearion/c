import logging
import csv
import json
import os
from io import StringIO, BytesIO
import asyncio
from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.exceptions import TelegramAPIError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, timedelta

# Konfigurasi
API_TOKEN = '7250733161:AAGAREybiUFzyOFiJMjjP0m64N60ohPMLuc'
DATA_FILE = 'absensi_data.json'
LOG_FILE = 'bot.log'

# Setup logging dengan rotasi file
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, maxBytes=10485760, backupCount=5),  # 10MB per file, max 5 files
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# State dan data
absen_sessions = {}
auto_absen_chats = set()
user_statistics = {}  # Untuk melacak statistik kehadiran per user

# Fungsi untuk menyimpan data ke file
async def save_data():
    data = {
        'auto_absen_chats': list(auto_absen_chats),
        'user_statistics': user_statistics
    }
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("Data berhasil disimpan")
    except Exception as e:
        logger.error(f"Gagal menyimpan data: {e}")

# Fungsi untuk memuat data dari file
async def load_data():
    global auto_absen_chats, user_statistics
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                auto_absen_chats = set(data.get('auto_absen_chats', []))
                user_statistics = data.get('user_statistics', {})
            logger.info("Data berhasil dimuat")
    except Exception as e:
        logger.error(f"Gagal memuat data: {e}")

# Tombol absen
def get_absen_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton('✅ Hadir', callback_data='hadir'),
        InlineKeyboardButton('🏠 WFH', callback_data='wfh'),
        InlineKeyboardButton('🤒 Sakit', callback_data='sakit'),
        InlineKeyboardButton('🏝️ Cuti', callback_data='cuti')
    )
    return keyboard

# Menu utama
def get_main_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(
        KeyboardButton('/startabsen'),
        KeyboardButton('/rekap'),
        KeyboardButton('/export'),
        KeyboardButton('/status')
    )
    return keyboard

# Cek apakah user adalah admin
async def is_admin(user_id, chat_id):
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.is_chat_admin() or member.status == 'creator'
    except TelegramAPIError as e:
        logger.error(f"Error saat memeriksa admin: {e}")
        return False

# Handler untuk perintah /start
@dp.message_handler(commands=['start'])
async def start_cmd(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Update user statistics jika belum ada
    if str(user_id) not in user_statistics:
        user_statistics[str(user_id)] = {
            'total_absen': 0,
            'hadir': 0,
            'wfh': 0,
            'sakit': 0,
            'cuti': 0,
            'last_active': datetime.now().strftime('%Y-%m-%d')
        }
        await save_data()
    
    welcome_text = """
🤖 *Bot Absensi v2.0*

Perintah yang tersedia:
• /startabsen [nama sesi] - Mulai absensi baru
• /rekap - Lihat rekap absensi saat ini
• /export - Export rekap ke file CSV
• /resetabsen - Reset sesi absensi saat ini
• /status - Lihat statistik kehadiran Anda
• /help - Bantuan lengkap

*Admin Only:*
• /enableauto - Aktifkan absen otomatis tiap 00:00
• /disableauto - Matikan absen otomatis
• /broadcast [pesan] - Kirim pengumuman ke semua peserta
    """
    
    await message.reply(welcome_text, parse_mode='Markdown', reply_markup=get_main_keyboard())
    logger.info(f"User {message.from_user.full_name} ({user_id}) memulai bot di chat {chat_id}")

# Handler untuk perintah /help
@dp.message_handler(commands=['help'])
async def help_cmd(message: types.Message):
    help_text = """
📚 *Bantuan Bot Absensi*

*Perintah Dasar:*
• `/startabsen [nama]` - Mulai sesi absensi baru (default: menggunakan tanggal hari ini)
• `/rekap` - Menampilkan daftar peserta yang hadir dalam sesi saat ini
• `/export` - Mengunduh file CSV berisi daftar kehadiran
• `/resetabsen` - Menghapus sesi absensi saat ini (Admin)
• `/status` - Melihat statistik kehadiran pribadi Anda

*Perintah Admin:*
• `/enableauto` - Mengaktifkan absensi otomatis setiap hari pukul 00:00
• `/disableauto` - Menonaktifkan absensi otomatis
• `/broadcast [pesan]` - Mengirim pengumuman ke semua peserta yang pernah absen

*Status Kehadiran:*
• ✅ Hadir - Hadir di lokasi kerja
• 🏠 WFH - Work From Home
• 🤒 Sakit - Tidak hadir karena sakit
• 🏝️ Cuti - Sedang cuti

*Tips:*
- Pastikan Anda telah absen setiap hari kerja
- Admin dapat menggunakan fitur export untuk laporan
- Data absensi dapat direset setiap awal bulan
    """
    
    await message.reply(help_text, parse_mode='Markdown')

# Handler untuk memulai absensi
@dp.message_handler(commands=['startabsen'])
async def start_absen(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    args = message.get_args()
    
    # Cek apakah grup atau private chat
    if message.chat.type not in ['group', 'supergroup']:
        await message.reply("⚠️ Fitur ini hanya bisa digunakan di grup.")
        return
    
    # Cek apakah admin (di grup)
    if not await is_admin(user_id, chat_id):
        await message.reply("❌ Hanya admin yang bisa memulai absensi.")
        return
    
    # Nama sesi
    sesi = args if args else f"Absensi {datetime.now().strftime('%d %B %Y')}"
    
    # Simpan sesi baru
    absen_sessions[chat_id] = {
        'sesi': sesi,
        'tanggal': datetime.now().strftime('%Y-%m-%d'),
        'created_by': user_id,
        'users': [],
        'start_time': datetime.now().strftime('%H:%M:%S')
    }
    
    logger.info(f"Absen dimulai di chat {chat_id} oleh {message.from_user.full_name} ({user_id})")
    
    # Pesan absensi dengan informasi lebih detail
    absen_msg = f"""
📝 *{sesi}*

📅 Tanggal: {datetime.now().strftime('%d %B %Y')}
⏰ Waktu Mulai: {datetime.now().strftime('%H:%M:%S')}
👤 Dimulai oleh: {message.from_user.full_name}

Silakan tekan salah satu tombol di bawah untuk absen:
✅ *Hadir* - Hadir di lokasi kerja
🏠 *WFH* - Work From Home
🤒 *Sakit* - Tidak hadir karena sakit
🏝️ *Cuti* - Sedang cuti
    """
    
    await message.reply(absen_msg, reply_markup=get_absen_keyboard(), parse_mode='Markdown')

# Handler untuk callback dari tombol absen
@dp.callback_query_handler(lambda c: c.data in ['hadir', 'wfh', 'sakit', 'cuti'])
async def process_absen(callback_query: types.CallbackQuery):
    user = callback_query.from_user
    user_id = user.id
    chat_id = callback_query.message.chat.id
    status = callback_query.data
    
    if chat_id not in absen_sessions:
        await callback_query.answer("Belum ada sesi absensi! Gunakan /startabsen dulu.", show_alert=True)
        return
    
    session = absen_sessions[chat_id]
    existing_user = next((u for u in session['users'] if u['id'] == user_id), None)
    
    status_emoji = {
        'hadir': '✅',
        'wfh': '🏠',
        'sakit': '🤒',
        'cuti': '🏝️'
    }
    
    status_text = {
        'hadir': 'Hadir',
        'wfh': 'WFH',
        'sakit': 'Sakit',
        'cuti': 'Cuti'
    }
    
    timestamp = datetime.now().strftime('%H:%M:%S')
    
    if existing_user:
        # User sudah absen, update status
        old_status = existing_user['status']
        existing_user['status'] = status
        existing_user['time'] = timestamp
        
        # Update statistik: kurangi status lama, tambah status baru
        str_user_id = str(user_id)
        if str_user_id in user_statistics:
            if old_status in user_statistics[str_user_id]:
                user_statistics[str_user_id][old_status] -= 1
            user_statistics[str_user_id][status] = user_statistics[str_user_id].get(status, 0) + 1
        
        await callback_query.answer(f"Status diubah menjadi {status_text[status]}! {status_emoji[status]}", show_alert=True)
        logger.info(f"{user.full_name} ({user_id}) mengubah status dari {old_status} ke {status} di chat {chat_id}")
    else:
        # User belum absen, tambahkan baru
        session['users'].append({
            'id': user_id,
            'name': user.full_name,
            'username': user.username,
            'status': status,
            'time': timestamp
        })
        
        # Update statistik
        str_user_id = str(user_id)
        if str_user_id not in user_statistics:
            user_statistics[str_user_id] = {
                'total_absen': 0,
                'hadir': 0,
                'wfh': 0,
                'sakit': 0,
                'cuti': 0,
                'last_active': datetime.now().strftime('%Y-%m-%d')
            }
        
        user_statistics[str_user_id]['total_absen'] += 1
        user_statistics[str_user_id][status] = user_statistics[str_user_id].get(status, 0) + 1
        user_statistics[str_user_id]['last_active'] = datetime.now().strftime('%Y-%m-%d')
        
        await callback_query.answer(f"Absensi {status_text[status]} berhasil! {status_emoji[status]}")
        logger.info(f"{user.full_name} ({user_id}) absen dengan status {status} di chat {chat_id}")
    
    # Simpan perubahan
    await save_data()
    
    # Update pesan absensi dengan daftar terbaru
    await update_absen_message(callback_query.message)

# Fungsi untuk memperbarui pesan absensi
async def update_absen_message(message):
    chat_id = message.chat.id
    if chat_id not in absen_sessions:
        return
    
    session = absen_sessions[chat_id]
    
    # Kelompokkan berdasarkan status
    hadir_list = []
    wfh_list = []
    sakit_list = []
    cuti_list = []
    
    for u in session['users']:
        status = u['status']
        name = u['name']
        time = u['time']
        
        if status == 'hadir':
            hadir_list.append(f"- {name} ({time})")
        elif status == 'wfh':
            wfh_list.append(f"- {name} ({time})")
        elif status == 'sakit':
            sakit_list.append(f"- {name} ({time})")
        elif status == 'cuti':
            cuti_list.append(f"- {name} ({time})")
    
    # Format pesan
    text = f"""
📝 *{session['sesi']}*
📅 Tanggal: {datetime.strptime(session['tanggal'], '%Y-%m-%d').strftime('%d %B %Y')}
⏰ Waktu Mulai: {session['start_time']}

*Status Kehadiran:*
"""
    
    # Tambahkan daftar per status
    if hadir_list:
        text += f"\n✅ *Hadir ({len(hadir_list)}):*\n" + "\n".join(hadir_list)
    
    if wfh_list:
        text += f"\n\n🏠 *WFH ({len(wfh_list)}):*\n" + "\n".join(wfh_list)
    
    if sakit_list:
        text += f"\n\n🤒 *Sakit ({len(sakit_list)}):*\n" + "\n".join(sakit_list)
    
    if cuti_list:
        text += f"\n\n🏝️ *Cuti ({len(cuti_list)}):*\n" + "\n".join(cuti_list)
    
    # Tambahkan total
    total = len(session['users'])
    text += f"\n\n*Total Peserta: {total}*"
    
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message.message_id,
            text=text,
            reply_markup=get_absen_keyboard(),
            parse_mode='Markdown'
        )
    except TelegramAPIError as e:
        logger.error(f"Gagal memperbarui pesan absensi: {e}")

# Handler untuk melihat rekap
@dp.message_handler(commands=['rekap'])
async def rekap_cmd(message: types.Message):
    chat_id = message.chat.id
    
    if chat_id not in absen_sessions or not absen_sessions[chat_id]['users']:
        await message.reply("Belum ada yang absen atau belum ada sesi absensi aktif.")
        return
    
    session = absen_sessions[chat_id]
    
    # Kelompokkan berdasarkan status
    hadir_list = []
    wfh_list = []
    sakit_list = []
    cuti_list = []
    
    for u in session['users']:
        status = u['status']
        name = u['name']
        time = u['time']
        
        if status == 'hadir':
            hadir_list.append(f"- {name} ({time})")
        elif status == 'wfh':
            wfh_list.append(f"- {name} ({time})")
        elif status == 'sakit':
            sakit_list.append(f"- {name} ({time})")
        elif status == 'cuti':
            cuti_list.append(f"- {name} ({time})")
    
    # Format pesan
    text = f"""
📊 *REKAP {session['sesi']}*
📅 Tanggal: {datetime.strptime(session['tanggal'], '%Y-%m-%d').strftime('%d %B %Y')}

*Status Kehadiran:*
"""
    
    # Tambahkan daftar per status
    if hadir_list:
        text += f"\n✅ *Hadir ({len(hadir_list)}):*\n" + "\n".join(hadir_list)
    
    if wfh_list:
        text += f"\n\n🏠 *WFH ({len(wfh_list)}):*\n" + "\n".join(wfh_list)
    
    if sakit_list:
        text += f"\n\n🤒 *Sakit ({len(sakit_list)}):*\n" + "\n".join(sakit_list)
    
    if cuti_list:
        text += f"\n\n🏝️ *Cuti ({len(cuti_list)}):*\n" + "\n".join(cuti_list)
    
    # Tambahkan total dan persentase
    total = len(session['users'])
    text += f"\n\n*Total Peserta: {total}*"
    
    hadir_percent = (len(hadir_list) / total * 100) if total > 0 else 0
    wfh_percent = (len(wfh_list) / total * 100) if total > 0 else 0
    sakit_percent = (len(sakit_list) / total * 100) if total > 0 else 0
    cuti_percent = (len(cuti_list) / total * 100) if total > 0 else 0
    
    text += f"\n\n*Persentase:*"
    text += f"\n✅ Hadir: {hadir_percent:.1f}%"
    text += f"\n🏠 WFH: {wfh_percent:.1f}%"
    text += f"\n🤒 Sakit: {sakit_percent:.1f}%"
    text += f"\n🏝️ Cuti: {cuti_percent:.1f}%"
    
    await message.reply(text, parse_mode='Markdown')

# Handler untuk export data
@dp.message_handler(commands=['export'])
async def export_cmd(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Cek apakah admin
    if message.chat.type in ['group', 'supergroup'] and not await is_admin(user_id, chat_id):
        await message.reply("❌ Hanya admin yang bisa mengexport data absensi.")
        return
    
    if chat_id not in absen_sessions or not absen_sessions[chat_id]['users']:
        await message.reply("Belum ada yang absen atau belum ada sesi absensi aktif.")
        return
    
    session = absen_sessions[chat_id]
    
    # Buat file CSV
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['No', 'Nama', 'Username', 'Status', 'Waktu'])
    
    for i, u in enumerate(session['users'], 1):
        status_text = {
            'hadir': 'Hadir',
            'wfh': 'WFH',
            'sakit': 'Sakit',
            'cuti': 'Cuti'
        }.get(u['status'], u['status'])
        
        writer.writerow([
            i, 
            u['name'], 
            u['username'] if 'username' in u and u['username'] else '-',
            status_text,
            u['time'] if 'time' in u else '-'
        ])
    
    output.seek(0)
    filename = f"rekap_{session['sesi'].replace(' ', '_')}_{session['tanggal']}.csv"
    
    # Kirim file
    await message.reply_document(
        types.InputFile(BytesIO(output.getvalue().encode('utf-8-sig')), filename=filename),
        caption=f"📊 Rekap {session['sesi']} ({session['tanggal']})"
    )
    
    logger.info(f"Rekap diexport di chat {chat_id} oleh {message.from_user.full_name} ({user_id})")

# Handler untuk reset absensi
@dp.message_handler(commands=['resetabsen'])
async def reset_cmd(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Cek apakah grup atau private chat
    if message.chat.type not in ['group', 'supergroup']:
        await message.reply("⚠️ Fitur ini hanya bisa digunakan di grup.")
        return
    
    # Cek apakah admin
    if not await is_admin(user_id, chat_id):
        await message.reply("❌ Hanya admin yang bisa mereset absensi.")
        return
    
    if chat_id in absen_sessions:
        # Simpan data terakhir sebelum direset (untuk keperluan audit)
        session = absen_sessions[chat_id]
        logger.warning(
            f"Absensi direset di chat {chat_id} oleh admin {message.from_user.full_name} ({user_id}). "
            f"Sesi: {session['sesi']}, Total peserta: {len(session['users'])}"
        )
        
        # Reset
        del absen_sessions[chat_id]
        await message.reply("✅ Sesi absensi telah direset.")
    else:
        await message.reply("Belum ada sesi absensi yang aktif.")

# Handler untuk melihat status pribadi
@dp.message_handler(commands=['status'])
async def status_cmd(message: types.Message):
    user_id = str(message.from_user.id)
    
    if user_id not in user_statistics:
        await message.reply("Anda belum pernah absen menggunakan bot ini.")
        return
    
    stats = user_statistics[user_id]
    
    text = f"""
📊 *Statistik Kehadiran*
👤 Nama: {message.from_user.full_name}

*Riwayat Kehadiran:*
✅ Hadir: {stats.get('hadir', 0)} kali
🏠 WFH: {stats.get('wfh', 0)} kali
🤒 Sakit: {stats.get('sakit', 0)} kali
🏝️ Cuti: {stats.get('cuti', 0)} kali

📝 Total Absen: {stats.get('total_absen', 0)} kali
📅 Terakhir Aktif: {stats.get('last_active', '-')}
    """
    
    await message.reply(text, parse_mode='Markdown')

# Handler untuk mengaktifkan auto-absen
@dp.message_handler(commands=['enableauto'])
async def enable_auto(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Cek apakah grup atau private chat
    if message.chat.type not in ['group', 'supergroup']:
        await message.reply("⚠️ Fitur ini hanya bisa digunakan di grup.")
        return
    
    # Cek apakah admin
    if not await is_admin(user_id, chat_id):
        await message.reply("❌ Hanya admin yang bisa mengaktifkan auto-absen.")
        return
    
    auto_absen_chats.add(chat_id)
    await save_data()
    
    await message.reply("""
✅ *Absen otomatis telah diaktifkan di grup ini.*

Bot akan memulai sesi absensi baru setiap hari pukul 00:00. Sesi sebelumnya akan direset secara otomatis.
    """, parse_mode='Markdown')
    
    logger.info(f"Auto-absen diaktifkan di chat {chat_id} oleh admin {message.from_user.full_name} ({user_id})")

# Handler untuk menonaktifkan auto-absen
@dp.message_handler(commands=['disableauto'])
async def disable_auto(message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Cek apakah grup atau private chat
    if message.chat.type not in ['group', 'supergroup']:
        await message.reply("⚠️ Fitur ini hanya bisa digunakan di grup.")
        return
    
    # Cek apakah admin
    if not await is_admin(user_id, chat_id):
        await message.reply("❌ Hanya admin yang bisa mematikan auto-absen.")
        return
    
    auto_absen_chats.discard(chat_id)
    await save_data()
    
    await message.reply("❌ Absen otomatis telah dimatikan di grup ini.")
    logger.info(f"Auto-absen dimatikan di chat {chat_id} oleh admin {message.from_user.full_name} ({user_id})")

# Handler untuk broadcast
@dp.message_handler(commands=['broadcast'])
async def broadcast_cmd(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Cek apakah grup dan admin
    if message.chat.type in ['group', 'supergroup'] and not await is_admin(user_id, chat_id):
        await message.reply("❌ Hanya admin yang bisa mengirim broadcast.")
        return
    
    # Dapatkan pesan
    args = message.get_args()
    if not args:
        await message.reply("⚠️ Silakan berikan pesan yang ingin di-broadcast.\nContoh: `/broadcast Pengumuman penting!`")
        return
    
    # Kumpulkan semua user_id yang pernah absen di grup ini
    user_ids = set()
    if chat_id in absen_sessions:
        for user in absen_sessions[chat_id]['users']:
            user_ids.add(user['id'])
    
    if not user_ids:
        await message.reply("⚠️ Belum ada peserta yang bisa dikirim broadcast.")
        return
    
    # Format pesan
    broadcast_text = f"""
📢 *PENGUMUMAN*
Dari: {message.chat.title if message.chat.type in ['group', 'supergroup'] else 'Admin'}

{args}

---
_Pesan ini dikirim melalui Bot Absensi_
    """
    
    # Kirim pesan ke semua user
    success = 0
    failed = 0
    
    await message.reply("🔄 Mengirim broadcast...")
    
    for uid in user_ids:
        try:
            await bot.send_message(uid, broadcast_text, parse_mode='Markdown')
            success += 1
            # Batasi rate untuk menghindari limit dari Telegram
            await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"Gagal mengirim broadcast ke {uid}: {e}")
            failed += 1
    
    await message.reply(f"✅ Broadcast selesai!\nBerhasil: {success}\nGagal: {failed}")
    logger.info(f"Broadcast dikirim oleh {message.from_user.full_name} ({user_id}) ke {success} peserta, {failed} gagal")

# Job untuk auto absen
async def auto_absen_job():
    for chat_id in auto_absen_chats:
        try:
            # Reset sesi sebelumnya jika ada
            if chat_id in absen_sessions:
                logger.info(f"Auto reset absensi di chat {chat_id}")
            
            # Buat sesi baru
            today = datetime.now()
            sesi = f"Absensi {today.strftime('%d %B %Y')}"
            
            absen_sessions[chat_id] = {
                'sesi': sesi,
                'tanggal': today.strftime('%Y-%m-%d'),
                'created_by': bot.id,
                'users': [],
                'start_time': today.strftime('%H:%M:%S')
            }
            
            # Kirim pesan absensi
            absen_msg = f"""
📝 *{sesi} (OTOMATIS)*

📅 Tanggal: {today.strftime('%d %B %Y')}
⏰ Waktu Mulai: {today.strftime('%H:%M:%S')}
👤 Dimulai oleh: Bot (otomatis)

Silakan tekan salah satu tombol di bawah untuk absen:
✅ *Hadir* - Hadir di lokasi kerja
🏠 *WFH* - Work From Home
🤒 *Sakit* - Tidak hadir karena sakit
🏝️ *Cuti* - Sedang cuti
            """
            
            await bot.send_message(