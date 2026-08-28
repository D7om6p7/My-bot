import os
import logging
import random
import string
import asyncio
import aiohttp
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# ------------------ التوكن (من متغيرات البيئة) ------------------
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise Exception("ضع توكن البوت في متغير البيئة BOT_TOKEN")

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ------------------ متغير لحفظ الـ NPSSO مؤقتاً ------------------
user_npsso = {}  # dictionary: {chat_id: npsso}

# عدد المحاولات القصوى قبل إيقاف البحث
MAX_ATTEMPTS = 10

# ------------------ دوال توليد اليوزرات ------------------
def generate_username():
    # اختيار عشوائي بين النمطين
    if random.choice([True, False]):
        # نمط PS + حرفين (أحرف كبيرة أو أرقام)
        chars = ''.join(random.choices(string.ascii_uppercase + string.digits, k=2))
        return f"PS{chars}"
    else:
        # نمط KKK + حرف كبير
        char = random.choice(string.ascii_uppercase)
        return f"KKK{char}"

# ------------------ دالة تغيير الاسم الفعلية ------------------
async def change_online_id(npsso: str, new_id: str) -> dict:
    """
    ترسل طلب تغيير الاسم إلى سوني.
    ترجع قاموساً يحتوي على النتيجة: {'success': bool, 'message': str, 'new_id': str}
    """
    url = "https://account.sonyentertainmentnetwork.com/api/v1/accounts/onlineIds"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "application/json",
        "Cookie": f"npsso={npsso}"
    }
    
    payload = {
        "onlineId": new_id
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.put(url, headers=headers, json=payload, timeout=15) as response:
                data = await response.json()
                if response.status == 200:
                    return {"success": True, "message": "تم تغيير الاسم بنجاح!", "new_id": new_id}
                else:
                    # تحليل رسالة الخطأ من سوني
                    error_message = data.get("error", {}).get("message", "خطأ غير معروف")
                    return {"success": False, "message": f"فشل التغيير: {error_message}", "new_id": new_id}
        except Exception as e:
            logger.error(f"خطأ في الاتصال: {e}")
            return {"success": False, "message": f"خطأ في الاتصال: {str(e)}", "new_id": new_id}

# ------------------ حدث الضغط على زر "ابحث وغير" ------------------
async def change_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    chat_id = update.effective_chat.id
    
    # التأكد من وجود npsso للمستخدم
    if chat_id not in user_npsso or not user_npsso[chat_id]:
        await query.edit_message_text(
            "⚠️ يرجى إرسال الـ NPSSO الخاص بحسابك أولاً.\n"
            "أرسل الأمر /start ثم اكتب الكود."
        )
        return
    
    npsso = user_npsso[chat_id]
    
    # بداية البحث
    await query.edit_message_text("🔍 بدء البحث عن اسم شاغر... (سيتم التأخير ثانيتين بين كل محاولة)")
    
    attempts = 0
    while attempts < MAX_ATTEMPTS:
        attempts += 1
        new_id = generate_username()
        
        # تحديث الرسالة بإظهار الاسم الذي يتم تجربته
        await query.edit_message_text(
            f"⏳ **المحاولة {attempts}/{MAX_ATTEMPTS}**\n"
            f"جاري تجربة الاسم: `{new_id}`"
        )
        
        # محاولة تغيير الاسم
        result = await change_online_id(npsso, new_id)
        
        # إذا نجح التغيير
        if result["success"]:
            await query.edit_message_text(
                f"✅ **تم العثور على اسم شاغر وتغييره بنجاح!**\n\n"
                f"🔹 الاسم الجديد: `{result['new_id']}`\n"
                f"🔹 عدد المحاولات: {attempts}\n\n"
                f"💡 ملاحظة: أول تغيير مجاني، والتغييرات التالية مدفوعة."
            )
            return
        
        # إذا فشل بسبب أن الاسم مأخوذ
        if "already in use" in result["message"].lower() or "taken" in result["message"].lower():
            await query.edit_message_text(
                f"⚠️ الاسم `{new_id}` مأخوذ.\n"
                f"⏳ انتظار ثانيتين قبل المحاولة التالية..."
            )
            # ⏳ هنا التأخير المطلوب (ثانيتين)
            await asyncio.sleep(2)
            continue
        else:
            # خطأ آخر (مشكلة في التوكن، أو حظر، أو خطأ في السيرفر)
            await query.edit_message_text(
                f"❌ **توقف البحث بسبب خطأ:**\n"
                f"{result['message']}\n\n"
                f"🛑 تأكد من صلاحية الـ NPSSO أو حاول لاحقاً."
            )
            return
    
    # إذا انتهت المحاولات العشر بدون نتيجة
    await query.edit_message_text(
        f"❌ **لم نجد اسماً شاغراً بعد {MAX_ATTEMPTS} محاولات.**\n"
        f"💡 حاول مرة أخرى لاحقاً، أو غير نمط البحث."
    )

# ------------------ استقبال الـ NPSSO من المستخدم ------------------
async def receive_npsso(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    npsso_text = update.message.text.strip()
    
    # التحقق البسيط من أن النص يبدو مثل npsso (طول حوالي 40-50 حرف)
    if len(npsso_text) < 30 or len(npsso_text) > 80:
        await update.message.reply_text(
            "⚠️ الـ NPSSO الذي أدخلته لا يبدو صحيحاً (الطول غير مناسب).\n"
            "تأكد من نسخ الكوكيز بشكل صحيح."
        )
        return
    
    # حفظ الـ npsso في الذاكرة المؤقتة
    user_npsso[chat_id] = npsso_text
    
    # عرض الأزرار بعد حفظ الـ npsso
    keyboard = [
        [InlineKeyboardButton("🔀 ابحث عن اسم شاغر وغيره (مع تأخير)", callback_data="change")]
    ]
    await update.message.reply_text(
        "✅ تم حفظ الـ NPSSO بنجاح!\n"
        "الآن اضغط على الزر. سيقوم البوت بتجربة أسماء عشوائية، وإذا كان الاسم مأخوذاً سينتظر ثانيتين ويجرب الذي يليه.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ------------------ أمر /start ------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    # إذا كان المستخدم قد أرسل npsso سابقاً، نعرض الأزرار مباشرة
    if chat_id in user_npsso and user_npsso[chat_id]:
        keyboard = [
            [InlineKeyboardButton("🔀 ابحث عن اسم شاغر وغيره (مع تأخير)", callback_data="change")]
        ]
        await update.message.reply_text(
            "👋 مرحباً مجدداً!\n"
            "اضغط الزر لبدء البحث التلقائي عن اسم شاغر (PS / KKK).",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.message.reply_text(
            "👋 أهلاً بك في بوت تغيير الاسم التلقائي.\n\n"
            "**للاستخدام:**\n"
            "1️⃣ اذهب إلى موقع PlayStation وسجل الدخول.\n"
            "2️⃣ استخرج قيمة الكوكيس المسماة `npsso` (من أدوات المطور).\n"
            "3️⃣ أرسل هذه القيمة في الشات (ستُحفظ مؤقتاً فقط).\n\n"
            "📌 مثال: `Nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn`\n\n"
            "بعد إرسالها، سيبدأ البوت بالبحث التلقائي مع تأخير ثانيتين بين كل محاولة."
        )

# ------------------ سيرفر الصحة (لـ Render) ------------------
async def health_check(request):
    return web.Response(text="Bot is running!")

async def start_health_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"✅ سيرفر الصحة شغال على المنفذ {port}")

# ------------------ التشغيل الرئيسي ------------------
async def main():
    asyncio.create_task(start_health_server())
    
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(change_button_callback, pattern="^change$"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_npsso))
    
    logger.info("✅ البوت شغال...")
    await application.run_polling()

if __name__ == "__main__":
    asyncio.run(main())