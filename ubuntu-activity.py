#!/usr/bin/env python2
# -*- coding: utf-8 -*-

import StringIO
import datetime
import json
import os
import re
import sys

from launchpadlib.launchpad import Launchpad

import psycopg2
import psycopg2.extensions

DATABASE = {'database': 'udd',
            'port': 5432,
            'host': 'udd-mirror.debian.net',
            'user': 'udd-mirror',
            'password': 'udd-mirror',
           }


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

    def __setattr__(self, name, value):
        self[name] = value


def js_date(date):
    if date is None:
        return None
    return int(date.strftime('%s')) * 1000


def mine_upload_history(conn):
    cur = conn.cursor()

    cur.execute("""
        SELECT count(*), date_trunc('week', date) AS bucket, component
        FROM ubuntu_upload_history
        WHERE changed_by_email != 'archive@ubuntu.com'
          AND changed_by_email != 'katie@jackass.ubuntu.com'
          AND changed_by_email != 'language-packs@ubuntu.com'
        GROUP BY bucket, component
        ORDER BY bucket;
    """)
    keys = ('count', 'bucket', 'component')
    data = {'main': [], 'universe': [], 'multiverse': [], 'restricted': [],
            'N/A': []}
    for row in cur.fetchall():
        result = AttrDict(**dict(zip(keys, row)))
        data[result.component].append([js_date(result.bucket), result.count])
    return data


def mine_by_affiliation(conn, affiliations):
    cur = conn.cursor()

    cur.execute(u"""
        CREATE TEMPORARY TABLE ubuntu_affiliations (
          name TEXT PRIMARY KEY,
          affiliation TEXT
        );""")
    for affil, people in affiliations.iteritems():
        content = u'\n'.join(u'\t'.join([person, affil]) for person in people)
        cur.copy_from(StringIO.StringIO(content.encode('utf-8')),
                      'ubuntu_affiliations',
                      columns=('name', 'affiliation'))
    with open('affiliation-table.txt', 'w') as f:
        cur.copy_to(f, 'ubuntu_affiliations')

    cur.execute(u"""
        SELECT count(*), date_trunc('week', date) AS bucket,
          COALESCE(affiliation, 'non-canonical') AS caffiliation
        FROM ubuntu_upload_history
        LEFT OUTER JOIN ubuntu_affiliations
          ON (changed_by_name = name)
        WHERE changed_by_email != 'archive@ubuntu.com'
          AND changed_by_email != 'katie@jackass.ubuntu.com'
          AND changed_by_email != 'language-packs@ubuntu.com'
        GROUP BY bucket, caffiliation
        ORDER BY bucket;
    """)
    keys = ('count', 'bucket', 'affiliation')
    data = {}
    for row in cur.fetchall():
        result = AttrDict(**dict(zip(keys, row)))
        if result.affiliation not in data:
            data[result.affiliation] = []
        data[result.affiliation].append([js_date(result.bucket), result.count])
    return data


def mine_top_uploaders(conn):
    cur = conn.cursor()

    cur.execute(u"""
        SELECT count(*) AS count,
          changed_by_name,
          regexp_replace(distribution, '-.*', '') AS release
        FROM ubuntu_upload_history
        WHERE changed_by_name != ''
          AND changed_by_email != 'archive@ubuntu.com'
          AND changed_by_email != 'katie@jackass.ubuntu.com'
          AND changed_by_email != 'language-packs@ubuntu.com'
        GROUP BY release, changed_by_name
        HAVING count(*) >= 10
        ORDER BY release;
    """)
    keys = ('count', 'name', 'release')
    data = {}
    for row in cur.fetchall():
        result = AttrDict(**dict(zip(keys, row)))
        if result.release not in data:
            data[result.release] = []
        data[result.release].append([result.name, result.count])
    return data


