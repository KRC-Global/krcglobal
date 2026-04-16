import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN       = os.environ['DISCORD_TOKEN']
DISCORD_CHANNEL_ID  = int(os.environ['DISCORD_CHANNEL_ID'])
GBMS_WEBHOOK_URL    = os.environ['GBMS_WEBHOOK_URL']
WEBHOOK_BOT_SECRET  = os.environ['WEBHOOK_BOT_SECRET']

SCHEDULE_HOUR   = int(os.environ.get('SCHEDULE_HOUR', '8'))
SCHEDULE_MINUTE = int(os.environ.get('SCHEDULE_MINUTE', '0'))
