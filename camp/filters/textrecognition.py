import os
import logging
import camp.exc as exc

from camp.util import dump
from camp.config import Config
from camp.filters import BaseFilter
from camp.core import ImageChops, Image
from camp.core.containers import SegmentGroup, Text
from camp.plugins.ocr import OCRPluginBase

log = logging.getLogger(__name__)


def _text_recognition_dump(result, args=None, kwargs=None, dump_dir=None):
    cbounds = Config.instance().config('argv:cbounds', (0, 0, 255)).value
    image = args[1]
    storage = kwargs['storage']['TextRecognitor']
    text, text_candidates = storage['text'], storage['text_candidates']
    graphical = storage['graphical']

    # Dump text region candidates
    image1 = image.copy()
    for t in text_candidates:
        t.display_bounds(image1, color=cbounds)
    image1.save(os.path.join(dump_dir, 'candidates.png'))

    # Dump recognized text regions
    image2 = image.copy()
    for t in text:
        t.display_bounds(image2, color=cbounds)
    image2.save(os.path.join(dump_dir, 'recognized.png'))

    # Dump difference text candidates and recognized text regions
    ImageChops.difference(image1, image2).save(
        os.path.join(dump_dir, 'difference.png'))

    # Dump remaining graphical segments
    image3 = Image.create(image.mode, image.width, image.height, background=(255, 255, 255))
    for g in graphical:
        g.display(image3, color=g.color)
    image3.save(os.path.join(dump_dir, 'graphical.png'))


