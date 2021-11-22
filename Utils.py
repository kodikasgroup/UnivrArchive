import _io
import logging
import os
import re

import telegram
from telegram import Update, InlineKeyboardMarkup
from telegram.ext import CallbackContext

import Handlers
from DbHandler import DbHandler
from FileHandler import FileHandler
from HashHandler import HashHandler
from MainButtonsGenerator import MainButtonsGenerator


class Utils:
    @staticmethod
    def get_start_message(opening: str, name: str) -> str:
        """
        composes the welcome message to send to the user based on input parameters
        :param opening: the welcome phrase (Benvetuto/a and Bentornato/a)
        :param name: the first name of the user
        :return: the message compose from given parameters
        """
        message = f"📘📗📙📘📗📙📘📗📙📘📗📙\n" + \
                  "Ciao 🍎{}🍎\n" + \
                  "{} nel bot UniVrInfoArchive\_bot, qui potrai trovare molto materiale che ti potrà essere d'aiuto per prepararti ai tuoi esami\.\n\n" + \
                  "Commandi che potrebbero esserti utili:\n" + \
                  "/credits mostra i crediti disponibili\n" + \
                  "/feedback \*messaggio\* se vuoi segnalarci qualcosa o darci consigli *[ovviamente il testo del messaggio senza asterischi]*\n" + \
                  "/info se ti servono informazioni\n" + \
                  "/exclusive per capire cos'è la sezione exclusive\n\n" + \
                  "Vuoi inviarci materiale ? Bene, basta che lo mandi sotto forma di file direttamente al bot\." + \
                  "Ti chiediamo cortesemente se hai piu file di creare una cartella compressa e poi inviarla\. " + \
                  "Una volta revisionati i file riceverai crediti da poter usare eventualmente nel area exclusive\.\n\n" + \
                  "📕📕📕Buon Studio 📕📕📕\n\n" + \
                  "Innoltre ci terremo a farti presente che essendoci comunque un lavoro dietro di progettazione e mantenimento \n" \
                  "abbiamo messo a disposizione un modo per chi voglia di sostenerci con una piccola donazione /donation " \
                  "inoltre per ringraziare di ció con una donazione superiore a 3 euro si ottiene lo stato di Vip \n" \
                  "che consentira di beneficiare ilimitatamente di Exclusive"
        message = message.format(name, opening)
        return message

    @staticmethod
    def info_message() -> str:
        """
        composes the info message to send to the user
        :return: the message
        """
        message = "Sezione Ancora da definire"
        return message

    @staticmethod
    def exclusive_message() -> str:
        """
        composes the info message to send to the user
        :return: the message
        """
        message = "⭐EXCLUSIVE é una sezione dedicata a chi ci aiuta a " \
                  "espandere il Bot con materiale l'idea ci é sorta per ringrazziare" \
                  " i membri piú attivi al interno riserviamo il materiale piú 'raro' e difficile da " \
                  "reperire qualsiasi persona che aiutera fornendo materiale riceverá un equivalente di crediti che potrá usare per scaricare del materiale della sezione"
        return message

    @staticmethod
    def delete_last_message(update: Update, context: CallbackContext):
        """

        :param update:
        :param context:
        :return:
        """
        message_id = update.callback_query.message.message_id
        chat_id = update.callback_query.from_user.id

        context.bot.delete_message(chat_id=chat_id,
                                   message_id=message_id)

    @staticmethod
    def send_file(context, path, chat_id):
        """

        :param context:
        :param path:
        :param chat_id:
        :return:
        """

        file = FileHandler.get_file_id(path)
        if file is None:
            file = open(path, 'rb')
            # transform bytes to megabyte
            # check if file size is greater than 7MB
            if os.path.getsize(path) / 1000000 > 7:
                message = "OOOPS\.\.\.\. Questo è imbarazzante\.\.\.😞😞" \
                          "\nSembra che il file che hai richiesto non sia ancora stato caricato nei ☁ server\.\.\.\." \
                          "\npertanto sarà necessario un po' di tempo prima che ti arrivi \(10\-30 secondi\)☁"
                context.bot.send_message(chat_id=chat_id,
                                         text=message,
                                         parse_mode=telegram.ParseMode.MARKDOWN_V2)

        response = context.bot.send_document(
            chat_id=chat_id,
            document=file
        )
        FileHandler.add_file_id(
            path=path,
            file_id=response.document.file_id
        )

        if type(file) is _io.BufferedReader:
            file.close()

        DbHandler.increase_download(chat_id)
        DbHandler.update_state(chat_id)

    @staticmethod
    def is_md5(text):
        """

        :param text: the string to chek against
        :return:
        """
        # https://stackoverflow.com/a/14300703
        pattern = "^[a-f0-9]{32}$"
        return re.match(pattern=pattern, string=text) is not None

    @staticmethod
    def send_buttons(text, update, context, chat_id):
        # Normal files

        try:
            if "__file" in text:
                Utils.file_button_handler(context, text, chat_id)
            else:
                if Utils.is_md5(text):
                    Utils.delete_last_message(update, context)
                    unhashed_text = HashHandler.get_corresponding_text(text)
                    splitted_text = unhashed_text.split('/')
                    splitted_text_size = len(splitted_text)
                    path = unhashed_text
                    selected_text = splitted_text[-1].replace('_', ' ').replace('-', ' ')
                    try:
                        if splitted_text_size == 2:
                            message_text = f"Hai scelto:\n{selected_text}📚📚📚"
                            buttons = MainButtonsGenerator.get_buttons(path, two_columns=True, back_button=True)
                        elif splitted_text_size == 3:
                            message_text = "⏰Scegli il Materiale⏰"
                            buttons = MainButtonsGenerator.get_buttons(path, back_button=True)
                        elif splitted_text_size == 4:
                            message_text = "💥ECCO IL MATERIALE DELLA SEZIONE💥"
                            buttons = MainButtonsGenerator.get_buttons(path, back_button=True)
                        else:
                            message_text = f"Hai scelto:\n{selected_text}"
                            buttons = MainButtonsGenerator.get_buttons(path, back_button=True)
                    except IndexError:
                        message_text += f"\n\n Sembra non ci sia nulla qua"
                        buttons = MainButtonsGenerator.get_empty_buttons(path, back_button=True)
                        # Utils.generic_error_handler(update, context,
                        #                            "Sembra che non ci siano file qua", "send buttons:")

                else:
                    # Study Course button clicked
                    message_text = f"Hai scelto:\n🗄{text}🗄"
                    path = text
                    try:
                        buttons = MainButtonsGenerator.get_buttons(path)
                    except IndexError:
                        message_text += f"\n\n Sembra non ci sia nulla qua"
                        buttons = MainButtonsGenerator.get_empty_buttons(path)
                    # delete last message
                    Utils.delete_last_message(update, context)

                reply_markup = InlineKeyboardMarkup(buttons)
                context.bot.send_message(chat_id=chat_id,
                                         text=message_text,
                                         reply_markup=reply_markup)

        # It is not used it is only as a precaution
        except IndexError:
            Utils.generic_error_handler(update, context,
                                        "Sembra che non ci siano file qua", "send buttons:")
        except:
            #Handlers.Handlers.start_handler(update, context)
            Utils.generic_error_handler(update, context,
                                        "Ci sono stati degli errori prova a riavviare /start", "Generic BadRequest:")

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
    def generic_error_handler(update: Update, context: CallbackContext, error_message: str, debug_message: str):
        """
        Log the error and send a telegram message to notify the developer.
        :param debug_message:
        :param error_message:
        :param update:
        :param context:
        :return:
        """
        logging.debug("An Error Occurred ", debug_message)
        # traceback.print_tb(context.error.__traceback__)

        # message = "Ci dispiace😞😞" \
        # "\nSembra si sia verificato un'errore perfavore riavvia il bot utilizzando il comando \/start"

        try:
            context.bot.send_message(chat_id=update.callback_query.from_user.id,
                                     text=error_message,
                                     parse_mode=telegram.ParseMode.MARKDOWN_V2)
        except AttributeError:
            context.bot.send_message(chat_id=update.message.from_user.id,
                                     text=error_message,
                                     parse_mode=telegram.ParseMode.MARKDOWN_V2)

        return
