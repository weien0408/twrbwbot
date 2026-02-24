import discord
from discord import app_commands
from discord.ext import commands
import json
import os
import random
import string
import aiohttp
import asyncio


HYPIXEL_API_KEY = "你的 Hypixel API Key"
TOKEN = "你的token"


REGISTER_CHANNEL_ID = 1475909779560992888
CATEGORY_ID = 1475528586143469840           
REPORT_LOG_CHANNEL_ID = 1471948355746791688   
RESULT_ANNOUNCE_CHANNEL_ID = 1475525389047566448  
OWNER_ROLE_ID = 1471934455705895047
ADMIN_ROLE_ID = 1471948205120946351
START_ROLE_ID = 1472352718722175190  

PLAYERS_DB = "players.json"
USER_DB = "user.json"
GATED_CHANNELS_DB = "gated_vcs.json"


SERVER_RULES = """
# 伺服器規則
## 1.對任何人請保持尊重、友善與包容
## 2.私人糾紛或是要吵架的請私下解決
## 3.禁止有威脅、騷擾、挑釁、性別歧視、種族歧視、仇恨言論、貶低、過度批判、腥羶色或讓人不舒服的文字與照片出現
## 4.禁止冒充他人
## 5.禁止刷屏
## 6.禁止未經對方允許擅自在語音頻道錄音、錄影

# 以上如有觸犯第一次禁言30天 第二次BAN
"""
SEASON_RULES = """
# 📜 賽季規則
## 🟢 全場可以使用
1. 階梯
2. 鑽石裝
3. 鑽石劍
4. 冰橋
5. 藍隊跟黃隊的島嶼
## 💎 鑽石 III 之後
1. 跳躍藥水
2. 速度藥水
## 🟢 綠寶 III 之後
1. 擊退棒
## ⚠️ 床被破壞後
1. 隱形藥水
2. 水桶
3. 終界珍珠
4. 火球炸鑽石島
5. 弓箭
## 🚫 全場禁止：黑曜石、活動物品
"""


RANKS = [
    (0, 200, 1471938798194528326),      
    (200, 400, 1471938837218328730),     
    (400, 600, 1471938873935270043),     
    (600, 800, 1471938889311719576),     
    (800, 1100, 1475783251397447843),    
    (1100, 1400, 1475783285836615742),   
    (1400, float("inf"), 1475783308234199225) 
]


def load_db(file):
    if not os.path.exists(file):
        with open(file, "w", encoding="utf-8") as f: json.dump({}, f)
        return {}
    with open(file, "r", encoding="utf-8") as f:
        try: return json.load(f)
        except: return {}

def save_db(file, data):
    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


async def update_member_visuals(member, elo, ign):
    if not member or isinstance(member, discord.User):
        return
    new_nick = f"({int(elo)}) {ign}"
    try:
        if member.nick != new_nick:
            await member.edit(nick=new_nick)
    except:
        pass

    target_role_id = None
    for low, high, role_id in RANKS:
        if low <= elo < high:
            target_role_id = role_id
            break
    if not target_role_id: return

    guild = member.guild
    target_role = guild.get_role(target_role_id)
 
    for _, _, role_id in RANKS:
        role = guild.get_role(role_id)
        if role in member.roles and role.id != target_role_id:
            await member.remove_roles(role)
  
    if target_role and target_role not in member.roles:
        await member.add_roles(target_role)


async def verify_hypixel(ign, discord_tag):
    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://api.mojang.com/users/profiles/minecraft/{ign}") as resp:
            if resp.status != 200: return "PLAYER_NOT_FOUND", None
            mojang_data = await resp.json()
            uuid = mojang_data['id']
        params = {"key": HYPIXEL_API_KEY, "uuid": uuid}
        async with session.get("https://api.hypixel.net/v2/player", params=params) as resp:
            if resp.status != 200: return "API_ERROR", None
            data = await resp.json()
            player_data = data.get('player')
            if not player_data: return "PLAYER_DATA_MISSING", None
            linked_discord = player_data.get('socialMedia', {}).get('links', {}).get('DISCORD')
            if linked_discord == discord_tag:
                return "SUCCESS", uuid
            else:
                return "DISCORD_MISMATCH", linked_discord


