# -*- coding: utf-8 -*-
"""
DARKSELF Diamond Manager Bot
مدیریت الماس، پرداخت کارت‌به‌کارت، گردونه شانس، بازی دوئل، جوین اجباری
"""
import asyncio, json, os, re, time, uuid, random, logging, secrets, math
from datetime import datetime
from zoneinfo import ZoneInfo

from pyrogram import Client, filters, idle
from pyrogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from pyrogram.errors import (
    SessionPasswordNeeded, PhoneCodeInvalid, PhoneCodeExpired,
    FloodWait, MessageNotModified, MessageIdInvalid,
    UserNotParticipant, ChatAdminRequired
)
from pyrogram.enums import ChatType, ChatMemberStatus

# ═══════════════════════════════════════════════════════════
#                      ⚙️ CONFIG — فقط این ۲ خط رو پر کن
# ═══════════════════════════════════════════════════════════
API_ID   = 38187703                                              # ← عدد API_ID خودت (مثال: 1234567)
API_HASH = "f6533e033ebbed5ad46924af5401e194"                                             # ← رشته API_HASH خودت (مثال: "abcdef123...")

# ═══════════════════════════════════════════════════════════
#                ✅ بقیه تنظیمات — نیازی به تغییر نیست
# ═══════════════════════════════════════════════════════════
BOT_TOKEN     = "8696887400:AAFgfEdEsf4O9Ma-hMRQoFH0NtIYfm-0pe0"
ADMIN_ID      = 8776382159
CARD_NUMBER   = "6219861435520217"
CARD_HOLDER   = "تقوی اصل"
DIAMOND_PRICE = 325                    # تومان برای هر الماس
SELF_COST_H   = 1                      # هر ساعت سلف = ۱ الماس
MIN_TOPUP     = 10
MAX_TOPUP     = 5000
WHEEL_COOLDOWN= 24 * 3600
WHEEL_PRIZES  = [1,1,1,2,2,3,3,5,8,12,20,50]
WHEEL_WEIGHTS = [30,30,15,10,6,4,2,1,1,0.5,0.3,0.2]
DUEL_MIN      = 10
DUEL_MAX      = 5000
DUEL_FEE      = 0.05
DUEL_TIMEOUT  = 60

FORCED_CHANNEL     = "cukur_ch_self"
FORCED_CHANNEL_URL = f"https://t.me/{FORCED_CHANNEL}"

TEHRAN = ZoneInfo("Asia/Tehran")

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger("DiamondBot")

# ═══════════════════════════════════════════════════════════
#                       STORAGE
# ═══════════════════════════════════════════════════════════
MANAGER_DB = "manager_data.json"
SELF_DB    = "bot_data.json"

def _default_db():
    return {
        "users": {},
        "payments": {},
        "duels": {},
        "settings": {
            "diamond_price": DIAMOND_PRICE,
            "self_cost_h":   SELF_COST_H,
            "card_number":   CARD_NUMBER,
            "card_holder":   CARD_HOLDER,
            "topup_open":    True,
        },
    }

def load_db():
    if os.path.exists(MANAGER_DB):
        try:
            with open(MANAGER_DB, "r", encoding="utf-8") as f:
                d = json.load(f)
            base = _default_db()
            for k, v in base.items():
                d.setdefault(k, v)
            d["settings"].setdefault("diamond_price", DIAMOND_PRICE)
            d["settings"].setdefault("self_cost_h", SELF_COST_H)
            d["settings"].setdefault("card_number", CARD_NUMBER)
            d["settings"].setdefault("card_holder", CARD_HOLDER)
            d["settings"].setdefault("topup_open", True)
            return d
        except Exception as e:
            log.error(f"DB load fail: {e}")
    return _default_db()

DB = load_db()
DB_LOCK = asyncio.Lock()

async def save_db():
    async with DB_LOCK:
        tmp = MANAGER_DB + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(DB, f, ensure_ascii=False, indent=2)
        os.replace(tmp, MANAGER_DB)
        try:
            os.chmod(MANAGER_DB, 0o600)
        except Exception:
            pass

def get_user(uid):
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
            "join_verified": False,
        }
        DB["users"][uid] = u
    return u

