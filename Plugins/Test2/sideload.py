import polars as pl
from datam8.plugins import Plugin
from datam8_model.plugin import UiSchema


class Test(Plugin):
    pass

    def list_schemas(self) -> pl.DataFrame:
        return pl.DataFrame()

    @classmethod
    def get_ui_schema(cls) -> UiSchema:
        return UiSchema(title="Test 2", authModes=[])
