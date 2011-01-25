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

from eoxserver.lib.util import EOxSXMLEncoder, isotime
from osgeo.osr import SpatialReference
from datetime import datetime

class EOxSGMLEncoder(EOxSXMLEncoder):
    def _initializeNamespaces(self):
        return {
            "gml": "http://www.opengis.net/gml/3.2"
        }
    
    def encodeLinearRing(self, ring, srid):
        if srid == 4326:
            pos_list = " ".join(["%f %f" % (point[1], point[0]) for point in ring])
        else:
            pos_list = " ".join(["%f %f" % point for point in ring])
        
        return self._makeElement(
            "gml", "LinearRing", [
                ("gml", "posList", pos_list)
            ]
        )

    def encodePolygon(self, poly, base_id):
        ext_element = self.encodeLinearRing(poly[0], poly.srid)
        
        if len(poly) > 1:
            int_elements = [("gml", "interior", [(self.encodeLinearRing(ring, poly.srid),)]) for ring in poly[1:]]
        else:
            int_elements = []
        
        sub_elements = [
            ("@gml", "id", "polygon_%s" % base_id),
            ("gml", "exterior", [(ext_element,)])
        ]
        sub_elements.extend(int_elements)

        return self._makeElement(
            "gml", "Polygon", sub_elements
        )

    def encodeMultiPolygon(self, geom, base_id):
        if geom.geom_type == "MultiPolygon":
            polygons = [self.encodePolygon(geom[c], "%s_%d" % (base_id, c+1)) for c in range(0, len(geom))]
        elif geom.geom_type == "Polygon":
            polygons = [self.encodePolygon(geom, base_id)]
        
        sub_elements = [("@gml", "id", "multisurface_%s" % base_id)]
        sub_elements.extend([
            ("gml", "surfaceMember", [
                (poly_element,)
            ]) for poly_element in polygons
        ])
        
        return self._makeElement(
            "gml", "MultiSurface", sub_elements
        )

class EOxSEOPEncoder(EOxSGMLEncoder):
    def _initializeNamespaces(self):
        ns_dict = super(EOxSEOPEncoder, self)._initializeNamespaces()
        ns_dict.update({
            "om": "http://www.opengis.net/om/2.0",
            "eop": "http://www.opengis.net/eop/2.0"
        })
        return ns_dict

    def encodeFootprint(self, footprint, eo_id):
        return self._makeElement(
            "eop", "Footprint", [
                ("@gml", "id", "footprint_%s" % eo_id),
                ("eop", "multiExtentOf", [
                    (self.encodeMultiPolygon(footprint, eo_id),)
                ])
            ]
        )
    
    def encodeEarthObservation(self, eo_metadata):
        eo_id = eo_metadata.getEOID()
        begin_time_iso = isotime(eo_metadata.getBeginTime())
        end_time_iso = isotime(eo_metadata.getEndTime())
        result_time_iso = isotime(datetime.now()) # TODO
        
        return self._makeElement(
            "eop", "EarthObservation", [
                ("@gml", "id", "eop_%s" % eo_id),
                ("om", "phenomenonTime", [
                    ("gml", "TimePeriod", [
                        ("@gml", "id", "phen_time_%s" % eo_id),
                        ("gml", "beginPosition", begin_time_iso),
                        ("gml", "endPosition", end_time_iso)
                    ])
                ]),
                ("om", "resultTime", [
                    ("gml", "TimeInstant", [
                        ("@gml", "id", "res_time_%s" % eo_id),
                        ("gml", "timePosition", result_time_iso)
                    ])
                ]),
                ("om", "procedure", []),
                ("om", "observedProperty", []),
                ("om", "featureOfInterest", [
                    (self.encodeFootprint(eo_metadata.getFootprint(), eo_id),)
                ]),
                ("om", "result", []),
                ("eop", "metaDataProperty", [
                    ("eop", "EarthObservationMetaData", [
                        ("eop", "identifier", eo_id),
                        ("eop", "acquisitionType", "NOMINAL"), # TODO
                        ("eop", "status", "ARCHIVED") # TODO
                    ])
                ])
            ]
        )

