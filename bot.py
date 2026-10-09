# -*- coding: utf-8 -*-
"""
DARKSELF Diamond Manager Bot
مدیریت الماس، پرداخت کارت‌به‌کارت، گردونه شانس و بازی دوئل
"""
import asyncio, json, os, re, time, uuid, random, logging, secrets, math
from datetime import datetime
from zoneinfo import ZoneInfo

from pyrogram import Client, filters, idle
from pyrogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, Contact
)
from pyrogram.errors import (
    SessionPasswordNeeded, PhoneCodeInvalid, PhoneCodeExpired,
    FloodWait, MessageNotModified, MessageIdInvalid, UserAlreadyParticipant
)
from pyrogram.enums import ChatType, ChatMemberStatus

# ═══════════════════════════════════════════
#                 CONFIG
# ═══════════════════════════════════════════
BOT_TOKEN     = "8696887400:AAFgfEdEsf4O9Ma-hMRQoFH0NtIYfm-0pe0"
API_ID        = 0                       # ← API_ID خودت رو بذار
API_HASH      = ""                      # ← API_HASH خودت رو بذار
ADMIN_ID      = 8776382159
CARD_NUMBER   = "6219861435520217"
CARD_HOLDER   = "تقوی اصل"
DIAMOND_PRICE = 325                     # تومان برای هر الماس
SELF_COST_H   = 1                       # هر ساعت سلف = ۱ الماس
MIN_TOPUP     = 10                      # حداقل شارژ
MAX_TOPUP     = 5000                    # حداکثر شارژ
WHEEL_COOLDOWN= 24*3600                 # ۲۴ ساعت
WHEEL_PRIZES  = [1,1,1,2,2,3,3,5,8,12,20,50]   # توزیع شانس
DUEL_MIN      = 10                      # حداقل شرط دوئل
DUEL_MAX      = 5000
DUEL_FEE      = 0.05                    # ۵٪ کمیسیون خانه
TEHRAN        = ZoneInfo("Asia/Tehran")

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger("DiamondBot")

# ═══════════════════════════════════════════
#              STORAGE
# ═══════════════════════════════════════════
DATA_FILE = "manager_data.json"

def _default_db():
    return {
        "users": {},          # uid -> {balance, activated_until, wheel_last, phone, ...}
        "payments": {},       # pid -> {uid, amount, diamonds, card_photo, receipt, status, ts}
        "duels": {},          # did -> {creator, amount, created_at, chat_id, msg_id, joined}
        "settings": {
            "diamond_price": DIAMOND_PRICE,
            "self_cost_h":   SELF_COST_H,
            "card_number":   CARD_NUMBER,
            "card_holder":   CARD_HOLDER,
            "topup_open":    True,
        },
        "wheel_log": {},      # uid -> [timestamps]
    }

def load_db():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
            base = _default_db()
            for k, v in base.items():
                d.setdefault(k, v)
            return d
        except Exception as e:
            log.error(f"DB load fail: {e}")
    return _default_db()

DB = load_db()
DB_LOCK = asyncio.Lock()

async def save_db():
    async with DB_LOCK:
        tmp = DATA_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(DB, f, ensure_ascii=False, indent=2)
        os.replace(tmp, DATA_FILE)

def get_user(uid: int) -> dict:
    uid = str(int(uid))
    u = DB["users"].get(uid)
    if not u:
        u = {
            "user_id": int(uid),
            "balance": 0,
            "activated_until": 0,
            "wheel_last": 0,
            "phone": "",
            "session_string": "",
            "registered_at": int(time.time()),
            "name": "",
            "username": "",
            "banned": False,
            "total_bought": 0,
            "total_spent": 0,
            "self_running": False,
        }
        DB["users"][uid] = u
    return u

def upd_user(uid: int, **kw):
    u = get_user(uid)
    u.update(kw)
    return u

def self_seconds_left(uid: int) -> int:
    u = get_user(uid)
    return max(0, int(u.get("activated_until", 0) - time.time()))

def fmt_self_left(uid: int) -> str:
    s = self_seconds_left(uid)
    if s <= 0:
        return "❌ فعال نیست"
    d, r = divmod(s, 86400)
    h, r = divmod(r, 3600)
    m, _ = divmod(r, 60)
    parts = []
    if d: parts.append(f"{d} روز")
    if h: parts.append(f"{h} ساعت")
    if m and not d: parts.append(f"{m} دقیقه")
    return " | ".join(parts) if parts else "کمتر از ۱ دقیقه"

def now_ts() -> int:
    return int(time.time())

def fmt_money(v: int) -> str:
    return f"{v:,}"

# ═══════════════════════════════════════════
#               BOT CLIENT
# ═══════════════════════════════════════════
app = Client("diamond_manager", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ═══════════════════════════════════════════
#            KEYBOARDS
# ═══════════════════════════════════════════
def main_menu_kb():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🚀 فعال‌سازی سلف"), KeyboardButton("💎 موجودی")],
        [KeyboardButton("💰 شارژ الماس"),   KeyboardButton("🎡 گردونه شانس")],
        [KeyboardButton("🎮 بازی الماسی"),  KeyboardButton("📖 راهنما")],
        [KeyboardButton("👤 پروفایل من")],
    ], resize_keyboard=True)

def admin_menu_kb():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📥 صف پرداخت"),   KeyboardButton("👥 کاربران")],
        [KeyboardButton("📊 آمار"),         KeyboardButton("⚙️ تنظیمات")],
        [KeyboardButton("📢 پیام همگانی"),  KeyboardButton("🔙 خروج از پنل")],
    ], resize_keyboard=True)

