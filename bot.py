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

intents = discord.Intents.default()
intents.message_content = True


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
        line = f'• {title}'
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
    lines = [f'📋 **Daglig sammanfattning för {assignee}** — {now_str}', '']

    if overdue:
        lines.append(f'🔴 **Försenade ({len(overdue)})**')
        for t, d in overdue:
            lines.append(fmt_task(t, d))
        lines.append('')

    if due_today:
        lines.append(f'🟡 **Förfaller idag ({len(due_today)})**')
        for t, d in due_today:
            lines.append(fmt_task(t, d))
        lines.append('')

    if due_tomorrow:
        lines.append(f'🟠 **Förfaller imorgon ({len(due_tomorrow)})**')
        for t, d in due_tomorrow:
            lines.append(fmt_task(t, d))
        lines.append('')

    if due_this_week:
        lines.append(f'📅 **Denna vecka ({len(due_this_week)})**')
        for t, d in due_this_week:
            lines.append(fmt_task(t, d))
        lines.append('')

    if later:
        lines.append(f'🔵 **Senare ({len(later)})**')
        for t, d in later:
            lines.append(fmt_task(t, d))
        lines.append('')

    if no_date:
        lines.append(f'📌 **Inget datum ({len(no_date)})**')
        for t, d in no_date:
            lines.append(fmt_task(t, d))
        lines.append('')

    if not task_list:
        lines.append('✅ Inga öppna uppgifter — bra jobbat!')

    return '\n'.join(lines).strip()


# ── Daily summary loop (08:00 Stockholm) ───────────────────────────────────────

@tasks.loop(time=datetime.now(STOCKHOLM).replace(hour=8, minute=0, second=0, microsecond=0).timetz())
async def daily_summary():
    print(f'Running daily summary at {datetime.now(STOCKHOLM).strftime("%H:%M %Z")}')
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
        summary = build_summary(assignee, task_list)
        try:
            await channel.send(summary)
            print(f'Sent summary to #{channel_name}')
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
            f'❌ Please use this command in **#{CHANNEL_NAME}**.', ephemeral=True
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
                    lines = [f'✅ **Task added:** {title}']
                    if customer:
                        lines.append(f'👤 **Customer:** {customer}')
                    if deadline:
                        lines.append(f'📅 **Deadline:** {deadline}')
                    if time:
                        lines.append(f'⏱ **Estimated time:** {time} min')
                    await interaction.followup.send('\n'.join(lines))
                else:
                    body = await resp.text()
                    print(f'Edge function error {resp.status}: {body}')
                    await interaction.followup.send('❌ Something went wrong. Check the bot logs.')
    except Exception as e:
        print(f'Error: {e}')
        await interaction.followup.send('❌ Could not reach the server.')


# ── /meeting ───────────────────────────────────────────────────────────────────

@client.tree.command(name='meeting', description='Add a meeting to Pixable')
@app_commands.describe(title='Meeting title or description')
async def meeting_command(
    interaction: discord.Interaction,
    title: str,
):
    if interaction.channel.name != CHANNEL_NAME:
        await interaction.response.send_message(
            f'❌ Please use this command in **#{CHANNEL_NAME}**.', ephemeral=True
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
                    await interaction.followup.send(f'✅ **Meeting added:** {title}')
                else:
                    body = await resp.text()
                    print(f'Edge function error {resp.status}: {body}')
                    await interaction.followup.send('❌ Something went wrong.')
    except Exception as e:
        print(f'Error: {e}')
        await interaction.followup.send('❌ Could not reach the server.')


# ── /summary ───────────────────────────────────────────────────────────────────

@client.tree.command(name='summary', description='Show your task summary right now')
async def summary_command(interaction: discord.Interaction):
    channel_name = interaction.channel.name
    assignee = PERSONAL_CHANNELS.get(channel_name)
    if not assignee:
        await interaction.response.send_message(
            '❌ This command only works in **#melvin** or **#arvid**.', ephemeral=True
        )
        return

    await interaction.response.defer()
    task_list = await fetch_tasks(assignee)
    summary = build_summary(assignee, task_list)
    await interaction.followup.send(summary)


client.run(DISCORD_TOKEN)