class SettlementView(discord.ui.View):
    def __init__(self, team_a, team_b, code, img_url):
        super().__init__(timeout=None)
        self.team_a = team_a
        self.team_b = team_b
        self.code = code
        self.img_url = img_url

        win_options = [
            discord.SelectOption(label="Team A (🔵) 勝", value="A"),
            discord.SelectOption(label="Team B (🔴) 勝", value="B"),
            discord.SelectOption(label="比賽作廢", value="VOID")
        ]
        self.add_item(discord.ui.Select(placeholder="🏆 選擇獲勝隊伍...", options=win_options, custom_id="win_select"))

        all_players = team_a + team_b
        mvp_options = [discord.SelectOption(label=p.display_name, value=str(p.id)) for p in all_players]
        self.add_item(discord.ui.Select(placeholder="🌟 選擇該場 MVP...", options=mvp_options, custom_id="mvp_select"))

    @discord.ui.button(label="✅ 確認結算", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction):
        staff_roles = [OWNER_ROLE_ID, ADMIN_ROLE_ID]
        if not any(r.id in staff_roles for r in interaction.user.roles):
            return await interaction.response.send_message("❌ 你不是管理員，別亂點！", ephemeral=True)

        win_side = next(i for i in self.children if i.custom_id == "win_select").values[0]
        mvp_id = next(i for i in self.children if i.custom_id == "mvp_select").values[0]

        if win_side == "VOID":
            await interaction.response.send_message(f"🚫 比賽 `{self.code}` 已作廢。")
            return await interaction.message.delete()

        p_db = load_db(PLAYERS_DB)
        winners = self.team_a if win_side == "A" else self.team_b
        losers = self.team_b if win_side == "A" else self.team_a

        for p in winners:
            p_db[str(p.id)]["elo"] += (25 if str(p.id) == mvp_id else 20)
            p_db[str(p.id)]["wins"] += 1
        for p in losers:
            if str(p.id) != mvp_id:
                p_db[str(p.id)]["elo"] = max(0, p_db[str(p.id)]["elo"] - 20)
            p_db[str(p.id)]["losses"] += 1

        save_db(PLAYERS_DB, p_db)

        for p in (self.team_a + self.team_b):
            await update_member_visuals(p, p_db[str(p.id)]["elo"], p_db[str(p.id)]["ign"])

        ann_channel = bot.get_channel(RESULT_ANNOUNCE_CHANNEL_ID)
        embed = discord.Embed(title=f"⚔️ 比賽結算完成: {self.code}", color=0xFFD700)
        embed.add_field(name="結果", value=f"Team {win_side} 獲勝", inline=True)
        embed.add_field(name="MVP", value=p_db[mvp_id]["ign"], inline=True)
        embed.set_image(url=self.img_url)
        await ann_channel.send(embed=embed)

        await interaction.response.send_message(f"✅ 已成功結算比賽 `{self.code}`")
        await interaction.message.delete()


class PickingView(discord.ui.View):
    def __init__(self, cap_a, cap_b, pool, code, txt_chan):
        super().__init__(timeout=None)  
        self.cap_a, self.cap_b, self.pool, self.code, self.txt_chan = cap_a, cap_b, pool, code, txt_chan
        self.team_a, self.team_b, self.turn = [cap_a], [cap_b], cap_a
        self.refresh_select()

    def refresh_select(self):
        self.clear_items()
        options = [discord.SelectOption(label=p.display_name, value=str(p.id)) for p in self.pool]
        select = discord.ui.Select(placeholder=f"請 {self.turn.display_name} 挑選成員...", options=options)
        select.callback = self.pick_callback
        self.add_item(select)

    async def pick_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.turn.id:
            return await interaction.response.send_message("不是你的回合！", ephemeral=True)

        picked_id = interaction.data['values'][0]
        picked_member = next(p for p in self.pool if str(p.id) == picked_id)
        self.pool.remove(picked_member)

        if self.turn == self.cap_a:
            self.team_a.append(picked_member)
            self.turn = self.cap_b if self.pool else None
        else:
            self.team_b.append(picked_member)
            self.turn = self.cap_a if self.pool else None

        if not self.pool:
            await self.start_match(interaction)
        else:
            self.refresh_select()
            await interaction.response.edit_message(content=f"🔵 Team A: {len(self.team_a)}/4 | 🔴 Team B: {len(self.team_b)}/4\n等待 {self.turn.mention} 選人...", view=self)

    async def start_match(self, interaction):
        cat = bot.get_channel(CATEGORY_ID)
        vc_a = await interaction.guild.create_voice_channel(f"🔵 Team A | {self.code}", category=cat)
        vc_b = await interaction.guild.create_voice_channel(f"🔴 Team B | {self.code}", category=cat)
        for p in self.team_a: await p.move_to(vc_a)
        for p in self.team_b: await p.move_to(vc_b)

        u_db = load_db(USER_DB)
        def get_ign(p): return u_db.get(str(p.id), p.display_name)
        cmd_a = f"/p {' '.join([get_ign(p) for p in self.team_a])}"
        cmd_b = f"/p {' '.join([get_ign(p) for p in self.team_b])}"

        embed = discord.Embed(title="⚔️ 隊伍分配完畢", description=SEASON_RULES, color=0x2ecc71)
        embed.add_field(name="🔵 Team A 指令", value=f"```{cmd_a}```", inline=False)
        embed.add_field(name="🔴 Team B 指令", value=f"```{cmd_b}```", inline=False)
        await self.txt_chan.send(content=" ".join([p.mention for p in self.team_a + self.team_b]), embed=embed)
        await interaction.message.delete()


class BedwarsBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.all())
    async def setup_hook(self):
        await self.tree.sync()

bot = BedwarsBot()


@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot: return
    if after.channel:
        gated = load_db(GATED_CHANNELS_DB)
        if str(after.channel.id) in gated:
            cfg = gated[str(after.channel.id)]
            p_data = load_db(PLAYERS_DB).get(str(member.id))
            elo = p_data['elo'] if p_data else -1
            if not (cfg['min'] <= elo <= cfg['max']):
                try:
                    await member.move_to(None)
                    await member.send(f" 分數不符！該頻道 ELO 門檻: `{cfg['min']} - {cfg['max']}`，你目前: `{elo if elo != -1 else '未註冊'}`")
                except: pass
                return

    if after.channel and len(after.channel.members) == 8:
        players = list(after.channel.members)
        match_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        captains = random.sample(players, 2)
        guild = member.guild
        category = bot.get_channel(CATEGORY_ID)
        overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False),
                      **{p: discord.PermissionOverwrite(view_channel=True) for p in players}}
        text_chan = await guild.create_text_channel(f"game-{match_code.lower()}", category=category, overwrites=overwrites)
        await text_chan.send(f"🎮 **比賽開始! ID: {match_code}**\n🔵 隊長: {captains[0].mention}\n🔴 隊長: {captains[1].mention}",
                             view=PickingView(captains[0], captains[1], [p for p in players if p not in captains], match_code, text_chan))


@bot.tree.command(name="profile", description="查看戰績")
async def profile(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    db = load_db(PLAYERS_DB)
    data = db.get(str(member.id))
    if not data: return await interaction.response.send_message("❌ 此玩家尚未註冊。")
    embed = discord.Embed(title=f"📊 {data['ign']} 的戰績清單", color=0x3498db)
    embed.add_field(name="積分 (ELO)", value=f"`{data['elo']}`", inline=True)
    embed.add_field(name="勝/敗", value=f"`{data['wins']}W / {data['losses']}L`", inline=True)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="leaderboard", description="查看 ELO 排行榜")
async def leaderboard(interaction: discord.Interaction):
    db = load_db(PLAYERS_DB)
    sorted_players = sorted(db.items(), key=lambda x: x[1]['elo'], reverse=True)[:10]
    txt = "\n".join([f"**#{i+1}** {v['ign']} — `{v['elo']}` ELO" for i, (k,v) in enumerate(sorted_players)])
    await interaction.response.send_message(embed=discord.Embed(title="🏆 全服前 10 名排行榜", description=txt or "尚無數據", color=0xf1c40f))


