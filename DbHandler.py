import logging

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
    def update_credits(chat_id: int, value: int) -> bool:
        """"
        modifies the credits of the user with the given chat_id adding the given quantity
        :param chat_id: the id of the user
        :param value: the quantity of credits to add
        :return:
        """
        curr_value = DbHandler.db_connection.get_credits(chat_id)
        if value < 0 and (-1 * value) > curr_value:
            logging.debug(f"Can't subtract {-1 * value} credits to User with chat_id: {chat_id}")
            return False
        else:
            new_value = curr_value + value
            DbHandler.db_connection.update_credits(chat_id, new_value)
            return True

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
        DbHandler.db_connection.update_state(chat_id)