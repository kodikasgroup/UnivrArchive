import logging
import sqlite3


class DbConnection:
    __instance = None

    def __initialize(self):
        """
        establish connection to database
        :return:
        """
        path = 'db/UserLogDB.db'
        try:
            self.conn = sqlite3.connect(path)
            logging.debug("Connected to DB!")
        except sqlite3.Error as error:
            logging.debug("An Error Occurred during db connection: ")
            logging.debug(f"{error}")

    def __execute_query(self, query: str, chat_id: int):
        """
        executes the given query and then returns the result of the execution
        :param query:
        :param chat_id:
        :return:
        """
        cur = self.conn.cursor()
        cur.execute(query)
        result = cur.fetchall()
        if result is None:
            logging.debug(f"ERROR invalid chat id: {chat_id}")
            return 0
        else:
            if len(result) == 1:
                return result[0][0]

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
        query = f"SELECT Vip FROM Reserved WHERE chat_id=={chat_id}"
        return self.__execute_query(query, chat_id)

    def get_credits(self, chat_id: int) -> int:
        """
        retrieves the number of credits of the given chat id
        :param chat_id: the id of the user
        :return:
        """
        query = f"SELECT Credit FROM Reserved WHERE chat_id=={chat_id}"
        return self.__execute_query(query, chat_id)