def upd_user(uid, **kw):
    u = get_user(uid)
    u.update(kw)
    return u

def self_seconds_left(uid):
    u = get_user(uid)
    return max(0, int(u.get("activated_until", 0) - time.time()))

def fmt_self_left(uid):
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

def now_ts(): return int(time.time())
def fmt_money(v): return f"{int(v):,}"

# ═══════════════════════════════════════════════════════════
#                       BOT CLIENT
# ═══════════════════════════════════════════════════════════
app = Client("diamond_manager", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ═══════════════════════════════════════════════════════════
#                       KEYBOARDS
# ═══════════════════════════════════════════════════════════
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

# ═══════════════════════════════════════════════════════════
#                   FORCED JOIN GUARD
# ═══════════════════════════════════════════════════════════
async def check_join(uid) -> bool:
    if uid == ADMIN_ID:
        return True
    u = get_user(uid)
    if u.get("join_verified"):
        return True
    try:
        m = await app.get_chat_member(FORCED_CHANNEL, uid)
        if m.status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
            return False
        u["join_verified"] = True
        await save_db()
        return True
    except UserNotParticipant:
        return False
    except Exception as e:
        log.warning(f"check_join fail for {uid}: {e}")
        return False

def join_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 عضویت در کانال", url=FORCED_CHANNEL_URL)],
        [InlineKeyboardButton("✅ عضو شدم", callback_data="check_join")],
    ])

async def force_join_msg(m: Message):
    await m.reply_text(
        "🔒 **برای استفاده از ربات، ابتدا در کانال ما عضو شوید.**\n\n"
        f"📢 @{FORCED_CHANNEL}\n\n"
        "پس از عضویت، روی دکمه «✅ عضو شدم» بزنید.",
        reply_markup=join_kb()
    )

# ═══════════════════════════════════════════════════════════
#                       STATES
# ═══════════════════════════════════════════════════════════
STATES = {}
REG_CLIENTS = {}

# ═══════════════════════════════════════════════════════════
#                   CHECK JOIN CALLBACK
# ═══════════════════════════════════════════════════════════
@app.on_callback_query(filters.regex("^check_join$"))
async def cb_check_join(c: Client, q: CallbackQuery):
    uid = q.from_user.id
    u = get_user(uid)
    u["join_verified"] = False
    ok = await check_join(uid)
    if ok:
        try:
            await q.message.delete()
        except Exception:
            pass
        await q.answer("✅ عضویت تأیید شد! حالا می‌تونی استفاده کنی.", show_alert=True)
        await cmd_start(c, q.message)
    else:
        await q.answer("❌ هنوز عضو نشدی! اول عضو شو بعد دکمه رو بزن.", show_alert=True)

# ═══════════════════════════════════════════════════════════
#                   /start & MAIN MENU
# ═══════════════════════════════════════════════════════════
@app.on_message(filters.command("start") & filters.private)
async def cmd_start(c: Client, m: Message):
    uid = m.from_user.id

    if not await check_join(uid):
        return await force_join_msg(m)

    u = get_user(uid)
    upd_user(uid, name=m.from_user.first_name or "",
             username=m.from_user.username or "")
    await save_db()

    text = (
        "✦ **𝗗𝗔𝗥𝗞𝗦𝗘𝗟𝗙** ✦\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "به ربات مدیریت سلف خوش اومدی 💎\n\n"
        f"💎 موجودی: **{u['balance']}** الماس\n"
        f"⏱ سلف: **{fmt_self_left(uid)}**\n"
        f"💵 هر الماس: **{fmt_money(DB['settings']['diamond_price'])}** تومان\n"
        f"⚡️ هزینه سلف: **{DB['settings']['self_cost_h']}** الماس/ساعت\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "از منوی پایین یکی رو انتخاب کن 👇"
    )
    await m.reply_text(text, reply_markup=main_menu_kb())

@app.on_message(filters.command("admin") & filters.private)
async def cmd_admin(c: Client, m: Message):
    if m.from_user.id != ADMIN_ID:
        return await m.reply_text("⛔️ دسترسی ندارید.")
    await m.reply_text("🛠 **پنل مدیریت**", reply_markup=admin_menu_kb())

