import logging
import sqlite3


class DbConnection:
    __instance = None

    def __initialize(self):
        path = 'db/UserLogDB.db'
        try:
            self.conn = sqlite3.connect(path)
            logging.debug("Connected to DB!")
        except sqlite3.Error as error:
            logging.debug("An Error Occurred during db connection: ")
            logging.debug(f"{error}")

    @staticmethod
    def get_instance():
        if DbConnection.__instance is None:
            DbConnection.__instance = DbConnection()
            DbConnection.__instance.__initialize()
        return DbConnection.__instance

    def get_vip_value(self, chat_id):
        """
        check the value of the vip column for the given chat id
        :param chat_id: the id of the user
        :return:
        """
        cur = self.conn.cursor()
        query = f"SELECT Vip FROM Reserved WHERE chat_id=={chat_id}"
        cur.execute(query)
        result = cur.fetchone()
        if result is None:
            logging.debug(f"ERROR invalid chat id: {chat_id}")
            return 0
        else:
            return result[0]
