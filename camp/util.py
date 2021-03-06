import os
import math
import time
import random
import logging

from camp.config import Config

log = logging.getLogger(__name__)


class Random(random.Random):
    """Overrides standard Random class and allows to specify range for the
    ``uniform`` function."""
    
    def __init__(self, rmin=0, rmax=1, seed=None):
        """Create new instance of random number generator.
        
        :param rmin: minimal value of random numbers generated by the
            ``uniform`` function
        :param rmax: maximal value of random numbers generated by the
            ``uniform`` function"""
        super(Random, self).__init__(seed)
        self.rmin = rmin
        self.rmax = rmax

    def uniform(self):
        """Generate random number from range specified in constructor."""
        return super(Random, self).uniform(self.rmin, self.rmax)


class Vector(object):
    """Class representing n-dimensional vectors."""
    
    def __init__(self, items):
        """Create new vector.
        
        :param items: sequence of vector's items"""
        self._items = tuple(items)

    def length(self):
        """Calculate length of this vector."""
        return math.sqrt(sum([c**2 for c in self]))

    def normalize(self):
        """Return a vector that is normalized version of current one."""
        l = self.length()
        return Vector([c/l for c in self])

    def dot(self, other):
        """Calculate dot product of this vector and provided another vector."""
        if len(self) != len(other):
            raise TypeError("vectors must have same dimensions")
        return sum([self[i]*other[i] for i in xrange(len(self))])
    
    def __mul__(self, other):
        """Allows to calculate dot product with * operator."""
        if not isinstance(other, Vector):
            raise TypeError(
                "unsupported operand type(s) for *: %s and %s" %
                (type(self), type(other)))
        return self.dot(other)

    def __iter__(self):
        for i in self._items:
            yield i

    def __getitem__(self, key):
        return self._items[key]

    def __len__(self):
        return len(self._items)

    def __repr__(self):
        return "%s([%s])" % (
            self.__class__.__name__,
            ', '.join([str(i) for i in self]))

    @classmethod
    def new(cls, a, b):
        """Make new vector pointing from ``a`` towards ``b`` and return new
        vector."""
        if len(a) != len(b):
            raise TypeError("points must have same dimensions")
        return Vector([b[i]-a[i] for i in xrange(len(a))])


class BaseDumper(object):
    """Class to be used by decorator :func:`dump` instead of simple function.
    It allows to check what was changed by the decorated function."""
    
    def __precall__(self, args=None, kwargs=None):
        """Called before call to decorated function."""

    def __postcall__(self, result, args=None, kwargs=None):
        """Called after call to decorated function."""

    def __call__(self, result, args=None, kwargs=None, dump_dir=None):
        """This method works in the same way as function dumpers."""
        raise NotImplementedError()

    @property
    def func_name(self):
        """Name of "function"."""
        return self.__class__.__name__


def asfloat(value):
    """Convert given value to float number and return it."""
    if isinstance(value, float):
        return value
    elif isinstance(value, basestring):
        try:
            return float(value)
        except ValueError:
            return float(value.
                replace('O', '0').
                replace('l', '1').
                replace('S', '5').
                replace('I', '1').
                replace(',', '.'))
    else:
        return float(value)


def asunicode(value):
    """Convert given value to unicode by trying different encodings and
    catching UnicodeDecodeError exceptions."""
    if isinstance(value, unicode):
        return value
    try:
        return unicode(value)
    except UnicodeDecodeError:
        try:
            return value.decode('utf-8')
        except UnicodeDecodeError:
            try:
                return value.decode('iso-8859-1')
            except UnicodeDecodeError:
                raise


def timeit(func):
    """Calculates execution time (in seconds) of decorated function."""
    def _timeit(*args, **kwargs):
        if not Config.instance().config('argv:timeit', False).asbool():
            return func(*args, **kwargs)
        log.debug('timing function %s', func)
        start = time.time()
        try:
            return func(*args, **kwargs)
        finally:
            log.debug("done for %s. Time: %1.3f sec",
                func, time.time() - start)
    return _timeit


def dump(dumper):
    """Decorator used to dump partial results for debugging purposes.
    
    :param dumper: dump function taking 3 arguments: the result of decorated
        function, the args of decorated function and the kwargs of decorated
        function"""
    def _dump(func):
        def __dump(*args, **kwargs):
            if not Config.instance().config('argv:dump', False).asbool():
                return func(*args, **kwargs)
            if isinstance(dumper, type) and issubclass(dumper, BaseDumper):
                dumper_ = dumper()
            else:
                dumper_ = dumper
            tmp = isinstance(dumper_, BaseDumper)
            if tmp:
                try:
                    dumper_.__precall__(args=args, kwargs=kwargs)
                except:
                    log.exception('__precall__ of %s failed:', dumper_)
            result = func(*args, **kwargs)
            if tmp:
                try:
                    dumper_.__postcall__(result, args=args, kwargs=kwargs)
                except:
                    log.exception('__postcall__ of %s failed:', dumper_)
            try:
                cfg = Config.instance()
                dump_dir = cfg.config(
                    'main:dump_dir',
                    os.path.join(Config.ROOT_DIR, 'data', 'dump')).asstring()
                infile = os.path.basename(cfg.config('argv:infile').asstring())
                dump_dir = os.path.join(dump_dir, infile, dumper_.func_name)
                if not os.path.isdir(dump_dir):
                    os.makedirs(dump_dir)
                cfg.save(os.path.join(dump_dir, 'config.ini'))
                log.debug('executing dump function: %s', dumper_)
                dumper_(result, args=args, kwargs=kwargs, dump_dir=dump_dir)
            except:
                log.exception('error while performing dump using function %s:', dumper_)
            return result
        __dump.func_name = func.func_name
        return __dump
    return _dump
