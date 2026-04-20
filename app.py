from telethon import TelegramClient, events
from telethon.sessions import StringSession
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
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10

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

    async def start_user_client(self):
        """Start the user client with auto-reconnect"""
        try:
            logger.info("🔄 Starting user client...")
            
            # Create session from string
            session = StringSession(SESSION_STRING)
            
            self.user_client = TelegramClient(
                session=session,
                api_id=API_ID,
                api_hash=API_HASH,
                connection_retries=None,
                retry_delay=5
            )
            
            await self.user_client.start()
            user_me = await self.user_client.get_me()
            logger.info(f"✅ User client started successfully: {user_me.first_name}")
            
            @self.user_client.on(events.NewMessage())
            async def handler(event):
                try:
                    # Check if message is from a chat (group/channel)
                    if not event.is_group:
                        return
                    
                    # Get chat ID
                    chat_id = event.chat_id
                    
                    # Check if chat is approved
                    if chat_id not in self.approved_groups:
                        return
                    
                    # Ignore if no sender
                    if not event.sender:
                        return
                    
                    # Check if message is from a bot and not from our own bot
                    if (event.sender.bot and 
                        self.bot_info and 
                        event.sender.id != self.bot_info.id):
                        
                        logger.info(f"🤖 Bot message detected from {event.sender.first_name} (ID: {event.sender.id}) in chat {chat_id}")
                        logger.info(f"📝 Message: {event.text[:100] if event.text else 'Media message'}")
                        logger.info(f"⏰ Will delete in {DELETE_DELAY} seconds...")
                        
                        # Wait DELETE_DELAY seconds then delete
                        await asyncio.sleep(DELETE_DELAY)
                        
                        try:
                            await event.delete()
                            logger.info(f"✅ Successfully deleted bot message from {event.sender.first_name} after {DELETE_DELAY} seconds")
                        except Exception as delete_error:
                            logger.error(f"❌ Failed to delete message: {delete_error}")
                            
                except Exception as e:
                    logger.error(f"Error in message handler: {e}")

            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to start user client: {e}")
            return False

    async def start_bot_client(self):
        """Start the bot client with auto-reconnect"""
        try:
            logger.info("🔄 Starting bot client...")
            self.bot_client = TelegramClient(
                session='bot_session',
                api_id=API_ID, 
                api_hash=API_HASH,
                connection_retries=None,
                retry_delay=5
            )
            
            await self.bot_client.start(bot_token=BOT_TOKEN)
            self.bot_info = await self.bot_client.get_me()
            logger.info(f"✅ Bot client started: {self.bot_info.first_name} (@{self.bot_info.username})")
            
            # Add start command handler
            @self.bot_client.on(events.NewMessage(pattern='/start'))
            async def start_handler(event):
                if not await self.is_owner(event.sender_id):
                    await event.reply("❌ You are not authorized to use this bot.")
                    return
                
                creator_text = "🤖 **Bot Message Deleter**\n\n"
                creator_text += "This Bot is created by [@itz_fizzyll](https://t.me/itz_fizzyll)\n\n"
                creator_text += "**Commands for Owner:**\n"
                creator_text += "• `/approve <group_id>` - Approve a group for monitoring\n"
                creator_text += "• `/unapprove <group_id>` - Remove group from monitoring\n"
                creator_text += "• `/list` - List all approved groups\n"
                creator_text += "• `/status` - Check bot status\n\n"
                creator_text += "**Features:**\n"
                creator_text += "• Automatically detects bot messages\n"
                creator_text += f"• Deletes messages after {DELETE_DELAY} seconds\n"
                creator_text += "• Works only in approved groups\n"
                creator_text += "• Monitors all bot activities\n\n"
                creator_text += f"**Approved Groups:** {len(self.approved_groups)}\n\n"
                creator_text += "🚀 *Bot is now running and monitoring...*"
                
                await event.reply(creator_text, link_preview=False)
            
            # Approve group command
            @self.bot_client.on(events.NewMessage(pattern='/approve'))
            async def approve_handler(event):
                if not await self.is_owner(event.sender_id):
                    await event.reply("❌ You are not authorized to use this command.")
                    return
                
                try:
                    args = event.text.split()
                    if len(args) < 2:
                        await event.reply("❌ Usage: /approve <group_id>\n\nExample: /approve -1001234567890")
                        return
                    
                    group_id = int(args[1])
                    self.approved_groups.add(group_id)
                    self.save_approved_groups()
                    
                    await event.reply(f"✅ Group {group_id} has been approved!\n\nBot will now monitor and delete bot messages in this group.")
                    logger.info(f"Group {group_id} approved by owner")
                    
                except ValueError:
                    await event.reply("❌ Invalid group ID. Please provide a valid numeric ID.")
                except Exception as e:
                    await event.reply(f"❌ Error: {str(e)}")
            
            # Unapprove group command
            @self.bot_client.on(events.NewMessage(pattern='/unapprove'))
            async def unapprove_handler(event):
                if not await self.is_owner(event.sender_id):
                    await event.reply("❌ You are not authorized to use this command.")
                    return
                
                try:
                    args = event.text.split()
                    if len(args) < 2:
                        await event.reply("❌ Usage: /unapprove <group_id>\n\nExample: /unapprove -1001234567890")
                        return
                    
                    group_id = int(args[1])
                    if group_id in self.approved_groups:
                        self.approved_groups.remove(group_id)
                        self.save_approved_groups()
                        await event.reply(f"✅ Group {group_id} has been removed from monitoring.")
                        logger.info(f"Group {group_id} unapproved by owner")
                    else:
                        await event.reply(f"❌ Group {group_id} is not in the approved list.")
                    
                except ValueError:
                    await event.reply("❌ Invalid group ID. Please provide a valid numeric ID.")
                except Exception as e:
                    await event.reply(f"❌ Error: {str(e)}")
            
            # List approved groups
            @self.bot_client.on(events.NewMessage(pattern='/list'))
            async def list_handler(event):
                if not await self.is_owner(event.sender_id):
                    await event.reply("❌ You are not authorized to use this command.")
                    return
                
                if not self.approved_groups:
                    await event.reply("📋 No groups are currently approved.\n\nUse /approve <group_id> to add a group.")
                else:
                    groups_list = "\n".join([f"• `{group_id}`" for group_id in self.approved_groups])
                    await event.reply(f"📋 **Approved Groups ({len(self.approved_groups)}):**\n\n{groups_list}")
            
            # Status command
            @self.bot_client.on(events.NewMessage(pattern='/status'))
            async def status_handler(event):
                if not await self.is_owner(event.sender_id):
                    await event.reply("❌ You are not authorized to use this command.")
                    return
                
                status_text = f"**Bot Status:**\n\n"
                status_text += f"✅ Bot is running\n"
                status_text += f"📊 Approved groups: {len(self.approved_groups)}\n"
                status_text += f"⏰ Deletion delay: {DELETE_DELAY} seconds\n"
                status_text += f"🤖 Bot username: @{self.bot_info.username}\n"
                status_text += f"🔄 Reconnect attempts: {self.reconnect_attempts}\n"
                status_text += f"📅 Uptime: Active\n\n"
                status_text += "**Commands:**\n"
                status_text += "/start - Show bot info\n"
                status_text += "/approve <id> - Approve group\n"
                status_text += "/unapprove <id> - Remove group\n"
                status_text += "/list - Show approved groups\n"
                status_text += "/status - Show this status"
                
                await event.reply(status_text)
            
            # Handle bot being added to groups
            @self.bot_client.on(events.ChatAction())
            async def chat_action_handler(event):
                if event.user_added and await event.get_user() == self.bot_info:
                    chat_id = event.chat_id
                    chat_title = event.chat.title if event.chat.title else "Unknown"
                    
                    creator_text = f"🤖 **Thanks for adding me to {chat_title}!**\n\n"
                    creator_text += "This Bot is created by [@itz_fizzyll](https://t.me/itz_fizzyll)\n\n"
                    creator_text += "⚠️ **This group is not approved yet!**\n\n"
                    creator_text += "The bot owner needs to approve this group using:\n"
                    creator_text += f"`/approve {chat_id}`\n\n"
                    creator_text += "**Requirements:**\n"
                    creator_text += "• Bot must be admin with delete permissions\n"
                    creator_text += "• User account must be admin with delete permissions\n\n"
                    creator_text += "Contact @itz_fizzyll to get this group approved."
                    
                    await event.reply(creator_text, link_preview=False)

            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to start bot client: {e}")
            return False

    async def keep_alive(self):
        """Keep the connection alive with periodic checks"""
        while self.running:
            try:
                await asyncio.sleep(300)  # Check every 5 minutes
                
                # Check if user client is still connected
                if self.user_client and not self.user_client.is_connected():
                    logger.warning("⚠️ User client disconnected, attempting to reconnect...")
                    await self.reconnect_user_client()
                
                # Check if bot client is still connected
                if self.bot_client and not self.bot_client.is_connected():
                    logger.warning("⚠️ Bot client disconnected, attempting to reconnect...")
                    await self.reconnect_bot_client()
                
                # Log status every hour
                if int(asyncio.get_event_loop().time()) % 3600 < 300:
                    logger.info(f"💓 Bot is alive - Monitoring {len(self.approved_groups)} approved groups")
                    
            except Exception as e:
                logger.error(f"Error in keep_alive: {e}")
                await asyncio.sleep(60)  # Wait a minute before retrying

    async def reconnect_user_client(self):
        """Reconnect user client"""
        try:
            if self.user_client:
                await self.user_client.disconnect()
            
            await self.start_user_client()
            self.reconnect_attempts = 0
            logger.info("✅ User client reconnected successfully")
        except Exception as e:
            self.reconnect_attempts += 1
            logger.error(f"❌ Failed to reconnect user client (Attempt {self.reconnect_attempts}/{self.max_reconnect_attempts}): {e}")
            
            if self.reconnect_attempts >= self.max_reconnect_attempts:
                logger.critical("Max reconnection attempts reached. Please restart the bot.")
                self.running = False

    async def reconnect_bot_client(self):
        """Reconnect bot client"""
        try:
            if self.bot_client:
                await self.bot_client.disconnect()
            
            await self.start_bot_client()
            logger.info("✅ Bot client reconnected successfully")
        except Exception as e:
            logger.error(f"❌ Failed to reconnect bot client: {e}")

    async def run(self):
        """Run both clients with keep-alive"""
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
            
            logger.info("🚀 Bot Message Deleter is now running!")
            logger.info(f"📝 Monitoring {len(self.approved_groups)} approved groups")
            logger.info(f"⏰ Bot messages will be deleted after {DELETE_DELAY} seconds")
            logger.info("👨‍💻 Created by @itz_fizzyll")
            
            # Start keep-alive task
            keep_alive_task = asyncio.create_task(self.keep_alive())
            
            # Keep both clients running
            await asyncio.gather(
                self.user_client.run_until_disconnected(),
                self.bot_client.run_until_disconnected(),
                keep_alive_task,
                return_exceptions=True
            )
                
        except Exception as e:
            logger.error(f"❌ Fatal error: {e}")
            import traceback
            logger.error(traceback.format_exc())
        finally:
            # Cleanup
            logger.info("🔄 Disconnecting clients...")
            self.running = False
            try:
                if self.user_client:
                    await self.user_client.disconnect()
                if self.bot_client:
                    await self.bot_client.disconnect()
            except:
                pass

async def main():
    """Main async function to run the bot with auto-restart"""
    while True:
        try:
            deleter = TelegramMessageDeleter()
            await deleter.run()
            
            # If bot stops, wait 10 seconds and restart
            logger.warning("⚠️ Bot stopped. Restarting in 10 seconds...")
            await asyncio.sleep(10)
            
        except KeyboardInterrupt:
            logger.info("⏹️ Bot stopped by user")
            break
        except Exception as e:
            logger.error(f"❌ Critical error in main loop: {e}")
            logger.info("Restarting in 30 seconds...")
            await asyncio.sleep(30)

if __name__ == "__main__":
    # For Heroku - simple execution with auto-restart
    logger.info("🚀 Starting Telegram Bot Message Deleter...")
    logger.info(f"⏰ Deletion delay set to: {DELETE_DELAY} seconds")
    logger.info(f"👑 Owner ID: {OWNER_ID}")
    logger.info("👨‍💻 Created by @itz_fizzyll")
    
    try:
        # Run the bot with auto-restart
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⏹️ Bot stopped by user")
    except Exception as e:
        logger.error(f"❌ Critical error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)
