import discord
from discord.ext import commands
import yt_dlp
import asyncio
from collections import deque
import os

intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.voice_states = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)


class MusicPlayer:
    def __init__(self):
        self.queue = deque()
        self.volume = 0.5
        self.now_playing = None
        self.loop = False
        self.vc = None
        self.current_ctx = None
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 3
        self.last_message = None


players = {}

def get_player(guild_id):
    if guild_id not in players:
        players[guild_id] = MusicPlayer()
    return players[guild_id]

FFMPEG_PATH = "C:/Users/user/Documents/ffmpeg-master-latest-win64-gpl-shared/bin/ffmpeg.exe"

ydl_opts = {
    'format': 'bestaudio/best',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'opus',
        'preferredquality': '256',  # 음질을 128에서 256으로 향상
    }],
    'ffmpeg_location': FFMPEG_PATH,
    'default_search': 'ytsearch',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'extract_flat': True,
    'skip_download': True,
}

async def search_youtube(query):
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            # 검색어로 검색
            info = ydl.extract_info(f"ytsearch:{query}", download=False)
            if 'entries' in info and info['entries']:
                # 첫 번째 검색 결과의 URL 가져오기
                video_url = info['entries'][0].get('original_url') or info['entries'][0].get('url') or info['entries'][0].get('webpage_url')
                return {
                    'webpage_url': video_url,
                    'title': info['entries'][0].get('title', 'Unknown title')
                }
            return None
        except Exception as e:
            print(f"검색 중 오류 발생: {e}")
            return None


@bot.event
async def on_ready():
    print(f'봇이 로그인했습니다: {bot.user}')
    await bot.change_presence(status=discord.Status.online, activity=discord.Game(name="!도움말"))

    # 슬래시 커맨드 동기화
    try:
        synced = await bot.tree.sync()
        print(f"🔄 {len(synced)}개의 슬래시 명령어가 동기화되었습니다.")
    except Exception as e:
        print(f"⚠️ 슬래시 명령어 동기화 중 오류 발생: {e}")


async def play_next(interaction, player):
    try:
        if not player.queue and not player.loop:
            player.now_playing = None
            return

        if player.loop and player.now_playing:
            url = player.now_playing
        else:
            if not player.queue:
                player.now_playing = None
                return
            url = player.queue.popleft()
            player.now_playing = url

        if not player.vc or not player.vc.is_connected():
            if interaction.user.voice:
                player.vc = await interaction.user.voice.channel.connect()
            else:
                await interaction.followup.send("음성 채널에 연결할 수 없습니다.")
                return

        if player.vc.is_playing():
            player.vc.stop()

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            url2 = info['url']
            title = info.get('title', 'Unknown title')
            thumbnail = info.get('thumbnail', None)
            duration = info.get('duration_string', 'Unknown duration')
            channel = info.get('channel', 'Unknown channel')

            embed = discord.Embed(
                title="🎵 Now Playing",
                description=f"**{title}**",
                color=discord.Color.blue()
            )
            if thumbnail:
                embed.set_thumbnail(url=thumbnail)
            embed.add_field(name="Duration", value=duration, inline=True)
            embed.add_field(name="Channel", value=channel, inline=True)

            ffmpeg_options = {
                'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
                'options': f'-vn -filter:a volume={player.volume} -ar 48000 -c:a libopus -b:a 256k -application audio'  # 비트레이트를 256k로 향상하고 audio 프로파일 사용
            }

            source = await discord.FFmpegOpusAudio.from_probe(
                url2,
                method='fallback',
                executable=FFMPEG_PATH,
                **ffmpeg_options
            )

            def after(error):
                if error:
                    print(f"재생 중 오류 발생: {error}")
                asyncio.run_coroutine_threadsafe(play_next(interaction, player), bot.loop)

            player.vc.play(source, after=after)
            await interaction.followup.send(embed=embed)

    except discord.errors.ClientException as e:
        if "Already playing audio" in str(e):
            player.vc.stop()
            await asyncio.sleep(0.5)
            await play_next(interaction, player)
        else:
            await interaction.followup.send(f"재생 중 클라이언트 오류 발생: {e}")
            player.now_playing = None
    except Exception as e:
        await interaction.followup.send(f"재생 중 오류 발생: {e}")
        player.now_playing = None

    except discord.errors.ClientException as e:
        if "Already playing audio" in str(e):
            player.vc.stop()
            await asyncio.sleep(0.5)
            await play_next(interaction, player)
        else:
            await interaction.followup.send(f"재생 중 클라이언트 오류 발생: {e}")
            player.now_playing = None
    except Exception as e:
        await interaction.followup.send(f"재생 중 오류 발생: {e}")
        player.now_playing = None


