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

PERSONAL_CHANNELS = {
    'melvin': 'Melvin',
    'arvid': 'Arvid',
}

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
        check_completed_tasks.start()
        print('Completed-task polling started.')
        check_ugc_submissions.start()
        print('UGC polling started.')


client = PixableBot()

_last_completed_check = datetime.now(timezone.utc)

DONE_TASKS_CHANNEL = 'done-tasks'
ALL_MENTION_USERNAMES = ['Melle', 'xpfrallanmlg']

_last_ugc_check = datetime.now(timezone.utc)


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
        print('Error fetching customers: ' + str(e))
    return []


async def fetch_new_ugc(since: datetime) -> list:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                EDGE_FUNCTION_URL,
                json={'action': 'get_new_ugc', 'since': since.isoformat()},
                headers={'x-bot-secret': BOT_SECRET, 'Content-Type': 'application/json'}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get('submissions', [])
                else:
                    body = await resp.text()
                    print('get_new_ugc error ' + str(resp.status) + ': ' + body)
    except Exception as e:
        print('Error fetching new UGC: ' + str(e))
    return []


async def fetch_recently_completed(since: datetime) -> list:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                EDGE_FUNCTION_URL,
                json={'action': 'get_recently_completed', 'since': since.isoformat()},
                headers={'x-bot-secret': BOT_SECRET, 'Content-Type': 'application/json'}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get('tasks', [])
                else:
                    body = await resp.text()
                    print('get_recently_completed error ' + str(resp.status) + ': ' + body)
    except Exception as e:
        print('Error fetching recently completed: ' + str(e))
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
                    print('get_tasks error ' + str(resp.status) + ': ' + body)
    except Exception as e:
        print('Error fetching tasks for ' + assignee + ': ' + str(e))
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

    def fmt(t, d):
        line = '- ' + t.get('title', '(no title)')
        c = t.get('customer_name')
        m = t.get('estimated_minutes')
        if c: line += ' [' + c + ']'
        parts = []
        if d: parts.append(d.strftime('%-d %b'))
        if m: parts.append(str(m) + ' min')
        if parts: line += '  (' + ', '.join(parts) + ')'
        return line

    now_str = datetime.now(STOCKHOLM).strftime('%A %-d %B')
    lines = ['Daglig sammanfattning for ' + assignee + ' - ' + now_str, '']

    for label, group in [
        ('Forsenade', overdue), ('Forfaller idag', due_today),
        ('Forfaller imorgon', due_tomorrow), ('Denna vecka', due_this_week),
        ('Senare', later), ('Inget datum', no_date)
    ]:
        if group:
            lines.append(label + ' (' + str(len(group)) + ')')
            for t, d in group: lines.append(fmt(t, d))
            lines.append('')

    if not task_list:
        lines.append('Inga oppna uppgifter - bra jobbat!')
    return '\n'.join(lines).strip()


def build_reminder(assignee: str, task_list: list, label: str):
    today = date.today()
    urgent = []
    for t in task_list:
        raw = t.get('due_date')
        d = None
        if raw:
            try: d = date.fromisoformat(raw[:10])
            except ValueError: pass
        if d is not None and d <= today:
            urgent.append((t, d))
    if not urgent:
        return None

    def fmt(t, d):
        line = '- ' + t.get('title', '(no title)')
        c = t.get('customer_name')
        m = t.get('estimated_minutes')
        if c: line += ' [' + c + ']'
        if m: line += '  (' + str(m) + ' min)'
        return line

    lines = [label + ' ' + assignee + ' - ' + str(len(urgent)) + ' uppgift(er) kvar idag:', '']
    for t, d in urgent: lines.append(fmt(t, d))
    return '\n'.join(lines).strip()


_TIMES = [
    datetime.now(STOCKHOLM).replace(hour=8,  minute=0, second=0, microsecond=0).timetz(),
    datetime.now(STOCKHOLM).replace(hour=12, minute=0, second=0, microsecond=0).timetz(),
    datetime.now(STOCKHOLM).replace(hour=16, minute=0, second=0, microsecond=0).timetz(),
]

@tasks.loop(time=_TIMES)
async def daily_summary():
    now_hour = datetime.now(STOCKHOLM).hour
    guild = discord.utils.get(client.guilds)
    if not guild: return

    for channel_name, assignee in PERSONAL_CHANNELS.items():
        channel = discord.utils.get(guild.text_channels, name=channel_name)
        if not channel: continue
        task_list = await fetch_tasks(assignee)
        discord_username = CHANNEL_DISCORD_USERS.get(channel_name)
        member = discord.utils.find(
            lambda m, u=discord_username: m.name == u or m.display_name == u,
            guild.members
        ) if discord_username else None
        mention = member.mention if member else ('@' + discord_username if discord_username else '')

        if now_hour == 8:
            message = build_summary(assignee, task_list)
        elif now_hour == 12:
            message = build_reminder(assignee, task_list, 'Lunchpaminnelse -')
        else:
            message = build_reminder(assignee, task_list, 'Slutpaminnelse -')

        if message is None: continue
        if now_hour != 8 and mention:
            message = mention + '\n' + message
        try:
            await channel.send(message)
        except Exception as e:
            print('Error sending to #' + channel_name + ': ' + str(e))


@daily_summary.before_loop
async def before_daily_summary():
    await client.wait_until_ready()


