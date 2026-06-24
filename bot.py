import discord
import aiohttp
import os
import re
from datetime import datetime

DISCORD_TOKEN = os.environ.get('DISCORD_TOKEN')
EDGE_FUNCTION_URL = 'https://vpnigzdiofqjsgruvnrw.supabase.co/functions/v1/discord-bot'
BOT_SECRET = 'pixable-discord-2024'
CHANNEL_NAME = 'pixable'

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)


@client.event
async def on_ready():
    print(f'Pixable Bot is online as {client.user}')


@client.event
async def on_message(message):
    if message.author == client.user:
        return

    if message.channel.name != CHANNEL_NAME:
        return

    content = message.content.strip()

    task_match = re.match(
        r'^(?:task|add task|create task|uppgift|ny uppgift)[:\s]+(.+)',
        content, re.IGNORECASE
    )

    meeting_match = re.match(
        r'^(?:meeting|add meeting|mote|nytt mote|boka mote)[:\s]+(.+)',
        content, re.IGNORECASE
    )

    help_match = re.match(r'^(help|\?|hjalp)$', content, re.IGNORECASE)

    if task_match:
        title = task_match.group(1).strip()
        payload = {'action': 'add_task', 'title': title}
        success_msg = f'Task added: {title}'
    elif meeting_match:
        title = meeting_match.group(1).strip()
        payload = {'action': 'add_meeting', 'title': title, 'date': datetime.now().isoformat()}
        success_msg = f'Meeting added: {title}'
    elif help_match:
        await message.channel.send('Pixable Bot Commands:\ntask: [description]\nmeeting: [title]')
        return
    else:
        return

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                EDGE_FUNCTION_URL,
                json=payload,
                headers={'x-bot-secret': BOT_SECRET, 'Content-Type': 'application/json'}
            ) as resp:
                if resp.status == 200:
                    await message.reply(success_msg)
                else:
                    body = await resp.text()
                    print(f'Error {resp.status}: {body}')
                    await message.reply('Something went wrong.')
    except Exception as e:
        print(f'Error: {e}')
        await message.reply('Could not reach the server.')


client.run(DISCORD_TOKEN)
