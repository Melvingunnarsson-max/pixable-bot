import discord
from discord import app_commands
from discord.ext import tasks
import aiohttp
import os
from datetime import datetime, date, timedelta, timezone
import pytz

DISCORD_TOKEN = os.environ.get('DISCORD_TOKEN')
EDGE_FUNCTION_URL = 'https://vpnigzdiofqjsgruvnrw.supabase.co/functions/v1/discord-bot'
BOT_SECRET = 'pixable-discord-2024'
CHANNEL_NAME = 'pixable'
STOCKHOLM = pytz.timezone('Europe/Stockholm')

# Channel name → assignee name mapping
PERSONAL_CHANNELS = {
    'melvin': 'Melvin',
    'arvid': 'Arvid',
}

# Channel name → Discord username to @mention in reminders
CHANNEL_DISCORD_USERS = {
    'melvin': 'Melle',
    'arvid': 'xpfrallanmlg',
}

intents = discord.Intents.default()
intents.message_content = True
intents.members = True


class PixableBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()
        print('Slash commands synced.')
        daily_summary.start()
        print('Daily summary task started.')


client = PixableBot()


# ── Helpers ────────────────────────────────────────────────────────────────────

async def fetch_customers(query: str) -> list:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                EDGE_FUNCTION_URL,
                json={'action': 'get_customers', 'query': query},
                headers={'x-bot-secret': BOT_SECRET, 'Content-Type': 'application/json'}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get('customers', [])
    except Exception as e:
        print(f'Error fetching customers: {e}')
    return []


async def fetch_tasks(assignee: str) -> list:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                EDGE_FUNCTION_URL,
                json={'action': 'get_tasks', 'assignee': assignee},
                headers={'x-bot-secret': BOT_SECRET, 'Content-Type': 'application/json'}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get('tasks', [])
                else:
                    body = await resp.text()
                    print(f'get_tasks error {resp.status}: {body}')
    except Exception as e:
        print(f'Error fetching tasks for {assignee}: {e}')
    return []


def build_summary(assignee: str, task_list: list) -> str:
    today = date.today()
    tomorrow = today + timedelta(days=1)
    week_end = today + timedelta(days=7)

    overdue, due_today, due_tomorrow, due_this_week, later, no_date = [], [], [], [], [], []

    for t in task_list:
        raw = t.get('due_date')
        d = None
        if raw:
            try:
                d = date.fromisoformat(raw[:10])
            except ValueError:
                pass

        if d is None:
            no_date.append((t, None))
        elif d < today:
            overdue.append((t, d))
        elif d == today:
            due_today.append((t, d))
        elif d == tomorrow:
            due_tomorrow.append((t, d))
        elif d <= week_end:
            due_this_week.append((t, d))
        else:
            later.append((t, d))

    def fmt_task(t, d):
        title = t.get('title', '(no title)')
        customer = t.get('customer_name')
        mins = t.get('estimated_minutes')
        line = f'\u2022 {title}'
        if customer:
            line += f' [{customer}]'
        details = []
        if d:
            details.append(d.strftime('%-d %b'))
        if mins:
            details.append(f'{mins} min')
        if details:
            line += f'  _({", ".join(details)})_'
        return line

    now_str = datetime.now(STOCKHOLM).strftime('%A %-d %B')
    lines = [f'\U0001f4cb **Daglig sammanfattning f\u00f6r {assignee}** \u2014 {now_str}', '']

    if overdue:
        lines.append(f'\U0001f534 **F\u00f6rsenade ({len(overdue)})**')
        for t, d in overdue:
            lines.append(fmt_task(t, d))
        lines.append('')

    if due_today:
        lines.append(f'\U0001f7e1 **F\u00f6rfaller idag ({len(due_today)})**')
        for t, d in due_today:
            lines.append(fmt_task(t, d))
        lines.append('')

    if due_tomorrow:
        lines.append(f'\U0001f7e0 **F\u00f6rfaller imorgon ({len(due_tomorrow)})**')
        for t, d in due_tomorrow:
            lines.append(fmt_task(t, d))
        lines.append('')

    if due_this_week:
        lines.append(f'\U0001f4c5 **Denna vecka ({len(due_this_week)})**')
        for t, d in due_this_week:
            lines.append(fmt_task(t, d))
        lines.append('')

    if later:
        lines.append(f'\U0001f535 **Senare ({len(later)})**')
        for t, d in later:
            lines.append(fmt_task(t, d))
        lines.append('')

    if no_date:
        lines.append(f'\U0001f4cc **Inget datum ({len(no_date)})**')
        for t, d in no_date:
            lines.append(fmt_task(t, d))
        lines.append('')

    if not task_list:
        lines.append('\u2705 Inga \u00f6ppna uppgifter \u2014 bra jobbat!')

    return '\n'.join(lines).strip()


