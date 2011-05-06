import random


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