def back_kb(cb="back_main"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data=cb)]])

# ═══════════════════════════════════════════
#           USER STATES (in-memory)
# ═══════════════════════════════════════════
STATES = {}   # uid -> {"step": "...", ...}

# ═══════════════════════════════════════════
#           /start & MAIN MENU
# ═══════════════════════════════════════════
@app.on_message(filters.command("start") & filters.private)
async def cmd_start(c: Client, m: Message):
    uid = m.from_user.id
    u = get_user(uid)
    upd_user(uid, name=m.from_user.first_name or "", username=m.from_user.username or "")
    await save_db()

    text = (
        "✦ **𝗗𝗔𝗥𝗞𝗦𝗘𝗟𝗙** ✦\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "به ربات مدیریت سلف خوش اومدی 💎\n\n"
        f"💎 موجودی فعلی: **{u['balance']}** الماس\n"
        f"⏱ سلف فعال: **{fmt_self_left(uid)}**\n"
        f"💵 هر الماس: **{fmt_money(DB['settings']['diamond_price'])}** تومان\n"
        f"⚡️ هزینه سلف: **{DB['settings']['self_cost_h']}** الماس در ساعت\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "از منوی پایین یکی رو انتخاب کن 👇"
    )
    await m.reply_text(text, reply_markup=main_menu_kb())

@app.on_message(filters.command("admin") & filters.private)
async def cmd_admin(c: Client, m: Message):
    if m.from_user.id != ADMIN_ID:
        return await m.reply_text("⛔️ دسترسی ندارید.")
    await m.reply_text("🛠 **پنل مدیریت**", reply_markup=admin_menu_kb())

# ═══════════════════════════════════════════
#               BALANCE
# ═══════════════════════════════════════════
@app.on_message(filters.private & filters.regex("^💎 موجودی$"))
async def balance_view(c: Client, m: Message):
    uid = m.from_user.id
    u = get_user(uid)
    left = self_seconds_left(uid)
    price = DB["settings"]["diamond_price"]

    # estimate hours remaining
    cost_h = DB["settings"]["self_cost_h"]
    hours = u["balance"] // cost_h if cost_h else 0

    text = (
        "✦ **𝗗𝗔𝗥𝗞𝗦𝗘𝗟𝗙** ✦  ·  WALLET\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"💎 **موجودی الماس:** `{u['balance']}`\n"
        f"⏱ **سلف فعال تا:** `{fmt_self_left(uid)}`\n"
        f"⌛️ **با موجودی فعلی:** `{hours}` ساعت دیگر می‌تونی سلف داشته باشی\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"💵 **ارزش موجودی:** `{fmt_money(u['balance']*price)}` تومان\n"
        f"🛒 **مجموع خرید:** `{fmt_money(u['total_bought'])}` تومان\n"
        f"📉 **مجموع مصرف:** `{u['total_spent']}` الماس"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 شارژ الماس", callback_data="go_topup")],
        [InlineKeyboardButton("🚀 فعال‌سازی سلف", callback_data="go_activate")],
        [InlineKeyboardButton("🔙 بستن", callback_data="close_msg")],
    ])
    await m.reply_text(text, reply_markup=kb)

# ═══════════════════════════════════════════
#           TOPUP (شارژ الماس)
# ═══════════════════════════════════════════
@app.on_message(filters.private & filters.regex("^💰 شارژ الماس$"))
async def topup_start(c: Client, m: Message):
    if not DB["settings"].get("topup_open", True):
        return await m.reply_text("⛔️ شارژ موقتاً بسته است.")
    STATES[m.from_user.id] = {"step": "topup_amount"}
    await m.reply_text(
        "💎 **چند الماس می‌خوای؟**\n"
        f"حداقل `{MIN_TOPUP}` حداکثر `{MAX_TOPUP}`\n\n"
        f"💵 قیمت هر الماس: `{fmt_money(DB['settings']['diamond_price'])}` تومان\n"
        "مثلاً: `100`\n\n"
        "برای لغو: `لغو`",
        reply_markup=ReplyKeyboardRemove()
    )

@app.on_message(filters.private & filters.text, group=5)
async def amount_handler(c: Client, m: Message):
    uid = m.from_user.id
    st = STATES.get(uid)
    if not st or st.get("step") != "topup_amount":
        return
    txt = (m.text or "").strip().replace("،", "").replace(",", "")
    if txt in ("لغو", "/cancel"):
        STATES.pop(uid, None)
        return await m.reply_text("لغو شد.", reply_markup=main_menu_kb())
    if not txt.isdigit():
        return await m.reply_text("❌ فقط عدد بفرست.")
    amount = int(txt)
    if amount < MIN_TOPUP or amount > MAX_TOPUP:
        return await m.reply_text(f"❌ بین {MIN_TOPUP} و {MAX_TOPUP}.")

    price = DB["settings"]["diamond_price"]
    total = amount * price

    pid = uuid.uuid4().hex[:12]
    DB["payments"][pid] = {
        "id": pid,
        "user_id": uid,
        "diamonds": amount,
        "amount_toman": total,
        "card_photo": None,
        "receipt": None,
        "status": "awaiting_card_auth",   # awaiting_card_auth -> awaiting_receipt -> awaiting_admin -> approved/rejected
        "created_at": now_ts(),
        "user_name": m.from_user.first_name or "",
        "user_username": m.from_user.username or "",
    }
    await save_db()
    STATES[uid] = {"step": "topup_card_auth", "pid": pid}

    await m.reply_text(
        "🔐 **احراز هویت پرداخت**\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"💎 تعداد الماس: `{amount}`\n"
        f"💵 مبلغ: `{fmt_money(total)}` تومان\n\n"
        "برای تأیید، **عکس کارت بانکی به نام خودت** رو بفرست.\n"
        "این عکس فقط برای مدیریت ارسال می‌شه و بعد از تأیید حذف می‌شود.\n\n"
        "برای لغو: `لغو`"
    )

