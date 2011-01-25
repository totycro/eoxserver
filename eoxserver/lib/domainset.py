#-----------------------------------------------------------------------
#
# This software is named EOxServer, a server for Earth Observation data.
#
# Copyright (C) 2011 EOX IT Services GmbH
# Authors: Stephan Krause, Stephan Meissl
#
# This file is part of EOxServer <http://www.eoxserver.org>.
#
#    EOxServer is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published
#    by the Free Software Foundation, either version 3 of the License,
#    or (at your option) any later version.
#
#    EOxServer is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with EOxServer. If not, see <http://www.gnu.org/licenses/>.
#
#-----------------------------------------------------------------------

from osgeo import gdal
from osgeo.osr import SpatialReference

import logging

import numpy
import numpy.linalg

from django.contrib.gis.geos import GEOSGeometry, Polygon, LineString

from eoxserver.lib.exceptions import (
    EOxSUnknownCRSException, EOxSInvalidAxisLabelException,
    EOxSInvalidSubsettingException
)
from eoxserver.lib.util import getDateTime, getSRIDFromCRSURI

class EOxSRectifiedGrid(object):
    def __init__(self,
        dim=2,
        spatial_dim=2,
        low=(0,0),
        high=(0,0),
        axis_labels=('lon','lat'),
        srid=4326,
        origin=(0,0),
        offsets=((1,0),(0,1))
    ):
        super(EOxSRectifiedGrid, self).__init__()
        self.dim = dim
        self.spatial_dim = spatial_dim
        self.low = low
        self.high = high
        self.axis_labels = axis_labels
        self.srid = srid
        self.origin = origin
        self.offsets = offsets
        
        # TODO: validate inputs
    
    def getExtent2D(self):
        if self.spatial_dim >= 2:
            lowx = self.origin[0] + self.low[0] * self.offsets[0][0] + self.low[1] * self.offsets[1][0]
            lowy = self.origin[1] + self.low[0] * self.offsets[0][1] + self.low[1] * self.offsets[1][1]
            highx = self.origin[0] + self.high[0] * self.offsets[0][0] + self.high[1] * self.offsets[1][0]
            highy = self.origin[1] + self.high[0] * self.offsets[0][1] + self.high[1] * self.offsets[1][1]
            
            return (min(lowx, highx), min(lowy, highy), max(lowx, highx), max(lowy, highy))
        else:
            raise Exception("Cannot compute 2D extent of grid with less than 2 spatial dimensions")
    
    def getBBOX(self):
        bbox = Polygon.from_bbox(self.getExtent2D())
        bbox.srid = int(self.srid)
        
        return bbox
    
    def contains(self, grid):
        this_minx, this_miny, this_maxx, this_maxy = self.getExtent2D()
        that_minx, that_miny, that_maxx, that_maxy = grid.getExtent2D()
        
        return this_minx <= that_minx and this_miny <= that_miny and \
               this_maxx >= that_maxx and this_maxy >= that_maxy
        
    def isSubGrid(self, grid):
        if self.spatial_dim == grid.spatial_dim:
            this_offsets = numpy.array([self.offsets[i][0:self.spatial_dim-1] for i in range(0, self.spatial_dim)])
            that_offsets = numpy.array([grid.offsets[i][0:grid.spatial_dim-1] for i in range(0, grid.spatial_dim)])
            
            if not numpy.all(numpy.equal(this_offsets, that_offsets)):
                return False
            else:
                this_low = numpy.array(self.origin[0:self.spatial_dim-1]) + numpy.linalg.dot(this_offsets, numpy.array(self.low[0:self.spatial_dim-1]))
                that_low = numpy.array(grid.origin[0:self.spatial_dim-1]) + numpy.linalg.dot(that_offsets, numpy.array(grid.low[0:self.spatial_dim-1]))
                
                v = numpy.linalg.solve(this_offsets, this_low - that_low)
                if numpy.all(numpy.equal(numpy.rint(v), v)) and \
                   all([(v[i] >= 0 and v[i] + self.high[i] - self.low[i] <= grid.high[i] - grid.low[i]) for i in range(0, self.spatial_dim - 1)]):
                    return True
                else:
                    return False
        else:
            return False

class EOxSSubsetting(object):
    def __init__(self, dimension, crs):
        super(EOxSSubsetting, self).__init__()
        
        self.dimension = dimension
        self.crs = crs
    
    def normalize(self, dimension, value):
        if value is None or len(value) == 0:
            return None
        elif dimension in ("time", "t"):
            if value[0] == '"' and value[-1] == '"':
                token = value.lstrip('"').rstrip('"')
                return getDateTime(token) # this raises an EOxSUnknkownParameterFormatException if the datetime format is not recognized
            else:
                raise EOxSInvalidSubsettingException("Date/Time tokens have to be enclosed in quotation marks (\")")
        else:
            try:
                return float(value)
            except:
                raise EOxSInvalidSubsettingException("'%s' not recognized as a number" % value)

    def validate(self, grid=None):
        return True
    
    def _getDataFromFootprint(self, footprint):
        srid = 4326
        
        env_minx, env_miny, env_maxx, env_maxy = footprint.extent
        
        return (srid, env_minx, env_miny, env_maxx, env_maxy)

