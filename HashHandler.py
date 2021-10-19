import hashlib

from pympler import asizeof


class HashHandler:
    lookup_table = {}

    @classmethod
    def generate_hash(cls, text):
        """

        :param text:
        :return:
        """
        result = hashlib.md5(text.encode()).hexdigest()
        cls.lookup_table[result] = text
        print(f"the hash_path table has {len(cls.lookup_table)}")
        print(f"the size is {asizeof.asizeof(cls.lookup_table)}")
        return result

    @classmethod
    def get_corresponding_text(cls, hash_text: str):
        """

        :param hash_text: the text to transform into plain text
        :return:
        """
        result = cls.lookup_table.get(hash_text, None)
        return result
