import copy

class Stats(dict):

    def __init__(self, count=0, total=0.0, min=0.0, max=0.0,
            sum_of_squares=0.0):

        # Attribute names here must not change as this is what
        # New Relic uses. Easier to adopt that convention rather
        # than something slightly different.

        self.count = count
        self.total = total
        self.min = min
        self.max = max
        self.sum_of_squares = sum_of_squares

    def __setattr__(self, name, value):
        self[name] = value

    def __getattr__(self, name):
        return self[name]

    def merge_stats(self, other):
        self.total += other.total
        self.min = self.count and min(self.min, other.min) or other.min
        self.max = max(self.max, other.max)
        self.sum_of_squares += other.sum_of_squares
        self.count += other.count

    def merge_value(self, value):
        self.total += value
        self.min = self.count and min(self.min, value) or value
        self.max = max(self.max, value)
        self.sum_of_squares += value ** 2
        self.count += 1

class Metrics(object):

    def __init__(self):
        self.metrics = {}

    def __iter__(self):
        return iter(self.metrics.items())

    def __len__(self):
        return len(self.metrics)

    def assign_value(self, name, value):
        if isinstance(value, Stats):
            sample = copy.copy(value)
            self.metrics[name] = sample
        else:
            sample = Stats()
            self.metrics[name] = sample
            sample.merge_value(value)

        return sample

    def merge_value(self, name, value):
        sample = self.fetch_stats(name)

        if isinstance(value, Stats):
            sample.merge_stats(value)
        else:
            sample.merge_value(value)

        return sample

    def fetch_stats(self, name):
        sample = self.metrics.get(name)

        if sample is None:
            sample = Stats()
            self.metrics[name] = sample

        return sample

    def merge_metrics(self, metrics):
        for name, stats in metrics:
            self.merge_value(name, stats)

    def assign_metrics(self, metrics):
        for name, stats in metrics:
            self.assign_value(name, stats)

    def clear_metrics(self):
        self.metrics.clear()