# ═══════════════════════════════════════════════════════════
#                       BALANCE
# ═══════════════════════════════════════════════════════════
@app.on_message(filters.private & filters.regex("^💎 موجودی$"))
async def balance_view(c: Client, m: Message):
    uid = m.from_user.id
    if not await check_join(uid):
        return await force_join_msg(m)
    u = get_user(uid)
    price = DB["settings"]["diamond_price"]
    cost_h = DB["settings"]["self_cost_h"]
    hours = u["balance"] // cost_h if cost_h else 0

    text = (
        "✦ **𝗗𝗔𝗥𝗞𝗦𝗘𝗟𝗙** ✦  ·  WALLET\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"💎 **موجودی الماس:** `{u['balance']}`\n"
        f"⏱ **سلف تا:** `{fmt_self_left(uid)}`\n"
        f"⌛️ **با موجودی فعلی:** `{hours}` ساعت\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"💵 **ارزش:** `{fmt_money(u['balance']*price)}` تومان\n"
        f"🛒 **خرید کل:** `{fmt_money(u.get('total_bought',0))}` تومان\n"
        f"📉 **مصرف کل:** `{u.get('total_spent',0)}` الماس"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 شارژ الماس", callback_data="go_topup")],
        [InlineKeyboardButton("🚀 فعال‌سازی سلف", callback_data="go_activate")],
    ])
    await m.reply_text(text, reply_markup=kb)

# ═══════════════════════════════════════════════════════════
#                       TOPUP
# ═══════════════════════════════════════════════════════════
@app.on_message(filters.private & filters.regex("^💰 شارژ الماس$"))
async def topup_start(c: Client, m: Message):
    uid = m.from_user.id
    if not await check_join(uid):
        return await force_join_msg(m)
    if not DB["settings"].get("topup_open", True):
        return await m.reply_text("⛔️ شارژ موقتاً بسته است.")
    STATES[uid] = {"step": "topup_amount"}
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
        "id": pid, "user_id": uid,
        "diamonds": amount, "amount_toman": total,
        "card_photo": None, "receipt": None,
        "status": "awaiting_card_auth",
        "created_at": now_ts(),
        "user_name": m.from_user.first_name or "",
        "user_username": m.from_user.username or "",
    }
    await save_db()
    STATES[uid] = {"step": "topup_card_auth", "pid": pid}
    await m.reply_text(
        "🔐 **احراز هویت پرداخت**\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"💎 الماس: `{amount}`\n"
        f"💵 مبلغ: `{fmt_money(total)}` تومان\n\n"
        "برای تأیید، **عکس کارت بانکی به نام خودت** رو بفرست.\n"
        "این عکس فقط برای مدیریت ارسال می‌شه.\n\n"
        "برای لغو: `لغو`"
    )

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
        if not p: return
        p["card_photo"] = m.photo.file_id
        p["status"] = "awaiting_receipt"
        await save_db()
        STATES[uid] = {"step": "topup_receipt", "pid": pid}
        total = p["diamonds"] * DB["settings"]["diamond_price"]
        s = DB["settings"]
        await m.reply_text(
            "✅ **عکس کارت دریافت شد.**\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"💵 مبلغ: `{fmt_money(total)}` تومان\n\n"
            "🏦 **کارت مقصد:**\n"
            f"`{s['card_number']}`\n"
            f"👤 به نام: **{s['card_holder']}**\n\n"
            "پس از واریز، **عکس رسید بانکی** رو بفرست.\n"
            "برای لغو: `لغو`"
        )
        try:
            await app.send_photo(
                ADMIN_ID, p["card_photo"],
                caption=(
                    "🆕 **درخواست شارژ**\n"
                    f"👤 [{p['user_name']}](tg://user?id={uid})\n"
                    f"🆔 `{uid}`\n"
                    f"💎 {p['diamonds']} الماس\n"
                    f"💵 {fmt_money(total)} تومان\n"
                    f"🔐 `{pid}`"
                ),
            )
        except Exception as e:
            log.warning(f"notify admin card fail: {e}")
        return

    if step == "topup_receipt":
        pid = st["pid"]
        p = DB["payments"].get(pid)
        if not p: return
        p["receipt"] = m.photo.file_id
        p["status"] = "awaiting_admin"
        await save_db()
        STATES.pop(uid, None)
        total = p["diamonds"] * DB["settings"]["diamond_price"]
        await m.reply_text(
            "⏳ **رسید دریافت شد.**\n"
            "پس از تأیید مدیریت، الماس‌ها اضافه می‌شن.",
            reply_markup=main_menu_kb()
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ تأیید", callback_data=f"pay_ok:{pid}"),
             InlineKeyboardButton("❌ رد", callback_data=f"pay_no:{pid}")],
            [InlineKeyboardButton("👤 پروفایل", callback_data=f"user_info:{uid}")],
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
            log.warning(f"notify admin receipt fail: {e}")
        return

