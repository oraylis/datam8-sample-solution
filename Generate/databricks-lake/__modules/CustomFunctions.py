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
        result = []
        for x in entity_list:
            # Check if v1 or v2 entity structure
            if hasattr(x, 'model_object') and hasattr(x.model_object, 'entity') and hasattr(x.model_object.entity, 'dataProduct'):
                # V1 structure
                if x.model_object.entity.dataProduct == data_product:
                    result.append(x.model_object.entity.dataModule)
            elif hasattr(x, 'data_product') and hasattr(x, 'data_module'):
                # V2 structure (UnifiedEntityFactory)
                if x.data_product == data_product:
                    result.append(x.data_module)
        return list(set(result))

    @staticmethod
    def get_data_products(entity_list: list) -> list[str]:
        """Get unique data products from a list of entities.

        Args:
            entity_list (list): List of entities.

        Returns:
            list[str]: List of unique data products.
        """
        result = []
        for x in entity_list:
            # Check if v1 or v2 entity structure
            if hasattr(x, 'model_object') and hasattr(x.model_object, 'entity') and hasattr(x.model_object.entity, 'dataProduct'):
                # V1 structure
                result.append(x.model_object.entity.dataProduct)
            elif hasattr(x, 'data_product'):
                # V2 structure (UnifiedEntityFactory)
                result.append(x.data_product)
        return list(set(result))

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
            entity_list (list): List of entities.

        Returns:
            list: List of model_object matching the specified module and data product.
        """
        result = []
        for x in entity_list:
            # Check if v1 or v2 entity structure
            if hasattr(x, 'model_object') and x.model_object and hasattr(x.model_object.entity, 'dataModule'):
                # V1 structure
                if x.model_object.entity.dataModule == module and x.model_object.entity.dataProduct == data_product:
                    result.append(x.model_object)
            elif hasattr(x, 'data_product') and hasattr(x, 'data_module'):
                # V2 structure (UnifiedEntityFactory)
                if x.data_module == module and x.data_product == data_product:
                    result.append(x)  # For v2, return the UnifiedEntityFactory itself
        return result

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
    def get_table_from_list(table, entity_list: list):
        """Get a table from a list of entities.

        Args:
            table: Table to retrieve (can be v1 or v2 entity).
            entity_list (list): List of entities.

        Returns:
            object: The specified table entity.
        """
        for x in entity_list:
            # Check if v1 or v2 entity
            if hasattr(x, 'model_object') and x.model_object:
                # V1 structure - access from entity JSON
                entity_obj = x.model_object.entity
                name_match = entity_obj.name == table.name
                product_match = entity_obj.dataProduct == table.dataProduct  
                module_match = entity_obj.dataModule == table.dataModule
            else:
                # V2 structure - access from UnifiedEntityFactory properties
                name_match = x.entity_name == table.name
                product_match = x.data_product == table.dataProduct
                module_match = x.data_module == table.dataModule
                entity_obj = x.entity
                
            if name_match and product_match and module_match:
                return entity_obj
        
        # If no match found, return None
        return None

    @staticmethod
    def list_bk_columns(model_object) -> list[str]:
        """List all BK columns.

        Args:
            model_object: An model_object entity from DataM8 (v1) or UnifiedEntityFactory (v2)
        Returns:
            list: the list if BK columns names. an empty list if no BK column exists.
        """
        if not hasattr(model_object, 'entity') or not hasattr(model_object.entity, 'attribute'):
            return []
            
        result = []
        for col in model_object.entity.attribute:
            # Check if v1 structure (has history attribute)
            if hasattr(col, 'history') and hasattr(col.history, 'value'):
                if col.history.value == "BK":
                    result.append(col.name)
            # Check if v2 structure (has type attribute directly)
            elif hasattr(col, 'type') and col.type == "BK":
                result.append(col.name)
        return result

    @staticmethod
    def list_scd0_columns(model_object) -> list[str]:
        """List all SCD0 columns.

        Args:
            model_object: An model_object entity from DataM8 (v1) or UnifiedEntityFactory (v2)
        Returns:
            list: the list if SCD0 columns names. an empty list if no SCD0 column exists.
        """
        if not hasattr(model_object, 'entity') or not hasattr(model_object.entity, 'attribute'):
            return []
            
        result = []
        for col in model_object.entity.attribute:
            # Check if v1 structure (has history attribute)
            if hasattr(col, 'history') and hasattr(col.history, 'value'):
                if col.history.value == "SCD0":
                    result.append(col.name)
            # Check if v2 structure (has type attribute directly)
            elif hasattr(col, 'type') and col.type == "SCD0":
                result.append(col.name)
        return result

    @staticmethod
    def list_scd1_columns(model_object) -> list[str]:
        """List all SCD1 columns.

        Args:
            model_object: An model_object entity from DataM8 (v1) or UnifiedEntityFactory (v2)
        Returns:
            list: the list if SCD1 columns names. an empty list if no SCD1 column exists.
        """
        if not hasattr(model_object, 'entity') or not hasattr(model_object.entity, 'attribute'):
            return []
            
        result = []
        for col in model_object.entity.attribute:
            # Check if v1 structure (has history attribute)
            if hasattr(col, 'history') and hasattr(col.history, 'value'):
                if col.history.value == "SCD1":
                    result.append(col.name)
            # Check if v2 structure (has type attribute directly)
            elif hasattr(col, 'type') and col.type == "SCD1":
                result.append(col.name)
        return result

    @staticmethod
    def list_scd2_columns(model_object) -> list[str]:
        """List all SCD2 columns.

        Args:
            model_object: An model_object entity from DataM8 (v1) or UnifiedEntityFactory (v2)
        Returns:
            list: the list if SCD2 columns names. an empty list if no SCD2 column exists.
        """
        if not hasattr(model_object, 'entity') or not hasattr(model_object.entity, 'attribute'):
            return []
            
        result = []
        for col in model_object.entity.attribute:
            # Check if v1 structure (has history attribute)
            if hasattr(col, 'history') and hasattr(col.history, 'value'):
                if col.history.value == "SCD2":
                    result.append(col.name)
            # Check if v2 structure (has type attribute directly)
            elif hasattr(col, 'type') and col.type == "SCD2":
                result.append(col.name)
        return result


def get_dict_modules() -> dict:
    """Retrieves a dictionary containing modules.

    Returns:
        dict: Dictionary containing modules.
    """
    __dict = {"custom_functions": CustomFunctions, "json": json, "os": os}

    return __dict
