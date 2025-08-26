import discord
from discord.ext import commands
import yt_dlp as youtube_dl
import asyncio
import nacl
from ytmusicapi import YTMusic
from keep_alive import keep_alive
from discord.ui import Button, View
from discord import Embed,ButtonStyle
import random
import os
from datetime import timedelta
from collections import deque
from concurrent.futures import ProcessPoolExecutor
import functools
from dotenv import load_dotenv

ytmusic = YTMusic()

opus_path = '/usr/lib/libopus.so.***'  # apk add --no-cache opus-dev

# Bot setup
intents = discord.Intents.default()
intents.message_content = True  # Allow bot to read messages
bot = commands.Bot(command_prefix="/", intents=intents)

# Music queue
ytdl_opts = {'format': 'bestaudio/best', 'noplaylist': True, 'quiet': True}
ytdl = youtube_dl.YoutubeDL(ytdl_opts)
music_queues = {}
music_auto_queues= {}
music_past={}
autoplay = True  # Enable autoplay

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'  # no video
}


# async def shutdown_if_no_active_members():
#     await client.wait_until_ready()
#     guild = client.get_guild(GUILD_ID)
#     while True:
#         members = [m for m in guild.members if not m.bot]
#         online = [m for m in members if m.status != discord.Status.offline]

#         if len(online) == 0:
#             print("No users online. Shutting down.")
#             await client.close()
#             os._exit(0)  # optional: ensure full shutdown

#         await asyncio.sleep(300)  # Check every 5 minutes

def create_now_playing_embed(title, url, requester, duration,next_title,next_url):
    duration=str(timedelta(seconds=duration))
    embed = Embed(
        title="🎶 Now Playing",
        description=f"**Track:** [{title}]({url})\n**Requested By:** {requester}  **Duration:** `{duration}`\n **Next:** [{next_title}]({next_url}) \n\n`~/equalizer for custom track control ~`",
        color=0x1DB954  # Spotify green, or use red/blue
    )
    return embed

class MusicPlayerView(View):
    def __init__(self, ctx, is_paused=False, message=None,autoplay_enabled=True):
        super().__init__(timeout=None)
        self.ctx = ctx
        self.is_paused = is_paused
        self.message = message  # to store the message for later edit
        self.autoplay_enabled = autoplay_enabled

    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary,row=0)
    async def previous(self, interaction, button):
        await interaction.response.send_message("Previous track (not implemented)", ephemeral=True)

    @discord.ui.button(label="⏸️", custom_id="pause", style=discord.ButtonStyle.primary,row=0)
    async def pause_button(self, interaction: discord.Interaction, button: Button):
        voice_client = discord.utils.get(bot.voice_clients, guild=self.ctx.guild)

        if voice_client.is_playing():
            voice_client.pause()
            self.is_paused = True
        elif voice_client.is_paused():
            voice_client.resume()
            self.is_paused = False
        else:
            await interaction.response.send_message("Nothing to pause/resume", ephemeral=True)
            return

        # Replace the button label
        new_view = MusicPlayerView(self.ctx, is_paused=self.is_paused)
        new_view.message = self.message  # forward the reference

        # Update button label
        label = "▶️" if self.is_paused else "⏸️"
        new_view.pause_button.label = label

        await interaction.response.edit_message(view=new_view)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.primary,row=0)
    async def skip(self, interaction, button):
        voice_client = discord.utils.get(bot.voice_clients, guild=self.ctx.guild)
        await interaction.response.send_message("Skipped", ephemeral=True)
        
        if voice_client:
            voice_client.stop()
            await asyncio.sleep(2)  # Wait a bit to ensure the stop is processed
            await play_next(self.ctx)
            

    @discord.ui.button(emoji="🔇", style=discord.ButtonStyle.secondary,row=1)
    async def mute(self, interaction, button):
        vc = interaction.guild.voice_client  # Get bot's voice connection
        if vc and vc.is_playing():
            vc.source.volume = 0.0  # Mute
            await interaction.response.send_message("🔇 Bot muted", ephemeral=True)
        else:
            await interaction.response.send_message("❗ Nothing is playing", ephemeral=True)

    @discord.ui.button(emoji="🔉", style=discord.ButtonStyle.secondary, row=1)
    async def partial_volume(self, interaction, button):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.source.volume = 0.5
            await interaction.response.send_message("🔉 Partial volume set (50%)", ephemeral=True)
        else:
            await interaction.response.send_message("❗ Nothing is playing", ephemeral=True)

    @discord.ui.button(emoji="🔊", style=discord.ButtonStyle.secondary,row=1)
    async def unmute(self, interaction, button):
        vc = interaction.guild.voice_client  # Get bot's voice connection
        if vc and vc.is_playing():
            vc.source.volume = 1.0  # Mute
            await interaction.response.send_message("🔇 Bot Unmuted", ephemeral=True)
        else:
            await interaction.response.send_message("❗ Nothing is playing", ephemeral=True)

    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary,row=2)
    async def loop(self, interaction, button):
        await interaction.response.send_message("Loop toggled (not implemented)", ephemeral=True)

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger,row=2)
    async def stop(self, interaction, button):
        voice_client = discord.utils.get(bot.voice_clients, guild=self.ctx.guild)
        if voice_client:
            music_queues[self.ctx.guild.id].clear()
            music_auto_queues[self.ctx.guild.id].clear()
            voice_client.stop()
            await interaction.response.send_message("Stopped", ephemeral=True)


    @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.success, row=2, custom_id="shuffle")
    async def toggle_shuffle(self, interaction: discord.Interaction, button: discord.ui.Button):

        self.autoplay_enabled = not self.autoplay_enabled
        status = "enabled" if self.autoplay_enabled else "disabled"

        # Create new view with updated shuffle state and style
        new_view = MusicPlayerView(
            ctx=self.ctx,
            is_paused=self.is_paused,
            message=self.message,
            autoplay_enabled=self.autoplay_enabled
        )
        new_view.autoplay_enabled = self.autoplay_enabled

        # Get the updated button and change its style
        for child in new_view.children:
            if isinstance(child, discord.ui.Button) and child.custom_id == "shuffle":
                child.style = ButtonStyle.success if self.autoplay_enabled else ButtonStyle.secondary
                break

        await interaction.response.edit_message(
            content=f"🔀 Shuffle {status}",
            view=new_view
        )


