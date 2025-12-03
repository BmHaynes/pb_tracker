import os
import re
import logging

import discord
from dotenv import load_dotenv
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

# ---------------- Logging setup ---------------- #

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

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
    """
    Headers are now:
      0: Discord_name
      1: RSN
      2+: bosses
    """
    if not headers:
        headers = ["Discord_name", "RSN"]

    existing = {h.lower() for h in headers if h}
    new_bosses = [b for b in bosses if b.lower() not in existing]

    if new_bosses:
        logging.info(f"Adding new boss columns to sheet: {new_bosses}")
        headers = headers + new_bosses
        write_headers(headers)

    return headers


def build_header_map(headers):
    return {h.lower(): i for i, h in enumerate(headers)}


def find_row(values, discord_name, rsn):
    """
    Find row where:
      col 0 == Discord_name
      col 1 == RSN
    """
    for row_index in range(1, len(values)):  # row 0 is headers
        row = values[row_index]
        if len(row) >= 2 and row[0] == discord_name and row[1] == rsn:
            return row_index
    return -1


def add_row(discord_name, rsn, col_count):
    logging.info(f"Creating new row for Discord_name='{discord_name}', RSN='{rsn}'")
    new_row = [""] * col_count
    new_row[0] = discord_name
    new_row[1] = rsn

    sheet.append(
        spreadsheetId=GOOGLE_SHEET_ID,
        range="BestTimes!A:ZZ",
        valueInputOption="RAW",
        body={"values": [new_row]},
    ).execute()


def update_cell(row, col, value):
    col_letter = col_to_letter(col)
    logging.info(f"Updating cell {col_letter}{row + 1} to {value}")
    sheet.update(
        spreadsheetId=GOOGLE_SHEET_ID,
        range=f"BestTimes!{col_letter}{row + 1}",
        valueInputOption="RAW",
        body={"values": [[value]]},
    ).execute()


def update_best_times(discord_name, rsn, boss_data):
    """
    boss_data is a list of: { "boss": name, "fastest": seconds_int }

    Sheet layout:
      col 0: Discord_name
      col 1: RSN
      col 2+: bosses
    """
    logging.info(f"Updating PBs for Discord_name='{discord_name}', RSN='{rsn}'")
    values, headers = get_sheet()

    boss_names = [b["boss"] for b in boss_data]
    logging.info(f"Bosses found for '{rsn}': {boss_names}")
    headers = ensure_boss_columns(boss_names, headers)
    header_map = build_header_map(headers)
    col_count = len(headers)

    # Find or create the row for this Discord_name + RSN pair
    row_index = find_row(values, discord_name, rsn)
    if row_index == -1:
        add_row(discord_name, rsn, col_count)
        values, headers = get_sheet()
        header_map = build_header_map(headers)
        row_index = find_row(values, discord_name, rsn)

    # Make sure row exists and has enough columns
    if row_index >= len(values):
        values.append([""] * col_count)

    row = values[row_index]
    if len(row) < col_count:
        row = row + [""] * (col_count - len(row))

    # Make sure the Discord_name and RSN columns are up to date
    # (handles if they change their Discord display name)
    if row[0] != discord_name:
        update_cell(row_index, 0, discord_name)
    if row[1] != rsn:
        update_cell(row_index, 1, rsn)

    improved = 0

    # Go through each boss PB
    for entry in boss_data:
        boss = entry["boss"]
        fastest = entry["fastest"]

        col = header_map.get(boss.lower())
        if col is None:
            logging.warning(f"Column not found for boss '{boss}', skipping.")
            continue

        old_val_str = row[col] if col < len(row) else ""

        try:
            old_val = int(old_val_str)
        except (ValueError, TypeError):
            old_val = None

        # Only update if better (lower) or no value yet
        if old_val is None or fastest < old_val:
            logging.info(f"Improved PB for {rsn} / {boss}: old={old_val}, new={fastest}")
            update_cell(row_index, col, fastest)
            improved += 1
        else:
            logging.info(f"No improvement for {rsn} / {boss}: old={old_val}, new={fastest}")

    logging.info(f"Total improved bosses for {discord_name} / {rsn}: {improved}")
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
    Read an rsprofile--1.properties string and return a list of accounts:

    [
      {
        "rsn": "IronDrag94",
        "boss_data": [ { "boss": "Alchemical Hydra", "fastest": 112 }, ... ]
      },
      ...
    ]
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
        logging.warning("No personalbest entries found in file.")
        return []

    accounts = []

    for hash_id, boss_map in pbs.items():
        rsn = names.get(hash_id)
        if not rsn:
            logging.info(f"Skipping hash '{hash_id}' with PBs but no displayName.")
            continue

        account_bosses = []
        for boss_raw, value_raw in boss_map.items():
            boss_name = simple_unescape(boss_raw)

            try:
                seconds = float(value_raw)
                seconds = int(round(seconds))
            except ValueError:
                logging.error(
                    f"Could not parse PB value '{value_raw}' "
                    f"for boss '{boss_name}' (RSN '{rsn}')"
                )
                continue

            account_bosses.append({
                "boss": boss_name,
                "fastest": seconds,
            })

        if not account_bosses:
            logging.info(f"No valid PBs for RSN '{rsn}', skipping.")
            continue

        logging.info(f"Found {len(account_bosses)} PBs for RSN '{rsn}'.")
        accounts.append({
            "rsn": rsn,
            "boss_data": account_bosses,
        })

    logging.info(f"Total RS accounts with PBs in file: {len(accounts)}")
    return accounts