# ───── card auth photo ─────
@app.on_message(filters.private & filters.photo, group=5)
async def photo_handler(c: Client, m: Message):
    uid = m.from_user.id
    st = STATES.get(uid)
    if not st:
        return
    step = st.get("step")

    if step == "topup_card_auth":
        pid = st["pid"]
        p = DB["payments"].get(pid)
        if not p:
            return
        p["card_photo"] = m.photo.file_id
        p["status"] = "awaiting_receipt"
        await save_db()
        STATES[uid] = {"step": "topup_receipt", "pid": pid}

        price = DB["settings"]["diamond_price"]
        total = p["diamonds"] * price
        s = DB["settings"]
        await m.reply_text(
            "✅ **عکس کارت دریافت شد.**\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"💵 مبلغ قابل واریز: `{fmt_money(total)}` تومان\n\n"
            "🏦 **اطلاعات کارت مقصد:**\n"
            f"`{s['card_number']}`\n"
            f"👤 به نام: **{s['card_holder']}**\n\n"
            "پس از واریز، **عکس رسید بانکی** رو بفرست.\n"
            "برای لغو: `لغو`"
        )
        # notify admin (photo)
        try:
            await app.send_photo(
                ADMIN_ID, p["card_photo"],
                caption=(
                    "🆕 **درخواست شارژ جدید**\n"
                    f"👤 کاربر: [{p['user_name']}](tg://user?id={uid})\n"
                    f"🆔 `{uid}`\n"
                    f"💎 {p['diamonds']} الماس\n"
                    f"💵 {fmt_money(total)} تومان\n"
                    f"🔐 PID: `{pid}`"
                ),
            )
        except Exception as e:
            log.warning(f"notify admin (card) fail: {e}")
        return

    if step == "topup_receipt":
        pid = st["pid"]
        p = DB["payments"].get(pid)
        if not p:
            return
        p["receipt"] = m.photo.file_id
        p["status"] = "awaiting_admin"
        await save_db()
        STATES.pop(uid, None)
        await save_db()

        price = DB["settings"]["diamond_price"]
        total = p["diamonds"] * price
        await m.reply_text(
            "⏳ **رسید دریافت شد.**\n"
            "پس از تأیید مدیریت، الماس‌ها اضافه می‌شوند.\n"
            "این عملیات معمولاً چند دقیقه طول می‌کشد."
        , reply_markup=main_menu_kb())

        # send receipt photo + approve buttons to admin
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ تأیید", callback_data=f"pay_ok:{pid}"),
             InlineKeyboardButton("❌ رد", callback_data=f"pay_no:{pid}")],
            [InlineKeyboardButton("👤 پروفایل کاربر", callback_data=f"user_info:{uid}")],
        ])
        try:
            await app.send_photo(
                ADMIN_ID, p["receipt"],
                caption=(
                    "🧾 **رسید پرداخت**\n"
                    f"👤 [{p['user_name']}](tg://user?id={uid}) | `{uid}`\n"
                    f"💎 {p['diamonds']} الماس = {fmt_money(total)} تومان\n"
                    f"🆔 `{pid}`"
                ),
                reply_markup=kb,
            )
        except Exception as e:
            log.warning(f"notify admin (receipt) fail: {e}")
        return

# ═══════════════════════════════════════════
#           SELF ACTIVATION
# ═══════════════════════════════════════════
@app.on_message(filters.private & filters.regex("^🚀 فعال‌سازی سلف$"))
async def activate_start(c: Client, m: Message):
    uid = m.from_user.id
    u = get_user(uid)

    if not u.get("session_string"):
        # need registration first
        STATES[uid] = {"step": "reg_phone"}
        return await m.reply_text(
            "📱 **ثبت‌نام سلف**\n\n"
            "برای فعال‌سازی اول باید سلف رو ثبت کنی.\n"
            "شماره تلگرامت رو با فرمت `+98912...` بفرست.\n\n"
            "برای لغو: `لغو`",
            reply_markup=ReplyKeyboardRemove()
        )

    # existing session → try to activate
    await try_activate(c, m, uid)

async def try_activate(c: Client, m: Message, uid: int):
    u = get_user(uid)
    cost = DB["settings"]["self_cost_h"]
    left = self_seconds_left(uid)

    if u["balance"] < cost:
        return await m.reply_text(
            "❌ **موجودی کافی نیست.**\n\n"
            f"💎 موجودی: `{u['balance']}` الماس\n"
            f"⚡️ هزینه هر ساعت: `{cost}` الماس\n\n"
            "برای ادامه سلف، ابتدا شارژ کن.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💰 شارژ الماس", callback_data="go_topup")],
            ])
        )

    # estimate how many hours we can prepay
    hours = u["balance"] // cost
    if hours < 1:
        return await m.reply_text("❌ الماس کافی نداری.")

    # Prepay: consume cost * min(hours, 24) up to 24h
    prepay_hours = min(hours, 24)
    cost_total = prepay_hours * cost
    new_balance = u["balance"] - cost_total
    new_until = max(left, 0) + prepay_hours * 3600

    upd_user(uid,
             balance=new_balance,
             activated_until=int(time.time()) + (new_until),
             self_running=True,
             total_spent=u.get("total_spent", 0) + cost_total)
    await save_db()

    # TODO: connect to self.py here (send signal / touch shared db)
    await touch_self_db(uid)

    await m.reply_text(
        "✅ **سلف فعال شد!**\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"⚡️ مدت فعال‌سازی: `{prepay_hours}` ساعت\n"
        f"💎 الماس مصرفی: `{cost_total}`\n"
        f"💎 موجودی جدید: `{new_balance}`\n"
        f"⏱ اعتبار: `{fmt_self_left(uid)}`\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "داخل Saved Messages تلگرام خودت دستور `پنل` یا `راهنما` رو بزن.",
        reply_markup=main_menu_kb()
    )

