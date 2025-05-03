import logging
from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

API_TOKEN = '7250733161:AAGipLasRdbeX4ll1s2l2KQ5wtODxgODZLo'

logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# Simpan data absensi
absen_sessions = {}

# Tombol absen
btn_hadir = InlineKeyboardButton('✅ Hadir', callback_data='hadir')
absen_keyboard = InlineKeyboardMarkup().add(btn_hadir)

@dp.message_handler(commands=['start'])
async def start_cmd(message: types.Message):
    await message.reply("Halo! Saya bot absensi. Gunakan /startabsen untuk memulai sesi.")

@dp.message_handler(commands=['startabsen'])
async def start_absen(message: types.Message):
    chat_id = message.chat.id
    absen_sessions[chat_id] = []  # reset sesi baru

    await message.reply("Absensi dimulai! Silakan tekan tombol di bawah untuk hadir:",
                        reply_markup=absen_keyboard)

@dp.callback_query_handler(lambda c: c.data == 'hadir')
async def process_absen(callback_query: types.CallbackQuery):
    user = callback_query.from_user
    chat_id = callback_query.message.chat.id

    # Cek apakah user sudah absen
    if chat_id not in absen_sessions:
        absen_sessions[chat_id] = []

    already_absen = any(u['id'] == user.id for u in absen_sessions[chat_id])

    if not already_absen:
        absen_sessions[chat_id].append({'id': user.id, 'name': user.full_name})
        await callback_query.answer("Absensi berhasil! ✅")
    else:
        await callback_query.answer("Kamu sudah absen hari ini!", show_alert=True)

    # Update daftar hadir
    daftar_hadir = '\n'.join([f"- {u['name']}" for u in absen_sessions[chat_id]])

    text = f"✅ *Daftar Hadir:*
{daftar_hadir}"

    await bot.edit_message_text(chat_id=chat_id,
                                message_id=callback_query.message.message_id,
                                text=text,
                                reply_markup=absen_keyboard,
                                parse_mode='Markdown')

@dp.message_handler(commands=['rekap'])
async def rekap_cmd(message: types.Message):
    chat_id = message.chat.id
    if chat_id not in absen_sessions or not absen_sessions[chat_id]:
        await message.reply("Belum ada yang absen.")
        return

    daftar_hadir = '\n'.join([f"- {u['name']}" for u in absen_sessions[chat_id]])
    await message.reply(f"✅ *Rekap Absen:*
{daftar_hadir}", parse_mode='Markdown')

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
