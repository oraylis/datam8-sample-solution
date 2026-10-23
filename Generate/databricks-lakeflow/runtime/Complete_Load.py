# Databricks notebook source
dbutils.widgets.text("job_name", "Manual", "Job Name")
dbutils.widgets.text("job_run_id", "Manual", "Job Run ID")
print(f"Finished running tasks for {dbutils.widgets.get('job_name')} ({dbutils.widgets.get('job_run_id')})")
