import logging
import traceback

import telegram
from decouple import config
from telegram import Update, InlineKeyboardMarkup
from telegram.ext import CallbackContext

from DbHandler import DbHandler
from ExclusiveButtonHandler import ExclusiveButtonHandler
from MainButtonsGenerator import ButtonGenerator
from MainButtonsHandler import StartButtonHandler
from Utils import Utils


class Handlers:
    rootUsers = []

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
        username = update.message.from_user.username

        DbHandler.add_user(chat_id, username, first_name)

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
    def material_receiver_handler(update: Update, context: CallbackContext):
        """
        Handle the reception of the files sent by the users
        :param update:
        :param context:
        :return:
        """
        id_channel_file = config('ID_CHANNEL_FILE')
        try:
            chat_id = update.message.from_user.id
            username = update.message.from_user.username
            file_id = update.message.message_id
        except AttributeError:
            chat_id = update.callback_query.from_user.id
            username = update.callback_query.from_user.username
            file_id = update.callback_query.message.message_id

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

    @staticmethod
    def credits_handler(update: Update, context: CallbackContext):
        """
        Send the user a message showing the number of credits that the user has
        :param update:
        :param context:
        :return:
        """
        chat_id = update.message.from_user.id
        user_credits = DbHandler.get_credits(chat_id)
        message = f"⭐️Crediti -> {user_credits}"

        context.bot.send_message(
            chat_id=chat_id,
            text=message
        )

    @staticmethod
    def feedback_handler(update: Update, context: CallbackContext):
        """
        Handles the feedback command, that copies the message sent byt he user
        and sent it to a specific channel
        :param update:
        :param context:
        :return:
        """
        id_channel_feedback = config('ID_CHANNEL_FEEDBACK')
        chat_id = update.message.from_user.id
        username = update.message.from_user.username
        user_message = update.message.text
        user_message = user_message.split('/feedback ')[1]
        message = f"ID:{chat_id} User:@{username}\n" + user_message

        context.bot.send_message(
            chat_id=id_channel_feedback,
            text=message
        )

    @staticmethod
    def root_handler(update: Update, context: CallbackContext):
        """
        Handles the root command that checks if the password is correct then
        it adds the user chat id to a list
        :param update:
        :param context:
        :return:
        """
        expected_password = config('ROOT_PASSWORD')
        chat_id = update.message.from_user.id
        user_message = update.message.text
        password = user_message.split('/root ')
        if len(password) > 1:
            password = password[1]
        else:
            password = ""
        message = "⚠️NOW YOU ARE ROOT⚠️\n" + \
                  "Available command:\n" \
                  "\t/givecredits @Username#numberofcredits\n" \
                  "\t/givecredits Id#numberofcredits\n" \
                  "\t/givecredits All#numberofcredits\n" \
                  "\t/givevip @Username\n" \
                  "\t/stats\n" \
                  "\t/sendmessage all#text\n" \
                  "\t/sendmessage id#text\n" \
                  "\t/sendmessage @username#text\n" \
                  "\t/remove @username\n" \
                  "\t/remove id\n"

        if expected_password == password:
            Handlers.rootUsers.append(chat_id)
            context.bot.send_message(
                chat_id=chat_id,
                text=message
            )

    @staticmethod
    def stats_handler(update: Update, context: CallbackContext):
        """
        Handles the stats command that sends a message containing bot stats
        :param update:
        :param context:
        :return:
        """
        chat_id = update.message.from_user.id
        if chat_id in Handlers.rootUsers:
            data = DbHandler.get_stats()
            message = f"Total Download = {data[0]}\n" \
                      f"Total User = {data[1]}"
            context.bot.send_message(
                chat_id=chat_id,
                text=message
            )

    @staticmethod
    def givecredits_handler(update: Update, context: CallbackContext):
        """
        Handles the givecredits command that set credits and send message_to_user
        :param update:
        :param context:
        :return:
        """
        chat_id = update.message.from_user.id
        if chat_id in Handlers.rootUsers:
            user_message = update.message.text
            string = user_message.split('/givecredits ')
            type =  string[1].split('#')
            message_to_user = "You got {} check your credits using the command: /credits".format(type[0])
            message_to_root = "Credits added"
            if type[0].__contains__('@'):
                """By USERNAME"""
                user_chat= DbHandler.update_credits(int(type[1]), user_id=type[0].replace("@", ""))
                if not user_chat:
                    context.bot.send_message(
                        chat_id=user_chat,
                        text=message_to_user
                    )
                    context.bot.send_message(
                        chat_id=chat_id,
                        text=message_to_root
                    )
            elif type[0].__contains__('all'):
                """ALL USER  """
                """TODO : FUNCTION FOR ALL USER"""
            else:
                """ID code """
                user_chat = DbHandler.update_credits(int(type[1]), user_id=int(type[0]))
                if not user_chat:
                    context.bot.send_message(
                        chat_id=user_chat,
                        text=message_to_user
                    )
                    context.bot.send_message(
                        chat_id=chat_id,
                        text=message_to_root
                    )


    @staticmethod
    def givevip_handler(update: Update, context: CallbackContext):
        """
        Handles the givecredits command that set credits and send message
        :param update:
        :param context:
        :return:
        """
        chat_id = update.message.from_user.id
        if chat_id in Handlers.rootUsers:
            user_message = update.message.text
            message_to_user = "you are now Vip!!!"
            message_to_root = "{} it's now Vip"
            string = user_message.split('/givevip')
            if string[1].__contains__('@'):
                """TODO: Function querry update by User"""
                ## DbHandler.add_vip()
                context.bot.send_message(
                    chat_id=chat_id,
                    text=message_to_root.format(string[1])
                )
            else:
                """Function querry by ID"""
                DbHandler.add_vip(int(string[1]))
                context.bot.send_message(
                    chat_id=int(string[1]),
                    text=message_to_user
                )
                context.bot.send_message(
                    chat_id=chat_id,
                    text=message_to_root.format(string[1])
                )

    @staticmethod
    def sendmessage_handler(update: Update, context: CallbackContext):
        """
        Handles the givecredits command that set credits and send message
        :param update:
        :param context:
        :return:
        """
        chat_id = update.message.from_user.id
        if chat_id in Handlers.rootUsers:
            user_message = update.message.text
            string = user_message.split('/sendmessage')
            type =  string[1].split('# ')
            if type[0].__contains__('@'):
                """TODO: Function querry update by User"""

            elif type[0].__contains__('all'):
                """TODO: Function querry for all """
            else :
                """TODO : Function querry by ID"""

    @staticmethod
    def remove_handler(update: Update, context: CallbackContext):
        """
        Handles the givecredits command that set credits and send message
        :param update:
        :param context:
        :return:
        """
        chat_id = update.message.from_user.id
        if chat_id in Handlers.rootUsers:
            user_message = update.message.text
            string = user_message.split('/sendmessage')
            type =  string[1].split('# ')
            if type[0].__contains__('@'):
                """TODO: Function querry update by User"""
            elif type[0].__contains__('all'):
                """TODO: Function querry for all """
            else :
                """TODO : Function querry by ID"""

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
