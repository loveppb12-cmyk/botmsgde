from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait, RPCError
import asyncio
import logging
from config import API_ID, API_HASH, SESSION_STRING, BOT_TOKEN
import os
import sys
import json

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
DELETE_DELAY = 135  # 135 seconds
OWNER_ID = 8595518118
APPROVED_GROUPS_FILE = 'approved_groups.json'

class TelegramMessageDeleter:
    def __init__(self):
        self.user_client = None
        self.bot_client = None
        self.bot_info = None
        self.approved_groups = self.load_approved_groups()
        self.running = True
        self.message_queue = asyncio.Queue()

    def load_approved_groups(self):
        """Load approved groups from file"""
        try:
            if os.path.exists(APPROVED_GROUPS_FILE):
                with open(APPROVED_GROUPS_FILE, 'r') as f:
                    return set(json.load(f))
            return set()
        except Exception as e:
            logger.error(f"Error loading approved groups: {e}")
            return set()

    def save_approved_groups(self):
        """Save approved groups to file"""
        try:
            with open(APPROVED_GROUPS_FILE, 'w') as f:
                json.dump(list(self.approved_groups), f)
        except Exception as e:
            logger.error(f"Error saving approved groups: {e}")

    async def is_owner(self, user_id):
        """Check if user is owner"""
        return user_id == OWNER_ID

    async def delete_message_worker(self):
        """Worker to handle message deletion with delay"""
        while self.running:
            try:
                message, chat_id, sender_name = await self.message_queue.get()
                await asyncio.sleep(DELETE_DELAY)
                try:
                    await message.delete()
                    logger.info(f"✅ Deleted bot message from {sender_name}")
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
                max_concurrent_transmissions=10
            )
            
            await self.user_client.start()
            user_me = await self.user_client.get_me()
            logger.info(f"✅ User client started: {user_me.first_name}")
            
            @self.user_client.on_message(filters.group & filters.bot)
            async def handler(client, message: Message):
                try:
                    chat_id = message.chat.id
                    
                    if chat_id not in self.approved_groups:
                        return
                    
                    if self.bot_info and message.from_user.id == self.bot_info.id:
                        return
                    
                    bot_name = message.from_user.first_name if message.from_user else "Unknown"
                    logger.info(f"🤖 Bot message from {bot_name} in chat {chat_id}")
                    
                    await self.message_queue.put((message, chat_id, bot_name))
                    
                except FloodWait as e:
                    await asyncio.sleep(e.value)
                except Exception as e:
                    logger.error(f"Handler error: {e}")

            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to start user client: {e}")
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
                max_concurrent_transmissions=10
            )
            
            await self.bot_client.start()
            self.bot_info = await self.bot_client.get_me()
            logger.info(f"✅ Bot started: {self.bot_info.first_name}")
            
            @self.bot_client.on_message(filters.command("start") & filters.private)
            async def start_cmd(client, message: Message):
                if not await self.is_owner(message.from_user.id):
                    await message.reply("❌ Unauthorized")
                    return
                
                text = f"""🤖 **Bot Message Deleter**

**Commands:**
/approve <id> - Approve group
/unapprove <id> - Remove group
/list - List approved groups
/status - Bot status

**Features:**
• Deletes bot messages after {DELETE_DELAY}s
• Optimized for large groups
• Auto-restart on failure

**Approved Groups:** {len(self.approved_groups)}

👨‍💻 Created by @itz_fizzyll"""
                
                await message.reply(text)
            
            @self.bot_client.on_message(filters.command("approve") & filters.private)
            async def approve_cmd(client, message: Message):
                if not await self.is_owner(message.from_user.id):
                    return
                
                try:
                    args = message.text.split()
                    if len(args) < 2:
                        await message.reply("Usage: /approve -1001234567890")
                        return
                    
                    group_id = int(args[1])
                    self.approved_groups.add(group_id)
                    self.save_approved_groups()
                    await message.reply(f"✅ Group {group_id} approved!")
                    logger.info(f"Group {group_id} approved")
                    
                except Exception as e:
                    await message.reply(f"Error: {str(e)}")
            
            @self.bot_client.on_message(filters.command("unapprove") & filters.private)
            async def unapprove_cmd(client, message: Message):
                if not await self.is_owner(message.from_user.id):
                    return
                
                try:
                    args = message.text.split()
                    if len(args) < 2:
                        await message.reply("Usage: /unapprove -1001234567890")
                        return
                    
                    group_id = int(args[1])
                    if group_id in self.approved_groups:
                        self.approved_groups.remove(group_id)
                        self.save_approved_groups()
                        await message.reply(f"✅ Group {group_id} removed!")
                        logger.info(f"Group {group_id} unapproved")
                    else:
                        await message.reply(f"Group {group_id} not approved")
                    
                except Exception as e:
                    await message.reply(f"Error: {str(e)}")
            
            @self.bot_client.on_message(filters.command("list") & filters.private)
            async def list_cmd(client, message: Message):
                if not await self.is_owner(message.from_user.id):
                    return
                
                if not self.approved_groups:
                    await message.reply("No approved groups")
                else:
                    groups = "\n".join([f"• `{gid}`" for gid in self.approved_groups])
                    await message.reply(f"**Approved Groups:**\n\n{groups}")
            
            @self.bot_client.on_message(filters.command("status") & filters.private)
            async def status_cmd(client, message: Message):
                if not await self.is_owner(message.from_user.id):
                    return
                
                status = f"""**Bot Status:**

✅ Running
📊 Groups: {len(self.approved_groups)}
⏰ Delay: {DELETE_DELAY}s
👑 Owner: {OWNER_ID}
⚡ Optimized for large groups

**System:** Heroku
**Library:** Pyrogram"""
                
                await message.reply(status)

            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to start bot client: {e}")
            return False

    async def run(self):
        """Run both clients"""
        try:
            if not await self.start_bot_client():
                return
            
            if not await self.start_user_client():
                return
            
            delete_worker = asyncio.create_task(self.delete_message_worker())
            
            logger.info("🚀 Bot is running!")
            logger.info(f"📊 Monitoring {len(self.approved_groups)} groups")
            logger.info("👨‍💻 Created by @itz_fizzyll")
            
            await asyncio.gather(
                self.user_client.run(),
                self.bot_client.run(),
                delete_worker
            )
                
        except Exception as e:
            logger.error(f"Fatal error: {e}")
        finally:
            self.running = False
            if self.user_client:
                await self.user_client.stop()
            if self.bot_client:
                await self.bot_client.stop()

async def main():
    """Main function with auto-restart"""
    while True:
        try:
            deleter = TelegramMessageDeleter()
            await deleter.run()
            logger.warning("Restarting in 10 seconds...")
            await asyncio.sleep(10)
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Error: {e}")
            await asyncio.sleep(30)

if __name__ == "__main__":
    logger.info("🚀 Starting Bot Message Deleter on Heroku...")
    logger.info(f"👑 Owner ID: {OWNER_ID}")
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped")
    except Exception as e:
        logger.error(f"Critical error: {e}")
        sys.exit(1)