async def touch_self_db(uid: int):
    """
    اطلاعات را در دیتابیس self (bot_data.json) می‌نویسد
    تا فایل self.py که در حال اجرا است، سلف را روشن کند.
    """
    SELF_DB = "bot_data.json"
    if not os.path.exists(SELF_DB):
        return
    try:
        with open(SELF_DB, "r", encoding="utf-8") as f:
            d = json.load(f)
        u_self = d.setdefault("users", {}).setdefault(str(uid), {})
        u_self["activation_ready_at"] = 0     # اجازه استارت فوری
        u_self["activation_id"] = uuid.uuid4().hex
        u_self["activation_notice_pending"] = False
        u_self["self_active"] = True
        s = u_self.setdefault("settings", {})
        s["self_active"] = True
        with open(SELF_DB, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
    except Exception as e:
        log.warning(f"touch_self_db fail: {e}")

# ═══════════════════════════════════════════
#           REGISTRATION (phone → code → pass)
# ═══════════════════════════════════════════
REG_CLIENTS = {}    # uid -> Client (during login)

@app.on_message(filters.private & filters.text, group=6)
async def reg_text(c: Client, m: Message):
    uid = m.from_user.id
    st = STATES.get(uid)
    if not st:
        return
    step = st.get("step")
    txt = (m.text or "").strip()

    if txt in ("لغو", "/cancel"):
        STATES.pop(uid, None)
        cl = REG_CLIENTS.pop(uid, None)
        if cl:
            try: await cl.disconnect()
            except: pass
        return await m.reply_text("لغو شد.", reply_markup=main_menu_kb())

    if step == "reg_phone":
        phone = txt.replace(" ", "").replace("-", "")
        if not re.match(r"^\+\d{8,15}$", phone):
            return await m.reply_text("❌ فرمت اشتباه. مثال: `+989121234567`")
        cl = Client(f"reg_{uid}", api_id=API_ID, api_hash=API_HASH,
                    in_memory=True, no_updates=True)
        try:
            await cl.connect()
            sent = await cl.send_code(phone)
        except FloodWait as fw:
            try: await cl.disconnect()
            except: pass
            return await m.reply_text(f"⏳ لطفاً {fw.value} ثانیه صبر کن.")
        except Exception as e:
            try: await cl.disconnect()
            except: pass
            return await m.reply_text(f"❌ خطا: `{str(e)[:120]}`")

        REG_CLIENTS[uid] = cl
        STATES[uid] = {"step": "reg_code", "phone": phone,
                       "hash": sent.phone_code_hash}
        await m.reply_text("📨 **کد تأیید ارسال شد.**\nکد را با فاصله یا چسبیده بفرست.\nمثال: `1 2 3 4 5`")

    elif step == "reg_code":
        cl = REG_CLIENTS.get(uid)
        if not cl:
            STATES.pop(uid, None)
            return await m.reply_text("❌ نشست منقضی. دوباره شروع کن.")
        code = re.sub(r"\D", "", txt)
        try:
            await cl.sign_in(st["phone"], st["hash"], code)
        except SessionPasswordNeeded:
            STATES[uid] = {"step": "reg_password", "phone": st["phone"]}
            return await m.reply_text("🔐 رمز دو مرحله‌ای را بفرست:")
        except (PhoneCodeInvalid, PhoneCodeExpired) as e:
            return await m.reply_text(f"❌ کد اشتباه/منقضی. دوباره: `{type(e).__name__}`")
        except Exception as e:
            return await m.reply_text(f"❌ خطا: `{str(e)[:120]}`")
        await finish_reg(c, m, uid, cl)

    elif step == "reg_password":
        cl = REG_CLIENTS.get(uid)
        if not cl:
            STATES.pop(uid, None)
            return await m.reply_text("❌ نشست منقضی.")
        try:
            await cl.check_password(txt)
        except Exception as e:
            return await m.reply_text(f"❌ رمز اشتباه: `{str(e)[:120]}`")
        await finish_reg(c, m, uid, cl)

async def finish_reg(c: Client, m: Message, uid: int, cl: Client):
    try:
        me = await cl.get_me()
        s_str = await cl.export_session_string()
    except Exception as e:
        return await m.reply_text(f"❌ خطا در خروجی نشست: `{e}`")
    finally:
        try: await cl.disconnect()
        except: pass
        REG_CLIENTS.pop(uid, None)

    phone = STATES[uid].get("phone", "")
    upd_user(uid, phone=phone, session_string=s_str,
             name=me.first_name or "", username=me.username or "")
    await save_db()
    STATES.pop(uid, None)

    # also save into self.py db so self can use it
    await save_session_to_self_db(uid, phone, s_str)

    await m.reply_text(
        "✅ **ثبت‌نام کامل شد.**\n\n"
        f"👤 نام: {me.first_name or ''}\n"
        f"📱 شماره: `{phone}`\n\n"
        "الان دکمه **🚀 فعال‌سازی سلف** رو بزن.",
        reply_markup=main_menu_kb()
    )

async def save_session_to_self_db(uid: int, phone: str, s_str: str):
    SELF_DB = "bot_data.json"
    try:
        if os.path.exists(SELF_DB):
            with open(SELF_DB, "r", encoding="utf-8") as f:
                d = json.load(f)
        else:
            d = {"users": {}, "sessions": {}, "admins": [ADMIN_ID], "banned_users": []}
        d.setdefault("users", {})[str(uid)] = d.get("users", {}).get(str(uid), {})
        u = d["users"][str(uid)]
        u["user_id"] = uid
        u["phone"] = phone
        u["session_string"] = s_str
        u.setdefault("settings", {})["self_active"] = False
        d.setdefault("sessions", {})[phone] = {"string": s_str, "user_id": uid}
        with open(SELF_DB, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
    except Exception as e:
        log.warning(f"save_session_to_self_db fail: {e}")

# ═══════════════════════════════════════════
#           LUCKY WHEEL (گردونه شانس)
# ═══════════════════════════════════════════
@app.on_message(filters.private & filters.regex("^🎡 گردونه شانس$"))
async def wheel_start(c: Client, m: Message):
    uid = m.from_user.id
    u = get_user(uid)
    last = u.get("wheel_last", 0)
    diff = now_ts() - last
    if diff < WHEEL_COOLDOWN:
        left = WHEEL_COOLDOWN - diff
        h, r = divmod(left, 3600)
        mm, _ = divmod(r, 60)
        return await m.reply_text(
            "🎡 گردونه امروز استفاده شده!\n"
            f"⏳ برگرد در: `{h} ساعت و {mm} دقیقه`",
            reply_markup=main_menu_kb()
        )
    # simple spin animation
    msg = await m.reply_text("🎡 **در حال چرخش...**\n\n🌀 Loading...")
    frames = ["🎡", "🌀", "💫", "⭐️", "✨"]
    for i in range(6):
        await asyncio.sleep(0.5)
        try:
            await msg.edit_text(f"🎡 **در حال چرخش...**\n\n{frames[i%len(frames)]}  " + "▰"*(i+1))
        except MessageNotModified:
            pass

    # weighted pick
    weights = [30,30,15,10,6,4,2,1,1,0.5,0.3,0.2]
    prize = random.choices(WHEEL_PRIZES, weights=weights[:len(WHEEL_PRIZES)], k=1)[0]
    u["balance"] += prize
    u["wheel_last"] = now_ts()
    await save_db()

    await msg.edit_text(
        "🎉 **گردونه چرخید!**\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🎁 جایزه: **{prize}** الماس\n"
        f"💎 موجودی جدید: **{u['balance']}**\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "فردا دوباره برگرد ✨"
    )

# ═══════════════════════════════════════════
#           PROFILE
# ═══════════════════════════════════════════
@app.on_message(filters.private & filters.regex("^👤 پروفایل من$"))
async def profile_view(c: Client, m: Message):
    uid = m.from_user.id
    u = get_user(uid)
    reg_t = datetime.fromtimestamp(u.get("registered_at", 0), TEHRAN).strftime("%Y/%m/%d")
    text = (
        "👤 **پروفایل شما**\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🆔 آیدی: `{uid}`\n"
        f"📱 شماره: `{u.get('phone') or '—'}`\n"
        f"📅 عضویت: `{reg_t}`\n"
        f"💎 موجودی: `{u['balance']}`\n"
        f"⏱ سلف: `{fmt_self_left(uid)}`\n"
        f"🛒 خرید کل: `{fmt_money(u.get('total_bought',0))}` تومان\n"
        f"📉 مصرف کل: `{u.get('total_spent',0)}` الماس\n"
        "━━━━━━━━━━━━━━━━━━"
    )
    await m.reply_text(text, reply_markup=main_menu_kb())

# ═══════════════════════════════════════════
#           HELP
# ═══════════════════════════════════════════
@app.on_message(filters.private & filters.regex("^📖 راهنما$"))
async def help_view(c: Client, m: Message):
    price = DB["settings"]["diamond_price"]
    await m.reply_text(
        "✦ **𝗗𝗔𝗥𝗞𝗦𝗘𝗟𝗙** ✦  ·  HELP\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🚀 **فعال‌سازی سلف:**\n"
        "ابتدا شماره‌ت رو ثبت کن، بعد با الماس فعال کن.\n"
        f"⚡️ هزینه: **{DB['settings']['self_cost_h']}** الماس/ساعت\n\n"
        "💎 **شارژ الماس:**\n"
        "کارت‌به‌کارت + ارسال رسید + تأیید مدیریت\n"
        f"💵 هر الماس: **{fmt_money(price)}** تومان\n\n"
        "🎡 **گردونه شانس:**\n"
        "هر ۲۴ ساعت یکبار رایگان بچرخون و الماس ببر\n\n"
        "🎮 **بازی الماسی:**\n"
        "داخل گروه ربات رو ادمین کن و بنویس:\n"
        "`بازی 100` → دوئل با شرط ۱۰۰ الماس\n"
        "هر کسی سریع‌تر دکمه **پیوستن** رو بزنه وارد می‌شه\n"
        "برنده تصادفی انتخاب می‌شه و برنده الماس می‌گیره\n"
        "━━━━━━━━━━━━━━━━━━"
    )

# ═══════════════════════════════════════════
#           BETTING GAME (in groups)
# ═══════════════════════════════════════════
@app.on_message(filters.group & filters.regex(r"^بازی\s+(\d+)$"))
async def duel_create(c: Client, m: Message):
    amount = int(m.matches[0].group(1))
    if amount < DUEL_MIN or amount > DUEL_MAX:
        return await m.reply_text(f"❌ شرط بین {DUEL_MIN} تا {DUEL_MAX} الماس.")
    u = get_user(m.from_user.id)
    if u["balance"] < amount:
        return await m.reply_text(f"❌ موجودی کافی نداری. موجودی: {u['balance']}")
    # reserve stake
    u["balance"] -= amount
    await save_db()

    did = uuid.uuid4().hex[:10]
    DB["duels"][did] = {
        "id": did, "creator": m.from_user.id, "amount": amount,
        "chat_id": m.chat.id, "created_at": now_ts(),
        "status": "open", "msg_id": m.id,
        "creator_name": m.from_user.first_name or "",
    }
    await save_db()

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔥 پیوستن به دوئل", callback_data=f"duel_join:{did}")
    ]])
    txt = (
        f"🎮 **دوئل الماسی** 🎮\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 سازنده: [{m.from_user.first_name}](tg://user?id={m.from_user.id})\n"
        f"💎 شرط: **{amount}** الماس\n"
        f"🏆 برنده کل: **{int(amount*2*(1-DUEL_FEE))}** الماس\n"
        f"(کمیسیون خانه: {int(DUEL_FEE*100)}٪)\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⏳ ۳۰ ثانیه فرصت داری سریع‌ترین پیوستن رو بزنی!"
    )
    sent = await m.reply_text(txt, reply_markup=kb)
    DB["duels"][did]["msg_id"] = sent.id
    await save_db()

    # auto-close after 60s
    asyncio.create_task(duel_timeout(did, 60))