# @bot.event
# async def on_ready():
#     await bot.tree.sync()
#     print(f'Logged in as {bot.user}')

@bot.command()
async def join(ctx):
    if ctx.user.voice:
        channel = ctx.user.voice.channel
        await channel.connect()
        print(f'Joined {channel}')
    else:
        await ctx.send("Join a voice channel first!")

async def search_youtube(query):
    try:
        search2=ytmusic.search(query)[0]
        video_url="https://www.youtube.com/watch?v="+search2['videoId']
        title=search2['title']
        return video_url,title
    except Exception as e:
        print(f"Error searching YouTube: {e}")
        return None, None

async def get_related_video(video_url):
    video_id=video_url.split("=")[-1]
    search2=random.choice(ytmusic.get_watch_playlist(video_id)['tracks'][1:15])
    video_url="https://www.youtube.com/watch?v="+search2['videoId']
    title=search2['title']
    return video_url,title

@bot.tree.command(name="play", description="Play a song by URL or name")
async def play(ctx, *, query: str):
    await ctx.response.defer()
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)

    if not voice_client:
        await join(ctx)
        voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
        music_queues[ctx.guild.id] = []
        music_auto_queues[ctx.guild.id] = []

    if "youtube.com" in query or "youtu.be" in query:
        url, title = query, "Unknown Title"
    else:
        url, title = await search_youtube(query)
        if not url:
            await ctx.followup.send("Could not find the song.")
            return
         
    info = await asyncio.to_thread(ytdl.extract_info, url, download=False)
    if title == "Unknown Title":
        title = info.get('title', 'Unknown Title')
    duration=info['duration']
    url2 = info['url']
    music_queues[ctx.guild.id].append((url2,url, title,duration))
    music_auto_queues[ctx.guild.id].clear()
    await ctx.followup.send(f"Added to queue: {title}")
    
    if not voice_client.is_playing():
        print("play_next called")
        asyncio.create_task(play_next(ctx, requester=ctx.user.mention))

