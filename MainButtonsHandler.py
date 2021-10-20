import telegram
from telegram import InlineKeyboardMarkup, Update
from telegram.ext import CallbackContext

from HashHandler import HashHandler
from MainButtonsGenerator import MainButtonsGenerator
from Utils import Utils


class MainButtonsHandler:

    @staticmethod
    def file_button_handler(context: CallbackContext, text: str, chat_id: int):
        """

        :param context:
        :param text: the hashed callback data in the following
               format `course/year/subject/subdir/FileName__file`
        :param chat_id:
        :return:
        """

        text = text.split("__")[0]
        text = HashHandler.get_corresponding_text(text)
        path = "archive" + "/" + text

        Utils.send_file(context, path, chat_id)

    @staticmethod
    def back_button_handler(update: Update, context: CallbackContext, text: str):
        """

        :param update:
        :param context:
        :param text:
        :return:
        """
        split_text = text.split('/')
        hash_text = split_text[0]
        hash_text_unhashed = HashHandler.get_corresponding_text(hash_text)
        back_type = split_text[1].split('__')[-1]
        split_text = hash_text_unhashed.split('/')
        course_name = split_text[0]

        chat_id = update.callback_query.from_user.id

        if back_type == 'subject':
            Utils.delete_last_message(update, context)
            MainButtonsHandler.course_button_handler(context, course_name, chat_id)
        elif back_type == 'subdir':
            param_text = '/'.join(split_text[:-1])
            MainButtonsHandler.year_button_handler(update, context, param_text, chat_id)
        elif back_type == 'file':
            param_text = '/'.join(split_text[:-1])
            MainButtonsHandler.subject_button_handler(update, context, param_text, chat_id)

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
