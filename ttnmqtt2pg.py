#!/usr/bin/env python3

# ttnmqtt2pg - stream The Things Network device's uplink messages
#              from MQTT to a PostgreSQL database
#
# SPDX-FileCopyrightText: © 2021 Georg Sauthoff <mail@gms.tf>
# SPDX-License-Identifier: GPL-3.0-or-later

import base64
import configargparse
import json
import logging
import paho.mqtt.client as mqtt
from pprint import pformat
import re
import signal
import sqlalchemy
import sqlalchemy.sql.sqltypes
import sqlalchemy.dialects.postgresql.base
import sys
import systemd.daemon

prefix = '/usr'
prog   = 'ttnmqtt2pg'

def parse_args():
    p = configargparse.ArgParser(
            default_config_files=[f'{prefix}/lib/{prog}/config.ini',
                f'/etc/{prog}.ini', f'~/.config/{prog}.ini'])
    p.add('-c', '--config', is_config_file=True,
            help='config file')
    p.add('--user', '-u', required=True, env_var='ttn_user',
            help='The Things Network user name such as someapp@ttn')
    p.add('--password', required=True, env_var='ttn_password',
            help='The Things Network password a.k.a. API-key')
    p.add('--host', default='eu1.cloud.thethings.network',
            env_var='ttn_host',
            help='The Things Network endpoint (default: %(default)s)')
    p.add('--port', '-p', default=8883, type=int,
            env_var='ttn_port',
            help='The Things Network endpoint port (default: %(default)d, 8883 is for encrypted connections)')
    p.add('--db', '-d', default='postgresql:///metricsdb',
            help='PostgreSQL metrics database URL (default: %(default)s)')
    p.add('--echo', action='store_true',
            help='echo SQLAlchemy statements to the log stream')
    p.add('--dry', action='store_true',
            help="don't actually commit any changes to the database")
    p.add('--debug', action='store_true',
            help='enable verbose output')
    p.add('--device-pattern', default='^.*-([^-]+-[^-]+)$',
            help='regular expression for substituing device ids (default: %(default)s)')
    p.add('--device-repl', default='\\1',
            help='replacement when substituing device ids with a regular expression - also supports backreferences (default: %(default)s)')
    p.add('--systemd', action='store_true',
            help='notify systemd during startup')
    args = p.parse_args()
    return args


# register postgis geography type with sqlalchemy to eliminate warnings
# alternatively, import geoalchemy2
class GEOGRAPHY(sqlalchemy.sql.sqltypes.TypeEngine):
    __visit_name__ = "geography"

    def __init__(self, point_type, srid):
        # e.g. 'PointZ'
        self.point_type = point_type
        # e.g. '4326'
        self.srid       = srid

sqlalchemy.dialects.postgresql.base.ischema_names['geography'] = GEOGRAPHY


# Global variables
log          = logging.getLogger(__name__)
db           = None
metrics_ins  = None
dry_run      = False
user         = None
debug        = None
device_id_re = None
device_repl  = None


def on_connect(c, userdata, flags, rc):
    topic = f'v3/{user}/devices/+/up'
    log.info(f'Connected - subscribing to: {topic}')
    c.subscribe(topic)


def on_message(c, userdata, msg):
    d = json.loads(msg.payload)
    if debug:
        log.debug(f'received on {msg.topic}: {pformat(d)}')
    e = extract_data(d)
    if debug:
        log.debug(f'extracted: {pformat(e)}')
    store(e)


def extract_data(d):
    h = {}
    h['device_id'] = d['end_device_ids']['device_id']
    u = d['uplink_message']
    h['consumed_airtime'] = u['consumed_airtime']
    for i in ( 'f_port', 'f_cnt', 'decoded_payload' ):
        h[i] = u.get(i)
    h['frm_payload'] = u.get('frm_payload', '')
    # XXX how to deal with multiple receiving gateways?
    m = u['rx_metadata'][0]
    h['gateway_id'] = m['gateway_ids']['gateway_id']
    for i in ('rssi', 'channel_rssi', 'time'):
        h[i] = m[i]
    for i in ('channel_index', 'snr'):
        h[i] = m.get(i)
    s = u['settings']
    for i in ('coding_rate', 'frequency'):
        v = s.get(i)
        if v is not None:
            h[i] = v
    l = s['data_rate']['lora']
    for i in ('bandwidth', 'spreading_factor', 'coding_rate'):
        v = l.get(i)
        if v is not None:
            h[i] = v
    g = m['location']
    for i in ('altitude', 'latitude', 'longitude'):
        h[i] = g[i]
    h['location_src'] = g['source']
    return h