# ═══════════════════════════════════════════════════════════
#                   SELF ACTIVATION
# ═══════════════════════════════════════════════════════════
@app.on_message(filters.private & filters.regex("^🚀 فعال‌سازی سلف$"))
async def activate_start(c: Client, m: Message):
    uid = m.from_user.id
    if not await check_join(uid):
        return await force_join_msg(m)
    u = get_user(uid)
    if not u.get("session_string"):
        STATES[uid] = {"step": "reg_phone"}
        return await m.reply_text(
            "📱 **ثبت‌نام سلف**\n\n"
            "برای فعال‌سازی اول باید سلف رو ثبت کنی.\n"
            "شماره تلگرامت رو با فرمت `+98912...` بفرست.\n\n"
            "برای لغو: `لغو`",
            reply_markup=ReplyKeyboardRemove()
        )
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
            "ابتدا شارژ کن.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💰 شارژ الماس", callback_data="go_topup")],
            ])
        )

    hours = u["balance"] // cost
    if hours < 1:
        return await m.reply_text("❌ الماس کافی نداری.")

    prepay_hours = min(hours, 24)
    cost_total = prepay_hours * cost
    new_balance = u["balance"] - cost_total
    new_until = max(left, 0) + prepay_hours * 3600

    upd_user(uid,
             balance=new_balance,
             activated_until=int(time.time()) + new_until,
             self_running=True,
             total_spent=u.get("total_spent", 0) + cost_total)
    await save_db()

    ok, err = await touch_self_db(uid)
    if not ok:
        return await m.reply_text(
            f"⚠️ سلف ثبت شد ولی اتصال به self.py ناموفق بود.\n`{err}`\n"
            "لطفاً به پشتیبانی اطلاع بده."
        )

    await m.reply_text(
        "✅ **سلف فعال شد!**\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"⚡️ مدت: `{prepay_hours}` ساعت\n"
        f"💎 مصرف: `{cost_total}` الماس\n"
        f"💎 موجودی جدید: `{new_balance}`\n"
        f"⏱ اعتبار: `{fmt_self_left(uid)}`\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🔔 **تا ۲۰ ثانیه دیگه سلف وصل می‌شه.**\n"
        "داخل Saved Messages تلگرام خودت دستور `پنل` رو بزن.",
        reply_markup=main_menu_kb()
    )

