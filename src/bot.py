import os
import io
import zipfile
import discord
import aiohttp
from dotenv import load_dotenv
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
UPLOAD_CHANNEL_ID = int(os.getenv("UPLOAD_CHANNEL_ID"))
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")


SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
sheets_service = build("sheets", "v4", credentials=creds)
sheet = sheets_service.spreadsheets().values()


def col_to_letter(n):
    result = ""
    n += 1
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        result = chr(65 + remainder) + result
    return result

async def get_sheet():
    resp = sheet.get(spreadsheetId=GOOGLE_SHEET_ID, range="BestTimes!A1:ZZ").execute()
    values = resp.get("values", [])
    headers = values[0] if values else []
    return values, headers

async def write_headers(headers):
    last_col = col_to_letter(len(headers) - 1)
    sheet.update(
        spreadsheetId=GOOGLE_SHEET_ID,
        range=f"BestTimes!A1:{last_col}1",
        valueInputOption="RAW",
        body={"values": [headers]}
    ).execute()

async def ensure_boss_columns(bosses, headers):
    if not headers:
        headers = ["Discord ID", "Username"]

    header_set = {h.lower() for h in headers if h}
    new_bosses = [b for b in bosses if b.lower() not in header_set]

    if new_bosses:
        headers = headers + new_bosses
        await write_headers(headers)
    return headers

def build_header_map(headers):
    return {h.lower(): i for i, h in enumerate(headers)}

def find_user_row(values, discord_id):
    for r in range(1, len(values)):
        if values[r][0] == discord_id:
            return r
    return -1

async def add_user_row(discord_id, username, col_count):
    new_row = [""] * col_count
    new_row[0] = discord_id
    new_row[1] = username

    sheet.append(
        spreadsheetId=GOOGLE_SHEET_ID,
        range="BestTimes!A:ZZ",
        valueInputOption="RAW",
        body={"values": [new_row]}
    ).execute()

async def update_cell(row, col, value):
    col_letter = col_to_letter(col)
    sheet.update(
        spreadsheetId=GOOGLE_SHEET_ID,
        range=f"BestTimes!{col_letter}{row+1}",
        valueInputOption="RAW",
        body={"values": [[value]]}
    ).execute()

# ---------------- Boss TXT Parsing ---------------- #
def parse_boss_txt(txt):
    stats = {}
    for line in txt.splitlines():
        line = line.strip()
        if not line:
            continue

        parts = line.split(" ", 1)
        if len(parts) != 2:
            continue

        num, label = parts
        try:
            num = int(num)
        except:
            continue

        stats[label.strip()] = num
    return stats

async def update_best_times(discord_id, username, boss_data):
    values, headers = await get_sheet()

    boss_names = [b["boss"] for b in boss_data]
    headers = await ensure_boss_columns(boss_names, headers)
    header_map = build_header_map(headers)
    col_count = len(headers)

    # Find or create user row
    row = find_user_row(values, discord_id)
    if row == -1:
        await add_user_row(discord_id, username, col_count)
        values, headers = await get_sheet()
        row = find_user_row(values, discord_id)

    improved = 0

    # Update username in column B
    await update_cell(row, 1, username)

    # Evaluate PB improvements
    for entry in boss_data:
        boss = entry["boss"]
        fastest = entry["fastest"]

        col = header_map.get(boss.lower())
        if col is None:
            continue

        # Old value
        try:
            old_val = int(values[row][col])
        except:
            old_val = None

        if old_val is None or fastest < old_val:
            await update_cell(row, col, fastest)
            improved += 1

    return improved

# ---------------- Discord Bot ---------------- #
intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)


@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user}")


@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if message.channel.id != UPLOAD_CHANNEL_ID:
        return

    if not message.attachments:
        return

    attachment = message.attachments[0]

    if not attachment.filename.lower().endswith(".zip"):
        return

    await message.reply("📦 ZIP detected — parsing...")

    # Download ZIP
    async with aiohttp.ClientSession() as session:
        async with session.get(attachment.url) as resp:
            data = await resp.read()

    z = zipfile.ZipFile(io.BytesIO(data))

    boss_data = []
    for name in z.namelist():
        lower = name.lower()
        if not lower.startswith("bossing-info/"):
            continue
        if not lower.endswith(".txt"):
            continue

        boss_name = os.path.basename(name).replace(".txt", "")
        with z.open(name) as f:
            txt = f.read().decode("utf-8", errors="ignore")

        stats = parse_boss_txt(txt)
        fastest = stats.get("Fastest Kill")
        if fastest is not None:
            boss_data.append({"boss": boss_name, "fastest": fastest})

    if not boss_data:
        await message.reply("❌ No valid bossing-info/*.txt files found.")
        return

    improved = await update_best_times(
        str(message.author.id),
        message.author.display_name,
        boss_data
    )

    await message.reply(
        f"✅ Updated PBs! Improved **{improved}** boss times."
    )

















    


client.run(DISCORD_TOKEN)