async def duel_timeout(did: str, secs: int):
    await asyncio.sleep(secs)
    d = DB["duels"].get(did)
    if not d or d["status"] != "open":
        return
    # refund
    u = get_user(d["creator"])
    u["balance"] += d["amount"]
    d["status"] = "expired"
    await save_db()
    try:
        await app.edit_message_text(
            d["chat_id"], d["msg_id"],
            f"⌛️ **دوئل منقضی شد.**\nشرط `{d['amount']}` الماس به سازنده برگشت."
        )
    except Exception:
        pass

@app.on_callback_query(filters.regex(r"^duel_join:"))
async def duel_join(c: Client, q: CallbackQuery):
    did = q.data.split(":")[1]
    d = DB["duels"].get(did)
    if not d or d["status"] != "open":
        return await q.answer("دوئل فعال نیست.", show_alert=True)
    if q.from_user.id == d["creator"]:
        return await q.answer("خودت نمی‌تونی وارد بشی.", show_alert=True)
    u = get_user(q.from_user.id)
    if u["balance"] < d["amount"]:
        return await q.answer(f"موجودی کم. نیاز: {d['amount']}", show_alert=True)

    # consume
    u["balance"] -= d["amount"]
    d["status"] = "done"
    await save_db()

    # random winner
    winner_uid = random.choice([d["creator"], q.from_user.id])
    loser_uid = q.from_user.id if winner_uid == d["creator"] else d["creator"]
    prize = int(d["amount"] * 2 * (1 - DUEL_FEE))

    w = get_user(winner_uid)
    w["balance"] += prize
    await save_db()

    winner_name = "سازنده" if winner_uid == d["creator"] else q.from_user.first_name
    try:
        await q.message.edit_text(
            "🎲 **نتیجه دوئل** 🎲\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"👤 سازنده: `{d['creator']}`\n"
            f"👤 پیوست‌شده: [{q.from_user.first_name}](tg://user?id={q.from_user.id})\n"
            f"💎 شرط هر نفر: **{d['amount']}**\n"
            f"🏆 **برنده:** `{winner_name}`\n"
            f"💰 جایزه: **{prize}** الماس\n"
            "━━━━━━━━━━━━━━━━━━"
        )
    except Exception:
        pass
    try:
        await q.answer(f"🎉 برنده شد: {winner_name} | {prize} الماس", show_alert=True)
    except Exception:
        pass
    try:
        await app.send_message(
            winner_uid, f"🏆 **تبریک!** در دوئل برنده شدی و {prize} الماس بردی."
        )
    except Exception:
        pass
    try:
        await app.send_message(
            loser_uid, f"💔 اینبار باختی. {d['amount']} الماس از دست دادی."
        )
    except Exception:
        pass

