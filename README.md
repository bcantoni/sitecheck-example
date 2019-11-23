# Sitecheck Project

This is a simple example project showing how you can use GitHub Actions to regularly check that your websites/projects are up and running as expected. I wrote this when I was moving a bunch of my side project domains around and I wanted to make sure I didn't break anything. (And to keep an eye on upcoming SSL certificate expirations.) This won't be as extensive as a real "uptime" monitoring service, but for side projects this free option is pretty powerful.

## How it Works

### GitHub Action

The action is defined in the file `./github/workflows/pythonapp.yml`. I started with the "Python app" workflow template, so if you've seen those before this structure will look very similar.

Some comments on the most relevant parts:

```
on:
  push:
  schedule:
    - cron: '0 0,15 * * *'
```

This sets up the action to run on any push and also on the cron schedule. The hours are UTC-based and in this example set to run twice per day.

```
- name: Set up Python 3.7
    uses: actions/setup-python@v1
    with:
    python-version: 3.7
```

Here we are just using Python 3.7 because we just need one environment, but if this was really testing your Python package you could specify a list of versions here (similar to what I do in my [s3data](https://github.com/bcantoni/s3data) project).

```
- name: Install dependencies
    run: |
    python -m pip install --upgrade pip
    pip install -r requirements.txt
```

Our specified dependencies are installed. If you add any packages needed make sure to include in `requirements.txt`.

```
- name: Test with sites.py
    id: sites
    env:
      TWILIO_ACCOUNT_SID: ${{ secrets.TWILIO_ACCOUNT_SID }}
      TWILIO_AUTH_TOKEN: ${{ secrets.TWILIO_AUTH_TOKEN }}
      TWILIO_FROM_NUMBER: ${{ secrets.TWILIO_FROM_NUMBER }}
      TWILIO_TO_NUMBER: ${{ secrets.TWILIO_TO_NUMBER }}
      AWS_ACCESS_KEY_ID: ${{ secrets.AWS_ACCESS_KEY_ID }}
      AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
      S3DATA_BUCKET: ${{ secrets.S3DATA_BUCKET }}
      SLACK_WEBHOOK: ${{ secrets.SLACK_WEBHOOK }}
    run: python sites.py --ci -v
```

Finally the step that actually runs the script. All the mappings under `env` will environment variables for the script from the contents of the repository secrets. The `sites.py` will set the return code to 0 for passing, otherwise it will be the number of errors found. It's probably most useful to run with the `-v` option so you can see the actual errors found (otherwise it's silent).

These are the command-line options for the script:

```
$ python sites.py -h
usage: sites.py [-h] [--ci] [--verbose] [--delete]

Check personal websites online and valid SSL certs

optional arguments:
  -h, --help     show this help message and exit
  --ci           CI mode including notifications
  --verbose, -v  Verbose mode
  --delete, -d   Delete existing stored data
```

### Twilio Integration

GitHub Actions will send you an email when you have a failing run. In the case of a site being down I wanted to find out more quickly, so I set up Twilio to text my own phone with any errors.

To use this with Twilio, you'll need to 'buy' a number (or use one you already have). You'll need your Account SID and Auth Token as well.

### Slack Integration

In a similar vein I added Slack integration to notify me of any issues. This is pretty easy to set up - you just need to create a webhook for the Slack workspace and channel you want to use, then the script does a simple post with the messages.

### AWS S3 Integration

I wanted to improve the notifications from this script to not notify me every single time it runs. Instead I just want to hear about any failing runs, and the first passing run after it had been failing. To support these I need to persist some state outside of GitHub Actions. I created a separate package [s3data](https://github.com/bcantoni/s3data) which can read/write a simple file in S3. I'm storing in JSON just a few fields from the last run: time, error count, and error messages.

## Using it for Your Projects

To use this project as a starting point for your own, these are the steps:

Fork this repo to your own account.

Locally you'll want a Python 3.7/3.8 environment (probably easiest with a virtual environment). Install dependencies with:

    pip install --upgrade pip
    pip install -r requirements.txt

Now you can edit `sites.py` to put your own sites and/or checks you want to make.

If you're using Twilio, set up these environment variables (secrets) in GitHub: TWILIO_AUTH_TOKEN, TWILIO_ACCOUNT_SID, TWILIO_FROM_NUMBER and TWILIO_TO_NUMBER. If you don't want to use Twilio, remove the code for `send_sms_messages`.

If you're using Slack, set up the SLACK_WEBHOOK secret in GitHub. If you don't want to use Slack, remove the code for `send_slack_messages`. 

If you're using AWS (for S3 storage between runs), set up these secrets in GitHub: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and S3DATA_BUCKET. If you don't want to use AWS S3, remove all the code related to `s3data`.

In fact if you don't need any of the above (or want to set it up later), adjust `pythonapp.yml` to run the code without the `--ci` option (i.e. just: `python sites.py -v`). Then you can add the other services later if you want.

Now try running the script locally to make sure everything works:

    python sites.py -v

Once it looks good, commit back to GitHub and check the [Actions](actions) tab to see how it goes. It will run each time you commit, so you can test it by committing a known bad check, then reverting back to a good state.
