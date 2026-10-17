import os
import json
import discord
from discord import app_commands
from discord.ext import commands, tasks

DATA_FILE = "player_data.json"

DEFAULT_DATA = {
    "linked_players": {},
    "kill_counts": {},
    "duel_data": {
        "active_duels": [],
        "duel_stats": {}
    },
    "kill_receipts": [],
    "recovery_audit": [],
    "reset_audit": []
}

def load_data():
    if not os.path.exists(DATA_FILE):
        save_data(DEFAULT_DATA)
        return DEFAULT_DATA
    try:
        with open(DATA_FILE, "r") as f:
            content = f.read().strip()
            if not content:
                return DEFAULT_DATA
            return json.loads(content)
    except Exception:
        return DEFAULT_DATA

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

class DuelView(discord.ui.View):
    def __init__(self, challenger: discord.Member, opponent: discord.Member):
        super().__init__(timeout=60)
        self.challenger = challenger
        self.opponent = opponent

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.green)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.opponent.id:
            await interaction.response.send_message("Only the challenged player can respond.", ephemeral=True)
            return
        
        for child in self.children:
            child.disabled = True
        
        data = load_data()
        challenger_id = str(self.challenger.id)
        opponent_id = str(self.opponent.id)
        
        for uid in [challenger_id, opponent_id]:
            if uid not in data["duel_data"]["duel_stats"]:
                data["duel_data"]["duel_stats"][uid] = {"wins": 0, "losses": 0}
        
        save_data(data)

        await interaction.response.edit_message(content=f"⚔️ **Duel Accepted!** {self.opponent.mention} has accepted the challenge from {self.challenger.mention}. Good luck!", view=self)
        self.stop()

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.red)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.opponent.id:
            await interaction.response.send_message("Only the challenged player can respond.", ephemeral=True)
            return
        
        for child in self.children:
            child.disabled = True
        
        await interaction.response.edit_message(content=f"❌ **Duel Declined.** {self.opponent.mention} declined the challenge from {self.challenger.mention}.", view=self)
        self.stop()

class RogueBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        if not self.update_leaderboards_loop.is_running():
            self.update_leaderboards_loop.start()
        print("Slash commands synced and leaderboard loop started.")

    @tasks.loop(minutes=5)
    async def update_leaderboards_loop(self):
        data = load_data()
        for guild in self.guilds:
            kd_channel = discord.utils.get(guild.text_channels, name="kd-leaderboard")
            duel_channel = discord.utils.get(guild.text_channels, name="1v1-leaderboard")
            
            if kd_channel:
                sorted_kills = sorted(data["kill_counts"].items(), key=lambda x: x[1].get("kills", 0), reverse=True)[:5]
                embed = discord.Embed(title="Global Kill Leaderboard", color=discord.Color.gold())
                desc = ""
                for idx, (ald_key, stats) in enumerate(sorted_kills, 1):
                    kills = stats.get("kills", 0)
                    deaths = stats.get("deaths", 0)
                    kd = kills if deaths == 0 else round(kills / deaths, 2)
                    desc += f"{idx}. {ald_key.replace('alderon:', '')} — Kills: {kills} · Deaths: {deaths} · K/D: {kd}\n"
                
                if not desc:
                    desc = "No recorded kills yet."
                embed.description = desc
                embed.set_footer(text="Auto-updating global kill leaderboard")
                
            if duel_channel:
                sorted_duels = sorted(data["duel_data"]["duel_stats"].items(), key=lambda x: x[1].get("wins", 0), reverse=True)[:5]
                embed_duel = discord.Embed(title="1v1 Duel Leaderboard", color=discord.Color.blurple())
                desc_duel = ""
                for idx, (uid, stats) in enumerate(sorted_duels, 1):
                    wins = stats.get("wins", 0)
                    losses = stats.get("losses", 0)
                    total = wins + losses
                    winrate = round((wins / total) * 100, 1) if total > 0 else 0.0
                    desc_duel += f"{idx}. <@{uid}> — Wins: {wins} · Losses: {losses} · Win rate: {winrate}%\n"
                    
                if not desc_duel:
                    desc_duel = "No recorded duels yet."
                embed_duel.description = desc_duel
                embed_duel.set_footer(text="Auto-updating 1v1 wins, losses, and win rates")

    @update_leaderboards_loop.before_loop
    async def before_leaderboards(self):
        await self.wait_until_ready()

bot = RogueBot()

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

@bot.tree.command(name="linkname", description="Link your Path of Titans name and Alderon ID.")
@app_commands.describe(in_game_name="Your in-game dinosaur/player name", alderon_id="Your Alderon ID")
async def linkname(interaction: discord.Interaction, in_game_name: str, alderon_id: str):
    data = load_data()
    user_id = str(interaction.user.id)
    
    data["linked_players"][user_id] = {
        "alderon_id": alderon_id,
        "discord_name": interaction.user.name,
        "player_name": in_game_name
    }
    
    save_data(data)
    await interaction.response.send_message(f"Successfully linked **{in_game_name}** with Alderon ID: **{alderon_id}**!", ephemeral=True)

@bot.tree.command(name="kd", description="Check Kills, Deaths, and K/D ratio for yourself or another player.")
@app_commands.describe(member="The member to check (leave blank for yourself)")
async def kd(interaction: discord.Interaction, member: discord.Member = None):
    target = member or interaction.user
    data = load_data()
    
    user_id = str(target.id)
    linked_info = data["linked_players"].get(user_id)
    
    if not linked_info:
        await interaction.response.send_message(f"{target.mention} has not linked their account yet using `/linkname`.", ephemeral=True)
        return
        
    alderon_key = f"alderon:{linked_info['alderon_id']}"
    stats = data["kill_counts"].get(alderon_key, {"kills": 0, "deaths": 0})
    kills = stats.get("kills", 0)
    deaths = stats.get("deaths", 0)
    
    kd_ratio = kills if deaths == 0 else round(kills / deaths, 2)
    
    embed = discord.Embed(title=f"Path of Titans K/D Profile — {linked_info['player_name']}", color=discord.Color.blurple())
    embed.add_field(name="Alderon ID", value=linked_info['alderon_id'], inline=False)
    embed.add_field(name="Kills", value=str(kills), inline=True)
    embed.add_field(name="Deaths", value=str(deaths), inline=True)
    embed.add_field(name="K/D Ratio", value=str(kd_ratio), inline=True)
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="duel", description="Challenge another player to a 1v1 duel.")
@app_commands.describe(member="The player you want to challenge")
async def duel(interaction: discord.Interaction, member: discord.Member):
    if member.id == interaction.user.id:
        await interaction.response.send_message("You can't duel yourself!", ephemeral=True)
        return
    
    if member.bot:
        await interaction.response.send_message("You can't duel a bot!", ephemeral=True)
        return

    view = DuelView(challenger=interaction.user, opponent=member)
    
    embed = discord.Embed(title="⚔️ Duel Challenge", color=discord.Color.gold())
    embed.add_field(name="Challenger", value=interaction.user.mention, inline=True)
    embed.add_field(name="Opponent", value=member.mention, inline=True)
    embed.description = f"Status: Waiting for {member.mention} to respond.\nOnly {member.mention} can respond."

    await interaction.response.send_message(content=member.mention, embed=embed, view=view)

TOKEN = os.getenv("DISCORD_TOKEN")
if TOKEN:
    bot.run(TOKEN)
