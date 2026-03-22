import polars as pl
from datam8.plugins import Plugin
from datam8_model.plugin import UiSchema


class Test(Plugin):
    pass

    def preview_data(self, table: str, /, schema: str | None = None, *, limit: int = 10) -> pl.LazyFrame:
        return pl.LazyFrame()

    @classmethod
    def get_ui_schema(cls) -> UiSchema:
        return UiSchema(title="Test", authModes=[])
