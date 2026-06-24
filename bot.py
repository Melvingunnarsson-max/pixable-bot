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


def parse_fields(raw: str) -> dict:
    parts = [p.strip() for p in raw.split('|')]
    result = {'title': parts[0]}
    for part in parts[1:]:
        m = re.match(r'^(?:customer|kund|client)\s*:\s*(.+)', part, re.IGNORECASE)
        if m:
            result['customer_name'] = m.group(1).strip()
            continue
        m = re.match(r'^(?:deadline|due|datum|forfall)\s*:\s*(.+)', part, re.IGNORECASE)
        if m:
            result['due_date'] = m.group(1).strip()
            continue
        m = re.match(r'^(?:time|tid|minutes|min|estimated)\s*:\s*(\d+)', part, re.IGNORECASE)
        if m:
            result['estimated_minutes'] = int(m.group(1))
            continue
    return result


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
        r'^(?:task|add task|create task|uppgift|ny uppgift|lagg till uppgift)[:\s]+(.+)',
        content, re.IGNORECASE | re.DOTALL
    )
    meeting_match = re.match(
        r'^(?:meeting|add meeting|mote|nytt mote|boka mote|lagg till mote)[:\s]+(.+)',
        content, re.IGNORECASE
    )
    help_match = re.match(r'^(help|\?|hjalp)$', content, re.IGNORECASE)

    if task_match:
        fields = parse_fields(task_match.group(1).strip())
        title = fields.pop('title')
        payload = {'action': 'add_task', 'title': title, **fields}
        extras = []
        if 'customer_name' in fields:
            extras.append(f"Customer: {fields['customer_name']}")
        if 'due_date' in fields:
            extras.append(f"Deadline: {fields['due_date']}")
        if 'estimated_minutes' in fields:
            extras.append(f"Time: {fields['estimated_minutes']} min")
        success_msg = f'Task added: {title}'
        if extras:
            success_msg += ' | ' + ' | '.join(extras)
    elif meeting_match:
        title = meeting_match.group(1).strip()
        payload = {'action': 'add_meeting', 'title': title, 'date': datetime.now().isoformat()}
        success_msg = f'Meeting added: {title}'
    elif help_match:
        await message.channel.send(
            'Pixable Bot Commands:\n\n'
            'task: [title] - Add a task\n'
            'task: [title] | customer: [name] | deadline: [YYYY-MM-DD] | time: [minutes]\n\n'
            'meeting: [title] - Add a meeting\n\n'
            'Swedish: uppgift / kund / tid / mote'
        )
        return
    else:
        return

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(EDGE_FUNCTION_URL, json=payload,
                headers={'x-bot-secret': BOT_SECRET, 'Content-Type': 'application/json'}) as resp:
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
