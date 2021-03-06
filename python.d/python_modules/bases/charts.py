# -*- coding: utf-8 -*-
# Description:
# Author: Ilya Mashchenko (l2isbad)

from bases.collection import safe_print

CHART_PARAMS = ['type', 'id', 'name', 'title', 'units', 'family', 'context', 'chart_type']
DIMENSION_PARAMS = ['id', 'name', 'algorithm', 'multiplier', 'divisor']
VARIABLE_PARAMS = ['id', 'value']

CHART_TYPES = ['line', 'area', 'stacked']
DIMENSION_ALGORITHMS = ['absolute', 'incremental', 'percentage-of-absolute-row', 'percentage-of-incremental-row']

CHART_BEGIN = 'BEGIN {type}.{id} {since_last}\n'
CHART_CREATE = "CHART {type}.{id} '{name}' '{title}' '{units}' '{family}' '{context}' " \
               "{chart_type} {priority} {update_every}\n"
CHART_OBSOLETE = "CHART {type}.{id} '{name}' '{title}' '{units}' '{family}' '{context}' " \
               "{chart_type} {priority} {update_every} 'obsolete'\n"


DIMENSION_CREATE = "DIMENSION '{id}' '{name}' {algorithm} {multiplier} {divisor} '{hidden}'\n"
DIMENSION_SET = "SET '{id}' = {value}\n"

CHART_VARIABLE_SET = "VARIABLE CHART '{id}' = {value}\n"

RUNTIME_CHART_CREATE = "CHART netdata.runtime_{job_name} '' 'Execution time for {job_name}' 'ms' 'python.d' " \
                       "netdata.pythond_runtime line 145000 {update_every}\n" \
                       "DIMENSION run_time 'run time' absolute 1 1\n"


def create_runtime_chart(func):
    """
    Calls a wrapped function, then prints runtime chart to stdout.

    Used as a decorator for SimpleService.create() method.
    The whole point of making 'create runtime chart' functionality as a decorator was
    to help users who re-implements create() in theirs classes.

    :param func: class method
    :return:
    """
    def wrapper(*args, **kwargs):
        self = args[0]
        ok = func(*args, **kwargs)
        if ok:
            safe_print(RUNTIME_CHART_CREATE.format(job_name=self.name,
                                                   update_every=self._runtime_counters.FREQ))
        return ok
    return wrapper


class ChartError(Exception):
    """Base-class for all exceptions raised by this module"""


class DuplicateItemError(ChartError):
    """Occurs when user re-adds a chart or a dimension that has already been added"""


class ItemTypeError(ChartError):
    """Occurs when user passes value of wrong type to Chart, Dimension or ChartVariable class"""


class ItemValueError(ChartError):
    """Occurs when user passes inappropriate value to Chart, Dimension or ChartVariable class"""


class Charts:
    """Represent a collection of charts

    All charts stored in a dict.
    Chart is a instance of Chart class.
    Charts adding must be done using Charts.add_chart() method only"""
    def __init__(self, job_name, priority, get_update_every):
        """
        :param job_name: <bound method>
        :param priority: <int>
        :param get_update_every: <bound method>
        """
        self.job_name = job_name
        self.priority = priority
        self.get_update_every = get_update_every
        self.charts = dict()

    def __len__(self):
        return len(self.charts)

    def __iter__(self):
        return iter(self.charts.values())

    def __repr__(self):
        return 'Charts({0})'.format(self)

    def __str__(self):
        return str([chart for chart in self.charts])

    def __contains__(self, item):
        return item in self.charts

    def __getitem__(self, item):
        return self.charts[item]

    def __delitem__(self, key):
        del self.charts[key]

    def __bool__(self):
        return bool(self.charts)

    def __nonzero__(self):
        return self.__bool__()

    def penalty_exceeded(self, penalty_max):
        """
        :param penalty_max: <int>
        :return:
        """
        return (chart for chart in self if chart.penalty > penalty_max and chart.alive)

    def add_chart(self, params):
        """
        Create Chart instance and add it to the dict

        Manually adds job name, priority and update_every to params.
        :param params: <list>
        :return:
        """
        params = [self.job_name()] + params
        chart_id = params[1]
        if chart_id in self.charts:
            raise DuplicateItemError("'{chart}' already in charts".format(chart=chart_id))
        else:
            new_chart = Chart(params)
            new_chart.params['update_every'] = self.get_update_every()
            new_chart.params['priority'] = self.priority
            self.priority += 1
            self.charts[new_chart.id] = new_chart
            return new_chart


