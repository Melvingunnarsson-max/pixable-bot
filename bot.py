import discord
from discord import app_commands
import aiohttp
import os
from datetime import datetime

DISCORD_TOKEN = os.environ.get('DISCORD_TOKEN')
EDGE_FUNCTION_URL = 'https://vpnigzdiofqjsgruvnrw.supabase.co/functions/v1/discord-bot'
BOT_SECRET = 'pixable-discord-2024'
CHANNEL_NAME = 'pixable'

intents = discord.Intents.default()
intents.message_content = True


class PixableBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()
        print('Slash commands synced.')


client = PixableBot()


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


async def customer_autocomplete(interaction, current):
    customers = await fetch_customers(current)
    return [app_commands.Choice(name=c['name'], value=c['name']) for c in customers[:25]]


@client.event
async def on_ready():
    print(f'Pixable Bot is online as {client.user}')


@client.tree.command(name='task', description='Add a task to Pixable')
@app_commands.describe(
    title='What needs to be done',
    customer='Customer to assign this to (optional)',
    deadline='Due date, e.g. 2026-07-15 (optional)',
    time='Estimated time in minutes (optional)',
)
@app_commands.autocomplete(customer=customer_autocomplete)
async def task_command(interaction, title: str, customer: str = None, deadline: str = None, time: int = None):
    if interaction.channel.name != CHANNEL_NAME:
        await interaction.response.send_message(f'Use this in #{CHANNEL_NAME}.', ephemeral=True)
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
            async with session.post(EDGE_FUNCTION_URL, json=payload,
                headers={'x-bot-secret': BOT_SECRET, 'Content-Type': 'application/json'}) as resp:
                if resp.status == 200:
                    lines = [f'Task added: {title}']
                    if customer: lines.append(f'Customer: {customer}')
                    if deadline: lines.append(f'Deadline: {deadline}')
                    if time: lines.append(f'Time: {time} min')
                    await interaction.followup.send('\n'.join(lines))
                else:
                    await interaction.followup.send('Something went wrong.')
    except Exception as e:
        print(f'Error: {e}')
        await interaction.followup.send('Could not reach the server.')


@client.tree.command(name='meeting', description='Add a meeting to Pixable')
@app_commands.describe(title='Meeting title')
async def meeting_command(interaction, title: str):
    if interaction.channel.name != CHANNEL_NAME:
        await interaction.response.send_message(f'Use this in #{CHANNEL_NAME}.', ephemeral=True)
        return
    await interaction.response.defer()
    payload = {'action': 'add_meeting', 'title': title, 'date': datetime.now().isoformat()}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(EDGE_FUNCTION_URL, json=payload,
                headers={'x-bot-secret': BOT_SECRET, 'Content-Type': 'application/json'}) as resp:
                if resp.status == 200:
                    await interaction.followup.send(f'Meeting added: {title}')
                else:
                    await interaction.followup.send('Something went wrong.')
    except Exception as e:
        print(f'Error: {e}')
        await interaction.followup.send('Could not reach the server.')


client.run(DISCORD_TOKEN)