@bot.tree.command(name="들어와", description="음성 채널에 봇을 연결합니다.")
async def 들어와(interaction: discord.Interaction):
    try:
        if interaction.user.voice is None:
            await interaction.response.send_message("음성 채널에 연결되어 있지 않습니다.")
            return

        player = get_player(interaction.guild_id)
        if player.vc and player.vc.is_connected():
            await interaction.response.send_message("이미 음성 채널에 연결되어 있습니다.")
            return

        player.vc = await interaction.user.voice.channel.connect()
        await interaction.response.send_message(f"{interaction.user.voice.channel.name} 채널에 연결되었습니다.")
    except Exception as e:
        await interaction.response.send_message(f"오류 발생: {e}")


@bot.tree.command(name="나가", description="음성 채널에서 봇이 나갑니다.")
async def 나가(interaction: discord.Interaction):
    try:
        player = get_player(interaction.guild_id)
        if not player.vc:
            await interaction.response.send_message("봇이 음성 채널에 없습니다.")
            return

        await player.vc.disconnect()
        player.vc = None
        player.queue.clear()
        player.now_playing = None
        await interaction.response.send_message("음성 채널에서 나갔습니다.")
    except Exception as e:
        await interaction.response.send_message(f"오류 발생: {e}")


@bot.tree.command(name="재생", description="제목 또는 URL로 음악을 재생합니다.")
@discord.app_commands.describe(query="재생할 음악의 제목이나 URL을 입력하세요")
async def 재생(interaction: discord.Interaction, query: str):
    await interaction.response.defer()

    try:
        if interaction.user.voice is None:
            await interaction.followup.send("음성 채널에 먼저 입장해주세요.")
            return

        player = get_player(interaction.guild_id)

        if not player.vc or not player.vc.is_connected():
            player.vc = await interaction.user.voice.channel.connect()
        elif player.vc.channel != interaction.user.voice.channel:
            await player.vc.move_to(interaction.user.voice.channel)

        # URL인지 확인
        is_url = query.startswith(('http://', 'https://', 'www.'))

        if is_url:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(query, download=False)
                if info.get('_type') == 'playlist':
                    entries = info['entries']
                    for entry in entries:
                        player.queue.append(entry['webpage_url'])
                    
                    embed = discord.Embed(
                        title="📑 Playlist Added",
                        description=f"**{info.get('title', 'Unknown')}**",
                        color=discord.Color.green()
                    )
                    embed.add_field(name="Tracks Added", value=str(len(entries)), inline=True)
                    await interaction.followup.send(embed=embed)
                else:
                    player.queue.append(query)
                    
                    embed = discord.Embed(
                        title="🎵 Track Added",
                        description=f"**{info.get('title', 'Unknown')}**",
                        color=discord.Color.green()
                    )
                    if info.get('thumbnail'):
                        embed.set_thumbnail(url=info['thumbnail'])
                    embed.add_field(name="Duration", value=info.get('duration_string', 'Unknown'), inline=True)
                    embed.add_field(name="Channel", value=info.get('channel', 'Unknown'), inline=True)
                    await interaction.followup.send(embed=embed)
        else:
            search_result = await search_youtube(query)
            if search_result:
                player.queue.append(search_result['webpage_url'])
                embed = discord.Embed(
                    title="🔍 Track Found & Added",
                    description=f"**{search_result.get('title', 'Unknown')}**",
                    color=discord.Color.green()
                )
                await interaction.followup.send(embed=embed)
            else:
                embed = discord.Embed(
                    title="❌ Error",
                    description="No search results found.",
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=embed)

        if not player.vc.is_playing():
            await play_next(interaction, player)
    except Exception as e:
        await interaction.followup.send(f"오류 발생: {e}")