def release_schedule(lp):
    ubu = lp.distributions['ubuntu']
    opened = None
    releases = []
    freezes = {
        'hoary': '2005-02-07',
        'breezy': '2005-08-11',
        'dapper': '2006-02-23',
        'edgy': '2006-09-07',
        'feisty': '2007-02-08',
        'gutsy': '2007-08-16',
        'hardy': '2008-02-14',
        'intrepid': '2008-08-28',
        'jaunty': '2009-02-19',
        'karmic': '2009-08-27',
        'lucid': '2010-02-18',
        'maverick': '2010-08-12',
        'natty': '2011-02-24',
        'oneiric': '2011-08-11',
        'precise': '2012-02-16',
        'quantal': '2012-08-23',
        'raring': '2013-03-07',
        'saucy': '2013-08-29',
        'trusty': '2014-02-20',
        'utopic': '2014-08-21',
        'vivid': '2015-02-19',
        'wily': '2015-08-20',
        'xenial': '2016-02-18',
        'yakkety': '2016-08-18',
        'zesty': '2017-02-16',
        'artful': '2017-08-24',
        'bionic': '2018-03-01',
        'cosmic': '2018-08-23',
        'disco': '2019-02-21',
        'eoan': '2019-08-22',
        'focal': '2020-02-27',
        'groovy': '2020-08-27',
        'hirsute': '2021-02-25',
        'impish': '2021-08-19',
        'jammy': '2022-02-24',
        'kinetic': '2022-08-25',
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


def guess_affiliations(conn, lp):
    cur = conn.cursor()
    cur.execute("""SELECT changed_by_name, changed_by_email, count(*) as count
                   FROM ubuntu_upload_history
                   WHERE changed_by_name != ''
                     AND changed_by_email != 'archive@ubuntu.com'
                     AND changed_by_email != 'katie@jackass.ubuntu.com'
                     AND changed_by_email != 'language-packs@ubuntu.com'
                   GROUP BY changed_by_name, changed_by_email;""")

    keys = ('name', 'email', 'count')
    people = {}
    for row in cur.fetchall():
        result = AttrDict(**dict(zip(keys, row)))
        if result.name not in people:
            result.affiliation = None
            result.email = [result.email]
            people[result.name] = result
        else:
            people[result.name].email.append(result.email)
            people[result.name].count += result.count

    by_hand = """
        Kees Cook
        Scott James Remnant
    """.decode('utf-8').strip()
    by_hand = set(person.strip() for person in by_hand.split('\n'))

    lp_valid_email_re = re.compile(r"^[_\.0-9a-zA-Z-+=]+"
                                   r"@(([0-9a-zA-Z-]{1,}\.)*)[a-zA-Z]{2,}$")

    for person in people.itervalues():
        if person.affiliation is None:
            sys.stdout.flush()
            print person.name.encode('utf-8')
            p = None
            if any(address.endswith('@canonical.com')
                    for address in person.email):
                person.affiliation = 'canonical'
                print " -> canonical (upload email)"
        if person.affiliation is None:
            for address in person.email:
                if lp_valid_email_re.match(address) is None:
                    print " Invalid e-mail address %s, skipping" % address
                    continue
                p = lp.people.getByEmail(email=address)
                if p is None:
                    continue
                for a in p.confirmed_email_addresses:
                    if a.email.endswith('@canonical.com'):
                        print " -> canonical (lp email)"
                        person.affiliation = 'canonical'
                        break
                if person.affiliation is not None:
                    break
        if person.affiliation is None and p is not None:
            for membership in p.memberships_details:
                name = membership.team.name
                if name.startswith('canonical-') and name != 'canonical-mysql':
                    print " -> canonical (lp group %s)" % name
                    person.affiliation = 'canonical'
                    break
                if name == 'not-canonical':
                    print " -> not canonical (lp group)"
                    person.affiliation = 'non-canonical'
                    break
        if person.affiliation is None and person.name in by_hand:
            print " -> canonical (by hand)"
            person.affiliation = 'canonical'

    print "================================================="
    print "Canonical: ", len([p for p in people.itervalues()
                              if p.affiliation == 'canonical'])
    print "Known non-Community: ", len([p for p in people.itervalues()
                                    if p.affiliation == 'non-canonical'])
    print "Unknown: ", len([p for p in people.itervalues()
                            if p.affiliation is None])

    with open('affiliations-list.txt', 'w') as f:
        by_uploads = people.values()
        by_uploads.sort(key=lambda x: x.count, reverse=True)
        for person in by_uploads:
            affil = '  '
            if person.affiliation == 'canonical':
                affil = ' C'
            if person.affiliation == 'non-canonical':
                affil = '!C'
            f.write('% 5i  %s  %s\n'
                    % (person.count, affil, person.name.encode('utf-8')))

    with open('people-cache.json', 'w') as f:
        json.dump(people, f)

    return people


def metadata(conn):
    cur = conn.cursor()
    cur.execute("""SELECT MAX(start_time)
                   FROM timestamps
                   WHERE source = 'ubuntu-upload-history'
                     AND command = 'run';""")
    udd_last_updated = js_date(cur.fetchone()[0])

    affiliations_updated = os.path.getmtime('people-cache.json') * 1000
    return {
        'udd_updated': udd_last_updated,
        'affiliations_updated': affiliations_updated,
    }


def cached_people():
    with open('people-cache.json', 'r') as f:
        people = json.load(f)
        for k in people:
            people[k] = AttrDict(**people[k])
    return people


def main():
    # Make sure we are dealing with Unicode:
    psycopg2.extensions.register_type(psycopg2.extensions.UNICODE)
    psycopg2.extensions.register_type(psycopg2.extensions.UNICODEARRAY)
    conn = psycopg2.connect(**DATABASE)
    conn.set_client_encoding('UTF-8')

    lp = Launchpad.login_with('ubuntu-activity', 'production')

    if os.path.exists('people-cache.json'):
        print "Loading people"
        people = cached_people()
    else:
        print "Guessing affiliations"
        people = guess_affiliations(conn, lp)

    affiliations = {'canonical': [], 'non-canonical': []}
    for person in people.itervalues():
        if person.affiliation == 'canonical':
            affiliations['canonical'].append(person.name)
        else:
            affiliations['non-canonical'].append(person.name)

    print "Mining upload history"
    by_component = mine_upload_history(conn)
    print "Mining by affiliation"
    by_affiliation = mine_by_affiliation(conn, affiliations)
    print "Looking up release schedule"
    top_uploaders = mine_top_uploaders(conn)
    releases = release_schedule(lp)
    meta = metadata(conn)

    with open('data.json', 'w') as f:
        json.dump({
            'meta': meta,
            'by_component': by_component,
            'by_affiliation': by_affiliation,
            'releases': releases,
            'top_uploaders': top_uploaders,
        }, f)
    conn.close()

if __name__ == '__main__':
    main()