def build_reminder(assignee: str, task_list: list, label: str):
    today = date.today()
    urgent = []

    for t in task_list:
        raw = t.get('due_date')
        d = None
        if raw:
            try:
                d = date.fromisoformat(raw[:10])
            except ValueError:
                pass
        if d is not None and d <= today:
            urgent.append((t, d))

    if not urgent:
        return None

    def fmt_task(t, d):
        title = t.get('title', '(no title)')
        customer = t.get('customer_name')
        mins = t.get('estimated_minutes')
        line = f'\u2022 {title}'
        if customer:
            line += f' [{customer}]'
        if mins:
            line += f'  _({mins} min)_'
        return line

    lines = [f'{label} **{assignee}** \u2014 {len(urgent)} uppgift(er) kvar idag:', '']
    for t, d in urgent:
        lines.append(fmt_task(t, d))
    return '\n'.join(lines).strip()


# ── Scheduled messages (08:00, 12:00, 16:00 Stockholm) ────────────────────────

_TIMES = [
    datetime.now(STOCKHOLM).replace(hour=8,  minute=0, second=0, microsecond=0).timetz(),
    datetime.now(STOCKHOLM).replace(hour=12, minute=0, second=0, microsecond=0).timetz(),
    datetime.now(STOCKHOLM).replace(hour=16, minute=0, second=0, microsecond=0).timetz(),
]

@tasks.loop(time=_TIMES)
async def daily_summary():
    now_hour = datetime.now(STOCKHOLM).hour
    print(f'Running scheduled message at {datetime.now(STOCKHOLM).strftime("%H:%M %Z")}')
    guild = discord.utils.get(client.guilds)
    if not guild:
        print('No guild found.')
        return

    for channel_name, assignee in PERSONAL_CHANNELS.items():
        channel = discord.utils.get(guild.text_channels, name=channel_name)
        if not channel:
            print(f'Channel #{channel_name} not found.')
            continue

        task_list = await fetch_tasks(assignee)

        discord_username = CHANNEL_DISCORD_USERS.get(channel_name)
        member = discord.utils.find(
            lambda m, u=discord_username: m.name == u or m.display_name == u,
            guild.members
        ) if discord_username else None
        mention = member.mention if member else (f'@{discord_username}' if discord_username else '')

        if now_hour == 8:
            message = build_summary(assignee, task_list)
        elif now_hour == 12:
            message = build_reminder(assignee, task_list, '\U0001f37d\ufe0f Lunchp\u00e5minnelse \u2014')
        else:
            message = build_reminder(assignee, task_list, '\U0001f514 Slutp\u00e5minnelse \u2014')

        if message is None:
            print(f'Nothing urgent for {assignee}, skipping reminder.')
            continue

        if now_hour != 8 and mention:
            message = f'{mention}\n{message}'

        try:
            await channel.send(message)
            print(f'Sent to #{channel_name}')
        except Exception as e:
            print(f'Error sending to #{channel_name}: {e}')


@daily_summary.before_loop
async def before_daily_summary():
    await client.wait_until_ready()


# ── Events ─────────────────────────────────────────────────────────────────────

