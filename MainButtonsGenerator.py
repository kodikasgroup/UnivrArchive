import os

from telegram import InlineKeyboardButton

from HashHandler import HashHandler


# noinspection PyTypeChecker
class MainButtonsGenerator:
    @staticmethod
    def get_buttons(button_path: str = "", **kwargs):
        """
        utils method that given the parameters it build the buttons
        :param button_path: the path of the clicked buttons
        :return: a list of buttons built following the given parameters
        """


        path = "archive" + "/" + button_path
        # since the directory name could contain an underscore we use double underscore to separate the
        # given string from the rest
        buttons = [
            InlineKeyboardButton(
                f"📖{d_name.replace('_', ' ').replace('-', ' ')}📖",
                callback_data=HashHandler.generate_hash(button_path + '/' + d_name) + '__file'
            ) if os.path.isfile(path + '/' + d_name)
            else
            InlineKeyboardButton(
                f"{d_name.replace('_', ' ').replace('-', ' ')}",
                callback_data=HashHandler.generate_hash(button_path + '/' + d_name)
            )
            for d_name in os.listdir(path)
        ]

        if "two_columns" in kwargs and kwargs["two_columns"] is True:
            # group subjects, MAX 2 on each row
            grouped_buttons = zip(
                buttons[:len(buttons) // 2],
                buttons[len(buttons) // 2:]
            )
            grouped_buttons = [list(t) for t in grouped_buttons]

            if len(buttons) % 2 != 0:
                grouped_buttons.append(
                    [buttons[-1]]
                )
            buttons = [
                *grouped_buttons
            ]
        if not type(buttons[0]) is list:
            # each button should be contained into a list
            buttons = [[b] for b in buttons]

        if "back_button" in kwargs and kwargs["back_button"] is True:
            back_callback_data = HashHandler.generate_hash(button_path)
            buttons.append(
                [
                    InlineKeyboardButton('<< BACK', callback_data=back_callback_data+"/BACK"),
                    InlineKeyboardButton('🏠HOME', callback_data='HOME')
                ]
            )
        else:
            buttons.append(
                [
                    InlineKeyboardButton('🏠HOME', callback_data='HOME')
                ]
            )

        return buttons

    @staticmethod
    def get_empty_buttons(button_path: str = "", **kwargs):
        buttons = []
        if "back_button" in kwargs and kwargs["back_button"] is True:
            back_callback_data = HashHandler.generate_hash(button_path)
            buttons.append(
                [
                    InlineKeyboardButton('<< BACK', callback_data=back_callback_data+"/BACK"),
                    InlineKeyboardButton('🏠HOME', callback_data='HOME')
                ]
            )
        else:
            buttons.append(
                [
                    InlineKeyboardButton('🏠HOME', callback_data='HOME')
                ]
            )

        return buttons

    @staticmethod
    def get_start_buttons() -> list:
        """
        checks all the directories inside the archive directory
        then for each one it generates a button
        :return:
        """
        path = "archive"
        buttons = []
        for d_name in os.listdir(path):
            if d_name == "EXCLUSIVE":
                # append eight pointed black star to the front and the back of the button text
                button_text = "✴" + d_name + "✴"
                buttons.append([InlineKeyboardButton(button_text, callback_data=d_name)])
            else:
                # append pencil to the front and the back of the button text
                button_text = "✏" + d_name + "✏"
                buttons.append([InlineKeyboardButton(button_text, callback_data=d_name)])
        return buttons
