import copy
import math
import psutil

from collections import namedtuple

from mod_wsgi import server_metrics as raw_server_metrics

SERVER_READY = '_'
SERVER_STARTING = 'S'
SERVER_BUSY_READ = 'R'
SERVER_BUSY_WRITE = 'W'
SERVER_BUST_KEEPALIVE = 'K'
SERVER_BUSY_LOG = 'L'
SERVER_BUSY_DNS = 'D'
SERVER_CLOSING = 'C'
SERVER_GRACEFUL = 'G'
SERVER_IDLE_KILL = 'I'
SERVER_DEAD = '.'

WORKER_STATUS = {
    SERVER_READY: 'Ready',
    SERVER_STARTING: 'Starting',
    SERVER_BUSY_READ: 'Read',
    SERVER_BUSY_WRITE: 'Write',
    SERVER_BUST_KEEPALIVE: 'Keepalive',
    SERVER_BUSY_LOG: 'Logging',
    SERVER_BUSY_DNS: 'DNS lookup',
    SERVER_CLOSING: 'Closing',
    SERVER_GRACEFUL: 'Graceful',
    SERVER_IDLE_KILL: 'Dying',
    SERVER_DEAD: 'Dead'
}

def server_metrics():
    """Returns server metrics, which are a combination of data from the
    raw mod_wsgi server metrics, along with further data derived from
    that raw data.

    """

    workers_busy = 0
    workers_idle = 0

    access_count = 0
    bytes_served = 0

    active_processes = 0

    # Grab the raw server metrics.

    result = raw_server_metrics()

    # Loop over all the processes and workers they contain aggregating
    # various details.

    for process in result['processes']:
        process['active_workers'] = 0

        for worker in process['workers']:
            # Here we determine whether a worker is busy or idle.

            status = worker['status']

            if not process['quiescing'] and process['pid']:
                if (status == SERVER_READY and process['generation'] ==
                        result['running_generation']):

                    process['active_workers'] += 1
                    workers_idle += 1

                elif status not in (SERVER_DEAD, SERVER_STARTING,
                        SERVER_IDLE_KILL):

                    process['active_workers'] += 1
                    workers_busy += 1

            # Here we aggregate number of requests served and
            # amount of bytes transferred.

            count = worker['access_count']

            if count or status not in (SERVER_READY, SERVER_DEAD):
                access_count += count
                bytes_served += worker['bytes_served']

        if process['active_workers']:
            active_processes += 1

    result['workers_busy'] = workers_busy
    result['workers_idle'] = workers_idle

    result['access_count'] = access_count
    result['bytes_served'] = bytes_served

    result['active_processes'] = active_processes

    return result

RequestSample = namedtuple('RequestSample', 'start_time duration')

