This repository contains ttnmqtt2pg, a small script for streaming
[LoRaWAN][1] uplink message payload (i.e. metrics) into a [PostgreSQL][7]
database, and an [Ansible][8] playbook for setting everything up (i.e.
the streaming service, Postgres, [Grafana][9], ...).

2021, Georg Sauthoff <mail@gms.tf>


## Getting Started

Basically it's:

1. review the Ansible roles
2. copy `group_vars/node.yml.sample` to `group_vars/node.yml` and adjust some settings
3. copy `hosts.sample` to `hosts` and adjust the hostname
4. run: `ansible-playbook -i hosts metricsdb.yml --diff`

The playbook is developed and tested against [Fedora][10] 35. It might
work with other target systems, possibly requiring minor
adjustments.


## Connecting Devices

Firstly, it's assumed that you already registered an account on
[TTN][2] (i.e. The Things Stack Community Edition, TTS) and that
you are located in the transmission range of some TTN Gateway.

Getting the data of LoRaWAN devices (such as sensor measurements) into a
Postgres database is then a matter of registering an so called 'application' to
your account and adding (i.e. registering)  one or multiple LoRaWAN end devices
to that TTN application. Finally, you have to create an API key for your TTN
application (only requires read-only access) and add an [MQTT integration][3].

For the `ttnmqtt2pg` setup you have to copy the username (such as `myapp@ttn`)
from the MQTT integration page and the API key value (that was displayed when
creating it) to `group_vars/node.yml`.

Since the metricsdb schema stores the decoded payload into a jsonb column
without caring about its schema (and it subscribes to uplink messages of _all_
devices), messages of new devices added to your existing TTN application are
automatically picked up. That means there is no need to restart the `ttnmqtt2pg`
service after adding another device on the [TTN UI/console][4].


## Table Schema

See `schema.sql` for the schema of the metrics database. The
metrics of all devices are stored in the partitioned `metrics`
table, which contains a time column (timestamptz), some columns
for generic device, gateway and connection attributes (such as
`device_id`, `location` and `rssi`) and a generically typed payload
(`pl`, type jsonb) column.

The table is range-partitioned by time (e.g. using weekly partitions). The
Ansible metricsdb role contains a task that creates a simple partition
maintenance cron job for that table.

Since most device models come with their own payload format and
TTN decodes the payload into JSON, storing it into a [jsonb][5] column
is quite flexible and a natural fit. Especially, it allows for
adding arbitrary devices without having to change the schema or
to update some payload field mapping configuration.

To speed up common queries, the time and payload columns are
indexed, i.e. using a B-tree and a [GIN index][6].

Note that `schema.sql` is executed by the metricsdb Ansible role
while setting up the database.


## Example Queries

Show location profile of the known devices:

    select device_id, ST_AsText(location), count(*) from metrics
        group by device_id, ST_AsText(location) order by device_id;

Show the top 10 measurements of a certain device:

    select time, device_id, pl->'iaq' as iaq, pl->'voc' as voc,
        pl->'eco2' as eco2, pl->'humidity' as humidity,
        pl->'temperature' as temperature
        from metrics
        where device_id = 'iaq-01'
        order by time, device_id desc limit 10;

The Grafana UI has some limited support for building queries, an end result
for a time series graph panel might look like this (modulo the
order-by clause, see below):

    SELECT
      $__timeGroupAlias("time",$__interval),
      avg((pl->'humidity')::float) AS "humidity",
      device_id
    FROM metrics
    WHERE
      $__timeFilter("time")
    GROUP BY 1, device_id
    ORDER BY 1, device_id

If you have heterogeneous devices where the - say - temperature field
is named differently, just coalesce on the fields:

    SELECT
      $__timeGroupAlias("time",$__interval),
      avg(coalesce(pl->'TempC_SHT', pl->'temperature')::float) AS "temp",
      device_id
    FROM metrics
    WHERE
      $__timeFilter("time")
    GROUP BY 1, device_id
    ORDER BY 1, device_id


NB: Ordering also by `device_id` is important because otherwise
the coloring in the Grafana panel might change between each
refresh (because it chooses colors on a first come first server
basis). Unfortunately, the Grafana Query builder just adds `order
by 1` such that one has to switch to editing raw SQL statements
to fix it.


## Related Work

There is
[ttn2postgresql](https://www.thethingsnetwork.org/labs/story/consuming-payload-data-with-python)
([repository](https://gitlab.com/shed909/ttn2postgresql/-/tree/main))
which also streams TTN MQTT uplink messages into a Postgres
database, using a different approach.

It's also implemented in Python and uses Eclipse's MQTT package.

However, there are some design differences, most notably:

- ttn2postgresql requires changes to a YAML configuration file (and a service
  restart) for each added device
- decoded payload fields of interest need to be mapped in that configuration file,
  i.e. with an 1:1 mapping from payload field to table column
- original payload and other generic fields aren't stored
- the decoded payload isn't stored in a jsonb column
- the current datetime of the record insertion is stored for each uplink message, not the timestamp provided by TTN
- data from different devices is stored in separate tables
- tables aren't partitioned
- the ttn2postgresql repository provides Docker/Docker-Compose examples for deployment/orchestration instead of Ansible roles
- service doesn't support systemd startup notifications


[1]: https://en.wikipedia.org/wiki/LoRa#LoRaWAN
[2]: https://www.thethingsnetwork.org/docs/quick-start/
[3]: https://www.thethingsindustries.com/docs/integrations/mqtt/
[4]: https://console.cloud.thethings.network/
[5]: https://www.postgresql.org/docs/13/datatype-json.html
[6]: https://www.postgresql.org/docs/13/gin-intro.html
[7]: https://en.wikipedia.org/wiki/PostgreSQL
[8]: https://en.wikipedia.org/wiki/Ansible_(software)
[9]: https://en.wikipedia.org/wiki/Grafana
[10]: https://en.wikipedia.org/wiki/Fedora_Linux
