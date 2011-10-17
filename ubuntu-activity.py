#!/usr/bin/env python
# -*- coding: utf-8 -*-

import datetime
import json

from launchpadlib.launchpad import Launchpad

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
    if date is None:
        return None
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

def mine_canonical():
    # Make sure we are dealing with Unicode:
    psycopg2.extensions.register_type(psycopg2.extensions.UNICODE)
    psycopg2.extensions.register_type(psycopg2.extensions.UNICODEARRAY)
    conn = psycopg2.connect(DB)
    conn.set_client_encoding('UTF-8')
    cur = conn.cursor()

    canonical_people = """
        Alexander Sack
        Andres Rodriguez
        Barry Warsaw
        Bryce Harrington
        Chris Coulson
        Chuck Short
        Colin Watson
        Daniel Holbach
        Daniel T Chen
        Dave Walker
        Didier Roche
        Dustin Kirkland
        Evan Dandrea
        James Westby
        Jamie Strandboge
        Jonathan Riddell
        Kees Cook
        Ken VanDine
        Laurent Bigonville
        Loïc Minier
        Luke Yelavich
        Marc Deslauriers
        Martin Pitt
        Mathias Gug
        Mathieu Trudel-Lapierre
        Matthias Klose
        Micah Gersten
        Michael Terry
        Michael Vogt
        Scott James Remnant
        Scott Moser
        Sebastien Bacher
        Steve Kowalik
        Steve Langasek
        Stéphane Graber
        Thierry Carrez
        Tim Gardner
        Timo Aaltonen
    """.decode('utf-8').strip()
    canonical_people = [name.strip() for name in canonical_people.split(u'\n')]
    cur.execute(u"""
        SELECT count(*), date_trunc('week', date) AS bucket,
          signed_by_name IN (%s)
          OR signed_by_email LIKE '%%@canonical.com'
          AS canonical
        FROM ubuntu_upload_history
        JOIN ubuntu_sources
          ON (ubuntu_upload_history.source = ubuntu_sources.source
              AND ubuntu_upload_history.distribution = ubuntu_sources.release)
        WHERE signed_by != 'N/A'
        GROUP BY bucket, canonical
        ORDER BY bucket;
    """ % u', '.join(u"'%s'" % name for name in canonical_people))
    keys = ('count', 'bucket', 'canonical')
    data = {True: [], False: []}
    for row in cur.fetchall():
        result = AttrDict(**dict(zip(keys, row)))
        data[result.canonical].append([js_date(result.bucket), result.count])
    return data


def release_schedule():
    lp = Launchpad.login_anonymously('ubuntu-activity', 'production')
    ubu = lp.distributions['ubuntu']
    opened = None
    releases = []
    freezes = {
        'hardy': '2008-02-14',
        'intrepid': '2008-08-28',
        'jaunty': '2009-02-19',
        'karmic': '2009-08-27',
        'lucid': '2010-02-18',
        'maverick': '2010-08-12',
        'natty': '2011-02-24',
        'oneiric': '2011-08-11',
        'precise': '2012-02-16',
    }
    for series in reversed(list(ubu.series)):
        freeze = freezes.get(series.name, None)
        if freeze:
            freeze = datetime.datetime.strptime(freeze, '%Y-%m-%d')
        releases.append({
            'name': series.name,
            'opened': js_date(opened),
            'released': js_date(series.datereleased),
            'freeze': js_date(freeze)
        })
        opened = series.datereleased
    return releases


def main():
    data = mine_upload_history()
    data['releases'] = release_schedule()
    affl = mine_canonical()
    data['canonical'] = affl[True]
    data['community'] = affl[False]

    with open('data.json', 'w') as f:
        json.dump(data, f)

if __name__ == '__main__':
    main()