class Scoreboard(object):

    """Container for holding selected server metrics accumulated from
    multiple samples making up a sampling period.

    """

    system_frequency = 1

    def __init__(self):
        # Setup the starting values. We need to grab an initial
        # set of server metrics as a reference point for certain
        # values.

        data = server_metrics()

        # Start of the period will be the time we just generated
        # the initial server metrics used as a reference.

        self.period_start = data['current_time']

        # The current end time for the period always starts out
        # as the same as the start time.

        self.period_end = self.period_start

        # Sample periods count tracks how many consecutive sample
        # periods have been run which have been chained together.

        self.sample_periods = 1

        # Sample count tracks how many samples have been collected
        # against this sample period.

        self.sample_count = 0

        # Sampler exiting flag indicates whether this is the final
        # sampling period to be reported on due to the sampler
        # exiting due to process shutdown or some other event.

        self.sampler_exiting = False

        # The server and thread limits are the maximum number of
        # processes and workers per process that can be created.
        # In practice the number of workers per process is always
        # fixed at the thread limit as Apache doesn't dynamically
        # adjust the number of running workers per process and
        # instead always creates the maximum number and leaves it
        # at that for the life of the process.

        self.server_limit = data['server_limit']
        self.thread_limit = data['thread_limit']

        # Active processes is how many Apache child processes
        # currently contain active workers. This is used between
        # samples, to determine whether relative to the last
        # sample, the number of processes increased or decreased.

        self.active_processes = 0

        # Running counters of the total number of running, starting
        # or stopped processes across all samples. The count of
        # running processes is used to determine the average number
        # of processes running for the whole sample period. The
        # counts of starting and stopping are used in reflecting
        # the amount of process churn.

        self.processes_running_count = 0
        self.processes_started_count = 0
        self.processes_stopped_count = 0

        # Running counters of the total number of idle and busy
        # workers across all samples. These counts are used to
        # detemine the average number of workers in each state
        # for the whole sample period.

        self.workers_idle_count = 0
        self.workers_busy_count = 0

        # Running counters of the actual workers statuses across
        # all samples. These counts are used to detemine the
        # average number of workers in each state for the whole
        # sample period. The statues are a more fine grained
        # depiction of the worker state compared to the summary
        # state of idle or busy.

        self.workers_status_count = dict.fromkeys(WORKER_STATUS.keys(), 0)

        # Access count is the number of completed requests that
        # have been handled by Apache. We have the total and a
        # delta for the current sampling period.

        self.access_count_total = data['access_count']
        self.access_count_delta = 0

        # Bytes served is the number of bytes which have been
        # transferred by Apache. We have the total and a delta
        # for the current sampling period.

        self.bytes_served_total = data['bytes_served']
        self.bytes_served_delta = 0

        # Request samples is a list of details for a subset of
        # requests derived from the server metrics. It is not
        # possible to collect the details of every request. We
        # can only even get samples where we see a worker, at the
        # time of the sample, which hasn't yet started a new
        # request and so can extract the details from the last
        # request that the worker handled. If a worker is
        # handling multiple requests between sample periods, we
        # also only get the opportunity to see the details for
        # the last one handled. The number of request samples
        # should be bounded by the number of workers times the
        # number of samples in the sample period.

        self.request_samples = []

        # Process system info records details of any processes
        # such as memory, CPU usage and context switches.

        self.processes_system_info = {}

    @property
    def duration(self):
        """The duration of the sampling period.

        """

        return self.period_end - self.period_start

    @property
    def processes_running(self):
        if self.sample_count == 0:
            return 0

        return math.ceil(float(self.processes_running_count) /
                self.sample_count)

    @property
    def workers_idle(self):
        if self.sample_count == 0:
            return 0

        return math.ceil(float(self.workers_idle_count) / self.sample_count)

    @property
    def workers_busy(self):
        if self.sample_count == 0:
            return 0

        return math.ceil(float(self.workers_busy_count) / self.sample_count)

    @property
    def workers_utilization(self):
        if self.sample_count == 0:
            return 0

        return (float(self.workers_busy_count) / self.sample_count) / (
                self.server_limit * self.thread_limit)

    @property
    def workers_status(self):
        result = {}

        if self.sample_count == 0:
            return result

        total = 0

        for value in self.workers_status_count.values():
            value = float(value) / self.sample_count
            total += value

        if total:
            for key, value in self.workers_status_count.items():
                if key != SERVER_DEAD and value != 0:
                   label = WORKER_STATUS.get(key, 'Unknown')
                   value = float(value) / self.sample_count
                   result[label] = (value / total) * total

        return result

    @property
    def request_percentiles(self):
        result = {}

        # Calculate from the set of sampled requests the average
        # and percentile metrics.

        requests = self.request_samples

        if requests:
            requests.sort(key=lambda e: e.duration)

            total = sum([x.duration for x in requests])

            # Chart as 'Average'.

            result['Average'] = total/len(requests)

            idx50 = int(0.50 * len(requests))
            result['Median'] = requests[idx50].duration

            idx95 = int(0.95 * len(requests))
            result['95%'] = requests[idx95].duration

            idx99 = int(0.99 * len(requests))
            result['99%'] = requests[idx99].duration

        return result

    @property
    def request_samples_quality(self):
        if self.access_count_delta == 0:
            return 0.0

        return float(len(self.request_samples)) / self.access_count_delta

    def update(self, rollover=False,exiting=False):
        """Updates the scoreboard values for the current sampling
        period by incorporating current server metrics.

        """

        # Grab the current server metrics.

        data = server_metrics()

        # Update times for current sampling period and number of
        # samples taken.

        sample_start = self.period_end
        sample_end = data['current_time']
        sample_duration = max(0, sample_end - sample_start)

        self.period_end = sample_end

        # Calculate changes in access count and bytes served since
        # the last sample.

        access_count_total = data['access_count']
        access_count_delta = access_count_total - self.access_count_total

        self.access_count_delta += access_count_delta
        self.access_count_total = access_count_total

        bytes_served_total = data['bytes_served']
        bytes_served_delta = bytes_served_total - self.bytes_served_total

        self.bytes_served_delta += bytes_served_delta
        self.bytes_served_total = bytes_served_total

        # Collect request samples. The requests must have completed
        # since the last sample time and the worker must not have
        # already started on a new request.

        for process in data['processes']:
            for worker in process['workers']:
                start_time = worker['start_time']
                stop_time = worker['stop_time']

                if (stop_time > start_time and sample_start < stop_time
                        and stop_time <= sample_end):

                    self.request_samples.append(RequestSample(
                            start_time=start_time,
                            duration=stop_time-start_time))

        # Calculate changes in the number of active, starting and
        # stopping processes, and the number of idle and busy workers.

        current_active_processes = data['active_processes']
        previous_active_processes = self.active_processes

        self.active_processes = current_active_processes
        self.processes_running_count += current_active_processes

        if current_active_processes > previous_active_processes:
            self.processes_started_count += (current_active_processes -
                    previous_active_processes)

        elif current_active_processes < previous_active_processes:
            self.processes_stopped_count += (previous_active_processes -
                    current_active_processes)

        self.workers_idle_count += data['workers_idle']
        self.workers_busy_count += data['workers_busy']

        for process in data['processes']:
           for worker in process['workers']:
               self.workers_status_count[worker['status']] += 1

        # Record details about state of processes.

        if self.sample_count % self.system_frequency == 0 or rollover:

            # First we mark all process entries as being dead. We
            # will then mark as alive those which truly are.

            for details in self.processes_system_info.values():
                details['dead'] = True

            for process in data['processes']:
                pid = process['pid']

                if pid == 0:
                    continue

                details = self.processes_system_info.get(pid)

                if details is None:
                    details = dict(pid=pid)

                    details['duration'] = 0.0

                    details['cpu_times'] = None
                    details['cpu_user_time'] = 0.0
                    details['cpu_system_time'] = 0.0

                    details['ctx_switches'] = None
                    details['ctx_switch_voluntary'] = 0
                    details['ctx_switch_involuntary'] = 0

                details['dead'] = False

                try:
                    p = psutil.Process(pid)

                except psutil.NoSuchProcess:
                    details['dead'] = True

                    continue

                try:
                    rss, vms = p.memory_info()

                    details['memory_rss'] = rss
                    details['memory_vms'] = vms

                except psutil.AccessDenied:
                    details['dead'] = True

                    continue

                except Exception:
                    raise

                try:
                    cpu_times = p.cpu_times()

                    if details['cpu_times'] is None:
                        details['cpu_times'] = cpu_times

                        # Note that we don't want to baseline CPU usage
                        # at zero the first time we see the process, as we
                        # want to capture any work performed in doing any
                        # startup initialisation of the process. This
                        # would occur before the first time we see it.
                        # Thus populate CPU usage with the initial values.
                        # Is slight risk that we may in part apportion
                        # this to the wrong sampling period if didn't fall
                        # within the sample, but nothing we can do about
                        # that.

                        details['cpu_user_time'] = cpu_times[0]
                        details['cpu_system_time'] = cpu_times[1]

                    else:
                        user_time = cpu_times[0] - details['cpu_times'][0]
                        system_time = cpu_times[1] - details['cpu_times'][1]

                        details['cpu_times'] = cpu_times
                        details['cpu_user_time'] += user_time
                        details['cpu_system_time'] += system_time

                except psutil.AccessDenied:
                    details['dead'] = True

                    continue

                except Exception:
                    raise

                try:
                    ctx_switches = p.num_ctx_switches()

                    if details['ctx_switches'] is None:
                        details['ctx_switches'] = ctx_switches

                    else:
                        voluntary = (ctx_switches.voluntary -
                                details['ctx_switches'].voluntary)
                        involuntary = (ctx_switches.involuntary -
                                details['ctx_switches'].involuntary)

                        details['ctx_switches'] = ctx_switches
                        details['ctx_switch_voluntary'] += voluntary
                        details['ctx_switch_involuntary'] += involuntary

                except psutil.AccessDenied:
                    details['dead'] = True

                    continue

                except NotImplementedError:
                    pass

                except Exception:
                    raise

                details['duration'] += sample_duration

                self.processes_system_info[pid] = details

        # Update the flag indicating whether the sampler is exiting
        # and this is the final sampling period data to be supplied.

        self.sampler_exiting = exiting

        self.sample_count += 1

    def rollover(self):
        """Creates a copy of the current scoreboard and resets any
        attributes back to initial values where appropriate for the
        start of a new sampling period.

        """

        # Create a copy. A shallow copy is enough.

        scoreboard = copy.deepcopy(self)

        # Reset selected attributes back to initial values.

        scoreboard.period_start = scoreboard.period_end

        scoreboard.sample_count = 0;

        scoreboard.access_count_delta = 0
        scoreboard.bytes_served_delta = 0

        scoreboard.processes_running_count = 0
        scoreboard.processes_started_count = 0
        scoreboard.processes_stopped_count = 0

        scoreboard.workers_idle_count = 0
        scoreboard.workers_busy_count = 0

        scoreboard.workers_status_count = dict.fromkeys(
                WORKER_STATUS.keys(), 0)

        scoreboard.request_samples = []

        # For record of processes, we want to remove just the dead ones.

        for pid, details in list(scoreboard.processes_system_info.items()):
            if details['dead']:
                del scoreboard.processes_system_info[pid]
            else:
                details['duration'] = 0.0
                details['cpu_user_time'] = 0.0
                details['cpu_system_time'] = 0.0
                details['ctx_switch_voluntary'] = 0
                details['ctx_switch_involuntary'] = 0

        # Increment the count of successive sampling periods.

        scoreboard.sample_periods += 1

        return scoreboard
