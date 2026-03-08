# Updating

Updating Voyage when using docker can be quite easy. Run a collections backup before upgrading, then pull the latest version and restart the containers.

## Pre-upgrade backup (recommended)

Before running migrations or updating containers, export a collections snapshot:

```bash
docker compose exec server python manage.py export_collections_backup
```

You can also provide a custom output path:

```bash
docker compose exec server python manage.py export_collections_backup --output /code/backups/collections_backup_pre_upgrade.json
```

The backup file includes a timestamp, record counts, and snapshot data for:

- `Collection`
- `CollectionItineraryItem`

Note: Make sure you are in the same directory as your `docker-compose.yml` file.

```bash
docker compose pull
docker compose up -d
```

## Updating the Region Data

Region and Country data in Voyage is provided by an open source project: [dr5hn/countries-states-cities-database](https://github.com/dr5hn/countries-states-cities-database). If you would like to update the region data in your Voyage instance, you can do so by running the following command. This will make sure your database is up to date with the latest region data for your version of Voyage. For security reasons, the region data is not automatically updated to the latest and is release version is controlled in the `settings.py` file.

```bash
docker exec -it <container> bash
```

Once you are in the container run the following command to resync the region data.

```bash
python manage.py download-countries --force
```
