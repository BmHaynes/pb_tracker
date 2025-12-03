import os
import re

import discord
from dotenv import load_dotenv
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

# ---------------- Load settings from .env ---------------- #

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
UPLOAD_CHANNEL_ID = int(os.getenv("UPLOAD_CHANNEL_ID"))  # channel where files go

GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")

# ---------------- Google Sheets setup ---------------- #

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
sheets_service = build("sheets", "v4", credentials=creds)
sheet = sheets_service.spreadsheets().values()


def col_to_letter(n: int) -> str:
    # 0 -> A, 1 -> B, etc.
    result = ""
    n += 1
    while n > 0:
        n, r = divmod(n - 1, 26)
        result = chr(65 + r) + result
    return result


def get_sheet():
    resp = sheet.get(
        spreadsheetId=GOOGLE_SHEET_ID,
        range="BestTimes!A1:ZZ"
    ).execute()
    values = resp.get("values", [])
    headers = values[0] if values else []
    return values, headers


def write_headers(headers):
    last_col = col_to_letter(len(headers) - 1)
    sheet.update(
        spreadsheetId=GOOGLE_SHEET_ID,
        range=f"BestTimes!A1:{last_col}1",
        valueInputOption="RAW",
        body={"values": [headers]},
    ).execute()


def ensure_boss_columns(bosses, headers):
    # First time, create basic headers
    if not headers:
        headers = ["Discord ID", "Username"]

    existing = {h.lower() for h in headers if h}
    new_bosses = [b for b in bosses if b.lower() not in existing]

    if new_bosses:
        headers = headers + new_bosses
        write_headers(headers)

    return headers


def build_header_map(headers):
    return {h.lower(): i for i, h in enumerate(headers)}


def find_user_row(values, discord_id):
    # Find the row index (starting from 0) where this Discord ID is
    for row_index in range(1, len(values)):  # row 0 is headers
        row = values[row_index]
        if row and row[0] == discord_id:
            return row_index
    return -1


def add_user_row(discord_id, username, col_count):
    new_row = [""] * col_count
    new_row[0] = discord_id
    new_row[1] = username

    sheet.append(
        spreadsheetId=GOOGLE_SHEET_ID,
        range="BestTimes!A:ZZ",
        valueInputOption="RAW",
        body={"values": [new_row]},
    ).execute()


def update_cell(row, col, value):
    col_letter = col_to_letter(col)
    sheet.update(
        spreadsheetId=GOOGLE_SHEET_ID,
        range=f"BestTimes!{col_letter}{row + 1}",
        valueInputOption="RAW",
        body={"values": [[value]]},
    ).execute()


def update_best_times(discord_id, username, boss_data):
    """
    boss_data is a list of: { "boss": name, "fastest": seconds_int }
    """
    values, headers = get_sheet()

    # Make sure all bosses have a column
    boss_names = [b["boss"] for b in boss_data]
    headers = ensure_boss_columns(boss_names, headers)
    header_map = build_header_map(headers)
    col_count = len(headers)

    # Find or create the user's row
    row_index = find_user_row(values, discord_id)
    if row_index == -1:
        add_user_row(discord_id, username, col_count)
        # Reload sheet to get the new row
        values, headers = get_sheet()
        header_map = build_header_map(headers)
        row_index = find_user_row(values, discord_id)

    # Make sure row exists and has enough columns
    if row_index >= len(values):
        values.append([""] * col_count)

    row = values[row_index]
    if len(row) < col_count:
        row = row + [""] * (col_count - len(row))

    # Update username (column B)
    update_cell(row_index, 1, username)

    improved = 0

    # Go through each boss PB
    for entry in boss_data:
        boss = entry["boss"]
        fastest = entry["fastest"]

        col = header_map.get(boss.lower())
        if col is None:
            continue

        old_val_str = row[col] if col < len(row) else ""

        try:
            old_val = int(old_val_str)
        except (ValueError, TypeError):
            old_val = None

        # Only update if better (lower) or no value yet
        if old_val is None or fastest < old_val:
            update_cell(row_index, col, fastest)
            improved += 1

    return improved


