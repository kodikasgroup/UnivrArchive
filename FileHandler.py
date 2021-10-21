from pympler import asizeof


class FileHandler:
    files = {}

    @classmethod
    def get_file_id(cls, path) -> int:
        """

        :param path:
        :return:
        """
        return cls.files.get(path, None)

    @classmethod
    def add_file_id(cls, path, file_id) -> None:
        """

        :param path:
        :param file_id:
        :return:
        """
        cls.files[path] = file_id
