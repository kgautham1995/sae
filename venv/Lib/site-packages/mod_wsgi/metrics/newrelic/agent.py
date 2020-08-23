import os
import logging
import math
import psutil

try:
    from ConfigParser import RawConfigParser, NoOptionError, NoSectionError
except ImportError:
    from configparser import RawConfigParser, NoOptionError, NoSectionError

import mod_wsgi

from .platform import Client
from ..sampler import Sampler
from ..statistics import Metrics, Stats

_logger = logging.getLogger(__name__)

def configuration_settings(app_name=None, license_key=None,
    config_file=None, environment=None):

    if config_file is None:
        config_file = os.environ.get('NEW_RELIC_CONFIG_FILE', None)

    if config_file is not None:
        config_object = RawConfigParser()

        if config_file:
            config_object.read([config_file])

        if environment is None:
            environment = os.environ.get('NEW_RELIC_ENVIRONMENT', None)

        def _option(name, section='newrelic', type=None, **kwargs):
            try:
                getter = 'get%s' % (type or '')
                return getattr(config_object, getter)(section, name)
            except NoOptionError:
                if 'default' in kwargs:
                    return kwargs['default']
                else:
                    raise

        def option(name, type=None, **kwargs):
            sections = []

            if environment is not None:
                sections.append('newrelic-platform:%s' % environment)

            sections.append('newrelic-platform')

            if environment is not None:
                sections.append('newrelic:%s' % environment)

            sections.append('newrelic')

            for section in sections:
                try:
                    return _option(name, section, type)
                except (NoOptionError, NoSectionError):
                    pass

            if 'default' in kwargs:
                return kwargs['default']

        if app_name is None:
            app_name = os.environ.get('NEW_RELIC_APP_NAME', None)
            app_name = option('app_name', default=app_name)

        if license_key is None:
            license_key = os.environ.get('NEW_RELIC_LICENSE_KEY', None)
            license_key = option('license_key', default=license_key)

    else:
        if app_name is None:
            app_name = os.environ.get('NEW_RELIC_APP_NAME', None)

        if license_key is None:
            license_key = os.environ.get('NEW_RELIC_LICENSE_KEY', None)

    if app_name is not None:
        app_name = app_name.split(';')[0].strip()

    return app_name, license_key

