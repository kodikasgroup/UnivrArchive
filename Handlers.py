import logging
import traceback

import telegram
from decouple import config
from telegram import Update, InlineKeyboardMarkup
from telegram.ext import CallbackContext

from ExclusiveButtonHandler import ExclusiveButtonHandler
from MainButtonsGenerator import ButtonGenerator
from MainButtonsHandler import StartButtonHandler
from Utils import Utils


class Handlers:

    @staticmethod
    def start_handler(update: Update, context: CallbackContext) -> None:
        """
        handle the command /start, it sends a gif, a welcome message and shows the
        buttons to access the archive
        :param update:
        :param context:
        :return:
        """

        chat_id = update.message.chat_id
        first_name = update.message.chat.first_name
        message = Utils.get_start_message(opening="Benvenuto/a", name=first_name)
        doc = open('resources/intro.gif', 'rb')
        buttons = ButtonGenerator.get_start_buttons()
        reply_markup = InlineKeyboardMarkup(buttons)

        context.bot.send_photo(chat_id, doc)
        context.bot.send_message(chat_id=chat_id,
                                 text=message,
                                 parse_mode=telegram.ParseMode.MARKDOWN_V2,
                                 reply_markup=reply_markup)

    @staticmethod
    def inline_button_handler(update: Update, context: CallbackContext) -> None:
        """
        handles callbacks derived from inline buttons
        :param update:
        :param context:
        :return:
        """

        chat_id = update.callback_query.from_user.id
        text = update.callback_query.data
        if text == 'HOME':
            StartButtonHandler.home_button_handler(update, context)
        elif 'BACK' in text:
            if 'EXCLUSIVE' in text:
                ExclusiveButtonHandler.back_button_handler(update, context, text, chat_id)
            else:
                StartButtonHandler.back_button_handler(update, context, text)
        elif 'EXCLUSIVE' in text:
            # Exclusive section
            if '__course' in text:
                ExclusiveButtonHandler.course_button_handler(context, text, chat_id)
            elif '__year' in text:
                ExclusiveButtonHandler.year_button_handler(update, context, text, chat_id)
                pass
            elif '__subject' in text:
                ExclusiveButtonHandler.subject_button_handler(update, context, text, chat_id)
            elif '__file' in text:
                ExclusiveButtonHandler.file_button_handler(context, text, chat_id)
                pass
            else:
                # handle when the user click the EXCLUSIVE button
                ExclusiveButtonHandler.exclusive_button_handler(context, chat_id)
        else:
            # Normal files
            if '__course' in text:
                StartButtonHandler.course_button_handler(context, text, chat_id)
            elif '__year' in text:
                StartButtonHandler.year_button_handler(update, context, text, chat_id)
            elif '__subject' in text:
                StartButtonHandler.subject_button_handler(update, context, text, chat_id)
            elif '__subdir' in text:
                StartButtonHandler.subdir_button_handler(update, context, text, chat_id)
            elif '__file' in text:
                StartButtonHandler.file_button_handler(update, context, text, chat_id)

    @staticmethod
    def error_handler(update: Update, context: CallbackContext):
        """
        Log the error and send a telegram message to notify the developer.
        :param update:
        :param context:
        :return:
        """
        logging.debug("An Error Occurred: ")
        traceback.print_tb(context.error.__traceback__)
        message = "Ci dispiace😞😞" \
                  "\nSembra si sia verificato un'errore perfavore riavvia il bot utilizzando il comando \/start"
        try:
            context.bot.send_message(chat_id=update.callback_query.from_user.id,
                                     text=message,
                                     parse_mode=telegram.ParseMode.MARKDOWN_V2)
        except AttributeError:
            context.bot.send_message(chat_id=update.message.from_user.id,
                                     text=message,
                                     parse_mode=telegram.ParseMode.MARKDOWN_V2)

    @staticmethod
    def material_receiver_handler(update: Update, context: CallbackContext):
        """
        Handle the reception of the files sent by the users
        :param update:
        :param context:
        :return:
        """
        id_channel_file = int(config('ID_CHANNEL_FILE'))
        chat_id = update.message.from_user.id
        username = update.message.from_user.username
        file_id = update.message.message_id

        user_message = "Il tuo file é stato inviato con successo, ti ringraziamo per la collaborazione" + \
                       " a breve riceverai una nostra risposta"
        channel_message = f"ID: {chat_id}\n" \
                          f"Username: @{username}\n" \
                          "Ha inviato :"

        # send message to user
        context.bot.send_message(
            chat_id=chat_id,
            text=user_message
        )

        # send message to channel
        context.bot.send_message(
            chat_id=id_channel_file,
            text=channel_message
        )

        # forward file
        context.bot.forward_message(
            chat_id=id_channel_file,
            from_chat_id=chat_id,
            message_id=file_id
        )