# ═══════════════════════════════════════════
#           CALLBACK ROUTER
# ═══════════════════════════════════════════
@app.on_callback_query()
async def cb_router(c: Client, q: CallbackQuery):
    data = q.data or ""
    uid = q.from_user.id

    if data == "close_msg":
        try: await q.message.delete()
        except: pass
        return await q.answer()

    if data == "go_topup":
        STATES[uid] = {"step": "topup_amount"}
        return await q.message.reply_text(
            f"💎 تعداد الماس؟ ({MIN_TOPUP}-{MAX_TOPUP})\nبرای لغو: `لغو`"
        )

    if data == "go_activate":
        return await try_activate(c, q.message, uid)

    if data.startswith("pay_ok:"):
        if uid != ADMIN_ID:
            return await q.answer("دسترسی نداری.", show_alert=True)
        pid = data.split(":")[1]
        p = DB["payments"].get(pid)
        if not p or p["status"] != "awaiting_admin":
            return await q.answer("قبلاً پردازش شده.", show_alert=True)
        p["status"] = "approved"
        p["approved_at"] = now_ts()
        u = get_user(p["user_id"])
        u["balance"] += p["diamonds"]
        u["total_bought"] = u.get("total_bought", 0) + p["amount_toman"]
        await save_db()
        try:
            await q.message.edit_caption(
                (q.message.caption or "") + "\n\n✅ **تأیید شد.**"
            )
        except Exception: pass
        try:
            await app.send_message(
                p["user_id"],
                f"✅ **پرداخت تأیید شد!**\n\n💎 {p['diamonds']} الماس به موجودی‌ت اضافه شد.\n"
                f"💎 موجودی جدید: `{u['balance']}`"
            )
        except Exception: pass
        return await q.answer("تأیید شد.", show_alert=True)

    if data.startswith("pay_no:"):
        if uid != ADMIN_ID:
            return await q.answer("دسترسی نداری.", show_alert=True)
        pid = data.split(":")[1]
        p = DB["payments"].get(pid)
        if not p:
            return await q.answer("پیدا نشد.", show_alert=True)
        p["status"] = "rejected"
        await save_db()
        try:
            await q.message.edit_caption(
                (q.message.caption or "") + "\n\n❌ **رد شد.**"
            )
        except Exception: pass
        try:
            await app.send_message(
                p["user_id"],
                "❌ **پرداخت رد شد.**\nاگر مطمئنی اشتباهی رخ داده، با پشتیبانی تماس بگیر."
            )
        except Exception: pass
        return await q.answer("رد شد.", show_alert=True)

    if data.startswith("user_info:"):
        if uid != ADMIN_ID:
            return await q.answer()
        tuid = int(data.split(":")[1])
        u = get_user(tuid)
        return await q.answer(
            f"👤 {u.get('name')}\n"
            f"🆔 {tuid}\n💎 {u['balance']}\n"
            f"🛒 خرید: {fmt_money(u.get('total_bought',0))}",
            show_alert=True
        )

    await q.answer()

