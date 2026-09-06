import os
import random
import string
import asyncio
import re
import aiohttp
import logging
from fastapi import FastAPI, Request, Response
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TOKEN = "7791564952:AAEq0NXIKY0-BD7MmcDwwkiml4GGQw4a6-Y"

app = FastAPI()
telegram_app = None

# Variabel global untuk melacak status loop aktif dan state input user
active_loops = set()
user_states = {} # Menyimpan state input dari user (email / otp)

class ManualProcessManager:
    @staticmethod
    async def wait_for_user_input(chat_id, context, prompt_text, timeout=300):
        """Fungsi pembantu untuk menjeda proses dan meminta input teks dari user di Telegram"""
        msg = await context.bot.send_message(chat_id=chat_id, text=prompt_text, parse_mode="HTML")
        user_states[chat_id] = asyncio.Future()
        
        try:
            return await asyncio.wait_for(user_states[chat_id], timeout=timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            user_states.pop(chat_id, None)

async def process_xl_esim_manual(chat_id, context, status_callback):
    # 1. Minta user memasukkan email secara manual lewat Telegram
    email_user = await ManualProcessManager.wait_for_user_input(
        chat_id, context, 
        "📧 <b>Silakan ketik/kirim Email Anda di sini:</b>\n(Contoh: namaemail@gmail.com)"
    )
    
    if not email_user or "@" not in email_user:
        return None, "Error: Email tidak valid atau waktu habis.", None, None, None, None

    email_target = email_user.strip()
    full_name = f"mhmdsari{''.join(random.choices(string.ascii_lowercase + string.digits, k=4))}xlstore"
    whatsapp = "08" + ''.join(random.choices(string.digits, k=9))
    
    screenshot_path = f"esim_{chat_id}.png"
    debug_path = f"debug_{chat_id}.png"

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        page = await browser.new_page(viewport={"width": 1366, "height": 768})
        
        try:
            logger.info("Membuka halaman XL...")
            await status_callback("🌐 [LOG: 1/7] Membuka halaman XL eSIM Trial...")
            await page.goto("https://www.xl.co.id/esim-trial/claim", timeout=90000, wait_until="domcontentloaded")

            logger.info("Klik mulai...")
            await status_callback("🖱️ [LOG: 2/7] Klik tombol mulai...")
            try:
                await page.wait_for_selector("text=Mulai Isi Data", timeout=20000)
                await page.get_by_text("Mulai Isi Data").first.click()
            except Exception:
                await page.click("button:has-text('Mulai Isi Data')", timeout=5000)
            
            await asyncio.sleep(2)

            logger.info("Isi data...")
            await status_callback(f"📝 [LOG: 3/7] Mengisi email: <b>{email_target}</b>...")
            try:
                inputs = await page.locator("input").all()
                if len(inputs) >= 3:
                    await inputs[0].fill(full_name)
                    await inputs[1].fill(email_target) # Menggunakan email murni ketikan user[span_1](start_span)[span_1](end_span)
                    await inputs[2].fill(whatsapp)
                else:
                    raise Exception("Gagal mendeteksi input form")
            except Exception as e:
                logger.error(f"Error isi data: {e}")
                raise Exception("Error: Form input tidak ditemukan.")

            logger.info("Ceklis T&C dan Kirim OTP...")
            await status_callback("📤 [LOG: 4/7] Mencentang persetujuan & mengirim OTP...")
            try:
                checkbox = page.locator("input[type='checkbox']")
                if await checkbox.count() > 0:
                    await checkbox.first.click(force=True)
                    await asyncio.sleep(1)

                try:
                    await page.get_by_role("button", name="Setuju").click(timeout=5000)
                except Exception:
                    try:
                        await page.get_by_role("button", name="Lanjut").click(timeout=5000)
                    except Exception:
                        await page.click("button:has-text('Setuju'), button:has-text('Lanjut'), button:has-text('Kirim')", timeout=5000)
            except Exception as e:
                logger.error(f"Error saat klik Lanjut/Checkbox: {e}")
                raise Exception("Error: Gagal mencentang syarat & ketentuan atau tombol lanjut.")

            # 2. Minta user memasukkan OTP secara manual lewat Telegram
            await status_callback(f"⏳ [LOG: 5/7] OTP dikirim ke <b>{email_target}</b>. Silakan cek email Anda!")
            otp_user = await ManualProcessManager.wait_for_user_input(
                chat_id, context,
                f"🔑 <b>Masukkan Kode OTP yang masuk ke email ({email_target}):</b>\n(Ketik 6 digit kode OTP saja)"
            )
            
            if not otp_user:
                raise Exception("Error: Waktu input OTP habis.")
            
            otp = otp_user.strip()
            logger.info(f"Input OTP manual: {otp}")
            await status_callback(f"✅ [LOG: OTP OK] Kode: `{otp}`. Memasukkan ke sistem...")
            
            try:
                await page.locator("input").first.click()
            except Exception:
                pass
            
            await page.keyboard.type(otp, delay=150)

            logger.info("Konfirmasi OTP...")
            await status_callback("📤 [LOG: Konfirmasi OTP] Menekan tombol Lanjut...")
            await asyncio.sleep(1.5)
            try:
                await page.get_by_role("button", name="Lanjut").click(timeout=10000)
            except Exception:
                await page.click("button:has-text('Lanjut'), button:has-text('Konfirmasi')")

            logger.info("Pilih nomor...")
            await status_callback("📱 [LOG: 6/7] Menunggu dan memilih nomor eSIM...")
            
            try:
                await page.wait_for_selector('input[type="radio"], label, .number-card, text=/08/', timeout=30000)
            except Exception:
                logger.warning("Timeout menunggu elemen pilihan nomor, mencoba lanjut paksa via evaluate...")

            await asyncio.sleep(3) 
            
            await page.evaluate("""() => {
                const radios = Array.from(document.querySelectorAll('input[type="radio"]'));
                if (radios.length > 0) {
                    radios[0].checked = true;
                    radios[0].click();
                    radios[0].dispatchEvent(new Event('change', { bubbles: true }));
                    return;
                }
                const candidates = Array.from(document.querySelectorAll('div, label, span, button')).filter(el => {
                    const text = el.innerText ? el.innerText.trim() : '';
                    return text.startsWith('08') && text.length >= 10 && text.length <= 15 && el.children.length <= 2;
                });
                if (candidates.length > 0) {
                    candidates[0].click();
                }
            }""")

            logger.info("Lanjut ke QR...")
            await status_callback("📤 [LOG: 7/7] Menekan tombol Lanjut...")
            await asyncio.sleep(2)

            await page.evaluate("""() => {
                const btns = Array.from(document.querySelectorAll('button, div[role="button"]'));
                const target = btns.find(b => b.innerText && (b.innerText.toLowerCase().includes('lanjut') || b.innerText.toLowerCase().includes('konfirmasi') || b.innerText.toLowerCase().includes('pilih')));
                if (target) {
                    target.click();
                }
            }""")

            logger.info("Proses akhir QR...")
            await status_callback("⏳ Sedang memproses eSIM di server XL (Menunggu QR Code)...")
            await asyncio.sleep(10) 
            
            await status_callback("✨ QR Code berhasil dimuat! Mengambil screenshot...")
            await page.screenshot(path=screenshot_path, full_page=True)
            await browser.close()
            
            if os.path.exists(debug_path):
                os.remove(debug_path)
                
            extracted_info = (
                "✅ <b>Berhasil Claim Esim 50GB 7Hari</b>\n\n"
                f"<b>Email Digunakan:</b> {email_target}\n"
                "Silakan cek QR Code di atas dan email Anda untuk detail lengkapnya.\n\n"
                "<b>CREATED:</b> @forariey"
            )
                
            return screenshot_path, extracted_info, None, None, None, None

        except Exception as e:
            logger.error(f"Error di proses utama: {e}")
            try:
                await page.screenshot(path=debug_path)
                await browser.close()
            except Exception:
                pass
            return debug_path, str(e), None, None, None, None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🚀 Mulai Claim Esim (Manual)", callback_data="start_claim")],
        [InlineKeyboardButton("💰 Support Owner", callback_data="donation")],
        [InlineKeyboardButton("🎦 Bot Alight Motion", url="https://t.me/amforariey_bot")],
        [InlineKeyboardButton("🗨️ Channel Update", url="https://t.me/forarieyproject")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("👋 <b>Selamat datang di Bot Claim eSIM XL!</b>\nSilakan pilih menu di bawah:", 
                                   reply_markup=reply_markup, parse_mode="HTML")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menangkap input teks yang dikirim user saat bot meminta email atau OTP"""
    chat_id = update.effective_chat.id
    text = update.message.text
    
    if chat_id in user_states:
        future = user_states[chat_id]
        if not future.done():
            future.set_result(text)
            try:
                await update.message.delete()
            except Exception:
                pass

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "donation":
        await query.message.reply_text("Dana : 082151916181\nShopeepay : 082151916181")
        
    elif query.data == "start_claim":
        chat_id = query.message.chat.id
        msg = await query.message.reply_text("🚀 Memulai sesi klaim eSIM interaktif...")
        
        async def update_status(text):
            try:
                await context.bot.edit_message_text(text=text, chat_id=chat_id, message_id=msg.message_id, parse_mode="HTML")
            except Exception:
                pass

        path, info, ms, pk, sm, ac = await process_xl_esim_manual(chat_id, context, update_status)
        
        if path and "esim_" in path and os.path.exists(path):
            caption = info
            keyboard_claim = [[InlineKeyboardButton("🧩 Register Biometrik", url="https://registrasi.xl.co.id")]]
            reply_markup_claim = InlineKeyboardMarkup(keyboard_claim)
            await context.bot.send_photo(
                chat_id=chat_id, 
                photo=open(path, 'rb'), 
                caption=caption, 
                parse_mode="HTML",
                reply_markup=reply_markup_claim
            )
            try:
                os.remove(path)
            except Exception:
                pass
        else:
            if path and os.path.exists(path):
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=open(path, 'rb'),
                    caption=f"❌ <b>Gagal Memproses:</b>\n<pre>{info}</pre>",
                    parse_mode="HTML"
                )
                os.remove(path)
            else:
                await context.bot.send_message(chat_id=chat_id, text=f"❌ <b>Gagal Memproses:</b>\n<pre>{info}</pre>", parse_mode="HTML")

@app.post("/")
async def webhook(request: Request):
    global telegram_app
    try:
        data = await request.json()
        if "message" in data:
            update = Update.de_json(data, telegram_app.bot)
            if update and update.message:
                await telegram_app.process_update(update)
        elif "callback_query" in data:
            update = Update.de_json(data, telegram_app.bot)
            if update and update.callback_query:
                await telegram_app.process_update(update)
    except Exception as e:
        logger.error(f"Error pada webhook: {e}")
    return {"status": "ok"}

@app.get("/")
async def health_check():
    return Response(content="Bot is running smoothly!", status_code=200)

@app.get("/go")
async def setup_webhook(request: Request):
    global telegram_app
    domain = os.getenv("RAILWAY_PUBLIC_DOMAIN")
    if domain:
        webhook_url = f"https://{domain}/"
    else:
        webhook_url = str(request.base_url) 
    
    try:
        success = await telegram_app.bot.set_webhook(url=webhook_url)
        if success:
            logger.info(f"Webhook berhasil diatur ke {webhook_url}")
            return {"status": "success", "message": f"Webhook otomatis aktif di {webhook_url}"}
        else:
            return {"status": "failed", "message": "Gagal mengatur webhook"}
    except Exception as e:
        logger.error(f"Error saat set webhook: {e}")
        return {"status": "error", "message": str(e)}

@app.on_event("startup")
async def startup_event():
    global telegram_app
    telegram_app = Application.builder().token(TOKEN).build()
    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CallbackQueryHandler(button_handler))
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    await telegram_app.initialize()
    await telegram_app.start()
    logger.info("Bot Telegram webhook siap menerima koneksi interaktif di Railway...")
