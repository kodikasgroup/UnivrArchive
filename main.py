from decouple import config
from Handlers import Handlers
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler
import logging

# set logging
logging.basicConfig(
    level=logging.DEBUG,
    filename='output.log',
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# instantiate bot
updater = Updater(
    token=config('TOKEN'),
    use_context=True
)
dispatcher = updater.dispatcher

# handler for start command
start_handler = CommandHandler('start', Handlers.start_handler)
button_handler = CallbackQueryHandler(Handlers.inline_button_handler)
dispatcher.add_handler(start_handler)
dispatcher.add_handler(button_handler)
dispatcher.add_error_handler(Handlers.error_handler)

log = logging.getLogger()
log.setLevel(logging.DEBUG)

# Start Graphics
print("####################################")
print("####                            ####")
print("####      UniVrInfoArchive      ####")
print("####            Bot             ####")
print("####                            ####")
print("####################################\n")

# start bot
updater.start_polling()


