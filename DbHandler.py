import logging
from datetime import datetime

from DbConnection import DbConnection


class DbHandler:
    db_connection = DbConnection.get_instance()

    @staticmethod
    def is_vip(chat_id: int) -> bool:
        """
        check if the user with the given chat id is vip
        :param chat_id: the id of the user
        :return:
        """
        value = DbHandler.db_connection.get_vip_value(chat_id)
        value = bool(value)
        logging.debug(f"User with chat_id: {chat_id}, has a vip value: {value}")
        return value

    @staticmethod
    def add_vip(chat_id: int):
        """
        Set Vip with the given chat id
        :param chat_id: the id of the user
        :return:
        """
        DbHandler.db_connection.add_vip(chat_id)
        logging.debug(f"User with chat_id: {chat_id}, has VIP now")

    @staticmethod
    def get_credits(chat_id: int) -> int:
        """
        retrieves the number of credits of the given chat id
        :param chat_id: the id of the user
        :return:
        """
        value = DbHandler.db_connection.get_credits(chat_id)
        logging.debug(f"User with chat_id: {chat_id}, has {value} credits")
        return value

    @staticmethod
    def update_credits(value: int, **kwargs) -> bool:
        """"
        modifies the credits of the user with the given chat_id adding the given quantity
        :param value: the quantity of credits to add
        :param kwargs: the id of the user or username syntax ' chat_id=XX or user_id=XX '
        :return:
        """
        if kwargs.__contains__("chat_id"):
            chat_id = kwargs.get("chat_id")
        else:
            chat_id = DbHandler.db_connection.get_chat_id(kwargs.get("user_id"))
        curr_value = DbHandler.db_connection.get_credits(chat_id)
        if value < 0 and (-1 * value) > curr_value:
            logging.debug(f"Can't subtract {-1 * value} credits to User with chat_id: {chat_id}")
            return False
        else:
            new_value = curr_value + value
            DbHandler.db_connection.update_credits(chat_id, new_value)
            return chat_id

    @staticmethod
    def update_credits_all(value: int) -> bool:
        return DbHandler.update_credits_all(value)

    @staticmethod
    def increase_download(chat_id: int):
        """
        Increases the download count of the user with the given chat id
        :param chat_id: the id of the user
        :return:
        """
        DbHandler.db_connection.increase_download(chat_id)
        logging.debug(f"Increased downloads of User with chat_id: {chat_id}")

    @staticmethod
    def update_state(chat_id: int):
        """
        updates the state column inside the User table with the current date and time
        :param chat_id: the id of the user
        :return:
        """
        today = datetime.now()
        today = today.replace(microsecond=0)
        DbHandler.db_connection.update_state(chat_id, today)

    @staticmethod
    def add_user(chat_id: int, username: str, f_name: str):
        """
        check if the user is present in the database if not
        add the user to it
        :param f_name: user first name
        :param chat_id: the id of user
        :param username: username
        :return:
        """
        today = datetime.now()
        today = today.replace(microsecond=0)

        # check if user already exists
        if not DbHandler.db_connection.contains(chat_id):
            DbHandler.db_connection.add_user(chat_id, f_name, username, today)

    @staticmethod
    def get_stats() -> tuple:
        """
        queries the Download table and returns the number of downloads
        :return: a tuple containing the total number of downloads and the total number of users
        """
        data = DbHandler.db_connection.get_stats()
        downloads = 0
        user_count = 0
        for _, d in data:
            downloads += d
            user_count += 1
        return downloads, user_count

    @staticmethod
    def get_id(username: str) -> int:
        return DbHandler.db_connection.get_chat_id(username)

    @staticmethod
    def get_all_id() -> list:
        return DbHandler.get_all_id()

    @staticmethod
    def remove_id(**kwargs):
        """"
        modifies the credits of the user with the given chat_id adding the given quantity
        :param value: the quantity of credits to add
        :param kwargs: the id of the user or username syntax ' chat_id=XX or user_id=XX '
        :return:
        """
        if kwargs.__contains__("chat_id"):
            chat_id = kwargs.get("chat_id")
        else:
            chat_id = DbHandler.db_connection.get_chat_id(kwargs.get("user_id"))
        curr_value = DbHandler.db_connection.delete_user(chat_id)