class EOxSCoverageGML10Encoder(EOxSXMLEncoder):
    def _initializeNamespaces(self):
        return {
            "gml": "http://www.opengis.net/gml/3.2",
            "gmlcov": "http://www.opengis.net/gmlcov/1.0",
            "swe": "http://www.opengis.net/swe/2.0"
        }
    
    def _getGMLId(self, id):
        if str(id)[0].isdigit():
            return "gmlid_%s" % str(id)
        else:
            return id
    
    def encodeDomainSet(self, coverage):
        return self._makeElement("gml", "domainSet", [
            (self.encodeGrid(coverage.getGrid(), "%s_grid" % coverage.getCoverageId()),)
        ])
    
    def encodeGrid(self, grid, id):
        grid_element = self._makeElement("gml", "RectifiedGrid", [
            ("", "@dimension", grid.dim),
            ("@gml", "id", self._getGMLId(id)),
            ("gml", "limits", [
                ("gml", "GridEnvelope", [
                    ("gml", "low", " ".join([str(c) for c in grid.low])),
                    ("gml", "high", " ".join([str(c) for c in grid.high]))
                ])
            ]),
            ("gml", "axisLabels", " ".join(grid.axis_labels)),
            ("gml", "origin", [
                ("gml", "Point", [
                    ("", "@srsName", "http://www.opengis.net/def/crs/EPSG/0/%s" % grid.srid),
                    ("@gml", "id", self._getGMLId("%s_origin" % id)),
                    ("gml", "pos", " ".join([str(c) for c in grid.origin]))
                ])
            ])
        ])
        
        for offset_vector in grid.offsets:
            grid_element.appendChild(self._makeElement("gml", "offsetVector", [
                ("", "@srsName", "http://www.opengis.net/def/crs/EPSG/0/%s" % grid.srid),
                ("", "@@", " ".join([str(c) for c in offset_vector]))
            ]))
                    
        return grid_element
    
    def encodeBoundedBy(self, minx, miny, maxx, maxy):
        #bbox = grid.getBBOX()
        
        #minx, miny, maxx, maxy = bbox.transform(4326, True).extent
        
        return self._makeElement("gml", "boundedBy", [
            ("gml", "Envelope", [
                ("", "@srsName", "http://www.opengis.net/def/crs/EPSG/0/4326"),
                ("", "@axisLabels", "lat long"),
                ("", "@uomLabels", "deg deg"),
                ("", "@srsDimension", 2),
                ("gml", "lowerCorner", "%f %f" % (miny, minx)),
                ("gml", "upperCorner", "%f %f" % (maxy, maxx))
            ])
        ])

    def encodeRangeType(self, coverage):
        return self._makeElement("gmlcov", "rangeType", [
            ("swe", "DataRecord", [(self.encodeRangeTypeField(channel),) for channel in coverage.getRangeType()])
        ])
    
    def encodeRangeTypeField(self, channel):
        return self._makeElement("swe", "field", [
            ("", "@name", channel.name),
            ("swe", "Quantity", [
                ("", "@definition", channel.definition),
                ("swe", "description", channel.description),
# TODO: Not in sweCommon anymore
#                ("swe", "name", channel.name),
                ("swe", "nilValues", [(self.encodeNilValue(nil_value),) for nil_value in channel.nil_values]),
                ("swe", "uom", [
                    ("", "@code", channel.uom)
                ]),
                ("swe", "constraint", [
                    ("swe", "AllowedValues", [
                        ("swe", "interval", "%s %s" % (channel.allowed_values_start, channel.allowed_values_end)),
                        ("swe", "significantFigures", channel.allowed_values_significant_figures)
                    ])
                ])
            ])
        ])
    
    def encodeNilValue(self, nil_value):
        return self._makeElement("swe", "NilValue", [
            ("", "@reason", nil_value.reason),
            ("", "@@", nil_value.value)
        ])


class EOxSWCS20Encoder(EOxSCoverageGML10Encoder):
    def _initializeNamespaces(self):
        ns_dict = super(EOxSWCS20Encoder, self)._initializeNamespaces()
        ns_dict.update({
            "wcs": "http://www.opengis.net/wcs/2.0",
            "xsi": "http://www.w3.org/2001/XMLSchema-instance"
        })
        return ns_dict
    
    def encodeCoverageDescription(self, coverage):
        return self._makeElement("wcs", "CoverageDescription", [
            ("@gml", "id", self._getGMLId(coverage.getCoverageId())),
            (self.encodeBoundedBy(*coverage.getWGS84Extent()),),
            ("wcs", "CoverageId", coverage.getCoverageId()),
            (self.encodeDomainSet(coverage),),
            (self.encodeRangeType(coverage),),
            ("wcs", "ServiceParameters", [
                ("wcs", "CoverageSubtype", coverage.getCoverageSubtype()),
            ])
        ])
    
    def encodeCoverageDescriptions(self, coverages, is_root=False):
        if is_root:
            sub_nodes = [("@xsi", "schemaLocation", "http://www.opengis.net/wcseo/1.0 http://schemas.opengis.net/wcseo/1.0/wcsEOAll.xsd")]
        else:
            sub_nodes = []
            
        sub_nodes.extend([(self.encodeCoverageDescription(coverage),) for coverage in coverages])
        return self._makeElement("wcs", "CoverageDescriptions", sub_nodes)

