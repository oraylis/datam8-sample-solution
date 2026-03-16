from typing import Any
from datam8.plugins import Plugin


class Test(Plugin):
    pass

    def get_ui_schema(self) -> Any:
        print("Test pluging from file")
