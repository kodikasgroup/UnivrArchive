import logging

from decouple import config
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters

from Handlers import Handlers

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

# command handlers
start_handler = CommandHandler('start', Handlers.start_handler)
credits_handler = CommandHandler('credits', Handlers.credits_handler)
feedback_handler = CommandHandler('feedback', Handlers.feedback_handler)

button_handler = CallbackQueryHandler(Handlers.inline_button_handler)
file_handler = MessageHandler(Filters.document, Handlers.material_receiver_handler)

dispatcher.add_handler(start_handler)
dispatcher.add_handler(credits_handler)
dispatcher.add_handler(feedback_handler)

dispatcher.add_handler(button_handler)
dispatcher.add_handler(file_handler)
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