async def touch_self_db(uid: int):
    try:
        if os.path.exists(SELF_DB):
            with open(SELF_DB, "r", encoding="utf-8") as f:
                d = json.load(f)
        else:
            d = {"users": {}, "sessions": {}, "admins": [ADMIN_ID],
                 "banned_users": [], "invalid_sessions": {}}

        d.setdefault("users", {})
        d.setdefault("sessions", {})
        d.setdefault("admins", [ADMIN_ID])
        d.setdefault("banned_users", [])
        d.setdefault("invalid_sessions", {})

        u_self = d["users"].setdefault(str(uid), {})
        m_u = get_user(uid)

        u_self["user_id"] = uid
        u_self["phone"] = m_u.get("phone", "")
        u_self["session_string"] = m_u.get("session_string", "")
        u_self["first_name"] = m_u.get("name", "")
        u_self["username"] = m_u.get("username", "")

        u_self["activation_ready_at"] = 0
        u_self["activation_id"] = uuid.uuid4().hex
        u_self["activation_notice_pending"] = False
        u_self["activation_failure_notified"] = False
        u_self["activation_notice_chat"] = uid
        u_self["last_start_attempt_ts"] = 0

        s = u_self.setdefault("settings", {})
        s["self_active"] = True
        s.setdefault("dot_commands", False)
        s.setdefault("font", "stylized")
        s.setdefault("clock", False)
        s.setdefault("clock_manual", False)
        s.setdefault("secretary", False)
        s.setdefault("auto_seen", False)
        s.setdefault("pv_lock", False)
        s.setdefault("anti_login", False)
        s.setdefault("anti_delete", False)
        s.setdefault("anti_edit", False)
        s.setdefault("enemy_active", False)
        s.setdefault("friend_active", False)
        s.setdefault("crash_active", False)
        s.setdefault("forced_join_active", False)
        s.setdefault("filter_words_active", False)
        s.setdefault("tabchi_pv", False)
        s.setdefault("tabchi_gp", False)
        s.setdefault("tabchi_smart", False)
        s.setdefault("avatar", False)
        s.setdefault("copy_mode", False)

        if m_u.get("phone") and m_u.get("session_string"):
            d["sessions"][m_u["phone"]] = {
                "string": m_u["session_string"],
                "user_id": uid
            }

        tmp = SELF_DB + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        os.replace(tmp, SELF_DB)
        try:
            os.chmod(SELF_DB, 0o600)
        except Exception:
            pass

        log.info(f"[SELF-DB] activation written for uid={uid}")
        return True, ""
    except Exception as e:
        log.error(f"touch_self_db fail: {e}")
        return False, str(e)[:150]

# ═══════════════════════════════════════════════════════════
#                   REGISTRATION
# ═══════════════════════════════════════════════════════════
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
        if not API_ID or not API_HASH:
            return await m.reply_text(
                "❌ **خطای سرور:** `API_ID` یا `API_HASH` تنظیم نشده.\n"
                "به مدیریت اطلاع بده."
            )
        cl = Client(f"reg_{uid}", api_id=API_ID, api_hash=API_HASH,
                    in_memory=True, no_updates=True)
        try:
            await cl.connect()
            sent = await cl.send_code(phone)
        except FloodWait as fw:
            try: await cl.disconnect()
            except: pass
            return await m.reply_text(f"⏳ {fw.value} ثانیه صبر کن.")
        except Exception as e:
            try: await cl.disconnect()
            except: pass
            return await m.reply_text(f"❌ خطا: `{str(e)[:120]}`")

        REG_CLIENTS[uid] = cl
        STATES[uid] = {"step": "reg_code", "phone": phone,
                       "hash": sent.phone_code_hash}
        await m.reply_text(
            "📨 **کد تأیید ارسال شد.**\n"
            "کد را با فاصله یا چسبیده بفرست.\n"
            "مثال: `1 2 3 4 5`"
        )

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
            return await m.reply_text(f"❌ کد اشتباه/منقضی: `{type(e).__name__}`")
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
        return await m.reply_text(f"❌ خطا در خروجی: `{e}`")
    finally:
        try: await cl.disconnect()
        except: pass
        REG_CLIENTS.pop(uid, None)

    phone = STATES[uid].get("phone", "")
    upd_user(uid, phone=phone, session_string=s_str,
             name=me.first_name or "", username=me.username or "")
    await save_db()
    STATES.pop(uid, None)

    ok, err = await save_session_to_self_db(uid, phone, s_str)
    if not ok:
        log.warning(f"save_session_to_self_db fail: {err}")

    await m.reply_text(
        "✅ **ثبت‌نام کامل شد.**\n\n"
        f"👤 نام: {me.first_name or ''}\n"
        f"📱 شماره: `{phone}`\n\n"
        "الان دکمه **🚀 فعال‌سازی سلف** رو بزن.",
        reply_markup=main_menu_kb()
    )

