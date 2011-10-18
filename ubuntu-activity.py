#!/usr/bin/env python
# -*- coding: utf-8 -*-

import StringIO
import datetime
import json
import os
import sys

from launchpadlib.launchpad import Launchpad

import psycopg2
import psycopg2.extensions

DATABASE = {'database': 'udd',
            'port': 5441,
            'host': 'localhost',
            'user': 'guest',
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


def mine_by_affiliation(conn, affiliations):
    cur = conn.cursor()

    cur.execute(u"""
        CREATE TEMPORARY TABLE ubuntu_affiliations (
          name TEXT PRIMARY KEY,
          affiliation TEXT
        );""")
    for affil, people in affiliations.iteritems():
        content = u'\n'.join(u'\t'.join([person, affil]) for person in people)
        cur.copy_from(StringIO.StringIO(content), 'ubuntu_affiliations',
                      columns=('name', 'affiliation'))
    with open('affiliation-table.txt', 'w') as f:
        cur.copy_to(f, 'ubuntu_affiliations')

    cur.execute(u"""
        SELECT count(*), date_trunc('week', date) AS bucket,
          COALESCE(affiliation, 'community') AS affiliation
        FROM ubuntu_upload_history
        LEFT OUTER JOIN ubuntu_affiliations
          ON (changed_by_name = name)
        WHERE signed_by != 'N/A'
        GROUP BY bucket, affiliation
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
        WHERE signed_by != 'N/A'
          AND changed_by_name != ''
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


def guess_affiliations(conn, lp):
    cur = conn.cursor()
    cur.execute("""SELECT changed_by_name, changed_by_email, count(*) as count
                   FROM ubuntu_upload_history
                   WHERE signed_by != 'N/A'
                     AND changed_by_name != ''
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
                    person.affiliation = 'community'
                    break
        if person.affiliation is None and person.name in by_hand:
            print " -> canonical (by hand)"
            person.affiliation = 'canonical'

    print "================================================="
    print "Canonical: ", len([p for p in people.itervalues()
                              if p.affiliation == 'canonical'])
    print "Known Community: ", len([p for p in people.itervalues()
                                    if p.affiliation == 'community'])
    print "Unknown: ", len([p for p in people.itervalues()
                            if p.affiliation is None])

    with open('affiliations-list.txt', 'w') as f:
        by_uploads = people.values()
        by_uploads.sort(key=lambda x: x.count, reverse=True)
        for person in by_uploads:
            affil = '  '
            if person.affiliation == 'canonical':
                affil = ' C'
            if person.affiliation == 'community':
                affil = '!C'
            f.write('% 5i  %s  %s\n'
                    % (person.count, affil, person.name.encode('utf-8')))

    with open('people-cache.json', 'w') as f:
        json.dump(people, f)


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

    affiliations = {'canonical': [], 'community': []}
    for person in people.itervalues():
        if person.affiliation == 'canonical':
            affiliations['canonical'].append(person.name)
        else:
            affiliations['community'].append(person.name)

    print "Mining upload history"
    by_component = mine_upload_history(conn)
    print "Mining by affiliation"
    by_affiliation = mine_by_affiliation(conn, affiliations)
    print "Looking up release schedule"
    top_uploaders = mine_top_uploaders(conn)
    releases = release_schedule(lp)

    with open('data.json', 'w') as f:
        json.dump({
            'by_component': by_component,
            'by_affiliation': by_affiliation,
            'releases': releases,
            'top_uploaders': top_uploaders,
        }, f)
    conn.close()

if __name__ == '__main__':
    main()
