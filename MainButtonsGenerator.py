import os

from telegram import InlineKeyboardButton

from HashHandler import HashHandler


class ButtonGenerator:
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
                buttons.append([InlineKeyboardButton(button_text, callback_data=d_name + '__course')])
        return buttons

    @staticmethod
    def get_year_buttons(course: str) -> list:
        """
        checks all the directories inside the given directory
        then for each one it generates a button
        :param course: the name of the selected course
        :return:
        """
        path = "archive" + "/" + course
        # since the directory name could contain an underscore we use double underscore to separate the
        # `year` string from the rest
        year_buttons = [InlineKeyboardButton(d_name.replace('_', ' '), callback_data=course + '/' + d_name + '__year')
                        for d_name in os.listdir(path)]

        buttons = [
            year_buttons,
            [InlineKeyboardButton('🏠HOME', callback_data='HOME')]
        ]
        return buttons

    @staticmethod
    def get_subject_buttons(course: str, year: str) -> list:
        """
        checks all the directories inside the directory of the selected course and selected year
        then for each one it generates a button
        :param course: the name of the selected course
        :param year: the name of the selected year
        :return:
        """

        path = "archive" + "/" + course + "/" + year
        # since the directory name could contain an underscore we use double underscore to separate the
        # `subject` string from the rest
        subject_buttons = [
            InlineKeyboardButton(
                d_name.replace('_', ' '),
                callback_data=course + '/' + year + '/' + d_name + '/' + '__subject'
            ) for d_name in os.listdir(path)
        ]

        # group subjects, MAX 2 on each row
        grouped_subject_buttons = zip(
            subject_buttons[:len(subject_buttons) // 2],
            subject_buttons[len(subject_buttons) // 2:]
        )
        grouped_subject_buttons = [list(t) for t in grouped_subject_buttons]

        if len(subject_buttons) % 2 != 0:
            grouped_subject_buttons.append(
                [subject_buttons[-1]]
            )

        base_back_file_callback_data = course + '/' + year
        back_callback_data = HashHandler.generate_hash(base_back_file_callback_data) + "/" + 'BACK__subject'
        buttons = [
            *grouped_subject_buttons,
            [
                InlineKeyboardButton('<< BACK', callback_data=back_callback_data),
                InlineKeyboardButton('🏠HOME', callback_data='HOME')
            ]
        ]
        return buttons

    @staticmethod
    def get_subdir_buttons(course: str, year: str, subject) -> list:
        """
        checks all the directories inside the directory of the selected course, selected year and selected subject
        then for each one it generates a button
        :param course: the name of the selected course
        :param year: the name of the selected year
        :param subject: the name of the selected subject
        :return:
        """
        path = "archive" + "/" + course + "/" + year + "/" + subject
        base_subdir_callback_data = course + "/" + year + "/" + subject + "/"
        subdir_buttons = [
            [
                InlineKeyboardButton(
                    d_name.replace('_', ' ').replace('-', ' '),
                    callback_data=HashHandler.generate_hash(base_subdir_callback_data + d_name) + '__subdir'
                )
            ] for d_name in os.listdir(path)
        ]
        base_back_file_callback_data = course + '/' + year + '/' + subject
        back_callback_data = HashHandler.generate_hash(base_back_file_callback_data) + "/" + 'BACK__subdir'
        buttons = [*subdir_buttons,
                   [
                       InlineKeyboardButton('<< BACK', callback_data=back_callback_data),
                       InlineKeyboardButton('🏠HOME', callback_data='HOME')]
                   ]
        return buttons

    @staticmethod
    def get_file_buttons(course, year, subject, subdir) -> list:
        """
        checks all the files inside the directory of the selected course, selected year, selected subject and
        selected subdir then for each one it generates a button
        :param course: the name of the selected course
        :param year: the name of the selected year
        :param subject: the name of the selected subject
        :param subdir: the name of the selected subdirectory (EG: APPUNTI)
        :return:
        """
        path = "archive" + "/" + course + "/" + year + "/" + subject + "/" + subdir
        base_file_callback_data = course + "/" + year + "/" + subject + "/" + subdir + "/"
        file_buttons = [
            [
                InlineKeyboardButton(
                    '📖' + d_name.replace('_', ' ').replace('-', ' ') + '📖',
                    callback_data=HashHandler.generate_hash(base_file_callback_data + d_name) + '__file'
                )
            ] for d_name in os.listdir(path)
        ]

        base_back_file_callback_data = course + '/' + year + '/' + subject + "/" + subdir
        back_callback_data = HashHandler.generate_hash(base_back_file_callback_data) + "/" + 'BACK__file'
        buttons = [
            *file_buttons,
            [
                InlineKeyboardButton('<< BACK', callback_data=back_callback_data),
                InlineKeyboardButton('🏠HOME', callback_data='HOME')
            ]
        ]

        return buttons
