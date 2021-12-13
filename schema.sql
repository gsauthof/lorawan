

-- sudo -u postgres psql -d metricsdb
-- CREATE EXTENSION postgis;

CREATE TABLE IF NOT EXISTS metrics (
    time        timestamptz NOT NULL,
    device_id   varchar(12) NOT NULL,

    location    geography(pointz,4326), -- longitude, latitude, altitude
    registry    boolean,                -- location source == SOURCE_REGISTRY
    gateway_id  varchar(28),

    sf          smallint,  -- spreading factor
    bw          integer,   -- bandwidth (Hz)
    rssi        real,      -- Received Signal Strength Indication (dBm)
    snr         real,      -- Signal to Noise Ratio (dB)
    c_rate      char(3),   -- coding rate
    airtime_us  integer,   -- airtime in microseconds

    freq        integer,   -- frequency (Hz)
    chan_idx    smallint,  -- channel index
    chan_rssi   real,      -- channel rssi (dBm)

    f_cnt       integer,
    f_port      smallint,

    frm_payload bytea,
    pl          jsonb
) PARTITION BY RANGE (time);

CREATE INDEX IF NOT EXISTS metrics_time_idx ON metrics(time);

CREATE INDEX IF NOT EXISTS metrics_pl_idx   ON metrics USING GIN(pl);


-- Weekly partioning example:

-- CREATE TABLE metrics_2021_11_29 PARTITION OF metrics FOR VALUES FROM ('2021-11-29') TO ('2021-12-06');
-- CREATE TABLE metrics_2021_12_06 PARTITION OF metrics FOR VALUES FROM ('2021-12-06') TO ('2021-12-13');
