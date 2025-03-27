import re
import json
import math
from typing import Any


class Helper:
    """Provides various utility methods."""

    @staticmethod
    def get_columns_by_tag(columns: list, tag: str) -> list:
        """Get a subset of columns by the given tag.

        Args:
            columns (list): List of columns to filter.
            tag (str): The tag which will be used to filter.

        Returns:
            list: A list of the subset of columns.
        """
        return [col for col in columns if tag in col.tags]

    @staticmethod
    def cleanup_name(name: str):
        """Cleans up a string to make it a valid identifier.

        Args:
            name (str): The string to be cleaned up.

        Returns:
            str: Cleaned up string.
        """
        translated_name = Helper.translate_umlaute(name)
        r = re.sub("[^a-zA-Z0-9_]", "_", translated_name)
        return r

    @staticmethod
    def cleanup_path(name: str):
        """Cleans up a string to make it suitable for a file path.

        Args:
            name (str): The string to be cleaned up.

        Returns:
            str: Cleaned up string.
        """
        r = re.sub("[^a-zA-Z0-9_/-]", "_", name)
        return r

    @staticmethod
    def translate_umlaute(characters: str):
        """Translates German umlaut characters to their ASCII equivalents.

        Args:
            characters (str): The string containing German umlaut characters.

        Returns:
            str: String with translated umlaut characters.
        """
        umlaute_translations = {
            ord("ä"): "ae",
            ord("Ä"): "Ae",
            ord("ü"): "ue",
            ord("Ü"): "Ue",
            ord("ö"): "oe",
            ord("Ö"): "Oe",
            ord("ß"): "ss",
        }
        return characters.translate(umlaute_translations)

    @staticmethod
    def build_name(*args: Any):
        """Builds a valid identifier from the given strings.

        Args:
            args (str): Strings to be joined.

        Returns:
            str: Joined string with cleaned up characters.
        """
        n = "_".join(map(str, args))
        return Helper.cleanup_name(n)

    @staticmethod
    def build_path(*args: str):
        """Builds a file path from the given strings.

        Args:
            args (str): Strings to be joined.

        Returns:
            str: Joined string with cleaned up characters.
        """
        n = "/".join(args)
        return Helper.cleanup_path(n)

    @staticmethod
    def attribute_mapping_to_dict(attribute_mapping: list[dict]) -> dict:
        """Converts a list of attribute mappings into a dictionary.

        Args:
            attribute_mapping (list): List of dictionaries representing attribute mappings.

        Returns:
            dict: Dictionary with attribute mappings.
        """
        return {item.target: item.source for item in attribute_mapping}

    @staticmethod
    def test_cleanup_name():
        """Test the cleanup_name method."""
        data = ["Create_stage_EBMS_main_EV585_FUNC_TYPES$", "_ABCDEF_ghijkl_0123456789^°§$%&/()=?`*+#'-.:,;<|³@€>"]
        [print(f"{d} -> {Helper.cleanup_name(d)}") for d in data]

    @staticmethod
    def test_build_name():
        """Test the build_name method."""
        print(Helper.build_name("abc", "sf$", "eg9"))
        print(Helper.build_name())
        print(Helper.build_name("abc", "sf$", "888"))

    @staticmethod
    def test_cleanup_path():
        """Test the cleanup_path method."""
        data = ["stage/EBMS/main/EV585_FUNC_TYPES$", "_A/B/C/DEF_ghijkl_0123456789^°§$%&/()=?`*+#'-.:,;<|³@€>"]
        [print(f"{d} -> {Helper.cleanup_path(d)}") for d in data]

    @staticmethod
    def test_build_path():
        """Test the build_path method."""
        print(Helper.build_path("abc", "sf$", "eg9"))
        print(Helper.build_path())
        print(Helper.build_path("abc", "sf$", "888"))


def get_dict_modules() -> dict:
    """Retrieves a dictionary containing modules.

    Returns:
        dict: Dictionary containing modules.
    """
    __dict = {
        "helper": Helper,
        "len": len,
        "str": str,
        "json": json,
        "math": math,
    }
    return __dict


# Unit tests
if __name__ == "__main__":
    Helper.test_cleanup_name()
    Helper.test_build_name()
    Helper.test_cleanup_path()
    Helper.test_build_path()