async def play_next(ctx,requester=None):
    view=MusicPlayerView(ctx)
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)

    if not voice_client or not voice_client.is_connected():
        await join(ctx)
        voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
        
    if voice_client.is_playing() or voice_client.is_paused():
        return  # Already playing something, do not re-enter
    
    if len(music_queues[ctx.guild.id])>0:
        url2,url,title,duration = music_queues[ctx.guild.id].pop(0)
        if ctx.guild.id not in music_past:
            music_past[ctx.guild.id] = deque(maxlen=10)  # Limit past tracks to 100
        else:
            music_past[ctx.guild.id].append(title)

        ffmpeg_opts = {
            'before_options': FFMPEG_OPTIONS['before_options'],
            'options': f"-vn -t {duration + 1}"  # +1 second buffer to prevent early cutoff
        }
        # source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(url2, executable="ffmpeg",**ffmpeg_opts))
        source = discord.FFmpegOpusAudio(url2, executable="ffmpeg", **ffmpeg_opts)
        voice_client.play(source,after=lambda e: asyncio.run_coroutine_threadsafe(play_next(ctx),bot.loop))
        
        # await asyncio.sleep(0.3)
        if view.autoplay_enabled:
            if len(music_auto_queues[ctx.guild.id])==0:
                last_played_url = url if 'url' in locals() else None
                next_title=""
                next_url=""
                if last_played_url:
                    next_url, next_title = await get_related_video(last_played_url)
                    while (not next_url) or (next_url in music_past.get(ctx.guild.id)):
                        next_url, next_title = await get_related_video(last_played_url)
                    if next_url:
                        info = await asyncio.to_thread(ytdl.extract_info, next_url, download=False)
                        duration2=info['duration']
                        next_url2 = info['url']
                        music_auto_queues[ctx.guild.id].append((next_url2,next_url,next_title,duration2))
                
                embed = create_now_playing_embed(title, url, requester, duration,next_title,next_url)
                message = await ctx.channel.send(embed=embed, view=view)
                view.message = message  # save reference to allow editing later
        
            else:
                embed = create_now_playing_embed(title, url, requester, duration,music_auto_queues[ctx.guild.id][0][2],music_auto_queues[ctx.guild.id][0][1])
                message = await ctx.channel.send(embed=embed, view=view)
                view.message = message  # save reference to allow editing later      
        return

    if len(music_queues[ctx.guild.id])==0:
        print("len",len(music_auto_queues[ctx.guild.id]))
        if len(music_auto_queues[ctx.guild.id])>0:
            url2,url,title,duration = music_auto_queues[ctx.guild.id].pop(0)
            ffmpeg_opts = {
                'before_options': FFMPEG_OPTIONS['before_options'],
                'options': f'-vn -t {duration + 1} -filter:a "volume=1.0"' # +1 second buffer to prevent early cutoff
            }

            source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(url2, executable="ffmpeg",**ffmpeg_opts))
            voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(ctx),bot.loop))
            
            if view.autoplay_enabled and len(music_auto_queues[ctx.guild.id])==0:
                last_played_url = url if 'url' in locals() else None
                next_title=""
                next_url=""
                if last_played_url:
                    next_url, next_title = await get_related_video(last_played_url)
                    while (not next_url) or (next_url in music_past.get(ctx.guild.id)):
                        next_url, next_title = await get_related_video(last_played_url)
                    if next_url:
                        info = await asyncio.to_thread(ytdl.extract_info, next_url, download=False)
                        next_url2 = info['url']
                        duration2=info['duration']
                        music_auto_queues[ctx.guild.id].append((next_url2,next_url,next_title,duration2))
                        
                embed = create_now_playing_embed(title, url, "Autoplay", duration,next_title,next_url)
                message = await ctx.channel.send(embed=embed, view=view)
                view.message = message  # save reference to allow editing later
        return
        
@bot.tree.command(name="pause", description="Pause a song by URL or name")
async def pause(ctx):
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if voice_client.is_playing():
        voice_client.pause()

@bot.tree.command(name="resume", description="Resume a song by URL or name")
async def resume(ctx):
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if voice_client.is_paused():
        voice_client.resume()

@bot.tree.command(name="stop", description="Stop song")
async def stop(ctx):
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if voice_client:
        music_queues[ctx.guild.id].clear()
        voice_client.stop()

@bot.command()
async def toggle_autoplay(ctx):
    global autoplay
    autoplay = not autoplay
    status = "enabled" if autoplay else "disabled"
    await ctx.send(f"Autoplay is now {status}.")
    
@bot.tree.command(name="skip", description="Skip song")
async def skip(ctx):
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if voice_client:
        voice_client.stop()
        await play_next(ctx)
        
discord.opus.load_opus("D:\\nlp\\disc_env\\Lib\\site-packages\\discord\\bin\\libopus-0.x64.dll")
load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
bot.run(TOKEN)