# ═══════════════════════════════════════════
#           ADMIN PANEL
# ═══════════════════════════════════════════
@app.on_message(filters.private & filters.regex("^📥 صف پرداخت$") & filters.user(ADMIN_ID))
async def admin_payments(c: Client, m: Message):
    pending = [p for p in DB["payments"].values() if p["status"] == "awaiting_admin"]
    if not pending:
        return await m.reply_text("✅ صف خالیه.")
    await m.reply_text(f"📥 **{len(pending)} درخواست در انتظار**")
    for p in pending[:20]:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ تأیید", callback_data=f"pay_ok:{p['id']}"),
             InlineKeyboardButton("❌ رد", callback_data=f"pay_no:{p['id']}")],
        ])
        cap = (
            f"👤 {p.get('user_name')} | `{p['user_id']}`\n"
            f"💎 {p['diamonds']} الماس = {fmt_money(p['amount_toman'])} تومان\n"
            f"🆔 `{p['id']}`"
        )
        try:
            if p.get("receipt"):
                await m.reply_photo(p["receipt"], caption=cap, reply_markup=kb)
            else:
                await m.reply_text(cap, reply_markup=kb)
        except Exception as e:
            log.warning(f"send payment item fail: {e}")

@app.on_message(filters.private & filters.regex("^👥 کاربران$") & filters.user(ADMIN_ID))
async def admin_users(c: Client, m: Message):
    users = list(DB["users"].values())
    users.sort(key=lambda x: x.get("registered_at", 0), reverse=True)
    total_bal = sum(u["balance"] for u in users)
    active = sum(1 for u in users if self_seconds_left(u["user_id"]) > 0)
    text = (
        "👥 **آمار کاربران**\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📊 کل: `{len(users)}`\n"
        f"⚡️ سلف فعال: `{active}`\n"
        f"💎 مجموع موجودی: `{fmt_money(total_bal)}` الماس\n"
        f"💵 ارزش: `{fmt_money(total_bal*DB['settings']['diamond_price'])}` تومان\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🆔 ۱۰ کاربر آخر:\n"
    )
    for u in users[:10]:
        text += f"`{u['user_id']}` | 💎 {u['balance']} | {u.get('name') or '—'}\n"
    await m.reply_text(text)

@app.on_message(filters.private & filters.regex("^📊 آمار$") & filters.user(ADMIN_ID))
async def admin_stats(c: Client, m: Message):
    total_pay = sum(1 for p in DB["payments"].values() if p["status"] == "approved")
    total_rev = sum(p["amount_toman"] for p in DB["payments"].values() if p["status"] == "approved")
    pending = sum(1 for p in DB["payments"].values() if p["status"] == "awaiting_admin")
    await m.reply_text(
        "📊 **آمار کل سیستم**\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"👥 کل کاربران: `{len(DB['users'])}`\n"
        f"💎 کل پرداخت تأییدشده: `{total_pay}`\n"
        f"⏳ در انتظار: `{pending}`\n"
        f"💵 درآمد کل: `{fmt_money(total_rev)}` تومان\n"
        "━━━━━━━━━━━━━━━━━━"
    )

@app.on_message(filters.private & filters.regex("^⚙️ تنظیمات$") & filters.user(ADMIN_ID))
async def admin_settings(c: Client, m: Message):
    s = DB["settings"]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"💵 قیمت الماس: {fmt_money(s['diamond_price'])}", callback_data="set:price")],
        [InlineKeyboardButton(f"⚡️ هزینه سلف: {s['self_cost_h']} الماس/ساعت", callback_data="set:cost")],
        [InlineKeyboardButton(f"🏦 کارت: {s['card_number']}", callback_data="set:card")],
        [InlineKeyboardButton(f"👤 صاحب کارت: {s['card_holder']}", callback_data="set:holder")],
        [InlineKeyboardButton(f"💰 شارژ: {'باز' if s.get('topup_open') else 'بسته'}", callback_data="set:topup")],
    ])
    await m.reply_text("⚙️ **تنظیمات**", reply_markup=kb)

