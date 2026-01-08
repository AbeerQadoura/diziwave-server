import os
import re
import asyncio
from telethon import TelegramClient
from aiohttp import web
from supabase import create_client, Client

# --- الإعدادات ---
API_ID = '38472605' 
API_HASH = '9212506c8bf2550cafbc42219b63590e' 
BOT_TOKEN = '8595298322:AAHnRe8FQ-dVWRwVOqaLkn5s4tuWwgQfe8I'
SESSION_NAME = 'diziwave_session'

# إعدادات Supabase (تأكد من صحتها)
SUPABASE_URL = "https://your-project-url.supabase.co" 
SUPABASE_KEY = "your-anon-key"

# إنشاء اتصال Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# إعداد تيليجرام (بدون تشغيله هنا)
client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

# --- دالة مساعدة لروابط تيليجرام ---
def parse_telegram_link(link):
    if 't.me/c/' in link:
        parts = link.split('/')
        chat_id = int('-100' + parts[-2])
        msg_id = int(parts[-1])
        return chat_id, msg_id
    elif 't.me/' in link:
        parts = link.split('/')
        chat_username = parts[-2]
        msg_id = int(parts[-1])
        return chat_username, msg_id
    return None, None

# --- إدارة دورة حياة تيليجرام (الحل للمشكلة) ---
async def telegram_lifecycle(app):
    # 1. عند تشغيل السيرفر: اتصل بتيليجرام
    print("⏳ جاري الاتصال بتيليجرام...")
    await client.start(bot_token=BOT_TOKEN)
    print("✅ Telegram Client Connected!")
    
    yield # هنا يعمل السيرفر ويبقى ينتظر
    
    # 2. عند إيقاف السيرفر: افصل تيليجرام بأمان
    print("🛑 جاري فصل تيليجرام...")
    await client.disconnect()
    print("👋 Telegram Client Disconnected")

# --- 1. دالة البث (Streaming) ---
async def handle_stream(request):
    link = request.query.get('link')
    cors_headers = {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, OPTIONS',
        'Access-Control-Allow-Headers': 'Range, Content-Type, Authorization',
        'Access-Control-Expose-Headers': 'Content-Range, Content-Length, Accept-Ranges',
    }

    if request.method == 'OPTIONS':
        return web.Response(status=204, headers=cors_headers)

    if not link:
        return web.Response(text="No link provided", status=400, headers=cors_headers)

    try:
        chat, msg_id = parse_telegram_link(link)
        message = await client.get_messages(chat, ids=msg_id)
        if not message or not message.media:
            return web.Response(text="Video not found", status=404, headers=cors_headers)

        file_size = message.file.size
        range_header = request.headers.get('Range')
        
        start_byte = 0
        end_byte = file_size - 1

        if range_header:
            match = re.search(r'bytes=(\d+)-(\d*)', range_header)
            if match:
                start_byte = int(match.group(1))
                if match.group(2):
                    end_byte = int(match.group(2))

        headers = {
            **cors_headers,
            'Content-Type': message.file.mime_type or 'video/mp4',
            'Content-Length': str(end_byte - start_byte + 1),
            'Accept-Ranges': 'bytes',
            'Content-Range': f'bytes {start_byte}-{end_byte}/{file_size}',
            'Connection': 'keep-alive',
        }

        resp = web.StreamResponse(status=206 if range_header else 200, headers=headers)
        await resp.prepare(request)

        try:
            async for chunk in client.iter_download(
                message.media, 
                offset=start_byte, 
                limit=end_byte - start_byte + 1,
                chunk_size=1024*1024 
            ):
                await resp.write(chunk)
                await resp.drain()
        except Exception:
            pass 

        return resp

    except Exception as e:
        print(f"❌ Error: {e}")
        return web.Response(text=str(e), status=500, headers=cors_headers)

# --- 2. دالة البحث (Search) ---
async def handle_search(request):
    cors_headers = {'Access-Control-Allow-Origin': '*'}
    query = request.query.get('q', '')

    if not query:
        return web.json_response([], headers=cors_headers)

    try:
        # البحث في Supabase
        response = supabase.table('series') \
            .select('*') \
            .ilike('title', f'%{query}%') \
            .execute()
        
        return web.json_response(response.data, headers=cors_headers)

    except Exception as e:
        print(f"Error searching: {e}")
        return web.json_response({'error': str(e)}, status=500, headers=cors_headers)

# --- إعداد التطبيق ---
async def init_app():
    app = web.Application()
    
    # 🔥 هنا السر: نربط دورة حياة تيليجرام بالتطبيق 🔥
    app.cleanup_ctx.append(telegram_lifecycle)
    
    # ربط المسارات
    app.router.add_get('/stream', handle_stream)
    app.router.add_options('/stream', handle_stream)
    app.router.add_get('/api/search', handle_search)
    
    return app

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    # نستخدم web.run_app مباشرة وهي تدير الـ Event Loop بشكل صحيح
    web.run_app(init_app(), port=port)