# ---------------- Discord bot setup ---------------- #

intents = discord.Intents.default()
intents.message_content = True  # make sure this is also enabled in the Discord dev portal

client = discord.Client(intents=intents)


@client.event
async def on_ready():
    logging.info(f"Logged in as {client.user}")


@client.event
async def on_message(message: discord.Message):
    # Ignore messages from bots
    if message.author.bot:
        return

    if message.channel.id != UPLOAD_CHANNEL_ID:
        return

    if not message.attachments:
        return

    attachment = message.attachments[0]
    filename_lower = attachment.filename.lower()

    # We only care about RuneLite profile .properties files
    if not (filename_lower.endswith(".properties") and "rsprofile" in filename_lower):
        logging.info(
            f"Ignoring attachment from {message.author} "
            f"(filename={attachment.filename}) - not an rsprofile properties file."
        )
        return

    logging.info(
        f"Received rsprofile file from {message.author} "
        f"in #{message.channel} (filename={attachment.filename})"
    )

    # Try to DM the user that we're processing their file
    try:
        await message.author.send(
            "📥 I got your RuneLite profile file. "
            "Processing ALL accounts and boss personal bests now..."
        )
    except discord.Forbidden:
        logging.warning(f"Could not DM {message.author} to confirm receipt (DMs disabled?).")

    # Download and parse the file
    try:
        data = await attachment.read()
        text = data.decode("utf-8", errors="ignore")
    except Exception as e:
        logging.exception("Error reading attachment data.")
        try:
            await message.author.send(f"❌ Error reading your file: {e}")
        except discord.Forbidden:
            await message.channel.send(
                f"{message.author.mention} ❌ Error reading your file (and I couldn't DM you).",
                delete_after=15
            )
        # Try to delete the original message anyway
        try:
            await message.delete()
        except discord.Forbidden:
            logging.warning("Could not delete user message (missing Manage Messages permission).")
        return

    accounts = parse_rsprofile_properties(text)

    if not accounts:
        try:
            await message.author.send(
                "❌ I couldn't find any boss personal bests in that file.\n"
                "Make sure it's your `rsprofile--1.properties` from `~/.runelite/profiles2/` "
                "and that you have at least one boss PB on at least one account."
            )
        except discord.Forbidden:
            await message.channel.send(
                f"{message.author.mention} ❌ No boss PBs found in that file "
                "(and I couldn't DM you).",
                delete_after=20
            )
    else:
        discord_name = message.author.display_name or message.author.name

        lines = []
        for account in accounts:
            rsn = account["rsn"]
            boss_data = account["boss_data"]

            try:
                improved = update_best_times(
                    discord_name,
                    rsn,
                    boss_data,
                )
                lines.append(f"- RSN **{rsn}**: improved **{improved}** boss time(s).")
            except Exception as e:
                logging.exception(f"Error updating sheet for RSN '{rsn}'.")
                lines.append(f"- RSN **{rsn}**: ❌ error updating PBs: {e}")

        summary = "✅ Finished updating your PBs.\n" + "\n".join(lines)

        try:
            await message.author.send(summary)
        except discord.Forbidden:
            logging.warning(f"Could not DM {message.author} PB summary, sending in channel.")
            await message.channel.send(
                f"{message.author.mention} {summary}",
                delete_after=30
            )

    # Finally, try to delete the original message (remove the file from the channel)
    try:
        await message.delete()
        logging.info(f"Deleted upload message from {message.author}.")
    except discord.Forbidden:
        logging.warning(
            "Could not delete user message - bot likely missing 'Manage Messages' permission."
        )


client.run(DISCORD_TOKEN)
