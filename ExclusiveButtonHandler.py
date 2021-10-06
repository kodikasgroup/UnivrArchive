import telegram
from telegram import InlineKeyboardMarkup, Update
from telegram.ext import CallbackContext

from DbHandler import DbHandler
from ExclusiveButtonGenerator import ExclusiveButtonGenerator
from HashHandler import HashHandler
from Utils import Utils


class ExclusiveButtonHandler:

    @staticmethod
    def file_button_handler(context, text, chat_id):
        """

        :param context:
        :param text: callback data from the clicked button
        :param chat_id: the id of the chat where to send the message
        :return:
        """
        hashed_text = text.split("#")[0]
        unhashed_text = HashHandler.get_corresponding_text(hashed_text)
        path = "archive/" + unhashed_text
        price = unhashed_text.split('/')[-1].split('.')[0]
        price = int(price)
        if DbHandler.is_vip(chat_id):
            Utils.send_file(context, path, chat_id)
        else:
            if DbHandler.get_credits(chat_id) >= price:
                DbHandler.update_credits(chat_id, (-1 * price))
                Utils.send_file(context, path, chat_id)
            else:
                message = "❌ ERRORE ❌\n" + \
                          "Sembra tu non abbia abbastanza Crediti\n" + \
                          "per visualizzare il tuo saldo attuale usa il comando /credits"
                context.bot.send_message(chat_id=chat_id,
                                         text=message)

    @staticmethod
    def subject_button_handler(update: Update, context: CallbackContext, text: str, chat_id: int):
        """

        :param update:
        :param context:
        :param text: callback data from the clicked button
        :param chat_id: the id of the chat where to send the message
        :return:
        """
        hashed_text = text.split("#")[0]
        unhashed_text = HashHandler.get_corresponding_text(hashed_text)
        splitted_text = unhashed_text.split('/')
        subject_name = splitted_text[3]
        year_name = splitted_text[2]
        course_name = splitted_text[1]
        buttons = ExclusiveButtonGenerator.get_file_buttons(course_name, year_name, subject_name)
        reply_markup = InlineKeyboardMarkup(buttons)
        message = "💥ECCO IL MATERIALE DELLA SEZIONE💥"
        Utils.delete_last_message(update, context)
        context.bot.send_message(chat_id=chat_id,
                                 text=message,
                                 reply_markup=reply_markup,
                                 parse_mode=telegram.ParseMode.MARKDOWN_V2)

    @staticmethod
    def year_button_handler(update: Update, context: CallbackContext, text: str, chat_id: int) -> None:
        """

        :param update:
        :param context:
        :param text: callback data from the clicked button
        :param chat_id: the id of the chat where to send the message
        :return:
        """
        hashed_text = text.split("#")[0]
        unhashed_text = HashHandler.get_corresponding_text(hashed_text)
        splitted_text = unhashed_text.split('/')
        year_name = splitted_text[2]
        course_name = splitted_text[1]
        buttons = ExclusiveButtonGenerator.get_subject_buttons(course_name, year_name)
        reply_markup = InlineKeyboardMarkup(buttons)
        message = f"Hai Scelto:\n{year_name.replace('_', ' ')}📚📚📚"
        Utils.delete_last_message(update, context)
        context.bot.send_message(chat_id=chat_id,
                                 text=message,
                                 reply_markup=reply_markup,
                                 parse_mode=telegram.ParseMode.MARKDOWN_V2)

    @staticmethod
    def course_button_handler(context: CallbackContext, text: str, chat_id: int) -> None:
        """

        :param context:
        :param text: callback data from the clicked button
        :param chat_id: the id of the chat where to send the message
        :return:
        """
        hashed_course_name = text.split('#')[0]
        course_name = HashHandler.get_corresponding_text(hashed_course_name).split('/')[1]
        buttons = ExclusiveButtonGenerator.get_year_buttons(course_name)
        reply_markup = InlineKeyboardMarkup(buttons)
        message = "Hai scelto:\n" + \
                  f"{course_name}"
        context.bot.send_message(chat_id=chat_id,
                                 text=message,
                                 reply_markup=reply_markup)

    @staticmethod
    def exclusive_button_handler(context: CallbackContext, chat_id: int) -> None:
        """
        handles when the user clicks on the EXCLUSIVE button,
        it should display the buttons for choosing the course of study
        :param context:
        :param chat_id: the id of the chat where to send the message
        :return:
        """
        buttons = ExclusiveButtonGenerator.get_course_buttons()
        reply_markup = InlineKeyboardMarkup(buttons)
        message = "Eccoci nel area ⭐️Exclusive⭐\n" + \
                  "Qui i file che trovi hanno un COSTO in crediti indicato al inizio del nome" + \
                  "questo credito verra scalato una volta che si richiede il suddetto file" + \
                  "\n\nSi prega di non condividere i file con gli altri per rispetto degli sviluppatori e per poter " \
                  "usufruire di file nuovi"
        context.bot.send_message(chat_id=chat_id,
                                 text=message,
                                 reply_markup=reply_markup)

    @staticmethod
    def back_button_handler(update: Update, context: CallbackContext, text: str, chat_id: int):
        """
        Handles the back buttons in the EXCLUSIVE section
        :param update:
        :param context:
        :param text: the callback data
        :param chat_id: the id of the chat where to send the message
        :return:
        """
        button_type = text.split("#")[2].split("__")[1]
        if button_type == 'year':
            Utils.delete_last_message(update, context)
            ExclusiveButtonHandler.exclusive_button_handler(context, chat_id)
        elif button_type == 'subject':
            Utils.delete_last_message(update, context)
            ExclusiveButtonHandler.course_button_handler(context, text, chat_id)
        elif button_type == 'file':
            ExclusiveButtonHandler.year_button_handler(update, context, text, chat_id)