@tasks.loop(minutes=5)
async def check_completed_tasks():
    global _last_completed_check
    since = _last_completed_check
    _last_completed_check = datetime.now(timezone.utc)

    completed = await fetch_recently_completed(since)
    if not completed: return

    guild = discord.utils.get(client.guilds)
    if not guild: return
    channel = discord.utils.get(guild.text_channels, name=DONE_TASKS_CHANNEL)
    if not channel: return

    mentions = []
    for username in ALL_MENTION_USERNAMES:
        member = discord.utils.find(
            lambda m, u=username: m.name == u or m.display_name == u,
            guild.members
        )
        mentions.append(member.mention if member else '@' + username)
    mention_str = ' '.join(mentions)

    for task in completed:
        title = task.get('title', '(no title)')
        assignee = task.get('assignee', '')
        customer = task.get('customer_name', '')
        line = 'Task done: ' + title
        if assignee: line += ' (av ' + assignee + ')'
        if customer: line += ' [' + customer + ']'
        await channel.send(mention_str + '\n' + line)


@check_completed_tasks.before_loop
async def before_check_completed():
    await client.wait_until_ready()


@tasks.loop(minutes=5)
async def check_ugc_submissions():
    global _last_ugc_check
    since = _last_ugc_check
    _last_ugc_check = datetime.now(timezone.utc)

    submissions = await fetch_new_ugc(since)
    if not submissions: return

    guild = discord.utils.get(client.guilds)
    if not guild: return
    channel = discord.utils.get(guild.text_channels, name='melvin')
    if not channel:
        print('Channel #melvin not found for UGC notification.')
        return

    member = discord.utils.find(
        lambda m: m.name == 'Melle' or m.display_name == 'Melle',
        guild.members
    )
    mention = member.mention if member else '@Melle'

    for sub in submissions:
        name = sub.get('name', 'Okand')
        await channel.send(mention + ' ' + name + ' fyllde precis i UGC formularet')


@check_ugc_submissions.before_loop
async def before_check_ugc():
    await client.wait_until_ready()


@client.event
async def on_ready():
    print('Pixable Bot is online as ' + str(client.user))


async def customer_autocomplete(interaction: discord.Interaction, current: str) -> list:
    customers = await fetch_customers(current)
    return [app_commands.Choice(name=c['name'], value=c['name']) for c in customers[:25]]


@client.tree.command(name='task', description='Add a task to Pixable')
@app_commands.describe(
    title='What needs to be done',
    customer='Customer to assign this to (optional)',
    deadline='Due date, e.g. 2026-07-15 (optional)',
    time='Estimated time in minutes (optional)',
)
@app_commands.autocomplete(customer=customer_autocomplete)
async def task_command(interaction: discord.Interaction, title: str, customer: str = None, deadline: str = None, time: int = None):
    if interaction.channel.name != CHANNEL_NAME:
        await interaction.response.send_message('Please use this command in #' + CHANNEL_NAME + '.', ephemeral=True)
        return
    await interaction.response.defer()
    payload = {'action': 'add_task', 'title': title}
    if customer: payload['customer_name'] = customer
    if deadline: payload['due_date'] = deadline
    if time: payload['estimated_minutes'] = time
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(EDGE_FUNCTION_URL, json=payload, headers={'x-bot-secret': BOT_SECRET, 'Content-Type': 'application/json'}) as resp:
                if resp.status == 200:
                    lines = ['Task added: ' + title]
                    if customer: lines.append('Customer: ' + customer)
                    if deadline: lines.append('Deadline: ' + deadline)
                    if time: lines.append('Estimated time: ' + str(time) + ' min')
                    await interaction.followup.send('\n'.join(lines))
                else:
                    await interaction.followup.send('Something went wrong.')
    except Exception as e:
        print('Error: ' + str(e))
        await interaction.followup.send('Could not reach the server.')


@client.tree.command(name='meeting', description='Add a meeting to Pixable')
@app_commands.describe(title='Meeting title or description')
async def meeting_command(interaction: discord.Interaction, title: str):
    if interaction.channel.name != CHANNEL_NAME:
        await interaction.response.send_message('Please use this command in #' + CHANNEL_NAME + '.', ephemeral=True)
        return
    await interaction.response.defer()
    payload = {'action': 'add_meeting', 'title': title, 'date': datetime.now().isoformat()}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(EDGE_FUNCTION_URL, json=payload, headers={'x-bot-secret': BOT_SECRET, 'Content-Type': 'application/json'}) as resp:
                if resp.status == 200:
                    await interaction.followup.send('Meeting added: ' + title)
                else:
                    await interaction.followup.send('Something went wrong.')
    except Exception as e:
        print('Error: ' + str(e))
        await interaction.followup.send('Could not reach the server.')


@client.tree.command(name='summary', description='Show your task summary right now')
async def summary_command(interaction: discord.Interaction):
    channel_name = interaction.channel.name
    assignee = PERSONAL_CHANNELS.get(channel_name)
    if not assignee:
        await interaction.response.send_message('This command only works in #melvin or #arvid.', ephemeral=True)
        return
    await interaction.response.defer()
    task_list = await fetch_tasks(assignee)
    summary = build_summary(assignee, task_list)
    await interaction.followup.send(summary)


client.run(DISCORD_TOKEN)