async def save_session_to_self_db(uid: int, phone: str, s_str: str):
    try:
        if os.path.exists(SELF_DB):
            with open(SELF_DB, "r", encoding="utf-8") as f:
                d = json.load(f)
        else:
            d = {"users": {}, "sessions": {}, "admins": [ADMIN_ID],
                 "banned_users": [], "invalid_sessions": {}}

        d.setdefault("users", {})
        d.setdefault("sessions", {})

        u_self = d["users"].setdefault(str(uid), {})
        u_self["user_id"] = uid
        u_self["phone"] = phone
        u_self["session_string"] = s_str
        s = u_self.setdefault("settings", {})
        s["self_active"] = False
        s.setdefault("dot_commands", False)

        d["sessions"][phone] = {"string": s_str, "user_id": uid}

        tmp = SELF_DB + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        os.replace(tmp, SELF_DB)
        try:
            os.chmod(SELF_DB, 0o600)
        except Exception:
            pass
        return True, ""
    except Exception as e:
        log.warning(f"save_session_to_self_db fail: {e}")
        return False, str(e)[:150]

# ═══════════════════════════════════════════════════════════
#                       LUCKY WHEEL
# ═══════════════════════════════════════════════════════════
@app.on_message(filters.private & filters.regex("^🎡 گردونه شانس$"))
async def wheel_start(c: Client, m: Message):
    uid = m.from_user.id
    if not await check_join(uid):
        return await force_join_msg(m)
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
    msg = await m.reply_text("🎡 **در حال چرخش...**\n\n🌀")
    frames = ["🎡", "🌀", "💫", "⭐️", "✨"]
    for i in range(6):
        await asyncio.sleep(0.5)
        try:
            await msg.edit_text(f"🎡 **در حال چرخش...**\n\n{frames[i%len(frames)]}  " + "▰"*(i+1))
        except MessageNotModified:
            pass

    prize = random.choices(WHEEL_PRIZES, weights=WHEEL_WEIGHTS, k=1)[0]
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

# ═══════════════════════════════════════════════════════════
#                       PROFILE
# ═══════════════════════════════════════════════════════════
@app.on_message(filters.private & filters.regex("^👤 پروفایل من$"))
async def profile_view(c: Client, m: Message):
    uid = m.from_user.id
    if not await check_join(uid):
        return await force_join_msg(m)
    u = get_user(uid)
    reg_t = datetime.fromtimestamp(u.get("registered_at", 0), TEHRAN).strftime("%Y/%m/%d")
    text = (
        "👤 **پروفایل شما**\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🆔 `{uid}`\n"
        f"📱 `{u.get('phone') or '—'}`\n"
        f"📅 عضویت: `{reg_t}`\n"
        f"💎 موجودی: `{u['balance']}`\n"
        f"⏱ سلف: `{fmt_self_left(uid)}`\n"
        f"🛒 خرید کل: `{fmt_money(u.get('total_bought',0))}` تومان\n"
        f"📉 مصرف: `{u.get('total_spent',0)}` الماس\n"
        "━━━━━━━━━━━━━━━━━━"
    )
    await m.reply_text(text, reply_markup=main_menu_kb())

# ═══════════════════════════════════════════════════════════
#                       HELP
# ═══════════════════════════════════════════════════════════
@app.on_message(filters.private & filters.regex("^📖 راهنما$"))
async def help_view(c: Client, m: Message):
    uid = m.from_user.id
    if not await check_join(uid):
        return await force_join_msg(m)
    price = DB["settings"]["diamond_price"]
    await m.reply_text(
        "✦ **𝗗𝗔𝗥𝗞𝗦𝗘𝗟𝗙** ✦  ·  HELP\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🚀 **فعال‌سازی سلف:**\n"
        "شماره‌ت رو ثبت کن، بعد با الماس فعال کن.\n"
        f"⚡️ هزینه: **{DB['settings']['self_cost_h']}** الماس/ساعت\n\n"
        "💎 **شارژ الماس:**\n"
        "کارت‌به‌کارت + ارسال رسید + تأیید مدیریت\n"
        f"💵 هر الماس: **{fmt_money(price)}** تومان\n\n"
        "🎡 **گردونه شانس:**\n"
        "هر ۲۴ ساعت یکبار رایگان بچرخون\n\n"
        "🎮 **بازی الماسی:**\n"
        "داخل گروه ربات رو ادمین کن و بنویس:\n"
        "`بازی 100` → دوئل با شرط ۱۰۰ الماس\n"
        "هر کی سریع‌تر دکمه **پیوستن** رو بزنه وارد می‌شه\n"
        "برنده تصادفی + کمیسیون خانه ۵٪\n"
        "━━━━━━━━━━━━━━━━━━"
    )

