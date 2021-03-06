import os
import logging
import camp.exc as exc

from camp.config import Config
from camp.core import Image, ImageStat
from camp.core.colorspace import Convert, Range
from camp.util import Random, dump
from camp.filters import BaseFilter
from camp.clusterer.metric import euclidean
from camp.clusterer.kmeans import kmeans, Cluster

log = logging.getLogger(__name__)


def _quantizer_dump(result, args=None, kwargs=None, dump_dir=None):
    result_file = os.path.join(dump_dir, 'after-quantization.png')
    result.save(result_file)


class Quantizer(BaseFilter):
    __f_colorspace__ = 'LAB'
    __f_metric__ = 'euclidean'
    __f_threshold1__ = 0.1
    __f_threshold2__ = 5.0

    def __init__(self, next_filter=None):
        super(Quantizer, self).__init__(next_filter=next_filter)
        self.colorspace = self.config('colorspace').value.upper()
        self.metric = self.config('metric').value
        if not callable(self.metric):
            try:
                module = __import__('camp.clusterer.metric', fromlist=[self.metric])
            except ImportError:
                raise exc.CampFilterError(
                    "metric: function '%s' does not exist in module "
                    "'camp.clusterer.metric'" % self.metric)
            self.metric = getattr(module, self.metric)
        self.__c_encoder = getattr(Convert, "rgb2%s" % self.colorspace.lower())\
            if self.colorspace != 'RGB' else lambda x: x
        self.__c_decoder = getattr(Convert, "%s2rgb" % self.colorspace.lower())\
            if self.colorspace != 'RGB' else lambda x: x
        self.threshold1 = self.config('threshold1').asfloat()
        self.threshold2 = self.config('threshold2').asfloat()

    def __get_samples(self, image):
        """Prepare and return list of samples for clusterer."""
        return [s[1] for s in image.colors(encoder=self.__c_encoder)]

    def __create_result_image(self, image, clusters):
        """Create result image by changing color of each pixel in source image
        to one of cluster centroid colors."""
        encoder = self.__c_encoder
        decoder = self.__c_decoder
        res = Image.create(image.mode, image.width, image.height)
        dpix = res.pixels
        spix = image.pixels
        cache = {}
        for y in xrange(image.height):
            for x in xrange(image.width):
                s = spix[x, y]
                if s not in cache:
                    for c in clusters:
                        if encoder(s) in c.samples:
                            val = decoder(c.centroid)
                            break
                    cache[s] = val
                    dpix[x, y] = val
                else:
                    dpix[x, y] = cache[s]
        return res

    def choose_clusters(self, image):
        """Heuristic used to choose cluster centers from training set.
        
        :param image: image to be quantized"""
        t1 = self.threshold1
        t2 = self.threshold2
        clusters = []
        npixels = float(image.npixels)
        metric = self.metric
        dim = image.nchannels
        rng = getattr(Range, self.colorspace, None)
        if not rng:
            raise ValueError("%s: range for %s colorspace is not specified" % (Range, self.colorspace))
        max_difference = metric(*rng)
        # Sort colors by number of occurences in the image, descending and
        # ignore rare colors
        colors = sorted([c for c in image.colors(encoder=self.__c_encoder) if c[0]/npixels*100 >= t1], key=lambda x: -x[0])
        for i in xrange(len(colors)):
            if not colors[i]:
                continue  # Go to next color - already processed
            candidates = []
            # Search for colors that are close to current color
            for j in xrange(len(colors)):
                if not colors[j]:
                    continue  # Go to next color - already processed
                diff = metric(colors[i][1], colors[j][1]) / max_difference * 100
                if diff <= t2:
                    candidates.append(colors[j][1])
                    if j != i:
                        colors[j] = None  # Mark color as processed
            # Calculate centroid
            centroid = [0, 0, 0]
            ncandidates = float(len(candidates))
            for k in xrange(len(centroid)):
                centroid[k] = sum([c[k] for c in candidates]) / ncandidates
            colors[i] = None  # Mark color as processed
            # Add new cluster
            clusters.append(Cluster(dim, metric=metric, centroid=tuple(centroid)))
        return clusters
    
    @dump(_quantizer_dump)
    def process(self, image, storage=None):
        if not isinstance(image, Image):
            raise TypeError("image: expecting %s, found %s" % (Image, type(image)))
        if image.mode.upper() != 'RGB':
            raise ValueError("image: expecting RGB image, found %s" % image.mode.upper())
        log.info('running quantization process')
        log.debug(
            'quantization settings: colorspace=%s, metric=%s, t1=%s, t2=%s',
            self.colorspace, self.metric.func_name, self.threshold1,
            self.threshold2)
        # Get samples from the source image
        samples = self.__get_samples(image)
        log.debug('number of colors before quantization: %d', len(samples))
        # Choose initial clusters for the K-Means clusterer
        initial_clusters = self.choose_clusters(image)
        log.debug('number of colors after quantization: %d', len(initial_clusters))
        # Perform clustering and return clusters
        clusters = kmeans(samples, initial_clusters)
        # Create output image
        return self.__create_result_image(image, clusters)
