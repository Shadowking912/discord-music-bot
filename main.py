import discord
from discord.ext import commands
import yt_dlp as youtube_dl
import asyncio
import nacl
from ytmusicapi import YTMusic
from keep_alive import keep_alive
from discord.ui import Button, View
from discord import Embed
import random
import os

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
autoplay = True  # Enable autoplay

async def shutdown_if_no_active_members():
    await client.wait_until_ready()
    guild = client.get_guild(GUILD_ID)
    while True:
        members = [m for m in guild.members if not m.bot]
        online = [m for m in members if m.status != discord.Status.offline]

        if len(online) == 0:
            print("No users online. Shutting down.")
            await client.close()
            os._exit(0)  # optional: ensure full shutdown

        await asyncio.sleep(300)  # Check every 5 minutes

def create_now_playing_embed(title, url, requester, duration,next_title,next_url):
    embed = Embed(
        title="🎶 Now Playing",
        description=f"**Track:** [{title}]({url})\n**Requested By:** {requester}  **Duration:** `{duration}`\n **Next**:[{next_title}]({next_url}) \n\n`~/equalizer for custom track control ~`",
        color=0x1DB954  # Spotify green, or use red/blue
    )
    return embed

class MusicPlayerView(View):
    def __init__(self, ctx, is_paused=False, message=None):
        super().__init__(timeout=None)
        self.ctx = ctx
        self.is_paused = is_paused
        self.message = message  # to store the message for later edit

    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction, button):
        await interaction.response.send_message("Previous track (not implemented)", ephemeral=True)

    @discord.ui.button(label="⏸️ Pause", custom_id="pause", style=discord.ButtonStyle.primary)
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
        label = "▶️ Play" if self.is_paused else "⏸️ Pause"
        new_view.pause_button.label = label

        await interaction.response.edit_message(view=new_view)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.primary)
    async def skip(self, interaction, button):
        voice_client = discord.utils.get(bot.voice_clients, guild=self.ctx.guild)
        await interaction.response.send_message("Skipped", ephemeral=True)
        
        if voice_client:
            voice_client.stop()
            await play_next(self.ctx)
            

    @discord.ui.button(emoji="🔇", style=discord.ButtonStyle.secondary)
    async def mute(self, interaction, button):
        await interaction.response.send_message("Muted (not implemented)", ephemeral=True)

    @discord.ui.button(emoji="🔊", style=discord.ButtonStyle.secondary)
    async def unmute(self, interaction, button):
        await interaction.response.send_message("Unmuted (not implemented)", ephemeral=True)

    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary)
    async def loop(self, interaction, button):
        await interaction.response.send_message("Loop toggled (not implemented)", ephemeral=True)

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger)
    async def stop(self, interaction, button):
        voice_client = discord.utils.get(bot.voice_clients, guild=self.ctx.guild)
        if voice_client:
            music_queues[self.ctx.guild.id].clear()
            music_auto_queues[self.ctx.guild.id].clear()
            voice_client.stop()
            await interaction.response.send_message("Stopped", ephemeral=True)



@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f'Logged in as {bot.user}')

@bot.command()
async def join(ctx):
    if ctx.user.voice:
        channel = ctx.user.voice.channel
        await channel.connect()
        print(f'Joined {channel}')
    else:
        await ctx.send("Join a voice channel first!")

async def search_youtube(query):
    search2=ytmusic.search(query)[0]
    video_url="https://www.youtube.com/watch?v="+search2['videoId']
    title=search2['title']
    return video_url,title

async def get_related_video(video_url):
    video_id=video_url.split("=")[-1]
    search2=random.choice(ytmusic.get_watch_playlist(video_id)['tracks'][1:])
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
            
    info= ytdl.extract_info(url, download=False)
    url2 = info['url']
    music_queues[ctx.guild.id].append((url2,url, title))
    await ctx.followup.send(f"Added to queue: {title}")

    if not voice_client.is_playing():
        await play_next(ctx, requester=ctx.user)

async def play_next(ctx,requester=None):
    view=MusicPlayerView(ctx)
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if not voice_client or not voice_client.is_connected():
        await join(ctx)
        voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
        
    if voice_client.is_playing() or voice_client.is_paused():
        return  # Already playing something, do not re-enter
    if len(music_queues[ctx.guild.id])>0:
        url2,url,title = music_queues[ctx.guild.id].pop(0)
        source = discord.FFmpegPCMAudio(url2, executable="ffmpeg")
        voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(ctx),bot.loop))
        
        if autoplay:
            if len(music_auto_queues[ctx.guild.id])==0:
                last_played_url = url if 'url' in locals() else None
                next_title=""
                next_url=""
                if last_played_url:
                    next_url, next_title = await get_related_video(last_played_url)
                    if next_url:
                        info= ytdl.extract_info(next_url, download=False)
                        next_url2 = info['url']
                        music_auto_queues[ctx.guild.id].append((next_url2,next_url,next_title))
                        # await ctx.channel.send(f"Autoplay: Added to queue: {next_title}",view=view)
                
                embed = create_now_playing_embed(title, url, requester, "Unknown Duration",next_title,next_url)
                message = await ctx.channel.send(embed=embed, view=view)
                view.message = message  # save reference to allow editing later

                        
            else:
                # await ctx.channel.send(f"Autoplay: Added to queue: {music_auto_queues[ctx.guild.id][0][2]}",view=view)
                embed = create_now_playing_embed(title, url, requester, "Unknown Duration",music_auto_queues[ctx.guild.id][0][2],music_auto_queues[ctx.guild.id][0][1])
                message = await ctx.channel.send(embed=embed, view=view)
                view.message = message  # save reference to allow editing later

  
        return

    if len(music_queues[ctx.guild.id])==0:
        print("len",len(music_auto_queues[ctx.guild.id]))
        if len(music_auto_queues[ctx.guild.id])>0:
            url2,url,title = music_auto_queues[ctx.guild.id].pop(0)
            source = discord.FFmpegPCMAudio(url2, executable="ffmpeg")
            voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(ctx),bot.loop))
            
            if autoplay and len(music_auto_queues[ctx.guild.id])==0:
                last_played_url = url if 'url' in locals() else None
                next_title=""
                next_url=""
                if last_played_url:
                    next_url, next_title = await get_related_video(last_played_url)
                    if next_url:
                        info= ytdl.extract_info(next_url, download=False)
                        next_url2 = info['url']
                        music_auto_queues[ctx.guild.id].append((next_url2,next_url,next_title))
                        
                embed = create_now_playing_embed(title, url, "Autoplay", "Unknown Duration",next_title,next_url)
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
        
keep_alive()
discord.opus.load_opus("libopus.so")
TOKEN = os.environ.get('discord_token')
bot.run(TOKEN)
