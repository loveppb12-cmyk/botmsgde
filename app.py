from pyrogram import Client, filters, enums
from pyrogram.types import Message, ChatMember
from pyrogram.errors import FloodWait, ChatAdminRequired
import asyncio
import logging
from config import API_ID, API_HASH, SESSION_STRING, BOT_TOKEN
import os
import sys
import time

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
DELETE_DELAY = 90  # seconds
MAX_RETRIES = 3

class TelegramMessageDeleter:
    def __init__(self):
        self.user_client = None
        self.bot_client = None
        self.bot_info = None
        self.deletion_queue = asyncio.Queue()
        self.is_running = True

    async def start_user_client(self):
        """Start the user client using string session"""
        try:
            logger.info("🔄 Starting user client...")
            
            self.user_client = Client(
                name="user_session",
                api_id=API_ID,
                api_hash=API_HASH,
                session_string=SESSION_STRING,
                in_memory=True
            )
            
            await self.user_client.start()
            user_me = await self.user_client.get_me()
            logger.info(f"✅ User client started successfully: {user_me.first_name} (ID: {user_me.id})")
            
            # Register message handler
            @self.user_client.on_message()
            async def message_handler(client: Client, message: Message):
                try:
                    # Ignore if no sender or not a group/channel
                    if not message.from_user or not message.chat:
                        return
                    
                    # Check if it's a group or supergroup
                    chat_type = message.chat.type
                    if chat_type not in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
                        return
                    
                    # Check if message is from a bot and not from our own bot
                    if (message.from_user.is_bot and 
                        self.bot_info and 
                        message.from_user.id != self.bot_info.id):
                        
                        logger.info(f"🤖 Bot message detected from {message.from_user.first_name} (ID: {message.from_user.id})")
                        logger.info(f"📝 Chat: {message.chat.title} (ID: {message.chat.id})")
                        logger.info(f"📝 Message: {message.text[:100] if message.text else 'Media message'}")
                        logger.info(f"⏰ Will delete in {DELETE_DELAY} seconds...")
                        
                        # Add to deletion queue
                        await self.deletion_queue.put({
                            'chat_id': message.chat.id,
                            'message_id': message.id,
                            'delay': DELETE_DELAY,
                            'retries': 0
                        })
                            
                except FloodWait as e:
                    logger.warning(f"⏳ Flood wait in handler: {e.value} seconds")
                    await asyncio.sleep(e.value)
                except Exception as e:
                    logger.error(f"Error in message handler: {e}")

            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to start user client: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    async def start_bot_client(self):
        """Start the bot client"""
        try:
            logger.info("🔄 Starting bot client...")
            self.bot_client = Client(
                name="bot_session",
                api_id=API_ID,
                api_hash=API_HASH,
                bot_token=BOT_TOKEN,
                in_memory=True
            )
            
            await self.bot_client.start()
            self.bot_info = await self.bot_client.get_me()
            logger.info(f"✅ Bot client started: {self.bot_info.first_name} (@{self.bot_info.username})")
            
            # Add start command handler with creator credit
            @self.bot_client.on_message(filters.command("start"))
            async def start_handler(client: Client, message: Message):
                creator_text = "🤖 **Bot Message Deleter**\n\n"
                creator_text += "This Bot is created by [@itz_fizzyll](https://t.me/itz_fizzyll)\n\n"
                creator_text += "**Features:**\n"
                creator_text += "• Automatically detects bot messages\n"
                creator_text += f"• Deletes messages after {DELETE_DELAY} seconds\n"
                creator_text += "• Works in groups where I'm admin\n"
                creator_text += "• Monitors all bot activities\n\n"
                creator_text += "**Requirements:**\n"
                creator_text += "• Bot must be admin with delete permissions\n"
                creator_text += "• User account must be admin with delete permissions\n\n"
                creator_text += "🚀 *Bot is now running and monitoring...*"
                
                await message.reply_text(creator_text, disable_web_page_preview=True)
            
            # Handle new chat members (when bot is added)
            @self.bot_client.on_message(filters.new_chat_members)
            async def bot_added_handler(client: Client, message: Message):
                for member in message.new_chat_members:
                    if member.id == self.bot_info.id:
                        creator_text = "🤖 **Thanks for adding me!**\n\n"
                        creator_text += "This Bot is created by [@uexnc](https://t.me/uexnc)\n\n"
                        creator_text += "I will automatically delete other bot messages "
                        creator_text += f"**{DELETE_DELAY} seconds** after they are sent.\n\n"
                        creator_text += "**Make sure to:**\n"
                        creator_text += "1. Promote me as admin\n"
                        creator_text += "2. Give me 'Delete Messages' permission\n"
                        creator_text += "3. Also promote the user account as admin\n\n"
                        creator_text += "Use /start to check my status"
                        
                        await message.reply_text(creator_text, disable_web_page_preview=True)
                        break

            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to start bot client: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    async def process_deletion_queue(self):
        """Process queued message deletions"""
        while self.is_running:
            try:
                # Get deletion task from queue
                task = await self.deletion_queue.get()
                
                # Wait for the specified delay
                await asyncio.sleep(task['delay'])
                
                # Try to delete the message
                try:
                    await self.user_client.delete_messages(
                        chat_id=task['chat_id'],
                        message_ids=task['message_id']
                    )
                    logger.info(f"✅ Successfully deleted message {task['message_id']} from chat {task['chat_id']}")
                    
                except FloodWait as e:
                    logger.warning(f"⏳ Flood wait for {e.value} seconds, retrying...")
                    if task['retries'] < MAX_RETRIES:
                        task['retries'] += 1
                        task['delay'] = e.value  # Wait for flood wait time
                        await self.deletion_queue.put(task)
                    else:
                        logger.error(f"❌ Failed to delete message after {MAX_RETRIES} retries")
                        
                except ChatAdminRequired:
                    logger.error(f"❌ Admin rights required to delete message in chat {task['chat_id']}")
                    
                except Exception as e:
                    logger.error(f"❌ Failed to delete message: {e}")
                    
                finally:
                    self.deletion_queue.task_done()
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in deletion queue processor: {e}")

    async def check_connections(self):
        """Check if both clients are connected properly"""
        try:
            if self.user_client and self.bot_client:
                user_me = await self.user_client.get_me()
                bot_me = await self.bot_client.get_me()
                
                logger.info(f"🔗 User account: {user_me.first_name} (@{user_me.username})")
                logger.info(f"🔗 Bot account: {bot_me.first_name} (@{bot_me.username})")
                logger.info("✅ Both clients are connected and ready!")
                return True
        except Exception as e:
            logger.error(f"❌ Connection check failed: {e}")
            return False

    async def run(self):
        """Run both clients"""
        try:
            # Start bot client first
            bot_started = await self.start_bot_client()
            if not bot_started:
                logger.error("❌ Failed to start bot client")
                return
                
            # Start user client
            user_started = await self.start_user_client()
            if not user_started:
                logger.error("❌ Failed to start user client")
                return
            
            if await self.check_connections():
                logger.info("🚀 Bot Message Deleter is now running!")
                logger.info("📝 Monitoring for bot messages...")
                logger.info(f"⏰ Bot messages will be deleted after {DELETE_DELAY} seconds")
                logger.info("👨‍💻 Created by @itz_fizzyll")
                
                # Start deletion queue processor
                queue_task = asyncio.create_task(self.process_deletion_queue())
                
                # Keep both clients running
                while self.is_running:
                    try:
                        await asyncio.sleep(1)
                    except KeyboardInterrupt:
                        break
                
                # Cleanup
                self.is_running = False
                queue_task.cancel()
                
            else:
                logger.error("❌ Failed to establish connections")
                
        except Exception as e:
            logger.error(f"❌ Fatal error: {e}")
            import traceback
            logger.error(traceback.format_exc())
        finally:
            # Cleanup
            logger.info("🔄 Disconnecting clients...")
            try:
                if self.user_client:
                    await self.user_client.stop()
                if self.bot_client:
                    await self.bot_client.stop()
            except:
                pass

async def main():
    """Main async function to run the bot"""
    deleter = TelegramMessageDeleter()
    await deleter.run()

if __name__ == "__main__":
    # For Heroku - simple execution
    logger.info("🚀 Starting Telegram Bot Message Deleter...")
    logger.info(f"⏰ Deletion delay set to: {DELETE_DELAY} seconds")
    logger.info("👨‍💻 Created by @itz_fizzyll")
    
    try:
        # Run the bot
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⏹️ Bot stopped by user")
    except Exception as e:
        logger.error(f"❌ Critical error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)
