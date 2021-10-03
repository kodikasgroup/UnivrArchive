import os

from telegram import InlineKeyboardButton

from HashHandler import HashHandler


class ExclusiveButtonGenerator:
    @staticmethod
    def _get_exclusive_buttons(path: str, button_type: str, button_path: str = ""):
        """
        utils method that given the parameters it build the buttons
        :param path: the real path to the directory
        :param button_type: it specifies what the button represents E.G file, course ecc...
        :param button_path: the path of the clicked buttons
        :return: a list of buttons built following the given parameters
        """
        # since the directory name could contain an underscore we use double underscore to separate the
        # given string from the rest
        buttons = [
            InlineKeyboardButton(
                d_name.replace('_', ' '),
                callback_data=HashHandler.generate_hash(button_path + '/' + d_name) + '#EXCLUSIVE' + button_type
            ) for d_name in os.listdir(path)
        ]
        return buttons

    @staticmethod
    def _get_exclusive_back_buttons(button_type: str, button_path: str = ""):
        back_callback_data = HashHandler.generate_hash(button_path) + "#EXCLUSIVE#" + "BACK" + button_type
        return InlineKeyboardButton('<< BACK', callback_data=back_callback_data)

    @staticmethod
    def get_course_buttons() -> list:
        """
        builds the buttons displaying the available courses in the EXCLUSIVE Section
        :return:
        """

        button_path = "EXCLUSIVE"
        path = "archive/" + button_path
        buttons = ExclusiveButtonGenerator._get_exclusive_buttons(path, "__course", button_path)
        buttons = [[b] for b in buttons]
        buttons.append(
            [InlineKeyboardButton('🏠HOME', callback_data='HOME')]
        )
        return buttons

    @staticmethod
    def get_year_buttons(course: str) -> list:
        """
        builds the buttons displaying the available years of study
        in the EXCLUSIVE Section of the selected course
        :return:
        """

        button_path = "EXCLUSIVE/" + course
        path = "archive/" + button_path
        buttons = ExclusiveButtonGenerator._get_exclusive_buttons(path, "__year", button_path)
        buttons.reverse()
        buttons = [[b] for b in buttons]
        buttons.append(
            [ExclusiveButtonGenerator._get_exclusive_back_buttons("__year", button_path),
             InlineKeyboardButton('🏠HOME', callback_data='HOME')]
        )
        return buttons

    @staticmethod
    def get_subject_buttons(course: str, year: str) -> list:
        """

        :return:
        """

        button_path = "EXCLUSIVE/" + course + "/" + year
        path = "archive/" + button_path
        buttons = ExclusiveButtonGenerator._get_exclusive_buttons(path, "__subject", button_path)
        buttons = [[b] for b in buttons]
        buttons.append(
            [ExclusiveButtonGenerator._get_exclusive_back_buttons("__subject", button_path),
             InlineKeyboardButton('🏠HOME', callback_data='HOME')]
        )
        return buttons

    @staticmethod
    def get_file_buttons(course, year, subject) -> list:
        button_path = "EXCLUSIVE/" + course + "/" + year + "/" + subject
        path = "archive/" + button_path
        buttons = ExclusiveButtonGenerator._get_exclusive_buttons(path, "__file", button_path)
        buttons = [[b] for b in buttons]
        buttons.append(
            [ExclusiveButtonGenerator._get_exclusive_back_buttons("__file", button_path),
             InlineKeyboardButton('🏠HOME', callback_data='HOME')]
        )
        return buttons
