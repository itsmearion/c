import logging
import csv
from io import StringIO
from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.executor import start_polling
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime

API_TOKEN = 'YOUR_BOT_TOKEN_HERE'

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# Simpan data absensi
absen_sessions = {}

# Simpan grup yang aktif auto-absen
auto_absen_chats = set()

# Tombol absen
btn_hadir = InlineKeyboardButton('✅ Hadir', callback_data='hadir')
absen_keyboard = InlineKeyboardMarkup().add(btn_hadir)

scheduler = AsyncIOScheduler()

async def is_admin(user_id, chat_id):
    member = await bot.get_chat_member(chat_id, user_id)
    return member.is_chat_admin()

@dp.message_handler(commands=['start'])
async def start_cmd(message: types.Message):
    await message.reply("Halo! Saya bot absensi.

Perintah:
/startabsen [nama sesi] - Mulai absensi baru
/rekap - Lihat rekap absensi
/export - Export rekap ke file
/resetabsen - Reset sesi absensi
/enableauto - Aktifkan absen otomatis tiap 00:00
/disableauto - Matikan absen otomatis")

@dp.message_handler(commands=['startabsen'])
async def start_absen(message: types.Message):
    chat_id = message.chat.id
    args = message.get_args()
    sesi = args if args else f"Absensi {datetime.now().strftime('%d %B %Y')}"

    absen_sessions[chat_id] = {
        'sesi': sesi,
        'users': []
    }

    logger.info(f"Absen dimulai di chat {chat_id} oleh {message.from_user.full_name} ({message.from_user.id})")

    await message.reply(f"📝 *{sesi}* dimulai!
Silakan tekan tombol di bawah untuk hadir:",
                        reply_markup=absen_keyboard, parse_mode='Markdown')

@dp.callback_query_handler(lambda c: c.data == 'hadir')
async def process_absen(callback_query: types.CallbackQuery):
    user = callback_query.from_user
    chat_id = callback_query.message.chat.id

    if chat_id not in absen_sessions:
        await callback_query.answer("Belum ada sesi absensi! Gunakan /startabsen dulu.", show_alert=True)
        return

    session = absen_sessions[chat_id]
    already_absen = any(u['id'] == user.id for u in session['users'])

    if not already_absen:
        session['users'].append({'id': user.id, 'name': user.full_name})
        await callback_query.answer("Absensi berhasil! ✅")
        logger.info(f"{user.full_name} ({user.id}) absen di chat {chat_id}")
    else:
        await callback_query.answer("Kamu sudah absen hari ini!", show_alert=True)

    daftar_hadir = '\n'.join([f"- {u['name']}" for u in session['users']])
    total = len(session['users'])

    text = f"📝 *{session['sesi']}*
✅ *Daftar Hadir ({total}):*
{daftar_hadir}"

    await bot.edit_message_text(chat_id=chat_id,
                                message_id=callback_query.message.message_id,
                                text=text,
                                reply_markup=absen_keyboard,
                                parse_mode='Markdown')

@dp.message_handler(commands=['rekap'])
async def rekap_cmd(message: types.Message):
    chat_id = message.chat.id
    if chat_id not in absen_sessions or not absen_sessions[chat_id]['users']:
        await message.reply("Belum ada yang absen.")
        return

    session = absen_sessions[chat_id]
    daftar_hadir = '\n'.join([f"- {u['name']}" for u in session['users']])
    total = len(session['users'])
    await message.reply(f"📝 *{session['sesi']}*
✅ *Daftar Hadir ({total}):*
{daftar_hadir}", parse_mode='Markdown')

@dp.message_handler(commands=['export'])
async def export_cmd(message: types.Message):
    chat_id = message.chat.id
    if chat_id not in absen_sessions or not absen_sessions[chat_id]['users']:
        await message.reply("Belum ada yang absen.")
        return

    session = absen_sessions[chat_id]

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['No', 'Nama'])
    for i, u in enumerate(session['users'], 1):
        writer.writerow([i, u['name']])

    output.seek(0)
    await message.reply_document(types.InputFile(output, filename="rekap_absen.csv"))
    logger.info(f"Rekap diexport di chat {chat_id} oleh {message.from_user.full_name} ({message.from_user.id})")

@dp.message_handler(commands=['resetabsen'])
async def reset_cmd(message: types.Message):
    chat_id = message.chat.id

    if not await is_admin(message.from_user.id, chat_id):
        await message.reply("❌ Hanya admin yang bisa mereset absensi.")
        return

    if chat_id in absen_sessions:
        del absen_sessions[chat_id]
        await message.reply("✅ Sesi absensi telah direset.")
        logger.warning(f"Absensi direset di chat {chat_id} oleh admin {message.from_user.full_name} ({message.from_user.id})")
    else:
        await message.reply("Belum ada sesi absensi yang aktif.")

@dp.message_handler(commands=['enableauto'])
async def enable_auto(message: types.Message):
    chat_id = message.chat.id

    if not await is_admin(message.from_user.id, chat_id):
        await message.reply("❌ Hanya admin yang bisa mengaktifkan auto-absen.")
        return

    auto_absen_chats.add(chat_id)
    await message.reply("✅ Absen otomatis tiap 00:00 telah diaktifkan di grup ini.")
    logger.info(f"Auto-absen diaktifkan di chat {chat_id} oleh admin {message.from_user.full_name} ({message.from_user.id})")

@dp.message_handler(commands=['disableauto'])
async def disable_auto(message: types.Message):
    chat_id = message.chat.id

    if not await is_admin(message.from_user.id, chat_id):
        await message.reply("❌ Hanya admin yang bisa mematikan auto-absen.")
        return

    auto_absen_chats.discard(chat_id)
    await message.reply("❌ Absen otomatis telah dimatikan di grup ini.")
    logger.info(f"Auto-absen dimatikan di chat {chat_id} oleh admin {message.from_user.full_name} ({message.from_user.id})")

async def auto_absen_job():
    for chat_id in auto_absen_chats:
        sesi = f"Absensi {datetime.now().strftime('%d %B %Y')}"
        absen_sessions[chat_id] = {
            'sesi': sesi,
            'users': []
        }
        await bot.send_message(chat_id, f"📝 *{sesi}* dimulai otomatis!
Silakan tekan tombol di bawah untuk hadir:",
                               reply_markup=absen_keyboard, parse_mode='Markdown')
        logger.info(f"Auto-absen dimulai otomatis di chat {chat_id}")

if __name__ == '__main__':
    scheduler.add_job(auto_absen_job, 'cron', hour=0, minute=0)
    scheduler.start()
    logger.info("Bot started.")
    executor.start_polling(dp, skip_updates=True)
