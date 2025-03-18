import discord
from discord.ext import commands
import yt_dlp as youtube_dl
import asyncio
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Конфигурация
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -filter:a "volume=0.8"'
}

# Инициализация бота
intents = discord.Intents.default()
intents.voice_states = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
queues = []
current_song = None
loop = False

# Настройки для YouTube DL
ytdl_format_options = {
    'format': 'bestaudio/best',
    'noplaylist': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0'
}

ytdl = youtube_dl.YoutubeDL(ytdl_format_options)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=False))
        
        if 'entries' in data:
            return [cls(discord.FFmpegPCMAudio(entry['url'], **FFMPEG_OPTIONS), data=entry) 
                   for entry in data['entries'] if entry]
        else:
            return [cls(discord.FFmpegPCMAudio(data['url'], **FFMPEG_OPTIONS), data=data)]

async def connect_to_voice(ctx):
    try:
        if not ctx.author.voice:
            await ctx.send("❌ Вы не в голосовом канале!")
            return None
        
        if ctx.voice_client:
            if ctx.voice_client.channel != ctx.author.voice.channel:
                await ctx.voice_client.move_to(ctx.author.voice.channel)
        else:
            await ctx.author.voice.channel.connect(timeout=60.0, reconnect=True)
        
        return ctx.voice_client
    except Exception as e:
        logging.error(f"Ошибка подключения: {e}")
        await ctx.send("❌ Не удалось подключиться к голосовому каналу")
        return None

async def play_next(ctx):
    global current_song, loop
    
    # Если очередь пуста и режим повтора включен, добавляем текущую песню обратно в очередь
    if not queues and loop and current_song:
        queues.append(current_song)
    
    # Если очередь все равно пуста (нет повтора или нет текущей песни), отключаемся
    if not queues:
        current_song = None  # Очищаем текущую песню
        if ctx.voice_client and ctx.voice_client.is_connected():
            await ctx.voice_client.disconnect(force=True)
        return
    
    try:
        current_song = queues.pop(0)

        def after_playing(error):
            if error:
                logging.error(f"Ошибка воспроизведения: {error}")
            if ctx.voice_client and ctx.voice_client.is_connected():
                fut = asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop)
                try:
                    fut.result()
                except Exception as e:
                    logging.error(f"Ошибка в after_playing: {e}")
        
        if not ctx.voice_client or not ctx.voice_client.is_connected():
            return
        
        ctx.voice_client.play(current_song, after=after_playing)
        await ctx.send(f"🎶 Сейчас играет: **{current_song.title}**")

    except Exception as e:
        logging.error(f"Ошибка в play_next: {e}")
        await ctx.send("🚫 Ошибка воспроизведения")

@bot.event
async def on_ready():
    logging.info(f'Бот {bot.user.name} готов к работе!')

@bot.command()
async def play(ctx, *, query):
    vc = await connect_to_voice(ctx)
    if not vc:
        return
    
    async with ctx.typing():
        try:
            players = await YTDLSource.from_url(query)
            if not players:
                return await ctx.send("🚫 Не удалось загрузить контент")
            
            queues.extend(players)
            
            if not vc.is_playing():
                await play_next(ctx)
            else:
                await ctx.send(f"🎵 Добавлено {len(players)} треков в очередь")
        
        except Exception as e:
            await ctx.send(f"🚫 Ошибка: {str(e)}")

@bot.command()
async def skip(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.send("⏩ Трек пропущен")

@bot.command()
async def stop(ctx):
    global current_song, loop
    current_song = None
    loop = False
    queues.clear()
    
    if ctx.voice_client:
        ctx.voice_client.stop()  # Сначала останавливаем воспроизведение
        await ctx.voice_client.disconnect()
    
    await ctx.send("⏹️ Воспроизведение остановлено")

@bot.command()
async def queue(ctx):
    if not queues and not current_song:
        return await ctx.send("📭 Очередь пуста!")
    
    items = []
    if current_song:
        items.append(f"Сейчас играет: {current_song.title}")
    
    for i, song in enumerate(queues[:10]):
        items.append(f"{i+1}. {song.title}")
    
    await ctx.send("🎧 Очередь воспроизведения:\n" + "\n".join(items))

@bot.command(name="loop", aliases=["repeat"])
async def toggle_loop(ctx):
    global loop
    loop = not loop
    await ctx.send(f"🔂 Режим повтора {'включен' if loop else 'выключен'}")

bot.run(TOKEN)
