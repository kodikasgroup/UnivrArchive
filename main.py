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
mode = config('ACTIVE_MODE')
if mode == 'DEPLOY':
    token = config('DEPLOY_TOKEN')
elif mode == 'BETA':
    token = config('BETA_TOKEN')
else:
    token = config('TOKEN')
updater = Updater(
    token=token,
    use_context=True
)
dispatcher = updater.dispatcher

# command handlers
start_handler = CommandHandler('start', Handlers.start_handler)
credits_handler = CommandHandler('credits', Handlers.credits_handler)
feedback_handler = CommandHandler('feedback', Handlers.feedback_handler)
info_handler = CommandHandler('info', Handlers.info_handler)
exclusive_handler = CommandHandler('exclusive', Handlers.exclusive_message)

# section handlers root mode
root_handler = CommandHandler('root', Handlers.root_handler)
stats_handler = CommandHandler('stats', Handlers.stats_handler)
give_credits_handler = CommandHandler('givecredits', Handlers.give_credits_handler)
give_vip_handler = CommandHandler('givevip', Handlers.give_vip_handler)
send_message_handler = CommandHandler('sendmessage', Handlers.send_message_handler)
remove_handler = CommandHandler('remove', Handlers.remove_handler)
donation_handler = CommandHandler('donation', Handlers.donation_handler)

button_handler = CallbackQueryHandler(Handlers.inline_button_handler)
file_handler = MessageHandler(Filters.document, Handlers.material_receiver_handler)

dispatcher.add_handler(start_handler)
dispatcher.add_handler(credits_handler)
dispatcher.add_handler(feedback_handler)
dispatcher.add_handler(info_handler)
dispatcher.add_handler(exclusive_handler)

dispatcher.add_handler(root_handler)
dispatcher.add_handler(stats_handler)
dispatcher.add_handler(give_credits_handler)
dispatcher.add_handler(give_vip_handler)
dispatcher.add_handler(send_message_handler)
dispatcher.add_handler(remove_handler)
dispatcher.add_handler(donation_handler)

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
