#!/usr/bin/env python

import json

import psycopg2
import psycopg2.extensions

DB = 'service=udd'

class AttrDict(dict):
    """Dictionary with attribute access"""

    def __init__(self, **kwargs):
        for key, value in kwargs.iteritems():
            self[key] = value

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError, e:
            raise AttributeError(e)


def js_date(date):
    return int(date.strftime('%s')) * 1000


def mine_upload_history():
    # Make sure we are dealing with Unicode:
    psycopg2.extensions.register_type(psycopg2.extensions.UNICODE)
    psycopg2.extensions.register_type(psycopg2.extensions.UNICODEARRAY)
    conn = psycopg2.connect(DB)
    conn.set_client_encoding('UTF-8')
    cur = conn.cursor()

    cur.execute("""
        SELECT count(*), date_trunc('week', date) AS bucket, component
        FROM ubuntu_upload_history
        JOIN ubuntu_sources
          ON (ubuntu_upload_history.source = ubuntu_sources.source
              AND ubuntu_upload_history.distribution = ubuntu_sources.release)
        WHERE signed_by != 'N/A'
        GROUP BY bucket, component
        ORDER BY bucket;
    """)
    keys = ('count', 'bucket', 'component')
    data = {'main': [], 'universe': [], 'multiverse': [], 'restricted': []}
    for row in cur.fetchall():
        result = AttrDict(**dict(zip(keys, row)))
        data[result.component].append([js_date(result.bucket), result.count])
    return data


def main():
    data = mine_upload_history()

    with open('data.json', 'w') as f:
        json.dump(data, f)

if __name__ == '__main__':
    main()
