#!/bin/bash

cat <<EOF | psql -d metricsdb --no-psqlrc --quiet
    SET client_min_messages TO WARNING;
    CREATE TABLE IF NOT EXISTS
        metrics_$(date -d monday +%Y_%m_%d)
        PARTITION OF metrics
        FOR VALUES FROM ('$(date -d  monday           -Id)')
                     TO ('$(date -d 'monday + 7 days' -Id)');
EOF

