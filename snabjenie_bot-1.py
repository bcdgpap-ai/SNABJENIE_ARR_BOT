import os
import sqlite3
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler, filters
)

TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "684032427"))
DB = "snabjenie.db"

OBJECT, MAP, ITEM, QTY, COMMENT, PHOTO = range(6)

def db():
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        object TEXT, map_url TEXT, item TEXT, qty TEXT, comment TEXT,
        photo_ids TEXT, worker_id INTEGER, worker_name TEXT,
        created_at TEXT, status TEXT DEFAULT '🆕 Новая'
    )""")
    return con

def main_menu(admin=False):
    rows = [[InlineKeyboardButton("➕ Новая заявка", callback_data="new")]]
    if admin:
        rows += [
            [InlineKeyboardButton("📋 Все заявки", callback_data="all")],
            [InlineKeyboardButton("🆕 Новые", callback_data="status:🆕 Новая"),
             InlineKeyboardButton("🔵 В работе", callback_data="status:🔵 В работе")],
            [InlineKeyboardButton("🟢 Выполненные", callback_data="status:🟢 Выполнено"),
             InlineKeyboardButton("🔴 Отклонённые", callback_data="status:🔴 Отклонено")]
        ]
    return InlineKeyboardMarkup(rows)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin = update.effective_user.id == ADMIN_ID
    text = ("📦 <b>СНАБЖЕНИЕ</b>\n\n"
            "Добро пожаловать! Выберите действие ниже.")
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=main_menu(admin))

async def begin(update, context):
    q = update.callback_query
    await q.answer()
    context.user_data.clear()
    await q.message.reply_text("🏗 <b>Название объекта:</b>", parse_mode="HTML")
    return OBJECT

async def text_step(update, context, key, prompt, next_state):
    context.user_data[key] = update.message.text.strip()
    await update.message.reply_text(prompt, parse_mode="HTML")
    return next_state

async def object_step(update, context):
    return await text_step(update, context, "object", "📍 <b>Ссылка на объект в 2ГИС:</b>", MAP)

async def map_step(update, context):
    context.user_data["map_url"] = update.message.text.strip()
    await update.message.reply_text("📦 <b>Что необходимо?</b>", parse_mode="HTML")
    return ITEM

async def item_step(update, context):
    return await text_step(update, context, "item", "🔢 <b>Количество:</b>", QTY)

async def qty_step(update, context):
    return await text_step(update, context, "qty", "💬 <b>Комментарий:</b>\nМожно написать «нет».", COMMENT)

async def comment_step(update, context):
    context.user_data["comment"] = update.message.text.strip()
    await update.message.reply_text("📸 <b>Отправьте фото.</b>\nМожно отправить несколько. Когда закончите, напишите <b>ГОТОВО</b>.", parse_mode="HTML")
    context.user_data["photos"] = []
    return PHOTO

async def photo_step(update, context):
    if update.message.photo:
        context.user_data.setdefault("photos", []).append(update.message.photo[-1].file_id)
        await update.message.reply_text("📸 Фото добавлено. Отправьте ещё или напишите <b>ГОТОВО</b>.", parse_mode="HTML")
        return PHOTO
    if update.message.text and update.message.text.strip().upper() == "ГОТОВО":
        con = db()
        u = update.effective_user
        data = context.user_data
        con.execute("""INSERT INTO requests
            (object,map_url,item,qty,comment,photo_ids,worker_id,worker_name,created_at)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (data["object"], data["map_url"], data["item"], data["qty"], data["comment"],
             ",".join(data.get("photos", [])), u.id, u.full_name,
             datetime.now().strftime("%Y-%m-%d %H:%M")))
        rid = con.execute("SELECT last_insert_rowid()").fetchone()[0]
        con.commit(); con.close()

        text = (f"🚨 <b>НОВАЯ ЗАЯВКА №{rid:03d}</b>\n\n"
                f"🏗 <b>Объект:</b> {data['object']}\n"
                f"📍 <b>2ГИС:</b> {data['map_url']}\n"
                f"📦 <b>Необходимо:</b> {data['item']}\n"
                f"🔢 <b>Количество:</b> {data['qty']}\n"
                f"💬 <b>Комментарий:</b> {data['comment']}\n"
                f"📸 <b>Фото:</b> {len(data.get('photos', []))}\n"
                f"👷 <b>Прораб:</b> {u.full_name}\n"
                f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}")
        await context.bot.send_message(ADMIN_ID, text, parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔵 В работу", callback_data=f"set:{rid}:🔵 В работе"),
                 InlineKeyboardButton("🟢 Выполнено", callback_data=f"set:{rid}:🟢 Выполнено")],
                [InlineKeyboardButton("🔴 Отклонить", callback_data=f"set:{rid}:🔴 Отклонено")]
            ]))
        await update.message.reply_text("✅ <b>Заявка отправлена!</b>", parse_mode="HTML",
                                        reply_markup=main_menu(u.id == ADMIN_ID))
        context.user_data.clear()
        return ConversationHandler.END
    await update.message.reply_text("Пожалуйста, отправьте фото или напишите <b>ГОТОВО</b>.", parse_mode="HTML")
    return PHOTO