# ═══════════════════════════════════════════════════════════
#                       BETTING GAME
# ═══════════════════════════════════════════════════════════
@app.on_message(filters.group & filters.regex(r"^بازی\s+(\d+)$"))
async def duel_create(c: Client, m: Message):
    amount = int(m.matches[0].group(1))
    if amount < DUEL_MIN or amount > DUEL_MAX:
        return await m.reply_text(f"❌ شرط بین {DUEL_MIN} تا {DUEL_MAX} الماس.")
    u = get_user(m.from_user.id)
    if u["balance"] < amount:
        return await m.reply_text(f"❌ موجودی کافی نداری. موجودی: {u['balance']}")
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
        InlineKeyboardButton("🔥 پیوستن", callback_data=f"duel_join:{did}")
    ]])
    txt = (
        f"🎮 **دوئل الماسی** 🎮\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 سازنده: [{m.from_user.first_name}](tg://user?id={m.from_user.id})\n"
        f"💎 شرط: **{amount}** الماس\n"
        f"🏆 برنده کل: **{int(amount*2*(1-DUEL_FEE))}** الماس\n"
        f"(کمیسیون خانه: {int(DUEL_FEE*100)}٪)\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"⏳ {DUEL_TIMEOUT} ثانیه فرصت!"
    )
    sent = await m.reply_text(txt, reply_markup=kb)
    DB["duels"][did]["msg_id"] = sent.id
    await save_db()

    asyncio.create_task(duel_timeout_task(did, DUEL_TIMEOUT))

async def duel_timeout_task(did: str, secs: int):
    await asyncio.sleep(secs)
    d = DB["duels"].get(did)
    if not d or d["status"] != "open":
        return
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

    u["balance"] -= d["amount"]
    d["status"] = "done"
    await save_db()

    winner_uid = random.choice([d["creator"], q.from_user.id])
    loser_uid = q.from_user.id if winner_uid == d["creator"] else d["creator"]
    prize = int(d["amount"] * 2 * (1 - DUEL_FEE))

    w = get_user(winner_uid)
    w["balance"] += prize
    await save_db()

    winner_name = d["creator_name"] if winner_uid == d["creator"] else q.from_user.first_name
    try:
        await q.message.edit_text(
            "🎲 **نتیجه دوئل** 🎲\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"👤 سازنده: `{d['creator']}`\n"
            f"👤 پیوست: [{q.from_user.first_name}](tg://user?id={q.from_user.id})\n"
            f"💎 شرط: **{d['amount']}**\n"
            f"🏆 **برنده:** `{winner_name}`\n"
            f"💰 جایزه: **{prize}** الماس\n"
            "━━━━━━━━━━━━━━━━━━"
        )
    except Exception:
        pass
    try:
        await q.answer(f"🎉 برنده: {winner_name} | {prize} الماس", show_alert=True)
    except Exception:
        pass
    try:
        await app.send_message(winner_uid,
            f"🏆 **تبریک!** {prize} الماس بردی.")
    except Exception:
        pass
    try:
        await app.send_message(loser_uid,
            f"💔 اینبار باختی. {d['amount']} الماس از دست دادی.")
    except Exception:
        pass

