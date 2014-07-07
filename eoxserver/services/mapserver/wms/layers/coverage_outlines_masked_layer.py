#-------------------------------------------------------------------------------
#
# Project: EOxServer <http://eoxserver.org>
# Authors: Martin Paces <martin.paces@eox.at>
#
#-------------------------------------------------------------------------------
# Copyright (C) 2014 EOX IT Services GmbH
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

from eoxserver.core import Component, implements
from eoxserver.resources.coverages import models
from eoxserver.services.mapserver.interfaces import LayerPluginInterface

from eoxserver.services.mapserver.wms.layers.coverage_outlines_layer_factory \
    import CoverageOutlinesLayerFactory

#-------------------------------------------------------------------------------
#from django.contrib.gis.geos.collections import MultiPolygon

class CoverageOutlinesMaskedLayerFactory(CoverageOutlinesLayerFactory):
    """ derived masked outlines' layer factory """

    def _outline_geom( self, cov ):

        outline = cov.footprint

        for mask_item in cov.vector_masks.all() :
            outline = outline - mask_item.geometry

        return outline 
        
        return self._masked_outline(mask_items,cov.footprint)

#-------------------------------------------------------------------------------

class CoverageOutlinesMaskedLayerPlugin(Component):
    implements(LayerPluginInterface)

    handles = (models.RectifiedDataset, models.RectifiedStitchedMosaic)
    suffixes = ("_masked_outlines",)
    requires_connection = True

    def get_layer_factory(self,suffix,options):  
        factory = CoverageOutlinesMaskedLayerFactory(suffix,options)
        factory.plugin = self
        return factory 
