"""Module to hold system information available for all templates"""

# TODO: adapt dictionaries to match your `Generate/databricks-lake/databricks.yml.jinja2`


class SystemProperties:
    """Provides access to system properties"""

    # TODO: fill out general information for your setup

    # Name of Azure Data Lake Gen2
    datalake_name = {
        "dev": "datam80adl0dev",
        "prod": "datam80adl0dev",
    }
    datalake_container_name = {
        "dev": "lakehousesample",
        "prod": "lakehousesample",
    }

    # target folders for the generator
    etl_folder = "/etl"
    utils_folder = "000-utils"
    raw_folder = "010-raw"
    stage_folder = "020-stage"
    core_folder = "030-core"
    curated_folder = "031-curated"

    # TODO: seperate into different classes?
    # class Databricks:
    #     """Provides access to databricks related properties"""

    # TODO: fill out the databricks information for your setup

    secret_scope_name = "akv_standard"
    dbr_runtime_version = "14.3.x-scala2.12"
    databricks_workspace_id = {
        "dev": "7233594485007442.67",
        "prod": "6773292217826798.73",
    }
    catalog_name = {
        "dev": "datam8_sample_dev",
        "prod": "datam8_sample_dev",
    }

    # UUID of service principals used to run jobs in each environment
    run_as_service_principal = {
        "dev": "33ae34c4-68ce-4e17-a7cc-ac989f810750",
        "prod": "8ccc6336-212c-47c8-8c77-7dac0cb69cb0",
    }

    # Display name of object owner
    owner = {
        "dev": "datam8_sample_dev_owner",
        "prod": "datam8_sample_dev_owner",
    }

    permissions = [
        {
            "group_name": "datam8_sample_dev_operations",
            "level": "CAN_RUN"
        }
    ]



def get_dict_modules() -> dict:
    """Retrieves a dictionary containing modules.

    Returns:
        dict: Dictionary containing modules.
    """
    __dict = {
        "SystemProperties": SystemProperties,
        # "Databricks": Databricks,
    }
    return __dict