@bot.tree.command(name="일시정지", description="현재 재생 중인 음악을 일시정지합니다.")
async def 일시정지(interaction: discord.Interaction):
    player = get_player(interaction.guild_id)
    if player.vc and player.vc.is_playing():
        player.vc.pause()
        embed = discord.Embed(
            title="⏸️ Paused",
            description="Music has been paused.",
            color=discord.Color.yellow()
        )
        await interaction.response.send_message(embed=embed)
    else:
        embed = discord.Embed(
            title="❌ Error",
            description="No music is currently playing.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed)


@bot.tree.command(name="재개", description="일시정지된 음악을 재개합니다.")
async def 재개(interaction: discord.Interaction):
    player = get_player(interaction.guild_id)
    if player.vc and player.vc.is_paused():
        player.vc.resume()
        embed = discord.Embed(
            title="▶️ Resumed",
            description="Music has been resumed.",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)
    else:
        embed = discord.Embed(
            title="❌ Error",
            description="No music is currently paused.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed)


@bot.tree.command(name="스킵", description="현재 재생 중인 음악을 스킵합니다.")
async def 스킵(interaction: discord.Interaction):
    player = get_player(interaction.guild_id)
    if player.vc and player.vc.is_playing():
        player.vc.stop()
        await interaction.response.send_message("현재 재생 중인 음악을 스킵합니다.")
        await play_next(interaction, player)
    else:
        await interaction.response.send_message("현재 재생 중인 음악이 없습니다.")


@bot.tree.command(name="대기열", description="현재 대기 중인 음악 목록을 확인합니다.")
async def 대기열(interaction: discord.Interaction):
    player = get_player(interaction.guild_id)
    embed = discord.Embed(
        title="🎶 Queue",
        color=discord.Color.blue()
    )

    if player.queue:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            queue_text = ""
            for i, url in enumerate(player.queue, 1):
                try:
                    info = ydl.extract_info(url, download=False)
                    title = info.get('title', 'Unknown title')
                    duration = info.get('duration_string', 'Unknown duration')
                    queue_text += f"`{i}.` **{title}** - `{duration}`\n"
                except:
                    queue_text += f"`{i}.` {url}\n"
            
            if player.now_playing:
                current_info = ydl.extract_info(player.now_playing, download=False)
                embed.add_field(
                    name="Now Playing",
                    value=f"**{current_info.get('title', 'Unknown')}**",
                    inline=False
                )
            
            embed.description = queue_text
            embed.set_footer(text=f"Total tracks in queue: {len(player.queue)}")
    else:
        embed.description = "Queue is empty!"
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="멈춰", description="현재 재생 중인 음악을 멈춥니다.")
async def 멈춰(interaction: discord.Interaction):
    player = get_player(interaction.guild_id)

    if player.vc and player.vc.is_playing():
        player.vc.stop()
        await interaction.response.send_message("현재 재생 중인 음악이 멈췄습니다.")
        player.now_playing = None
        await play_next(interaction, player)
    else:
        await interaction.response.send_message("현재 재생 중인 음악이 없습니다.")



bot.run('MTMzMzg0ODIzOTc5NTA4MTI3OA.GJNXgF.mvWwhWI0x6c0OLiumYCL1vr8d3stHjsWomlXNo')