class EOxSWCS20EOAPEncoder(EOxSWCS20Encoder):
    def _initializeNamespaces(self):
        ns_dict = super(EOxSWCS20EOAPEncoder, self)._initializeNamespaces()
        ns_dict.update({
            "ows": "http://www.opengis.net/ows/2.0",
            "wcseo": "http://www.opengis.net/wcseo/1.0",
            "xlink": "http://www.w3.org/1999/xlink"
        })
        return ns_dict
    
    def encodeEOMetadata(self, coverage):
        eop_encoder = EOxSEOPEncoder()
        
        return self._makeElement("gmlcov", "metadata", [
            ("wcseo", "EOMetadata", [
                (eop_encoder.encodeEarthObservation(coverage),)
            ]),
        ])

    def encodeContents(self):
        return self._makeElement("wcs", "Contents", [])

    def encodeCoverageSummary(self, coverage):
        return self._makeElement("wcs", "CoverageSummary", [
            ("wcs", "CoverageId", coverage.getCoverageId()),
            ("wcs", "CoverageSubtype", coverage.getCoverageSubtype()),
            ("wcs", "CoverageSubtype", "RectifiedEOCoverage"),
            ("wcs", "CoverageSubtype", coverage.getEOCoverageSubtype()),
        ])

    def encodeCoverageDescription(self, coverage):
        return self._makeElement("wcs", "CoverageDescription", [
            ("@gml", "id", self._getGMLId(coverage.getCoverageId())),
            (self.encodeBoundedBy(*coverage.getWGS84Extent()),),
            ("wcs", "CoverageId", coverage.getCoverageId()),
            (self.encodeEOMetadata(coverage),),
            (self.encodeDomainSet(coverage),),
            (self.encodeRangeType(coverage),),
            ("wcs", "ServiceParameters", [
                ("wcs", "CoverageSubtype", coverage.getCoverageSubtype()),
                ("wcs", "CoverageSubtype", "RectifiedEOCoverage"),
                ("wcs", "CoverageSubtype", coverage.getEOCoverageSubtype()),
            ])
        ])
    
    def encodeDatasetSeriesDescription(self, dataset_series):
        return self._makeElement("wcseo", "DatasetSeriesDescription", [
            ("@gml", "id", self._getGMLId(dataset_series.getEOID())),
            (self.encodeBoundedBy(*dataset_series.getWGS84Extent()),),
            ("wcseo", "DatasetSeriesId", dataset_series.getEOID()),
            (self.encodeTimePeriod(dataset_series),),
#            ("wcseo", "ServiceParameters", [
# TODO: Include all referenced EO Coverages:            
#                ("wcseo", "rectifiedDataset", datasetseries.getCoverageSubtype()),
#                ("wcseo", "referenceableDataset", datasetseries.getCoverageSubtype()),
#                ("wcseo", "rectifiedStitchedMosaic", datasetseries.getCoverageSubtype()),
#                ("wcseo", "referenceableStitchedMosaic", datasetseries.getCoverageSubtype()),
#            ])
        ])

    def encodeDatasetSeriesDescriptions(self, datasetseriess):
        return self._makeElement("wcseo", "DatasetSeriesDescriptions", [(self.encodeDatasetSeriesDescription(datasetseries),) for datasetseries in datasetseriess])
        
    def encodeEOCoverageSetDescription(self, datasetseriess, coverages):
        return self._makeElement("wcseo", "EOCoverageSetDescription", [
            ("@xsi", "schemaLocation", "http://www.opengis.net/wcseo/1.0 http://schemas.opengis.net/wcseo/1.0/wcsEOAll.xsd"),
            (self.encodeCoverageDescriptions(coverages),),
            (self.encodeDatasetSeriesDescriptions(datasetseriess),),
        ])

    def encodeEOProfile(self):
        return self._makeElement("ows", "Profile", "http://www.opengis.net/spec/WCS_profile_earth-observation/1.0")

    def encodeDescribeEOCoverageSetOperation(self, http_service_url):
        return self._makeElement("ows", "Operation", [
            ("", "@name", "DescribeEOCoverageSet"),
            ("ows", "DCP", [
                ("ows", "HTTP", [
                    ("ows", "Get", [
                        ("@xlink", "href", "%s?" % http_service_url),
                        ("@xlink", "type", "simple")
                    ]),
                    ("ows", "Post", [
                        ("@xlink", "href", "%s?" % http_service_url),
                        ("@xlink", "type", "simple")
                    ])
                ])
            ])
        ])
    
    def encodeWGS84BoundingBox(self, dataset_series):
        minx, miny, maxx, maxy = dataset_series.getWGS84Extent()
        
        return self._makeElement("ows", "WGS84BoundingBox", [
            ("ows", "LowerCorner", "%f %f" % (minx, miny)),
            ("ows", "UpperCorner", "%f %f" % (maxx, maxy))
        ])
    
    def encodeTimePeriod(self, dataset_series):
        return self._makeElement("gml", "TimePeriod", [
            ("@gml", "id", self._getGMLId("%s_timeperiod" % dataset_series.getEOID())),
            ("gml", "beginPosition", dataset_series.getBeginTime().strftime("%Y-%m-%dT%H:%M:%S")),
            ("gml", "endPosition", dataset_series.getEndTime().strftime("%Y-%m-%dT%H:%M:%S"))
        ])

    def encodeDatasetSeriesSummary(self, dataset_series):
        return self._makeElement("wcseo", "DatasetSeriesSummary", [
            (self.encodeWGS84BoundingBox(dataset_series),),
            ("wcseo", "DatasetSeriesId", dataset_series.getEOID()),
            (self.encodeTimePeriod(dataset_series),)
        ])
