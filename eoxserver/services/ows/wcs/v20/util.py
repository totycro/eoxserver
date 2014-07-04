#-------------------------------------------------------------------------------
# $Id$
#
# Project: EOxServer <http://eoxserver.org>
# Authors: Fabian Schindler <fabian.schindler@eox.at>
#
#-------------------------------------------------------------------------------
# Copyright (C) 2013 EOX IT Services GmbH
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell 
# copies of the Software, and to permit persons to whom the Software is 
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies of this Software or works derived from this Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#-------------------------------------------------------------------------------


import re
from datetime import datetime

from lxml.builder import ElementMaker

from eoxserver.core.util.xmltools import NameSpace, NameSpaceMap, ns_xsi
from eoxserver.core.util.timetools import parse_iso8601
from eoxserver.services.subset import Trim, Slice, is_temporal
from eoxserver.services.gml.v32.encoders import (
    ns_gml, ns_gmlcov, ns_om, ns_eop, GML, GMLCOV, OM, EOP
)
from eoxserver.services.ows.common.v20.encoders import ns_xlink, ns_ows, OWS
from eoxserver.services.exceptions import (
    InvalidSubsettingException, InvalidAxisLabelException, 
    NoSuchFieldException, IllegalFieldSequenceException
)


# namespace declarations
ns_ogc = NameSpace("http://www.opengis.net/ogc", "ogc")
ns_wcs = NameSpace("http://www.opengis.net/wcs/2.0", "wcs")
ns_crs = NameSpace("http://www.opengis.net/wcs/service-extension/crs/1.0", "crs")
ns_rsub = NameSpace("http://www.opengis.net/wcs/range-subsetting/1.0", "rsub")
ns_eowcs = NameSpace("http://www.opengis.net/wcseo/1.0", "wcseo", "http://schemas.opengis.net/wcseo/1.0/wcsEOAll.xsd")
ns_swe = NameSpace("http://www.opengis.net/swe/2.0", "swe")

# namespace map
nsmap = NameSpaceMap(
    ns_xlink, ns_ogc, ns_ows, ns_gml, ns_gmlcov, ns_wcs, ns_crs, ns_rsub, 
    ns_eowcs, ns_om, ns_eop, ns_swe
)

# Element factories

WCS = ElementMaker(namespace=ns_wcs.uri, nsmap=nsmap)
CRS = ElementMaker(namespace=ns_crs.uri, nsmap=nsmap)
EOWCS = ElementMaker(namespace=ns_eowcs.uri, nsmap=nsmap)
SWE = ElementMaker(namespace=ns_swe.uri, nsmap=nsmap)


subset_re = re.compile(r'(\w+)(,([^(]+))?\(([^,]*)(,([^)]*))?\)')
size_re = re.compile(r'(\w+)\(([^)]*)\)')
resolution_re = re.compile(r'(\w+)\(([^)]*)\)')


class Size(object):
    def __init__(self, axis, value):
        self.axis = axis
        self.value = int(value)


class Resolution(object):
    def __init__(self, axis, value):
        self.axis = axis
        self.value = float(value)


class RangeSubset(list):

    def get_band_indices(self, range_type, offset=0):
        current_idx = -1
        all_bands = range_type.cached_bands[:]
        
        for subset in self:
            if isinstance(subset, basestring):
                # slice, i.e single band
                start = stop = subset

            else:
                start, stop = subset

            start_idx = self._find(all_bands, start)
            if start != stop:
                stop_idx = self._find(all_bands, stop)
                if stop_idx <= start_idx:
                    raise IllegalFieldSequenceException(
                        "Invalid interval '%s:%s'." % (start, stop), start
                    )

                # expand interval to indices
                for i in range(start_idx, stop_idx+1):
                    yield i + offset

            else: 
                # return the item
                yield start_idx + offset


    def _find(self, all_bands, name):
        for i, band in enumerate(all_bands):
            if band.name == name or band.identifier == name:
                return i
        raise NoSuchFieldException("Field '%s' does not exist." % name, name)