# ---------------- RuneLite rsprofile parsing ---------------- #

def simple_unescape(name: str) -> str:
    """
    Basic unescaping: turns "duke\ sucellus" into "duke sucellus".
    This doesn't try to handle every possible escape, just the common ones.
    """
    name = name.replace("\\ ", " ")
    name = name.replace("\\:", ":")
    name = name.replace("\\=", "=")
    name = name.replace("\\\\", "\\")
    return name


def parse_rsprofile_properties(text: str):
    """
    Read an rsprofile--1.properties string and return:

    osrs_name (can be None),
    boss_data = [ { "boss": boss_name, "fastest": seconds_int }, ... ]
    """

    type_re = re.compile(r"^rsprofile\.rsprofile\.(\w+)\.type=(.+)$")
    name_re = re.compile(r"^rsprofile\.rsprofile\.(\w+)\.displayName=(.+)$")
    pb_re = re.compile(r"^personalbest\.rsprofile\.(\w+)\.(.+)=(.+)$")

    types = {}
    names = {}
    pbs = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        m = type_re.match(line)
        if m:
            hash_id, t = m.groups()
            types[hash_id] = t.strip()
            continue

        m = name_re.match(line)
        if m:
            hash_id, n = m.groups()
            names[hash_id] = n.strip()
            continue

        m = pb_re.match(line)
        if m:
            hash_id, boss_raw, value_raw = m.groups()
            pbs.setdefault(hash_id, {})[boss_raw.strip()] = value_raw.strip()
            continue

    if not pbs:
        return None, []

    # Choose which profile to use:
    # Prefer STANDARD profiles that have PBs
    chosen_hash = None
    for h, t in types.items():
        if t == "STANDARD" and h in pbs:
            chosen_hash = h
            break

    # If none found, just use the first PB hash
    if chosen_hash is None:
        chosen_hash = next(iter(pbs.keys()))

    osrs_name = names.get(chosen_hash)
    boss_data = []

    for boss_raw, value_raw in pbs[chosen_hash].items():
        boss_name = simple_unescape(boss_raw)

        try:
            seconds = float(value_raw)
            seconds = int(round(seconds))
        except ValueError:
            continue

        boss_data.append({
            "boss": boss_name,
            "fastest": seconds,
        })

    # Sort for consistency (optional)
    boss_data.sort(key=lambda x: x["boss"].lower())
    return osrs_name, boss_data


# ---------------- Discord bot setup ---------------- #

intents = discord.Intents.default()
intents.message_content = True  # make sure this is also enabled in the Discord dev portal

client = discord.Client(intents=intents)


@client.event
async def on_ready():
    print(f"Logged in as {client.user}")


@client.event
async def on_message(message: discord.Message):
    # Ignore messages from bots
    if message.author.bot:
        return

    # Only listen in the configured channel
    if message.channel.id != UPLOAD_CHANNEL_ID:
        return

    if not message.attachments:
        return

    attachment = message.attachments[0]
    filename_lower = attachment.filename.lower()

    # We only care about RuneLite profile .properties files
    if not (filename_lower.endswith(".properties") and "rsprofile" in filename_lower):
        return

    await message.reply("Found RuneLite profile file, reading boss personal bests...")

    # Download the file bytes and decode as text
    data = await attachment.read()
    text = data.decode("utf-8", errors="ignore")

    osrs_name, boss_data = parse_rsprofile_properties(text)

    if not boss_data:
        await message.reply(
            "I couldn't find any boss personal bests in that file.\n"
            "Make sure it's your `rsprofile--1.properties` from `~/.runelite/profiles2/` "
            "and that you have at least one boss PB."
        )
        return

    # Use RuneLite name if we have it, otherwise Discord display name
    name_for_sheet = osrs_name or message.author.display_name

    improved = update_best_times(
        str(message.author.id),
        name_for_sheet,
        boss_data,
    )

    extra = f" for **{osrs_name}**" if osrs_name else ""
    await message.reply(f"Updated PBs{extra}! Improved **{improved}** boss time(s).")


client.run(DISCORD_TOKEN)
