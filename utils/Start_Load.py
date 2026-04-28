# Databricks notebook source
# MAGIC %md
# MAGIC # Generic notebook to start a load

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

dbutils.widgets.text("job_name", "", "Job Name")
dbutils.widgets.text("job_run_id", "", "Job Run ID")

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

job_name = dbutils.widgets.get("job_name")
job_run_id = dbutils.widgets.get("job_run_id")

# run_mode = dbutils.widgets.get("run_mode")
# sandbox = dbutils.widgets.get("sandbox")

# COMMAND ----------

dbutils.jobs.taskValues.set("job_name", job_name)
dbutils.jobs.taskValues.set("job_run_id", job_run_id)

# COMMAND ----------

# DBTITLE 1,Get variable values
print("Environment: %s" % env)
print("Catalog: %s" % catalog_name)
# print("Mode: %s" % run_mode)

# COMMAND ----------

catalog = Catalog(catalog_name)
catalog.set_active()

# COMMAND ----------

# MAGIC %md
# MAGIC # Start load

# COMMAND ----------

# DBTITLE 1,Start load and store load UUID
{
    "Job_Run_ID": job_run_id,
    "Job_Name": job_name,
    "Insert_Time_UTC": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "Status": "Started",
}