@client.event
async def on_ready():
    print(f'Pixable Bot is online as {client.user}')


# ── Autocomplete ───────────────────────────────────────────────────────────────

async def customer_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    customers = await fetch_customers(current)
    return [
        app_commands.Choice(name=c['name'], value=c['name'])
        for c in customers[:25]
    ]


# ── /task ──────────────────────────────────────────────────────────────────────

@client.tree.command(name='task', description='Add a task to Pixable')
@app_commands.describe(
    title='What needs to be done',
    customer='Customer to assign this to (optional)',
    deadline='Due date, e.g. 2026-07-15 (optional)',
    time='Estimated time in minutes (optional)',
)
@app_commands.autocomplete(customer=customer_autocomplete)
async def task_command(
    interaction: discord.Interaction,
    title: str,
    customer: str = None,
    deadline: str = None,
    time: int = None,
):
    if interaction.channel.name != CHANNEL_NAME:
        await interaction.response.send_message(
            f'\u274c Please use this command in **#{CHANNEL_NAME}**.', ephemeral=True
        )
        return

    await interaction.response.defer()

    payload = {'action': 'add_task', 'title': title}
    if customer:
        payload['customer_name'] = customer
    if deadline:
        payload['due_date'] = deadline
    if time:
        payload['estimated_minutes'] = time

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                EDGE_FUNCTION_URL,
                json=payload,
                headers={'x-bot-secret': BOT_SECRET, 'Content-Type': 'application/json'}
            ) as resp:
                if resp.status == 200:
                    lines = [f'\u2705 **Task added:** {title}']
                    if customer:
                        lines.append(f'\U0001f464 **Customer:** {customer}')
                    if deadline:
                        lines.append(f'\U0001f4c5 **Deadline:** {deadline}')
                    if time:
                        lines.append(f'\u23f1 **Estimated time:** {time} min')
                    await interaction.followup.send('\n'.join(lines))
                else:
                    body = await resp.text()
                    print(f'Edge function error {resp.status}: {body}')
                    await interaction.followup.send('\u274c Something went wrong. Check the bot logs.')
    except Exception as e:
        print(f'Error: {e}')
        await interaction.followup.send('\u274c Could not reach the server.')


# ── /meeting ───────────────────────────────────────────────────────────────────

@client.tree.command(name='meeting', description='Add a meeting to Pixable')
@app_commands.describe(title='Meeting title or description')
async def meeting_command(
    interaction: discord.Interaction,
    title: str,
):
    if interaction.channel.name != CHANNEL_NAME:
        await interaction.response.send_message(
            f'\u274c Please use this command in **#{CHANNEL_NAME}**.', ephemeral=True
        )
        return

    await interaction.response.defer()

    payload = {
        'action': 'add_meeting',
        'title': title,
        'date': datetime.now().isoformat(),
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                EDGE_FUNCTION_URL,
                json=payload,
                headers={'x-bot-secret': BOT_SECRET, 'Content-Type': 'application/json'}
            ) as resp:
                if resp.status == 200:
                    await interaction.followup.send(f'\u2705 **Meeting added:** {title}')
                else:
                    body = await resp.text()
                    print(f'Edge function error {resp.status}: {body}')
                    await interaction.followup.send('\u274c Something went wrong.')
    except Exception as e:
        print(f'Error: {e}')
        await interaction.followup.send('\u274c Could not reach the server.')


# ── /summary ───────────────────────────────────────────────────────────────────

@client.tree.command(name='summary', description='Show your task summary right now')
async def summary_command(interaction: discord.Interaction):
    channel_name = interaction.channel.name
    assignee = PERSONAL_CHANNELS.get(channel_name)
    if not assignee:
        await interaction.response.send_message(
            '\u274c This command only works in **#melvin** or **#arvid**.', ephemeral=True
        )
        return

    await interaction.response.defer()
    task_list = await fetch_tasks(assignee)
    summary = build_summary(assignee, task_list)
    await interaction.followup.send(summary)


client.run(DISCORD_TOKEN)
