import logging
import sqlite3
from datetime import datetime


class DbConnection:
    __instance = None

    def __initialize(self):
        """
        establish connection to database
        :return:
        """
        path = 'db/UserLogDB.db'
        try:
            self.conn = sqlite3.connect(path, check_same_thread=False)
            logging.debug("Connected to DB!")
        except sqlite3.Error as error:
            logging.debug("An Error Occurred during db connection: ")
            logging.debug(f"{error}")

    def __execute__query(self, query: str, *args) -> None:
        """
        executes the given query
        :param query: the sql interrogation to execute
        :return:
        """
        try:
            cur = self.conn.cursor()
            if len(args) != 0:
                cur.execute(query, *args)
            else:
                cur.execute(query)
            self.conn.commit()
        except sqlite3.Error as error:
            logging.debug("An Error Occurred during the execution of the following query:\n" +
                          query)
            logging.debug(f"{error}")

    def __execute_select_query(self, query: str, *args):
        """
        executes the given query and then returns the result of the execution
        :param query: the sql interrogation to execute
        :return:
        """
        cur = self.conn.cursor()
        if len(args) != 0:
            cur.execute(query, args)
        else:
            cur.execute(query)
        result = cur.fetchall()
        if result is None:
            logging.debug(f"ERROR invalid query:\n" + query)
            return 0
        else:
            if len(result) == 1:
                return result[0][0]
            else:
                return result

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
        return self.__execute_select_query(query)

    def get_credits(self, chat_id: int) -> int:
        """
        retrieves the number of credits of the given chat id
        :param chat_id: the id of the user
        :return:
        """
        query = f"SELECT Credit FROM Reserved WHERE chat_id=={chat_id}"
        return self.__execute_select_query(query)

    def update_credits(self, chat_id: int, value: int) -> None:
        """
        modifies the credits of the user with the given chat_id adding the given quantity
        :param chat_id: the id of the user
        :param value: the quantity of credits to add
        :return:
        """
        query = f"UPDATE Reserved SET Credit = {value} WHERE chat_id=={chat_id}"
        self.__execute__query(query)

    def increase_download(self, chat_id: int):
        """
        Increases the download count of the user with the given chat id
        :param chat_id: the id of the user
        :return:
        """
        query = f"UPDATE Download SET n_download = n_download+1 WHERE chat_id=={chat_id}"
        self.__execute__query(query)

    def update_state(self, chat_id: int, today: datetime):
        """
        updates the state column inside the User table with the current date and time
        :param today: current date and time
        :param chat_id: the id of the user
        :return:
        """
        query = "UPDATE User SET state = ? WHERE chat_id==?"
        self.__execute__query(query, today, chat_id)

    def contains(self, chat_id: int) -> bool:
        """
        Checks if the user is present into the db
        :param chat_id: the id of the user
        :return:
        """
        query = f"SELECT * FROM User WHERE chat_id=={chat_id}"
        result = self.__execute_select_query(query)
        return result is not None and not len(result) == 0

    def get_chat_id(self, username: str) -> int:
        """
        Given a username checks into the db and
        returns the chat id corresponding
        :param username: the username
        :return:
        """
        query = f"SELECT chat_id FROM User WHERE username==?"
        result = self.__execute_select_query(query, username)
        return result

    def add_user(self, chat_id: int, f_name: str, username: str, today: datetime):
        query = "INSERT INTO User VALUES (?, ?, ?, ?)"
        self.__execute__query(query, (chat_id, f_name, username, today))
