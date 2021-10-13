import os

import telegram
from telegram import Update
from telegram.ext import CallbackContext

from DbHandler import DbHandler
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
        DbHandler.increase_download(chat_id)
        DbHandler.update_state(chat_id)
