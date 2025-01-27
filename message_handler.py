from collections import deque
import time
from ai_handler import generate_ai_response
from instagram_api import send_message as send_instagram_message, reply_to_comment, fetch_comment_text
from utils import is_duplicate_message, conversation_history
from reminder_bot import get_reminder_bot
import logging
import asyncio

logger = logging.getLogger(__name__)

message_queue = deque(maxlen=100)
reminder_bot = get_reminder_bot()

# New: Message batch storage
message_batches = {}
BATCH_TIMEOUT = 15  # seconds

async def handle_instagram_event(event_data):
    for entry in event_data.get('entry', []):
        if 'messaging' in entry:
            for messaging_event in entry['messaging']:
                await handle_instagram_message(messaging_event)
        elif 'changes' in entry:
            for change in entry.get('changes', []):
                if change.get('field') == 'mentions':
                    await handle_instagram_mention(change.get('value', {}))

async def handle_instagram_message(message_data):
    sender_id = message_data.get('sender', {}).get('id')
    message = message_data.get('message', {})
    message_text = message.get('text', '')
    timestamp = message_data.get('timestamp', time.time() * 1000)
    
    if not sender_id or not message_text or message.get('is_echo', False):
        logger.debug(f"Skipping message: sender_id={sender_id}, message_text={message_text}, is_echo={message.get('is_echo', False)}")
        return

    if is_duplicate_message(message_queue, sender_id, message_text, timestamp):
        logger.debug(f"Skipping duplicate message from sender {sender_id}")
        return

    # Add user to reminder bot tracking
    await reminder_bot.add_user_message(sender_id)

    # Add message to batch
    if sender_id not in message_batches:
        message_batches[sender_id] = {'messages': [], 'last_time': time.time()}
    
    message_batches[sender_id]['messages'].append(message_text)
    message_batches[sender_id]['last_time'] = time.time()

    # Check if it's time to process the batch
    if time.time() - message_batches[sender_id]['last_time'] > BATCH_TIMEOUT:
        await process_message_batch(sender_id)

async def process_message_batch(sender_id):
    if sender_id not in message_batches:
        return

    batch = message_batches[sender_id]
    combined_message = "\n".join(batch['messages'])

    logger.info(f"Generating AI response for sender {sender_id} (batch of {len(batch['messages'])} messages)")
    ai_response = await generate_ai_response(sender_id, combined_message)
    
    logger.info(f"Sending message to sender {sender_id}")
    success = await send_instagram_message(sender_id, ai_response)
    
    if success:
        logger.info(f"Instagram message sent successfully to sender {sender_id}")
    else:
        logger.error(f"Failed to send Instagram message to sender {sender_id}")

    # Clear the processed batch
    del message_batches[sender_id]

async def handle_instagram_mention(mention_data):
    comment_id = mention_data.get('comment_id')
    
    if comment_id:
        logger.info(f"Fetching comment text for comment {comment_id}")
        comment_text = await fetch_comment_text(comment_id)
        if comment_text:
            logger.info(f"Generating AI response for comment {comment_id}")
            ai_response = await generate_ai_response(comment_id, comment_text)
            
            logger.info(f"Replying to comment {comment_id}")
            success = await reply_to_comment(comment_id, ai_response)
            if success:
                logger.info(f"Instagram reply sent successfully to comment {comment_id}")
            else:
                logger.error(f"Failed to send Instagram reply to comment {comment_id}")
        else:
            logger.error(f"Failed to fetch comment text for comment {comment_id}")
    else:
        logger.error("Error: Invalid Instagram mention data received")

async def handle_message(platform, user_id, message_text):
    logger.info(f"Generating AI response for {platform} user {user_id}")
    ai_response = await generate_ai_response(str(user_id), message_text)
    return ai_response

# New: Function to process pending message batches
async def process_pending_batches():
    current_time = time.time()
    for sender_id, batch in list(message_batches.items()):
        if current_time - batch['last_time'] > BATCH_TIMEOUT:
            await process_message_batch(sender_id)