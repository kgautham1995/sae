import threading
import atexit
import time

try:
    import Queue as queue
except ImportError:
    import queue

from .scoreboard import Scoreboard

import mod_wsgi

class Sampler(object):

    sample_interval = 1.0
    report_interval = 60.0

    def __init__(self):
        self.running = False
        self.lock = threading.Lock()

        self.sampler_queue = queue.Queue()

        self.sampler_thread = threading.Thread(target=self.sampler_loop)
        self.sampler_thread.setDaemon(True)

        self.consumer_queue = queue.Queue()

        self.consumer_thread = threading.Thread(target=self.consumer_loop)
        self.consumer_thread.setDaemon(True)

        self.consumers = []

    def register(self, callback):
        self.consumers.append(callback)

    def consumer_loop(self):
        while True:
            scoreboard = self.consumer_queue.get()

            for consumer in self.consumers:
                consumer(scoreboard)

            if scoreboard.sampler_exiting:
                return

    def distribute(self, scoreboard):
        self.consumer_queue.put(scoreboard)

    def sampler_loop(self):
        scoreboard = Scoreboard()

        scheduled_time = time.time()
        period_end_time = scheduled_time + self.report_interval

        while True:
            try:
                # We want to collect metrics on a regular second
                # interval so we need to align the timeout value.

                now = time.time()
                scheduled_time += self.sample_interval
                timeout = max(0, scheduled_time - now)

                self.sampler_queue.get(timeout=timeout)

                # If we get here we have been notified to exit.
                # We update the scoreboard one last time and then
                # distribute it to any consumers.

                scoreboard.update(rollover=True, exiting=True)

                self.distribute(scoreboard)

                return

            except queue.Empty:
                pass

            # Update the scoreboard for the current sampling period.
            # Need to check first whether after we will be rolling it
            # over for next sampling period as well so can do any
            # special end of sampling period actions.

            now = time.time()

            if now >= period_end_time:
                scoreboard.update(rollover=True)

                # Distribute scoreboard to any consumers. It
                # is expected that they will read but not update
                # as same instance is used for all.

                self.distribute(scoreboard)

                period_end_time += self.report_interval

                # Rollover to a new scoreboard for the next
                # sampling period.

                scoreboard = scoreboard.rollover()

            else:
                scoreboard.update(rollover=False)

    def terminate(self):
        try:
            self.sampler_queue.put(None)
        except Exception:
            pass

        self.sampler_thread.join()
        self.consumer_thread.join()

    def start(self):
        if mod_wsgi.server_metrics() is None:
            return

        with self.lock:
            if not self.running:
                self.running = True
                atexit.register(self.terminate)
                self.sampler_thread.start()
                self.consumer_thread.start()
