import json
import os
import math


class CustomFunctions:
    """Provides custom functions for data processing."""

    @staticmethod
    def get_data_modules(entity_list: list, data_product: str) -> list[str]:
        """Get data modules for a specific data product from a list of entities.

        Args:
            entity_list (list): List of entities.
            data_product (str): Data product to filter entities.

        Returns:
            list[str]: List of data modules for the specified data product.
        """
        return list(
            set(
                [
                    x.model_object.entity.dataModule
                    for x in entity_list
                    if x.model_object.entity.dataProduct == data_product
                ]
            )
        )

    @staticmethod
    def get_data_products(entity_list: list) -> list[str]:
        """Get unique data products from a list of entities.

        Args:
            entity_list (list): List of entities.

        Returns:
            list[str]: List of unique data products.
        """
        return list(set([x.model_object.entity.dataProduct for x in entity_list]))

    @staticmethod
    def get_entities_for_module(data_product: str, module: str, entity_list: list) -> list:
        """Get entities for a specific module and data product from a list of entities.

        Args:
            data_product (str): Data product to filter entities.
            module (str): Module to filter entities.
            entity_list (list): List of entities.

        Returns:
            list: List of entities matching the specified module and data product.
        """

        return [
            i.entity
            for i in CustomFunctions.get_model_objects_for_module(
                data_product=data_product, module=module, entity_list=entity_list
            )
        ]

    @staticmethod
    def get_model_objects_for_module(data_product: str, module: str, entity_list: list) -> list:
        """Get model objects for a specific module and data product from a list of entities.

        Args:
            data_product (str): Data product to filter entities.
            module (str): Module to filter entities.
            model_object (list): List of model objects.

        Returns:
            list: List of model_object matching the specified module and data product.
        """
        return [
            x.model_object
            for x in entity_list
            if x.model_object.entity.dataModule == module and x.model_object.entity.dataProduct == data_product
        ]

    @staticmethod
    def create_bucket_from_list(entity_list: list, bucket_size: int) -> list[list]:
        """Create buckets of entities from a list.

        Args:
            entity_list (list): List of entities.
            bucket_size (int): Size of each bucket.

        Returns:
            list[list]: List of buckets containing entities.
        """
        bucket_count = math.ceil(len(entity_list) / bucket_size)
        result = []

        for i in range(bucket_count):
            result.append((i, [x for x in entity_list[bucket_size * i : bucket_size * (i + 1)]]))

        return result

    @staticmethod
    def get_table_from_list(table: str, entity_list: list):
        """Get a table from a list of entities.

        Args:
            table (str): Table to retrieve.
            entity_list (list): List of entities.

        Returns:
            object: The specified table.
        """
        return [
            x.model_object.entity
            for x in entity_list
            if x.model_object.entity.name == table.name
            and x.model_object.entity.dataProduct == table.dataProduct
            and x.model_object.entity.dataModule == table.dataModule
        ].pop()

    @staticmethod
    def list_bk_columns(model_object) -> list[str]:
        """List all BK columns.

        Args:
            model_object: An model_object entity from DataM8
        Returns:
            list: the list if BK columns names. an empty list if no BK column exists.
        """
        return [col.name for col in model_object.entity.attribute if col.history.value == "BK"]

    @staticmethod
    def list_scd0_columns(model_object) -> list[str]:
        """List all SCD0 columns.

        Args:
            model_object: An model_object entity from DataM8
        Returns:
            list: the list if SCD0 columns names. an empty list if no SCD0 column exists.
        """
        return [col.name for col in model_object.entity.attribute if col.history.value == "SCD0"]

    @staticmethod
    def list_scd1_columns(model_object) -> list[str]:
        """List all SCD1 columns.

        Args:
            model_object: An model_object entity from DataM8
        Returns:
            list: the list if SCD1 columns names. an empty list if no SCD1 column exists.
        """
        return [col.name for col in model_object.entity.attribute if col.history.value == "SCD1"]

    @staticmethod
    def list_scd2_columns(model_object) -> list[str]:
        """List all SCD2 columns.

        Args:
            model_object: An model_object entity from DataM8
        Returns:
            list: the list if SCD2 columns names. an empty list if no SCD2 column exists.
        """
        return [col.name for col in model_object.entity.attribute if col.history.value == "SCD2"]


def get_dict_modules() -> dict:
    """Retrieves a dictionary containing modules.

    Returns:
        dict: Dictionary containing modules.
    """
    __dict = {"custom_functions": CustomFunctions, "json": json, "os": os}

    return __dict