class SectionsMixIn(object):
    """ Mix-in for request decoders that use sections.
    """

    def section_included(self, *sections):
        """ See if one of the sections is requested.
        """
        if not self.sections:
            return True

        requested_sections = map(lambda s: s.lower(), self.sections)

        for section in map(lambda s: s.lower(), sections):
            section = section.lower()
            if "all" in requested_sections or section in requested_sections:
                return True

        return False



def parse_subset_kvp(string):
    """ Parse one subset from the WCS 2.0 KVP notation.
    """

    try:

        match = subset_re.match(string)
        if not match:
            raise Exception("Could not parse input subset string.")

        axis = match.group(1)
        parser = get_parser_for_axis(axis)
        crs = match.group(3)
        
        if match.group(6) is not None:
            return Trim(
                axis, parser(match.group(4)), parser(match.group(6)), crs
            )
        else:
            return Slice(axis, parser(match.group(4)), crs)
    except InvalidAxisLabelException:
        raise
    except Exception, e:
        raise InvalidSubsettingException(str(e))


def parse_size_kvp(string):
    """ Parses a size from the given string.
    """

    match = size_re.match(string)
    if not match:
        raise ValueError("Invalid size parameter given.")

    return Size(match.group(1), match.group(2))


def parse_resolution_kvp(string):
    """ Parses a resolution from the given string.
    """

    match = resolution_re.match(string)
    if not match:
        raise ValueError("Invalid resolution parameter given.")

    return Resolution(match.group(1), match.group(2))


def parse_range_subset_kvp(string):
    """ Parse a rangesubset structure from the WCS 2.0 KVP notation.
    """

    rangesubset = RangeSubset()
    for item in string.split(","):
        if ":" in item:
            rangesubset.append(item.split(":"))
        else:
            rangesubset.append(item)

    return rangesubset


def parse_subset_xml(elem):
    """ Parse one subset from the WCS 2.0 XML notation. Expects an lxml.etree
        Element as parameter.
    """

    try:
        dimension = elem.findtext(ns_wcs("Dimension"))
        parser = get_parser_for_axis(dimension)
        if elem.tag == ns_wcs("DimensionTrim"):
            return Trim(
                dimension,
                parser(elem.findtext(ns_wcs("TrimLow"))),
                parser(elem.findtext(ns_wcs("TrimHigh")))
            )
        elif elem.tag == ns_wcs("DimensionSlice"):
            return Slice(
                dimension,
                parser(elem.findtext(ns_wcs("SlicePoint")))
            )
    except Exception, e:
        raise InvalidSubsettingException(str(e))


def parse_range_subset_xml(elem):
    """ Parse a rangesubset structure from the WCS 2.0 XML notation.
    """

    rangesubset = RangeSubset()

    for child in elem:
        item = child[0]
        if item.tag == ns_rsub("RangeComponent"):
            rangesubset.append(item.text)
        elif item.tag == ns_rsub("RangeInterval"):
            rangesubset.append((
                item.findtext(ns_rsub("startComponent")),
                item.findtext(ns_rsub("endComponent"))
            ))
    
    return rangesubset


def float_or_star(value):
    """ Parses a string value that is either a floating point value or the '*'
        character. Raises a `ValueError` if no float could be parsed.
    """

    if value == "*":
        return None
    return float(value)


def parse_quoted_temporal(value):
    """ Parses a quoted temporal value.
    """

    if value == "*":
        return None

    if not value[0] == '"' and not value[-1] == '"':
        raise ValueError("Temporal value needs to be quoted with double quotes.")

    return parse_iso8601(value[1:-1])


def get_parser_for_axis(axis):
    """ Returns the correct parsing function for the given axis.
    """

    if is_temporal(axis):
        return parse_quoted_temporal
    else:
        return float_or_star