@bot.tree.command(name="register", description="綁定 Minecraft 帳號")
async def register(interaction: discord.Interaction, ign: str):

    
    if interaction.channel.id != REGISTER_CHANNEL_ID:
        return await interaction.response.send_message(
            f" 請到指定頻道使用此指令！",
            ephemeral=True
        )

    
    await interaction.response.defer()
    status, result = await verify_hypixel(ign, str(interaction.user))
    if status == "SUCCESS":
        u_db, p_db = load_db(USER_DB), load_db(PLAYERS_DB)
        u_db[str(interaction.user.id)] = ign
        p_db[str(interaction.user.id)] = {"ign": ign, "elo": 0, "wins": 0, "losses": 0, "uuid": result}
        save_db(USER_DB, u_db)
        save_db(PLAYERS_DB, p_db)
        role = interaction.guild.get_role(START_ROLE_ID)
        if role: await interaction.user.add_roles(role)
        await update_member_visuals(interaction.user, 0, ign)
        await interaction.followup.send(f"✅ 註冊成功！歡迎 {ign}。")
        msg = await interaction.original_response()
        await asyncio.sleep(3)
        await msg.delete()
    else:
        msg = {
            "PLAYER_NOT_FOUND": "找不到該玩家，請檢查 ID 是否拼錯。",
            "API_ERROR": "Hypixel API 暫時連線失敗，請稍後再試。",
            "DISCORD_MISMATCH": f"連結不符！Hypixel 內設定為 {result}，但你的 Discord 是 {interaction.user}。",
            "NO_LINKED_DISCORD": "你尚未在 Hypixel 內連結 Discord。"
        }.get(status, "發生未知錯誤。")
        await interaction.followup.send(f" 驗證失敗：{msg}")
        msg = await interaction.original_response()
        await asyncio.sleep(3)
        await msg.delete()


    


@bot.tree.command(name="report_win", description="回報勝場 (需附上截圖)")
async def report_win(interaction: discord.Interaction, screenshot: discord.Attachment):
    if "game-" not in interaction.channel.name:
        return await interaction.response.send_message(" 請在比賽專屬頻道使用此指令！", ephemeral=True)
    code = interaction.channel.name.split("-")[1].upper()
    all_members = [m for m in interaction.channel.members if not m.bot]
    log_chan = bot.get_channel(REPORT_LOG_CHANNEL_ID)
    await log_chan.send(f" **來自頻道 {interaction.channel.name} 的結算請求**",
                        view=SettlementView(all_members[:4], all_members[4:], code, screenshot.url))
    await interaction.response.send_message(" 數據已送往管理員室審核！")


@bot.tree.command(name="setup_vc", description="admin commands")
@app_commands.checks.has_permissions(manage_guild=True)
async def setup_vc(interaction: discord.Interaction, channel: discord.VoiceChannel, min_elo: int, max_elo: int):
    staff_roles = [OWNER_ROLE_ID, ADMIN_ROLE_ID]
    if not any(r.id in staff_roles for r in interaction.user.roles):
        return await interaction.response.send_message(" 權限不足", ephemeral=True)
    db = load_db(GATED_CHANNELS_DB)
    db[str(channel.id)] = {"min": min_elo, "max": max_elo}
    save_db(GATED_CHANNELS_DB, db)
    await interaction.response.send_message(f" 設定成功！{channel.mention} 現在僅限 ELO {min_elo}-{max_elo} 進入。")




@bot.tree.command(name="rules", description="admin commands")
async def rules(interaction: discord.Interaction):
    staff_roles = [OWNER_ROLE_ID, ADMIN_ROLE_ID]

    if not any(r.id in staff_roles for r in interaction.user.roles):
        return await interaction.response.send_message(" 權限不足。", ephemeral=True)

    embed = discord.Embed(
        title="📜 規則",
        description=SERVER_RULES,
        color=0x2ecc71
    )

    await interaction.response.send_message(" 規則已發送", ephemeral=True)
    await interaction.channel.send(embed=embed)


@bot.tree.command(name="howtoplay", description="admin commands")
async def howtoplay(interaction: discord.Interaction):

    staff_roles = [OWNER_ROLE_ID, ADMIN_ROLE_ID]

    if not any(role.id in staff_roles for role in interaction.user.roles):
        return await interaction.response.send_message(
            "❌ 只有管理員可以使用此指令。",
            ephemeral=True
        )
    

    await interaction.response.defer(ephemeral=True)
    file_path = r"C:\Users\swxhz\OneDrive\Desktop\twrbw\kirby-roblox.gif"
    file = discord.File(file_path, filename="kirby-roblox.gif")
    
    try:
        await interaction.delete_original_response()  
    except:
        pass  

    
    embed = discord.Embed(
        title=" 怎麼連到 Minecraft 帳號？",
        description="""
# 怎麼連到Minecraft帳號

## 1. 進到 hypixel.net 然後選到個人檔案
## 2. 之後選擇社群媒體
## 3. 點選 discord
## 4. 在聊天室輸入你的 dc id
## 5. 之後回到這裡輸入 /register {你的ID}

by twrbw bot
""",
        color=0x3498db
    )
    embed.set_image(url="attachment://kirby-roblox.gif")

    
    msg = await interaction.followup.send(embed=embed, file=file)
    
 


bot.run(TOKEN)