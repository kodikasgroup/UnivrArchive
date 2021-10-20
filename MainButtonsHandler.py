import telegram
from telegram import InlineKeyboardMarkup, Update
from telegram.ext import CallbackContext

from HashHandler import HashHandler
from MainButtonsGenerator import MainButtonsGenerator
from Utils import Utils


class MainButtonsHandler:

    @staticmethod
    def back_button_handler(update: Update, context: CallbackContext, text: str):
        """

        :param update:
        :param context:
        :param text:
        :return:
        """
        chat_id = update.callback_query.from_user.id

        split_text = text.split('/')
        hash_text = split_text[0]
        ushashed_text = HashHandler.get_corresponding_text(hash_text)
        splitted_text = ushashed_text.split('/')[:-1]
        ushashed_text = '/'.join(splitted_text)
        if len(splitted_text) != 1:
            hash_text = HashHandler.generate_hash(ushashed_text)
            Utils.send_buttons(hash_text, update, context, chat_id)
        else:
            Utils.send_buttons(ushashed_text, update, context, chat_id)

    @staticmethod
    def home_button_handler(update: Update, context: CallbackContext) -> None:
        """

        :param update:
        :param context:
        :return:
        """
        chat_id = update.callback_query.from_user.id
        first_name = update.callback_query.from_user.first_name
        message = Utils.get_start_message(opening="Ben ritornato/a", name=first_name)

        buttons = MainButtonsGenerator.get_start_buttons()
        reply_markup = InlineKeyboardMarkup(buttons)

        Utils.delete_last_message(update, context)

        context.bot.send_message(chat_id=chat_id,
                                 text=message,
                                 parse_mode=telegram.ParseMode.MARKDOWN_V2,
                                 reply_markup=reply_markup)