# ═══════════════════════════════════════════════════════════
#                   CALLBACK ROUTER
# ═══════════════════════════════════════════════════════════
@app.on_callback_query()
async def cb_router(c: Client, q: CallbackQuery):
    data = q.data or ""
    uid = q.from_user.id

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
            await q.message.edit_caption((q.message.caption or "") + "\n\n✅ **تأیید شد.**")
        except Exception: pass
        try:
            await app.send_message(
                p["user_id"],
                f"✅ **پرداخت تأیید شد!**\n\n💎 {p['diamonds']} الماس اضافه شد.\n"
                f"💎 موجودی: `{u['balance']}`"
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
            await q.message.edit_caption((q.message.caption or "") + "\n\n❌ **رد شد.**")
        except Exception: pass
        try:
            await app.send_message(p["user_id"],
                "❌ **پرداخت رد شد.** با پشتیبانی تماس بگیر.")
        except Exception: pass
        return await q.answer("رد شد.", show_alert=True)

    if data.startswith("user_info:"):
        if uid != ADMIN_ID:
            return await q.answer()
        tuid = int(data.split(":")[1])
        u = get_user(tuid)
        return await q.answer(
            f"👤 {u.get('name')}\n🆔 {tuid}\n💎 {u['balance']}\n"
            f"🛒 خرید: {fmt_money(u.get('total_bought',0))}",
            show_alert=True
        )

    await q.answer()

# ═══════════════════════════════════════════════════════════
#                   ADMIN PANEL
# ═══════════════════════════════════════════════════════════
@app.on_message(filters.private & filters.regex("^📥 صف پرداخت$") & filters.user(ADMIN_ID))
async def admin_payments(c: Client, m: Message):
    pending = [p for p in DB["payments"].values() if p["status"] == "awaiting_admin"]
    if not pending:
        return await m.reply_text("✅ صف خالیه.")
    await m.reply_text(f"📥 **{len(pending)} درخواست**")
    for p in pending[:20]:
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ تأیید", callback_data=f"pay_ok:{p['id']}"),
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
        "━━━━━━━━━━━━━━━━━━\n🆔 ۱۰ کاربر آخر:\n"
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
        "📊 **آمار کل**\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"👥 کاربران: `{len(DB['users'])}`\n"
        f"💎 پرداخت تأییدشده: `{total_pay}`\n"
        f"⏳ در انتظار: `{pending}`\n"
        f"💵 درآمد: `{fmt_money(total_rev)}` تومان\n"
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
    await q.message.reply_text(f"مقدار جدید برای **{key}**:")
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
    await m.reply_text("پیام رو بفرست. برای لغو: `لغو`")

@app.on_message(filters.private & filters.user(ADMIN_ID) &
                ~filters.command("start") & ~filters.command("admin"), group=8)
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

# ═══════════════════════════════════════════════════════════
#                   BILLING LOOP
# ═══════════════════════════════════════════════════════════
async def billing_loop():
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
                    u["self_running"] = False
                    changed = True
                    try:
                        await app.send_message(u["user_id"],
                            "⏰ **زمان سلف تمام شد.** شارژ کن و دوباره فعال کن.")
                    except Exception: pass
                    continue
                u["balance"] = max(0, u["balance"] - cost_min)
                u["total_spent"] = u.get("total_spent", 0) + cost_min
                changed = True
                if u["balance"] <= 0 and u["activated_until"] > 0:
                    u["activated_until"] = 0
                    u["self_running"] = False
                    try:
                        await app.send_message(u["user_id"],
                            "❌ **موجودی تموم شد.** سلف متوقف شد.")
                    except Exception: pass
            if changed:
                for u in DB["users"].values():
                    u["balance"] = int(u["balance"])
                await save_db()
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error(f"billing_loop: {e}")

# ═══════════════════════════════════════════════════════════
#                       MAIN
# ═══════════════════════════════════════════════════════════
async def main():
    if not API_ID or not API_HASH:
        print("\n" + "="*55)
        print("⚠️  خطا: API_ID و API_HASH خالی هستند!")
        print("="*55)
        print("برو داخل فایل bot.py، بالای فایل این دو خط رو پر کن:")
        print("   API_ID   = 1234567   ← عدد خودت")
        print('   API_HASH = "abc..."  ← رشته خودت')
        print("="*55 + "\n")
        return

    await app.start()
    me = await app.get_me()
    log.info(f"Bot started: @{me.username} ({me.id})")
    try:
        await app.send_message(ADMIN_ID, "✅ ربات مدیریت الماس روشن شد.")
    except Exception: pass
    asyncio.create_task(billing_loop())
    await idle()

if __name__ == "__main__":
    app.run(main())#