class Agent(object):

    guid = 'au.com.dscpl.wsgi.mod_wsgi'
    version = '1.1.0'

    max_retries = 10

    def __init__(self, sampler=None, app_name=None, license_key=None,
            config_file=None, environment=None):

        self.sampler = None

        if mod_wsgi.version < (4, 2, 0):
            _logger.fatal('Version 4.2.0 or newer of mod_wsgi is required '
                    'for running the New Relic platform plugin. The plugin '
                    'has been disabled.')

            return

        app_name, license_key = configuration_settings(app_name,
                license_key, config_file, environment)

        if not license_key or not app_name:
            _logger.fatal('Either the license key or application name was '
                    'not specified for the New Relic platform plugin. The '
                    'plugin has been disabled.')

            return

        _logger.info('New Relic platform plugin reporting to %r.', app_name)

        self.client = Client(license_key)

        self.license_key = license_key
        self.app_name = app_name

        self.sampler = sampler or Sampler()

        self.sampler.register(self.process)

        self.metrics = Metrics()
        self.epoch = None
        self.retries = 0

    def upload(self, metrics, duration):
        try:
            self.client.send_metrics(self.app_name, self.guid, self.version,
                    duration, metrics)

        except self.client.RetryDataForRequest:
            return True

        except Exception:
            pass

        return False

    def record(self, name, value):
        name = 'Component/' + name
        self.metrics.merge_value(name, value)

    def rollover(self):
        self.metrics = Metrics()
        self.epoch = None
        self.retries = 0

    def process(self, scoreboard):
        # Record metric to track how many Apache server instances are
        # reporting. The 'Server/Instances' metric should be charted as
        # a 'Count', rounded to an 'Integer'.

        self.record('Server/Instances[|servers]', 0)

        # If this is the first sampling period, take that to mean that
        # this is a new process and Apache was just (re)started. If we
        # are being told the sampler is exiting, we take it that Apache
        # is being shutdown. Both can show up if shutdown during the
        # first sampling period. The 'Server/Lifecycle' metrics should
        # be charted as a 'Count', rounded to an 'Integer'.

        if scoreboard.sample_periods == 1:
            self.record('Server/Lifecycle/Starting[|servers]', 0)

        if scoreboard.sampler_exiting:
            self.record('Server/Lifecycle/Stopping[|servers]', 0)

        # Record metric to track how many processes are in use. This is
        # calculated as an average from the total number which which
        # were reported in use in each individual sample. The
        # 'Process/Instances' metric should be charted as a 'Count',
        # rounded to an 'Integer'.

        self.record('Processes/Instances[|processes]', Stats(
                count=scoreboard.processes_running))

        # Also separately record how many processes were counted as
        # having been started or stopped in the sampling period. These
        # would be used to represent the amount of process churn which
        # is occuring due to Apache's dynamic management of the number
        # of processes. The 'Process/Lifecycle' metrics should be
        # charted as a 'Count', rounded to an 'Integer'.

        self.record('Processes/Lifecycle/Starting[|processes]',
                Stats(count=scoreboard.processes_started_count))

        self.record('Processes/Lifecycle/Stopping[|processes]',
                Stats(count=scoreboard.processes_stopped_count))

        # Record metric to track how many workers are in idle and busy
        # states. This is calculated as an average from the total number
        # which were reported in each state in each individual sample.
        # The 'Workers/Availability' metrics should be charted as a
        # 'Count', rounded to an 'Integer'.

        self.record('Workers/Availability/Idle[|workers]', Stats(
                count=scoreboard.workers_idle))
        self.record('Workers/Availability/Busy[|workers]', Stats(
                count=scoreboard.workers_busy))

        # Record metric to track more fine grained status of each
        # worker. This is calculated as an average from the total number
        # which were reported in each state in each individual sample.
        # The 'Workers/Status' metrics should be charted as 'Average'
        # value, rounded to an 'Integer'.

        for label, value in scoreboard.workers_status.items():
           self.record('Workers/Status/%s[workers]' % label, value)

        # Record metric to track the utilisation of the server. The
        # 'Workers/Utilization' metric should be charted as 'Average
        # value', with number format of 'Percentage'.

        self.record('Workers/Utilization[server]',
                scoreboard.workers_utilization)

        # Record metric to track the request throughput. The
        # 'Requests/Throughput' metric should be charted as 'Throughput'.

        self.record('Requests/Throughput[|requests]', Stats(
                count=scoreboard.access_count_delta,
                total=scoreboard.access_count_delta))

        # Record metric to track number of bytes served up. This is
        # believed only to be from response content. There is no known
        # separate measure for bytes uploaded. The 'Requests/Bytes Served'
        # should be charted as 'Rate'.

        self.record('Requests/Bytes Served[bytes]',
                scoreboard.bytes_served_delta)

        # Record metric to track request response time. This is
        # calculated as an average from the request samples. That is, it
        # is not across all requests. The 'Requests/Response Time'
        # metric should be charted as 'Average'.

        for request in scoreboard.request_samples:
            self.record('Requests/Response Time[seconds|request]',
                    request.duration)

        # Record metric to track percentile breakdown of request
        # response time. That is, it is not across all requests. The
        # 'Requests/Percentiles' metric should be charted as 'Average'.

        for label, value in scoreboard.request_percentiles.items():
            self.record('Requests/Percentiles/%s[seconds]' % label, value)

        # Record metric to track what percentage of all requests were
        # captured as samples. The 'Requests/Sample Quality' metric
        # should be charted as 'Average' converted to a 'Percentage'.

        self.record('Requests/Sample Quality[requests]',
                scoreboard.request_samples_quality)

        user_time = 0.0
        system_time = 0.0

        memory_rss = 0

        for process in scoreboard.processes_system_info.values():
            user_time += process['cpu_user_time']
            system_time += process['cpu_system_time']
            memory_rss += process['memory_rss']

            # Record metric to track memory usage by processes. The
            # 'Processes/Memory/Physical' metric should be charted as
            # 'Average'.

            self.record('Processes/Memory/Physical[bytes]',
                    process['memory_rss'])

            # Record metrics to track the number of context switches.
            # The 'Processes/Context Switches' metrics should be charted
            # as 'Rate'.

            self.record('Processes/Context Switches/Voluntary[context]',
                    process['ctx_switch_voluntary'])
            self.record('Processes/Context Switches/Involuntary[context]',
                    process['ctx_switch_involuntary'])

        # Record metric to track combined memory usage of whole server.
        # The 'Server/Memory/Physical' metric should be charted as
        # 'Average'.

        self.record('Server/Memory/Physical[bytes]', memory_rss)

        # Record metric to track the CPU usage for user and system. The
        # 'Processes/CPU Usage' metric should be charted as 'Rate'.

        self.record('Processes/CPU Usage[cpu]', user_time + system_time)
        self.record('Processes/CPU Usage/User[cpu]', user_time)
        self.record('Processes/CPU Usage/System[cpu]', system_time)

        # Now attempt to upload the metric data to New Relic. Make sure
        # we don't try and upload data from too short of a sampling
        # period as it will be rejected anyway. Retain any which is too
        # short so it is merged with subsequent sampling period.

        if self.epoch is not None:
            duration = scoreboard.period_end - self.epoch
        else:
            duration = scoreboard.duration

        if duration > 1.0:
            retry = self.upload(self.metrics.metrics, duration)
        else:
            retry = True

        # If a failure occurred but the failure type was such that we
        # could try again to upload the data, then retain the metrics
        # for next time. If we have two many failed attempts though we
        # give up.

        if retry:
            self.retries += 1

            if self.retries == self.max_retries:
                self.rollover()

            elif self.epoch is None:
                self.epoch = scoreboard.period_start

        else:
            self.rollover()

    def start(self):
        if self.sampler is not None:
            self.sampler.start()