async def list_requests(update, context, status=None):
    q = update.callback_query
    await q.answer()
    if q.from_user.id != ADMIN_ID:
        return
    con = db()
    if status:
        rows = con.execute("SELECT id,object,worker_name,status FROM requests WHERE status=? ORDER BY id DESC", (status,)).fetchall()
    else:
        rows = con.execute("SELECT id,object,worker_name,status FROM requests ORDER BY id DESC").fetchall()
    con.close()
    if not rows:
        await q.message.reply_text("📋 Заявок пока нет.", reply_markup=main_menu(True))
        return
    text = "📋 <b>ЗАЯВКИ</b>\n\n"
    buttons = []
    for rid, obj, worker, st in rows[:30]:
        text += f"№{rid:03d}  |  {obj[:24]}  |  {st}\n"
        buttons.append([InlineKeyboardButton(f"№{rid:03d} — {obj[:30]}", callback_data=f"view:{rid}")])
    await q.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))

async def callback(update, context):
    q = update.callback_query
    if q.data == "new":
        return await begin(update, context)
    if q.from_user.id != ADMIN_ID:
        await q.answer("Нет доступа", show_alert=True); return
    if q.data == "all":
        await list_requests(update, context); return
    if q.data.startswith("status:"):
        await list_requests(update, context, q.data.split(":",1)[1]); return
    if q.data.startswith("set:"):
        _, rid, status = q.data.split(":",2)
        con = db()
        con.execute("UPDATE requests SET status=? WHERE id=?", (status, rid))
        con.commit()
        row = con.execute("SELECT object FROM requests WHERE id=?", (rid,)).fetchone()
        con.close()
        await q.answer("Статус изменён")
        await q.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"📊 {status}", callback_data="noop")]
        ]))
        return
    if q.data.startswith("view:"):
        rid = int(q.data.split(":")[1])
        con = db()
        row = con.execute("""SELECT object,map_url,item,qty,comment,photo_ids,worker_name,created_at,status
                            FROM requests WHERE id=?""", (rid,)).fetchone()
        con.close()
        if not row:
            await q.answer("Заявка не найдена", show_alert=True); return
        obj,map_url,item,qty,comment,photos,worker,created,status = row
        text = (f"📄 <b>ЗАЯВКА №{rid:03d}</b>\n\n"
                f"🏗 <b>Объект:</b> {obj}\n📍 <b>2ГИС:</b> {map_url}\n"
                f"📦 <b>Необходимо:</b> {item}\n🔢 <b>Количество:</b> {qty}\n"
                f"💬 <b>Комментарий:</b> {comment}\n📸 <b>Фото:</b> {len(photos.split(',')) if photos else 0}\n"
                f"👷 <b>Прораб:</b> {worker}\n🕐 {created}\n📊 <b>Статус:</b> {status}")
        await q.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔵 В работу", callback_data=f"set:{rid}:🔵 В работе"),
             InlineKeyboardButton("🟢 Выполнено", callback_data=f"set:{rid}:🟢 Выполнено")],
            [InlineKeyboardButton("🔴 Отклонить", callback_data=f"set:{rid}:🔴 Отклонено")],
            [InlineKeyboardButton("⬅️ К заявкам", callback_data="all")]
        ]))
    elif q.data != "noop":
        await q.answer()

async def cancel(update, context):
    context.user_data.clear()
    await update.message.reply_text("❌ Создание заявки отменено.", reply_markup=main_menu(update.effective_user.id == ADMIN_ID))
    return ConversationHandler.END

def main():
    if not TOKEN:
        raise RuntimeError("Не задан BOT_TOKEN")
    db()
    app = ApplicationBuilder().token(TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(begin, pattern="^new$")],
        states={
            OBJECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, object_step)],
            MAP: [MessageHandler(filters.TEXT & ~filters.COMMAND, map_step)],
            ITEM: [MessageHandler(filters.TEXT & ~filters.COMMAND, item_step)],
            QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, qty_step)],
            COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, comment_step)],
            PHOTO: [MessageHandler(filters.PHOTO | (filters.TEXT & ~filters.COMMAND), photo_step)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(callback))
    app.run_polling()

if __name__ == "__main__":
    main()