class TextRecognitor(BaseFilter):
    """Filter used to split set of segments into two distinct sets: one
    containing textual segments, and one containing graphical (non-textual)
    segments.

    :attr __f_max_width__: maximal width of potential letter
    :attr __f_max_height__: maximal height of potential letter
    :attr __f_letter_delta__: maximal distance between two letters
    :attr __f_word_delta__: maximal distance between two words
    :attr __f_min_word_area__: minimal area of pixels composing word (used
        to remove minor segments before OCR procedure)
    :attr __f_max_vertical_height__: maximal height of vertical letters. Used
        to ignore already found horizontal text segments while searching for
        vertical text segments
    :attr __f_min_vfactor__: minimal value of segment's ``vfactor`` property
        that still makes the segment's orientation vertical"""
    __f_max_width__ = 40
    __f_max_height__ = 30
    __f_letter_delta__ = 6
    __f_word_delta__ = 12
    __f_min_word_area__ = 20
    __f_max_vertical_height__ = 30
    __f_min_vfactor__ = 2.5
    
    def extract_text(self, image, segments_):
        """Find and return group of segments composing textual information."""
        max_width = self.config('max_width').asint()
        max_height = self.config('max_height').asint()
        letter_delta = self.config('letter_delta').asint()
        word_delta = self.config('word_delta').asint()
        min_word_area = self.config('min_word_area').asint()
        max_vertical_height = self.config('max_vertical_height').asint()
        min_vfactor = self.config('min_vfactor').asfloat()

        def box_filter(segments):
            """Removes segments which bounds does not fit in given maximal
            bounds. Used to leave segments that are mostly like to be text
            segments."""
            candidates = set()
            for s in segments:
                if s.width > max_width or s.height > max_height:
                    continue
                candidates.add(s)
            return candidates

        def clear_letters(segments):
            """Removes internal segments from letters like ``P`` or ``B``. This
            is done by removing segments that have none neighbours from outside
            of ``segments`` sequence."""
            candidates = set()
            indices = set([s.index for s in segments])
            permanently_removed = 0
            for s in segments:
                for n in s.neighbours:
                    if n not in indices:
                        candidates.add(s)
                        break
                else:
                    permanently_removed += 1
                    segments_.remove(s)  # Letter internal segments won't be used
            log.debug(
                'number of permanently removed segments after letter '
                'clear process: %d', permanently_removed)
            return candidates
        
        def merge_segments(segments):
            """Group letter candidates into larger connected structures using
            same algorithm as the one used to extract segments from the
            image.""" 
            tmp = set(segments)
            segment_map = dict([(s.index, s) for s in segments])
            indices = set(segment_map.keys())
            groups = []
            while tmp:
                segment = tmp.pop()
                stack = [segment]
                group = SegmentGroup(len(groups))
                group.segments.add(segment)
                while stack:
                    s = stack.pop()
                    for n in s.neighbours:
                        if n in indices:
                            tmp.discard(segment_map[n])
                            indices.remove(n)
                            stack.append(segment_map[n])
                            group.segments.add(segment_map[n])
                groups.append(group)
            return groups
        
        def extract_text_regions(segments):
            """Extracts regions that are supposed to be text regions and
            perform OCR recognition on text region candidates. """
            
            def group(bound_map, delta, horizontal=True):
                Y1 = 1 if horizontal else 0
                Y2 = 3 if horizontal else 2
                X1 = 0 if horizontal else 1
                X2 = 2 if horizontal else 3
                bound_set = set(bound_map.keys())
                groups = set()
                while bound_set:
                    cur = min(bound_set, key=lambda x: x[0]+x[1])
                    hmin, hmax = cur[Y1], cur[Y2]
                    bound_set.remove(cur)
                    group = SegmentGroup(0)
                    group.segments.add(bound_map[cur])
                    while bound_set:
                        #candidates = filter(lambda x: x[0]-cur[2]>=0 and x[0]-cur[2]<=delta, bound_set)
                        candidates = sorted(filter(lambda x: x[X1]>=cur[X1] and x[X1]-cur[X2]<=delta, bound_set), key=lambda x: -x[Y2])
                        for c in candidates:
                            if c[Y1] > hmax or c[Y2] < hmin:
                                continue
                            group.segments.add(bound_map[c])
                            bound_set.remove(c)
                            cur = c
                            break
                        else:
                            break
                    #to_be_added = filter(lambda x: x[0]<=group.right and x[2]>=group.left and x[1]<=group.bottom and x[3]>=group.top, bound_set)
                    #for b in to_be_added:
                    #    group.segments.add(bound_map[b])
                    #    bound_set.remove(b)
                    groups.add(group)
                return groups
            
            horizontal_text = set()
            vertical_text = set()

            # Group letters into words (horizontal)
            words = group(dict([(s.bounds, s) for s in segments]), letter_delta)

            # Group words into sentences (horizontal)
            sentences = group(dict([(w.bounds, w) for w in words if len(w.area) > min_word_area]), word_delta)

            # Split set into horizontal text region candidates and vertical
            # text region candidates
            for s in sentences:
                if s.width <= max_vertical_height:
                    vertical_text.add(s)
                else:
                    horizontal_text.add(s)
            
            # Group letters into words (vertical)
            words = group(dict([(s.bounds, s) for s in vertical_text]), letter_delta, horizontal=False)

            # Group words into sentences (vertical)
            sentences = group(dict([(s.bounds, s) for s in words]), word_delta, horizontal=False)
            
            return horizontal_text.union(sentences)
        
        # Workflow
        candidates = box_filter(segments_)
        candidates = clear_letters(candidates)
        candidates = merge_segments(candidates)
        candidates = extract_text_regions(candidates)
        
        # Perform OCR recognition using external OCR process or processes. OCR
        # plugins can be comma-separated to make fallback processing (one does
        # not recognize text - another will try again)
        result = set()
        ocrs = []
        for OCRClass in OCRPluginBase.load_all():
            ocrs.append(OCRClass(working_dir=os.path.join('data', 'ocr', OCRClass.__name__)))
        for c in candidates:
            horizontal = True
            for o in ocrs:
                if c.vfactor >= min_vfactor:  # Vertical text test
                    text = o.perform(c, angles=[270, 90, 0])
                    if text:
                        horizontal = False
                else:
                    text = o.perform(c)
                if text:
                    break
            if text:
                c.genre = Text(text=text, horizontal=horizontal)
                result.add(c)

        return result, candidates
    
    @dump(_text_recognition_dump)
    def process(self, image, storage=None):
        log.info('splitting segments into set of textual and non-textual segments')
        try:
            segments = storage['Segmentizer']['segments']
        except KeyError, e:
            raise exc.CampFilterError("missing in 'storage': %s" % e)
        
        # Text recognition process
        log.debug('searching for text regions')
        text, text_candidates = self.extract_text(image, segments)
        
        # Now split set of segment into two disjoined sets - one containing
        # textual segments, and one containing graphical segments
        textual = set()
        graphical = set()
        for s in segments:
            if isinstance(s.genre, Text):
                textual.add(s)
            else:
                graphical.add(s)
        log.debug('found %d text regions combined of total %d segments', len(text), len(textual))
        log.debug('remaining non-text segments: %d', len(graphical))

        # Save results for next filter
        storage[self.__class__.__name__] = {
            'text': text,
            'text_candidates': text_candidates,
            'graphical': graphical}
        return image
