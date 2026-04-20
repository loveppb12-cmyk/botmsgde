from pyrogram import Client, filters
from pyrogram.types import Message, ChatMember
from pyrogram.enums import ChatMemberStatus
from pyrogram.errors import FloodWait, RPCError
import asyncio
import logging
from config import API_ID, API_HASH, SESSION_STRING, BOT_TOKEN
import os
import sys
import json
from datetime import datetime

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
DELETE_DELAY = 10  # 135 seconds
OWNER_ID = 8595518118

class TelegramMessageDeleter:
    def __init__(self):
        self.user_client = None
        self.bot_client = None
        self.bot_info = None
        self.user_info = None
        self.running = True
        self.message_queue = asyncio.Queue(maxsize=1000)
        self.processed_messages = set()
        self.active_groups = set()  # Groups where both are admins
        self.last_admin_check = {}  # Cache admin status
        self.check_interval = 300  # Check admin status every 5 minutes

    async def check_admin_status(self, chat_id):
        """Check if both user and bot are admins in the group"""
        try:
            # Check current time to avoid too frequent checks
            current_time = datetime.now().timestamp()
            if chat_id in self.last_admin_check:
                if current_time - self.last_admin_check[chat_id] < self.check_interval:
                    return chat_id in self.active_groups
            
            self.last_admin_check[chat_id] = current_time
            
            # Get chat members
            try:
                # Check bot admin status
                bot_member = await self.bot_client.get_chat_member(chat_id, self.bot_info.id)
                bot_is_admin = bot_member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
                
                # Check user account admin status
                user_member = await self.user_client.get_chat_member(chat_id, self.user_info.id)
                user_is_admin = user_member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
                
                # Check if both have delete permissions
                bot_can_delete = True
                if bot_is_admin and bot_member.privileges:
                    bot_can_delete = bot_member.privileges.can_delete_messages
                
                user_can_delete = True
                if user_is_admin and user_member.privileges:
                    user_can_delete = user_member.privileges.can_delete_messages
                
                if bot_is_admin and user_is_admin and bot_can_delete and user_can_delete:
                    if chat_id not in self.active_groups:
                        self.active_groups.add(chat_id)
                        logger.info(f"✅ Both are admins in chat {chat_id} - Bot will now delete messages")
                    return True
                else:
                    if chat_id in self.active_groups:
                        self.active_groups.discard(chat_id)
                        logger.warning(f"⚠️ Lost admin permissions in chat {chat_id}")
                    return False
                    
            except Exception as e:
                logger.error(f"Error checking admin status in {chat_id}: {e}")
                return False
                
        except Exception as e:
            logger.error(f"Admin check error: {e}")
            return False

    async def is_owner(self, user_id):
        """Check if user is owner"""
        return user_id == OWNER_ID

    async def delete_message_worker(self):
        """Worker to handle message deletion with delay"""
        while self.running:
            try:
                message, chat_id, sender_name, message_id = await self.message_queue.get()
                
                if message_id in self.processed_messages:
                    continue
                    
                self.processed_messages.add(message_id)
                
                if len(self.processed_messages) > 10000:
                    self.processed_messages.clear()
                
                await asyncio.sleep(DELETE_DELAY)
                
                try:
                    # Check if still admin before deleting
                    if await self.check_admin_status(chat_id):
                        await message.delete()
                        logger.info(f"✅ Deleted bot message from {sender_name} in {chat_id}")
                    else:
                        logger.warning(f"⚠️ Cannot delete - lost admin rights in {chat_id}")
                except Exception as e:
                    logger.error(f"❌ Failed to delete message: {e}")
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in delete worker: {e}")

    async def start_user_client(self):
        """Start the user client"""
        try:
            logger.info("🔄 Starting user client...")
            
            self.user_client = Client(
                name="user_session",
                api_id=API_ID,
                api_hash=API_HASH,
                session_string=SESSION_STRING,
                workdir=".",
                in_memory=False,
                max_concurrent_transmissions=20,
                sleep_threshold=60
            )
            
            await self.user_client.start()
            self.user_info = await self.user_client.get_me()
            logger.info(f"✅ User client started: {self.user_info.first_name} (ID: {self.user_info.id})")
            
            @self.user_client.on_message(filters.group & filters.bot)
            async def handler(client, message: Message):
                try:
                    chat_id = message.chat.id
                    
                    # Check if both are admins
                    if not await self.check_admin_status(chat_id):
                        return
                    
                    # Don't delete our own bot's messages
                    if self.bot_info and message.from_user.id == self.bot_info.id:
                        return
                    
                    # Generate unique message ID
                    message_id = f"{chat_id}_{message.id}"
                    
                    if message_id in self.processed_messages:
                        return
                    
                    bot_name = message.from_user.first_name if message.from_user else "Unknown"
                    logger.info(f"🤖 Bot message from {bot_name} (ID: {message.from_user.id}) in chat {chat_id}")
                    
                    if message.text:
                        logger.info(f"📝 Message: {message.text[:100]}")
                    else:
                        logger.info(f"📝 Media message")
                    
                    await self.message_queue.put((message, chat_id, bot_name, message_id))
                    
                except FloodWait as e:
                    logger.warning(f"Flood wait {e.value}s - waiting...")
                    await asyncio.sleep(e.value)
                except Exception as e:
                    logger.error(f"Handler error: {e}")
            
            # Also handle when bot is added to group
            @self.user_client.on_message(filters.group & filters.new_chat_members)
            async def member_add_handler(client, message: Message):
                try:
                    for member in message.new_chat_members:
                        if member.id == self.bot_info.id:
                            chat_id = message.chat.id
                            logger.info(f"🤖 Bot added to group {chat_id}")
                            # Check admin status after a few seconds
                            await asyncio.sleep(5)
                            if await self.check_admin_status(chat_id):
                                await message.reply(
                                    f"✅ **Bot is ready!**\n\n"
                                    f"I will automatically delete messages from other bots in this group.\n\n"
                                    f"**Requirements met:**\n"
                                    f"✓ Bot is admin\n"
                                    f"✓ User account is admin\n"
                                    f"✓ Delete permissions enabled\n\n"
                                    f"⏰ Messages will be deleted after {DELETE_DELAY} seconds.\n\n"
                                    f"👨‍💻 Created by @itz_fizzyll"
                                )
                            else:
                                await message.reply(
                                    f"⚠️ **Cannot start monitoring!**\n\n"
                                    f"Please ensure:\n"
                                    f"1. Bot is promoted as admin\n"
                                    f"2. User account (@{self.user_info.username}) is promoted as admin\n"
                                    f"3. Both have 'Delete Messages' permission\n\n"
                                    f"After promoting, I will automatically start working."
                                )
                            break
                except Exception as e:
                    logger.error(f"Member add handler error: {e}")

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
                workdir=".",
                max_concurrent_transmissions=20,
                sleep_threshold=60
            )
            
            await self.bot_client.start()
            self.bot_info = await self.bot_client.get_me()
            logger.info(f"✅ Bot started: {self.bot_info.first_name} (@{self.bot_info.username})")
            
            # Owner commands only
            @self.bot_client.on_message(filters.command("start") & filters.private)
            async def start_cmd(client, message: Message):
                if not await self.is_owner(message.from_user.id):
                    await message.reply("❌ Unauthorized user!")
                    return
                
                text = f"""🤖 **Bot Message Deleter - Active!**

**Status:** ✅ Running
**Groups Active:** {len(self.active_groups)}
**Delete Delay:** {DELETE_DELAY} seconds
**Library:** Pyrogram (Optimized)

**How it works:**
1. Add bot to any group
2. Promote bot as admin with delete permissions
3. Promote user account (@{self.user_info.username}) as admin
4. Bot automatically detects and deletes bot messages

**Commands:**
/status - Check bot status
/stats - View performance stats

**Note:** No approval needed! Bot works automatically where both are admins.

👨‍💻 Created by @itz_fizzyll"""
                
                await message.reply(text, disable_web_page_preview=True)
            
            @self.bot_client.on_message(filters.command("status") & filters.private)
            async def status_cmd(client, message: Message):
                if not await self.is_owner(message.from_user.id):
                    return
                
                # Update admin status for all groups
                active_count = 0
                for chat_id in list(self.active_groups):
                    if await self.check_admin_status(chat_id):
                        active_count += 1
                
                status_text = f"""**📊 Bot Status Report**

**General:**
✅ Status: Running
👑 Owner: `{OWNER_ID}`
⏰ Delete delay: {DELETE_DELAY}s

**Performance:**
📊 Active groups: {len(self.active_groups)}
🔄 Queue size: {self.message_queue.qsize()}
💾 Cache size: {len(self.processed_messages)}

**Account Info:**
🤖 Bot: @{self.bot_info.username}
👤 User: @{self.user_info.username}

**Requirements:**
• Bot must be admin ✓
• User must be admin ✓
• Delete permissions ✓

Bot works automatically in any group where both accounts are admins!"""
                
                await message.reply(status_text)
            
            @self.bot_client.on_message(filters.command("stats") & filters.private)
            async def stats_cmd(client, message: Message):
                if not await self.is_owner(message.from_user.id):
                    return
                
                stats_text = f"""**📈 Performance Statistics**

**Active Groups:** {len(self.active_groups)}
**Queue Size:** {self.message_queue.qsize()}
**Processed Messages:** {len(self.processed_messages)}
**Delete Delay:** {DELETE_DELAY}s

**System Info:**
**Library:** Pyrogram 2.0.106
**Host:** Heroku

Bot is actively monitoring all groups where both accounts are admins."""
                
                await message.reply(stats_text)

            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to start bot client: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    async def keep_alive(self):
        """Keep the bot alive and monitor performance"""
        last_log = datetime.now()
        
        while self.running:
            try:
                await asyncio.sleep(60)
                
                # Log status every 5 minutes
                if (datetime.now() - last_log).seconds >= 300:
                    logger.info(f"💓 Heartbeat - Active Groups: {len(self.active_groups)} | Queue: {self.message_queue.qsize()} | Cache: {len(self.processed_messages)}")
                    last_log = datetime.now()
                
                # Clear cache if too large
                if len(self.processed_messages) > 20000:
                    self.processed_messages.clear()
                    logger.info("Cache automatically cleared")
                
                # Periodically recheck admin status for all groups
                if int(datetime.now().timestamp()) % 1800 < 60:  # Every 30 minutes
                    for chat_id in list(self.active_groups):
                        await self.check_admin_status(chat_id)
                
                # Check connections
                if self.user_client and not self.user_client.is_connected:
                    logger.warning("⚠️ User client disconnected! Reconnecting...")
                    await self.user_client.reconnect()
                
                if self.bot_client and not self.bot_client.is_connected:
                    logger.warning("⚠️ Bot client disconnected! Reconnecting...")
                    await self.bot_client.reconnect()
                    
            except Exception as e:
                logger.error(f"Keep-alive error: {e}")

    async def run(self):
        """Run both clients"""
        try:
            if not await self.start_bot_client():
                return
            
            if not await self.start_user_client():
                return
            
            # Start workers
            delete_worker = asyncio.create_task(self.delete_message_worker())
            keep_alive_task = asyncio.create_task(self.keep_alive())
            
            logger.info("🚀 **Bot Message Deleter is RUNNING!**")
            logger.info("⚡ Mode: Automatic - Works where both are admins")
            logger.info(f"⏰ Deletion delay: {DELETE_DELAY} seconds")
            logger.info(f"🤖 Bot: @{self.bot_info.username}")
            logger.info(f"👤 User: @{self.user_info.username}")
            logger.info("👨‍💻 Created by @itz_fizzyll")
            
            # Run both clients
            await asyncio.gather(
                self.user_client.run(),
                self.bot_client.run(),
                delete_worker,
                keep_alive_task
            )
                
        except Exception as e:
            logger.error(f"Fatal error: {e}")
            import traceback
            logger.error(traceback.format_exc())
        finally:
            self.running = False
            if self.user_client:
                await self.user_client.stop()
            if self.bot_client:
                await self.bot_client.stop()

async def main():
    """Main function with auto-restart"""
    restart_count = 0
    
    while True:
        try:
            deleter = TelegramMessageDeleter()
            await deleter.run()
            
            restart_count += 1
            logger.warning(f"⚠️ Bot stopped! Restart #{restart_count} in 10 seconds...")
            await asyncio.sleep(10)
            
        except KeyboardInterrupt:
            logger.info("⏹️ Bot stopped by user")
            break
        except Exception as e:
            logger.error(f"❌ Critical error: {e}")
            logger.info("Restarting in 30 seconds...")
            await asyncio.sleep(30)

if __name__ == "__main__":
    logger.info("🚀 Starting Telegram Bot Message Deleter on Heroku...")
    logger.info("⚡ Mode: Automatic - Works in all groups where both are admins")
    logger.info("👨‍💻 Created by @itz_fizzyll")
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped")
    except Exception as e:
        logger.error(f"Critical error: {e}")
        sys.exit(1)
