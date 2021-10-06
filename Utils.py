import os

import telegram
from telegram import Update
from telegram.ext import CallbackContext

from FileHandler import FileHandler


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
                  "📕📕📕Buon Studio 📕📕📕"
        message = message.format(name, opening)
        return message

    @staticmethod
    def delete_last_message(update: Update, context: CallbackContext):
        message_id = update.callback_query.message.message_id
        chat_id = update.callback_query.from_user.id

        context.bot.delete_message(chat_id=chat_id,
                                   message_id=message_id)

    @staticmethod
    def send_file(context, path, chat_id):
        # TODO increase downloads
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
