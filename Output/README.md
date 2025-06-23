To deploy asset bundle from local computer use the following commands depending on the target environment

# dev
## login
There are two ways, one is to simply login to Azure CLI an the correct tenant.
```sh
az login -t xxxxx-xxxxxx
```

The second option is to login directly to the workspace via the Databricks CLI.
```sh
databricks auth login --host https://adb-7233594485007442.67.azuredatabricks.net`
```

### validation and deploy
`databricks bundle validate`   
`databricks bundle deploy`

### destroy 
`databricks bundle destroy`
 
# other environemnts
Normally it should not be necessary to directly connect to other environemnts.
If it is necessary simple add the option `-t <target>` to any of the above
commands.