class EOxSSlice(EOxSSubsetting):
    def __init__(self, dimension, crs, slice_point):
        super(EOxSSlice, self).__init__(dimension, crs)
        
        self.slice_point = self.normalize(dimension, slice_point)
    
    def validate(self, grid=None):
        if self.slice_point is not None:
            if grid is not None:
                if self.dimension not in grid.axis_labels:
                    raise EOxSInvalidAxisLabelException("Invalid axis label '%s'" % self.dimension)
        else:
            raise EOxSInvalidSubsettingException("Empty slices are not allowed")
        
        return True
    
    def crosses(self, footprint):
        srid, env_minx, env_miny, env_maxx, env_maxy = self._getDataFromFootprint(footprint)
        
        if self.dimension == "long":
            line = LineString((self.slice_point, env_miny), (self.slice_point, env_maxy), srid=srid)
        elif self.dimension == "lat":
            line = LineString((env_minx, self.slice_point), (env_maxx, self.slice_point), srid=srid)
        else:
            raise EOxSInternalError("Can handle 2D coverages only.")
        
        return line.crosses(bbox)

class EOxSTrim(EOxSSubsetting):
    def __init__(self, dimension, crs, trim_low, trim_high):
        super(EOxSTrim, self).__init__(dimension, crs)

        self.trim_low = self.normalize(dimension, trim_low)
        self.trim_high = self.normalize(dimension, trim_high)
        
    def validate(self, grid=None):
        if self.trim_low is not None and self.trim_high is not None and self.trim_high < self.trim_low:
            raise EOxSInvalidSubsettingException("Lower bound of trim greater than upper bound")
            
        #if grid is not None:
        #    if self.dimension not in grid.axis_labels:
        #        raise EOxSInvalidAxisLabelException("Invalid axis label '%s'" % self.dimension)
        
        if self.dimension not in ("time", "long", "lat"):
            raise EOxSInvalidAxisLabelException("Invalid axis label '%s'. Use 'time', 'long' and 'lat'." % self.dimension)

        return True
    
    def _getPolygon(self, srid, env_minx, env_miny, env_maxx, env_maxy):
        EPSILON = 1e-10
        
        if self.dimension == "long":
            miny = env_miny
            maxy = env_maxy
            
            if self.trim_low is None:
                minx = env_minx 
            else:
                minx = max(env_minx, self.trim_low)
            
            if self.trim_high is None:
                maxx = env_maxx
            else:
                maxx = min(env_maxx, self.trim_high)
                
        elif self.dimension == "lat":
            minx = env_minx
            maxx = env_maxx
            
            if self.trim_low is None:
                miny = env_miny
            else:
                miny = max(env_miny, self.trim_low)
            
            if self.trim_high is None:
                maxy = env_maxy
            else:
                maxy = min(env_maxy, self.trim_high)
        
        if maxx <= minx or maxy <= miny:
            return GEOSGeometry("POLYGON EMPTY", srid=srid)
        else:
            # in order to be prepared for rounding and string conversion
            # errors, make the extent a little bit larger
            minx = minx * (1 - EPSILON)
            miny = miny * (1 - EPSILON)
            maxx = maxx * (1 + EPSILON)
            maxy = maxy * (1 + EPSILON)
            
            poly = Polygon.from_bbox((minx, miny, maxx, maxy))
            poly.srid = srid
            
            return poly
               
    def overlaps(self, footprint):
        srid, env_minx, env_miny, env_maxx, env_maxy = self._getDataFromFootprint(footprint)
        
        poly = self._getPolygon(srid, env_minx, env_miny, env_maxx, env_maxy)
        
        return footprint.intersects(poly)
    
    def contains(self, footprint):
        srid, env_minx, env_miny, env_maxx, env_maxy = self._getDataFromFootprint(footprint)
        
        poly = self._getPolygon(srid, env_minx, env_miny, env_maxx, env_maxy)
        
        return poly.contains(footprint)

def getGridFromFile(filename, collection_srid=None):
    ds = gdal.Open(str(filename))

    gt = ds.GetGeoTransform()
    
    srs = SpatialReference()
    srs.ImportFromWkt(ds.GetProjection())

    srs.AutoIdentifyEPSG()
    if srs.IsProjected():
        axis_labels = ('x', 'y')
        if collection_srid is None:
            srid = srs.GetAuthorityCode("PROJCS")
        else:
            srid = collection_srid
    elif srs.IsGeographic():
        axis_labels = ('lon', 'lat')
        if collection_srid is None:
            srid = srs.GetAuthorityCode("GEOGCS")
        else:
            srid = collection_srid
    else:
        axis_labels = ('x', 'y')
        srid = collection_srid
    #logging.debug("EOxSCoverageInterface._getGridFromFile: SRID: %s" % str(srid))

    return EOxSRectifiedGrid(
        dim=2,
        low=(0, 0),
        high=(ds.RasterXSize - 1, ds.RasterYSize - 1),
        axis_labels=axis_labels,
        srid=srid,
        origin=(gt[0], gt[3]),
        offsets=((gt[1], gt[4]), (gt[2], gt[5]))
    )
