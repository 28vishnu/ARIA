import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from google import genai
from brain.tools.security_executor import SecurityExecutor
from brain.prompts.jarvis_system import JARVIS_SYSTEM_PROMPT

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("TELEGRAM_ADMIN_CHAT_ID", "123456789"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Initialize Clients
ai_client = genai.Client(api_key=GEMINI_API_KEY)
executor = SecurityExecutor(admin_chat_id=ADMIN_CHAT_ID)

# In-memory store for pending permission requests
pending_commands = {}

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_CHAT_ID:
        await update.message.reply_text("Access Denied, Sir. Unauthorized clearance level.")
        return

    user_input = update.message.text
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    # Step 1: LLM System Reasoning & Command Detection
    try:
        response = ai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"{JARVIS_SYSTEM_PROMPT}\n\nUser Request: {user_input}\n\nDetermine if this requires running a PowerShell command. If so, return standard JSON format: {{\"powershell\": \"<command>\"}}. Otherwise, output standard JARVIS reply."
        )
        reply_text = response.text

        # Check if the model generated a command payload
        if '{"powershell":' in reply_text:
            import json
            json_match = re.search(r'\{.*"powershell":.*\}', reply_text, re.DOTALL)
            if json_match:
                cmd_data = json.loads(json_match.group(0))
                ps_command = cmd_data.get("powershell")

                # Check Security Level
                if executor.is_high_risk(ps_command):
                    req_id = str(hash(ps_command))
                    pending_commands[req_id] = ps_command

                    keyboard = [
                        [
                            InlineKeyboardButton("✅ Authorize", callback_data=f"approve_{req_id}"),
                            InlineKeyboardButton("❌ Deny", callback_data=f"deny_{req_id}"),
                        ]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)

                    await update.message.reply_text(
                        f"⚡ *Security Alert, Sir.*\n\nThe following high-risk action requires your explicit approval:\n`{ps_command}`",
                        parse_mode="Markdown",
                        reply_markup=reply_markup
                    )
                    return
                else:
                    # Execute safe standard script directly
                    exec_res = executor.execute_powershell(ps_command)
                    stdout = exec_res["stdout"] or "Executed silently with zero exit status."
                    stderr = f"\nWarning/Errors:\n{exec_res['stderr']}" if exec_res["stderr"] else ""
                    
                    await update.message.reply_text(
                        f"Right away, Sir. Execution complete.\n\n```\n{stdout}{stderr}\n```",
                        parse_mode="Markdown"
                    )
                    return

        # Standard Conversational Output
        await update.message.reply_text(reply_text)

    except Exception as e:
        logging.error(f"Error handling request: {e}")
        await update.message.reply_text("My apologies, Sir. An internal anomaly occurred while processing that request.")

async def handle_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    action, req_id = data.split("_", 1)

    if req_id not in pending_commands:
        await query.edit_message_text("This approval token has expired or is invalid, Sir.")
        return

    ps_command = pending_commands.pop(req_id)

    if action == "approve":
        await query.edit_message_text(f"Permission granted, Sir. Executing: `{ps_command}`...", parse_mode="Markdown")
        exec_res = executor.execute_powershell(ps_command)
        out = exec_res["stdout"] if exec_res["stdout"] else "Execution successful (no output)."
        err = f"\n*Errors:*\n`{exec_res['stderr']}`" if exec_res["stderr"] else ""

        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f" Execution Complete, Sir:\n\n```powershell\n{out}\n```\n{err}",
            parse_mode="Markdown"
        )
    else:
        await query.edit_message_text(f"🚫 Action cancelled as requested, Sir.")

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.add_handler(CallbackQueryHandler(handle_button_click))
    print("ARIA JARVIS Telegram Core Active...")
    app.run_polling()