@app.on_callback_query(filters.regex(r"^set:"))
async def cb_settings(c: Client, q: CallbackQuery):
    if q.from_user.id != ADMIN_ID:
        return await q.answer()
    key = q.data.split(":")[1]
    if key == "topup":
        DB["settings"]["topup_open"] = not DB["settings"].get("topup_open", True)
        await save_db()
        return await q.answer("تغییر کرد.", show_alert=True)
    STATES[ADMIN_ID] = {"step": f"set_{key}"}
    await q.message.reply_text(f"مقدار جدید برای **{key}** رو بفرست:")
    return await q.answer()

@app.on_message(filters.private & filters.user(ADMIN_ID), group=7)
async def admin_set_handler(c: Client, m: Message):
    st = STATES.get(ADMIN_ID)
    if not st or not str(st.get("step", "")).startswith("set_"):
        return
    key = st["step"][4:]
    txt = (m.text or "").strip()
    if key == "price":
        if not txt.isdigit(): return await m.reply_text("عدد بفرست.")
        DB["settings"]["diamond_price"] = int(txt)
    elif key == "cost":
        if not txt.isdigit(): return await m.reply_text("عدد بفرست.")
        DB["settings"]["self_cost_h"] = int(txt)
    elif key == "card":
        DB["settings"]["card_number"] = txt
    elif key == "holder":
        DB["settings"]["card_holder"] = txt
    await save_db()
    STATES.pop(ADMIN_ID, None)
    await m.reply_text("✅ ذخیره شد.", reply_markup=admin_menu_kb())

@app.on_message(filters.private & filters.regex("^📢 پیام همگانی$") & filters.user(ADMIN_ID))
async def admin_broadcast(c: Client, m: Message):
    STATES[ADMIN_ID] = {"step": "broadcast"}
    await m.reply_text("پیام (متن/عکس/ویدیو) رو بفرست. برای لغو: `لغو`")

@app.on_message(filters.private & filters.user(ADMIN_ID) & ~filters.command("start") & ~filters.command("admin"), group=8)
async def admin_broadcast_send(c: Client, m: Message):
    st = STATES.get(ADMIN_ID)
    if not st or st.get("step") != "broadcast":
        return
    if (m.text or "") == "لغو":
        STATES.pop(ADMIN_ID, None)
        return await m.reply_text("لغو شد.", reply_markup=admin_menu_kb())
    STATES.pop(ADMIN_ID, None)
    msg = await m.reply_text("📢 در حال ارسال...")
    ok = 0; fail = 0
    for u in list(DB["users"].values()):
        try:
            await m.copy(u["user_id"])
            ok += 1
            await asyncio.sleep(0.05)
        except Exception:
            fail += 1
    await msg.edit_text(f"✅ ارسال شد.\nموفق: {ok}\nناموفق: {fail}",
                        reply_markup=admin_menu_kb())

@app.on_message(filters.private & filters.regex("^🔙 خروج از پنل$") & filters.user(ADMIN_ID))
async def admin_exit(c: Client, m: Message):
    await m.reply_text("خارج شدی.", reply_markup=main_menu_kb())

# ═══════════════════════════════════════════
#           BILLING LOOP (هر دقیقه)
# ═══════════════════════════════════════════
async def billing_loop():
    """
    هر 60 ثانیه یکبار:
    - برای هر کاربر با سلف فعال، 1/60 هزینه ساعت رو کسر می‌کنه
    - اگر موجودی تموم شد، سلف رو می‌بنده
    """
    while True:
        try:
            await asyncio.sleep(60)
            cost_h = DB["settings"]["self_cost_h"]
            cost_min = cost_h / 60.0
            changed = False
            for uid_s, u in list(DB["users"].items()):
                if not u.get("self_running"):
                    continue
                if self_seconds_left(u["user_id"]) <= 0:
                    # expired
                    u["self_running"] = False
                    changed = True
                    try:
                        await app.send_message(
                            u["user_id"],
                            "⏰ **زمان سلف تمام شد.** برای ادامه، شارژ کن و دوباره فعال کن."
                        )
                    except Exception:
                        pass
                    continue
                # debit
                u["balance"] = max(0, u["balance"] - cost_min)
                u["total_spent"] = u.get("total_spent", 0) + cost_min
                changed = True
                if u["balance"] <= 0 and u["activated_until"] > 0:
                    u["activated_until"] = 0
                    u["self_running"] = False
                    try:
                        await app.send_message(
                            u["user_id"],
                            "❌ **موجودی الماس تموم شد.** سلف متوقف شد."
                        )
                    except Exception:
                        pass
            if changed:
                # round balances to int for storage
                for u in DB["users"].values():
                    u["balance"] = int(u["balance"])
                await save_db()
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error(f"billing_loop: {e}")

# ═══════════════════════════════════════════
#               MAIN
# ═══════════════════════════════════════════
async def main():
    await app.start()
    me = await app.get_me()
    log.info(f"Bot started: @{me.username} ({me.id})")
    try:
        await app.send_message(ADMIN_ID, "✅ ربات مدیریت الماس روشن شد.")
    except Exception: pass
    asyncio.create_task(billing_loop())
    await idle()

if __name__ == "__main__":
    print("Starting Diamond Manager Bot...")
    app.run(main())