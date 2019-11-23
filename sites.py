#!/usr/bin/env python
'''
Check websites to make sure they are up, are handling www/https redirects
as expected, and have valid not-expiring-soon SSL certificates.

Brian Cantoni

todo:
- move server list from here to an external yaml file
- better controls to allow AWS, Twilio and Slack to be optional
'''

import argparse
import datetime
import os
import re
import requests
import s3data
import socket
import ssl
import sys
import time
from twilio.rest import Client as TwilioClient


def ssl_expiry_datetime(hostname):
    '''Get SSL certificate expire time from a website'''
    ssl_date_fmt = r'%b %d %H:%M:%S %Y %Z'

    context = ssl.create_default_context()
    conn = context.wrap_socket(
        socket.socket(socket.AF_INET),
        server_hostname=hostname,
    )
    conn.settimeout(3.0)

    conn.connect((hostname, 443))
    ssl_info = conn.getpeercert()

    return datetime.datetime.strptime(ssl_info['notAfter'], ssl_date_fmt)


def ssl_valid_time_remaining(hostname):
    '''Get the number of days left in a cert's lifetime.'''
    expires = ssl_expiry_datetime(hostname)

    return expires - datetime.datetime.utcnow()


def check_sites(verbose=False):
    '''
    Server test array fields:
        url - URL to test with HTTP HEAD operation
        code - expected HTTP response code
        redirect - expected redirect URL for 301/302 responses, only used when expected code=301/302
        contents - expected contents in page (HTTP GET), only used when expected code=200
    '''
    servers = [
        {'url': 'http://www.readthedocs.org/', 'code': 302, 'redirect': 'http://readthedocs.org/'},
        {'url': 'http://readthedocs.org/', 'code': 302, 'redirect': 'https://readthedocs.org/'},
        {'url': 'https://readthedocs.org/', 'code': 200, 'contents': 'Technical documentation lives here'},

        {'url': 'http://www.python.org/', 'code': 301, 'redirect': 'https://www.python.org/'},
        {'url': 'http://python.org/', 'code': 301, 'redirect': 'https://python.org/'},
        {'url': 'https://www.python.org/', 'code': 200, 'contents': 'official home of the Python Programming Language'},

        {'url': 'http://thunderbird.net/', 'code': 301, 'redirect': 'https://thunderbird.net/'},
        {'url': 'http://www.thunderbird.net/', 'code': 301, 'redirect': 'https://www.thunderbird.net/'},
        {'url': 'https://www.thunderbird.net/en-US/', 'code': 200, 'contents': 'Software made to make email easier'},
    ]

    errors = []

    for s in servers:
        if verbose:
            print("checking {}".format(s['url']))

        try:
            r = requests.head(s['url'])
        except requests.exceptions.RequestException as e:
            errors.append("Fail: {} exception {}".format(s['url'], e))
            break

        if r.status_code != s['code']:
            errors.append("Fail: {} expected response code {} received {}".format(
                          s['url'], s['code'], r.status_code))
        else:
            if r.status_code == 301 or r.status_code == 302:
                if r.headers['Location'] != s['redirect']:
                    errors.append("Fail: {} expected redirect {} received {}".format(
                                  s['url'], s['redirect'], r.headers['Location']))
            elif r.status_code == 200:
                r2 = requests.get(s['url'])
                if r2.status_code != 200:
                    raise Exception("unexpected http response code {} from get {}"
                                    .format(r.status_code, s['url']))
                matches = re.findall(s['contents'], r2.content.decode('utf-8'))
                if not matches:
                    errors.append("Fail: {} expected contents {}".format(s['url'],
                                  s['contents']))

    ssl_hosts = [
        'readthedocs.org',
        'www.python.org',
        'www.thunderbird.net',
    ]
    for s in ssl_hosts:
        if verbose:
            print("checking SSL {}".format(s))
        remaining = ssl_valid_time_remaining(s)
        if remaining < datetime.timedelta(days=0):
            errors.append("Fail: SSL cert for {} already expired!".format(s))
        elif remaining < datetime.timedelta(3):
            errors.append("Fail: SSL cert for {} expiring in {} days".format(s, remaining.days))

    if verbose:
        print("Done. {} server and {} SSL certs checks; found {} error(s)"
              .format(len(servers), len(ssl_hosts), len(errors)))
        print('\033[91m' + "\n".join(errors) + '\033[0m')

    return(errors)


def send_sms_messages(twilio_sid, twilio_auth_token, from_number, to_number, messages, verbose=False):
    '''send SMS message via Twilio'''
    client = TwilioClient(twilio_sid, twilio_auth_token)
    for m in messages:
        message = client.messages.create(
            body=m,
            from_=from_number,
            to=to_number
        )
        if verbose:
            print(message.sid)

    return


def send_slack_messages(slack_webhook_url, messages, verbose=False):
    '''send Slack message to channel using webhook'''
    for m in messages:
        req = requests.post(slack_webhook_url, json={'text': m})
        if verbose:
            print("Response from Slack webhook: {} {}".format(req.status_code, req.content))

    return


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Check personal websites online and valid SSL certs")
    parser.add_argument('--ci', action="store_true", help="CI mode including notifications")
    parser.add_argument('--verbose', '-v', action="store_true", help="Verbose mode")
    parser.add_argument('--delete', '-d', action="store_true", help="Delete existing stored data")
    args = parser.parse_args()

    errors = check_sites(args.verbose)
    rc = len(errors)

    # in CI mode, save results in S3 and also send results via SMS and Slack
    if args.ci:
        s3 = s3data.S3Data(
            os.environ['AWS_ACCESS_KEY_ID'],
            os.environ['AWS_SECRET_ACCESS_KEY'],
            os.environ['S3DATA_BUCKET'],
        )

        s3key = 'sitecheck-data'
        if args.delete:
            s3.delete(s3key)

        last = s3.get(s3key)
        if last:
            print("last run rc {} at {} which is {}".format(
                last['results'],
                last['lastRun'],
                datetime.datetime.fromtimestamp(last['lastRun']).strftime('%Y-%m-%d %H:%M:%S'))
            )

        data = {
            "lastRun": int(time.time()),
            "version": 1,
            "results": rc,
            "errors": errors,
        }
        s3.put(s3key, data)

        # send notifications only if currently failing or was failing, now passing
        if not last or errors or (not errors and last and last['results'] != 0):
            # send multiple messages if needed to get around Twilio 160 char limit
            msg = []
            if rc == 0:
                msg.append("Sitecheck PASS")
            else:
                msg.append("Sitecheck {} Errors:".format(rc))
                for e in errors:
                    msg.append(e)

            if args.verbose:
                print("CI mode")
            send_sms_messages(
                os.environ['TWILIO_ACCOUNT_SID'],
                os.environ['TWILIO_AUTH_TOKEN'],
                os.environ['TWILIO_FROM_NUMBER'],
                os.environ['TWILIO_TO_NUMBER'],
                msg,
                args.verbose,
            )
            send_slack_messages(
                os.environ['SLACK_WEBHOOK'],
                msg,
                args.verbose,
            )

    sys.exit(rc)
