# Databricks notebook source
# MAGIC %md
# MAGIC # Generic notebook to complete a load

# COMMAND ----------

# MAGIC %md
# MAGIC ## Initialize base settings

# COMMAND ----------

import datetime

# COMMAND ----------

# DBTITLE 1,Initialize Migration Framework
# MAGIC
# MAGIC %run ./MigrationFramework

# COMMAND ----------

# DBTITLE 1,Initialize Logging Framework
# MAGIC %run ./LoggingFramework

# COMMAND ----------

dbutils.widgets.text("env", "dev", "Environment")
dbutils.widgets.text("catalog_name", "datam8_campus_dev_fka", "Catalog Name")
dbutils.widgets.text("owner", "datam8_sample_dev_owner", "Owner")

# dbutils.widgets.dropdown(
#     "run_mode",
#     "INFO",
#     ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
#     "Run Mode",
# )
#dbutils.widgets.text("sandbox", "_", "Sandbox")

# COMMAND ----------

# Retrieve a job-level parameter (will use default if it doesn't exist)
env = dbutils.widgets.get("env")
catalog_name = dbutils.widgets.get("catalog_name")
owner = dbutils.widgets.get("owner")

# run_mode = dbutils.widgets.get("run_mode")
# sandbox = dbutils.widgets.get("sandbox")

# COMMAND ----------

# DBTITLE 1,Get variable values
job_name = dbutils.jobs.taskValues.get("Start_Load", "job_name", "Manual", "Manual")
job_run_id = dbutils.jobs.taskValues.get("Start_Load", "job_run_id", "1234", "1234")

# COMMAND ----------

print("Environment: %s" % env)
print("Catalog: %s" % catalog_name)
# print("Mode: %s" % run_mode)

# COMMAND ----------

# DBTITLE 1,Set default catalog
catalog = Catalog(catalog_name)
catalog.set_active()

# COMMAND ----------

# MAGIC %md
# MAGIC # Complete load

# COMMAND ----------

# DBTITLE 1,Complete load
{
    "Job_Run_ID": job_run_id,
    "Job_Name": job_name,
    "Insert_Time_UTC": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "Status": "Completed",
}