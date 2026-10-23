# Databricks notebook source
dbutils.widgets.text("job_name", "Manual", "Job Name")
dbutils.widgets.text("job_run_id", "Manual", "Job Run ID")

dbutils.jobs.taskValues.set(key="job_name", value=dbutils.widgets.get("job_name"))
dbutils.jobs.taskValues.set(key="job_run_id", value=dbutils.widgets.get("job_run_id"))
print(f"Starting {dbutils.widgets.get('job_name')} ({dbutils.widgets.get('job_run_id')})")