class Chart:
    """Represent a chart"""
    def __init__(self, params):
        """
        :param params: <list>
        """
        if not isinstance(params, list):
            raise ItemTypeError("'chart' must be a list type")
        if not len(params) >= 8:
            raise ItemValueError("invalid value for 'chart', must be {0}".format(CHART_PARAMS))

        self.params = dict(zip(CHART_PARAMS, (p or str() for p in params)))
        self.name = '{type}.{id}'.format(type=self.params['type'],
                                         id=self.params['id'])
        if self.params.get('chart_type') not in CHART_TYPES:
            self.params['chart_type'] = 'absolute'

        self.dimensions = list()
        self.variables = set()
        self.alive = True
        self.penalty = 0

    def __getattr__(self, item):
        try:
            return self.params[item]
        except KeyError:
            raise AttributeError("'{instance}' has no attribute '{attr}'".format(instance=repr(self),
                                                                                 attr=item))

    def __repr__(self):
        return 'Chart({0})'.format(self.id)

    def __str__(self):
        return self.id

    def __iter__(self):
        return iter(self.dimensions)

    def __contains__(self, item):
        return item in [dimension.id for dimension in self.dimensions]

    def suppress(self):
        self.alive = False

    def unsuppress(self):
        self.penalty = 0
        self.alive = True

    def add_variable(self, variable):
        """
        :param variable: <list>
        :return:
        """
        self.variables.add(ChartVariable(variable))

    def add_dimension(self, dimension):
        """
        :param dimension: <list>
        :return:
        """
        dim = Dimension(dimension)

        if dim.id in self:
            raise DuplicateItemError("'{dimension}' already in '{chart}' dimensions".format(dimension=dim.id,
                                                                                            chart=self.name))
        self.dimensions.append(dim)
        return dim

    def add_dimension_and_push_chart(self, dimension):
        """
        :param dimension: <list>
        :return:
        """
        dim = self.add_dimension(dimension)
        self.unsuppress()
        safe_print(self.create(dim))

    def create(self, dimension=None):
        """
        :param dimension: Dimension
        :return:
        """
        chart = CHART_CREATE.format(**self.params)
        if not dimension:
            dimensions = ''.join([dimension.create() for dimension in self.dimensions])
            variables = ''.join([var.set(var.value) for var in self.variables if var])
            return chart + dimensions + variables
        else:
            dimensions = dimension.create()
            return chart + dimensions

    def begin(self, since_last):
        """
        :param since_last: <int>: microseconds
        :return:
        """
        return CHART_BEGIN.format(type=self.type,
                                  id=self.id,
                                  since_last=since_last)

    def obsolete(self):
        return CHART_OBSOLETE.format(**self.params)


class Dimension:
    """Represent a dimension"""
    def __init__(self, params):
        """
        :param params: <list>
        """
        if not isinstance(params, list):
            raise ItemTypeError("'dimension' must be a list type")
        if not params:
            raise ItemValueError("invalid value for 'dimension', must be {0}".format(DIMENSION_PARAMS))

        self.params = dict(zip(DIMENSION_PARAMS, (p or str() for p in params)))
        self.params['name'] = self.params.get('name') or self.params['id']

        if self.params.get('algorithm') not in DIMENSION_ALGORITHMS:
            self.params['algorithm'] = 'absolute'
        if not isinstance(self.params.get('multiplier'), int):
            self.params['multiplier'] = 1
        if not isinstance(self.params.get('divisor'), int):
            self.params['divisor'] = 1
        self.params.setdefault('hidden', '')

    def __getattr__(self, item):
        try:
            return self.params[item]
        except KeyError:
            raise AttributeError("'{instance}' has no attribute '{attr}'".format(instance=repr(self),
                                                                                 attr=item))

    def __repr__(self):
        return 'Dimension({0})'.format(self.id)

    def __str__(self):
        return self.id

    def create(self):
        return DIMENSION_CREATE.format(**self.params)

    def set(self, value):
        """
        :param value: <str>: must be a digit
        :return:
        """
        return DIMENSION_SET.format(id=self.id,
                                    value=value)


class ChartVariable:
    """Represent a chart variable"""
    def __init__(self, params):
        """
        :param params: <list>
        """
        if not isinstance(params, list):
            raise ItemTypeError("'variable' must be a list type")
        if not params:
            raise ItemValueError("invalid value for 'variable' must be: {0}".format(VARIABLE_PARAMS))

        self.params = dict(zip(VARIABLE_PARAMS, params))
        self.params.setdefault('value', None)

    def __getattr__(self, item):
        try:
            return self.params[item]
        except KeyError:
            raise AttributeError("'{instance}' has no attribute '{attr}'".format(instance=repr(self),
                                                                                 attr=item))

    def __bool__(self):
        return self.value is not None

    def __nonzero__(self):
        return self.__bool__()

    def __repr__(self):
        return 'ChartVariable({0})'.format(self.id)

    def __str__(self):
        return self.id

    def __eq__(self, other):
        if isinstance(other, ChartVariable):
            return self.id == other.id
        return False

    def __hash__(self):
        return hash(repr(self))

    def set(self, value):
        return CHART_VARIABLE_SET.format(id=self.id,
                                         value=value)