def store(d):
    location    = f'POINTZ({d["longitude"]} {d["latitude"]} {d["altitude"]})'
    airtime_us  = d['consumed_airtime']
    airtime_us  = int(float(airtime_us[:airtime_us.rindex('s')]) * 10**6)
    frm_payload = base64.decodebytes(d['frm_payload'].encode('ascii'))
    device_id   = device_id_re.sub(device_repl, d['device_id'])

    db.execute(metrics_ins, {
            'time': d['time'],
            'device_id': device_id, 'location': location,
            'registry': (d['location_src'] == 'SOURCE_REGISTRY'),
            'gateway_id': d['gateway_id'],
            'sf': d['spreading_factor'], 'bw': d['bandwidth'], 'rssi': d['rssi'],
            'snr': d['snr'], 'c_rate': d['coding_rate'], 'airtime_us': airtime_us,
            'freq': d['frequency'], 'chan_idx': d['channel_index'],
            'chan_rssi': d['channel_rssi'], 'f_cnt': d['f_cnt'], 'f_port': d['f_port'],
            'frm_payload': frm_payload, 'pl': d['decoded_payload']
            })

    # i.e. 'commit [or rollback] as you go' style ...
    if dry_run:
        db.rollback()
    else:
        db.commit()


def setup_logging(debug):
    log_format      = '%(asctime)s - %(levelname)-8s - %(message)s [%(name)s]'
    log_date_format = '%Y-%m-%d %H:%M:%S'
    logging.basicConfig(format=log_format, datefmt=log_date_format,
            level=(logging.DEBUG if debug else logging.INFO))


def on_sigterm(sig, frm):
    # NB: c.loop() and thus c.loop_forever() catches all Exception derived
    #     exceptions when blocking on network receives ...
    #     we thus raise a BaseException derived exception ...
    raise KeyboardInterrupt()


def mainP():
    signal.signal(signal.SIGTERM, on_sigterm)
    args = parse_args()
    global user
    global dry_run
    global debug
    global device_id_re
    global device_repl
    user, dry_run, debug = args.user, args.dry, args.debug
    device_id_re = re.compile(args.device_pattern)
    device_repl  = args.device_repl

    setup_logging(args.debug)

    # future=True => Unlock SQLAlchemy 2.0 features in order to silence deprecation
    #                warning about removal of implicit auto-commit, executing text statements,
    #                and similar.
    #                Also, this enables 'commit as you go' style code already in SQLAlchemy 1.4.
    # this argument can be removed again with SQLAlchemy >= 2
    engine = sqlalchemy.create_engine(args.db, echo=args.echo, future=True)
    global db
    db   = engine.connect()

    # it's ok if we lose the last few inserts in case of a server crash
    # NB: fsync after each insert doesn't scale with a lot of events
    # cf. https://www.postgresql.org/docs/13/wal-async-commit.html
    db.execute(sqlalchemy.text('SET synchronous_commit = off'))

    meta = sqlalchemy.MetaData()
    metrics_table = sqlalchemy.Table('metrics', meta, autoload_with=engine)
    global metrics_ins
    metrics_ins = metrics_table.insert()

    c = mqtt.Client()
    c.enable_logger()
    c.tls_set()
    c.on_connect = on_connect
    c.on_message = on_message
    c.username_pw_set(args.user, args.password)
    c.connect(args.host, args.port)

    if args.systemd:
        systemd.daemon.notify('READY=1')

    c.loop_forever()

def main():
    try:
        return mainP()
    except KeyboardInterrupt:
        pass

if __name__ == '__main__':
    sys.exit(main())
